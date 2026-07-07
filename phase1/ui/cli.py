"""
CLI 界面 - 命令行对话式摄像头控制
"""
import os
from datetime import datetime
from typing import Optional

import cv2

from phase1.core.config import save_config, AppConfig
from phase1.core.camera import CameraManager, CameraStatus
from phase1.network.discovery import discover_usb_cameras, discover_network_cameras, verify_onvif_camera
from phase1.core.events import EventBus, CameraEvent
from phase1.core.llm import LocalLLMClient, ParsedCommand
from phase1.ui.base import BaseUI


# ──────────────────────────────────────────────
#  ANSI 颜色码
# ──────────────────────────────────────────────
class Colors:
    RESET  = "\033[0m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"


# ──────────────────────────────────────────────
#  CLI 实现
# ──────────────────────────────────────────────
class CLIApp(BaseUI):
    """命令行交互界面"""

    BANNER = f"""
{Colors.CYAN}{Colors.BOLD}╔══════════════════════════════════════════════╗
║       Agentic Camera Control System          ║
║          智能摄像头控制系统 v0.1.0             ║
╚══════════════════════════════════════════════╝{Colors.RESET}
{Colors.BLUE}直接告诉我你想做什么，例如：{Colors.RESET}
  “扫描局域网摄像头”、“连接摄像头并拉流”、“截图”、“自动设置”
  输入 {Colors.GREEN}/help{Colors.RESET} 查看所有命令，输入 {Colors.GREEN}/quit{Colors.RESET} 退出
"""

    HELP_TEXT = f"""
{Colors.BOLD}可用命令：{Colors.RESET}
  {Colors.GREEN}/stream{Colors.RESET}       - 获取视频流 (USB: 打开预览窗口, ONVIF: 显示RTSP地址)
  {Colors.GREEN}/snapshot{Colors.RESET}     - 截图并保存
  {Colors.GREEN}/preview{Colors.RESET}      - 打开摄像头实时预览窗口
  {Colors.GREEN}/status{Colors.RESET}       - 查看摄像头状态
  {Colors.GREEN}/list{Colors.RESET}         - 列出所有摄像头
  {Colors.GREEN}/discover{Colors.RESET}     - 扫描可用 USB 摄像头
  {Colors.GREEN}/discover_net{Colors.RESET} - 扫描局域网 ONVIF/RTSP 摄像头
  {Colors.GREEN}/connect{Colors.RESET}      - 连接摄像头
  {Colors.GREEN}/password{Colors.RESET}    - 设置连接密码 (用法: /password <密码>)
  {Colors.GREEN}/disconnect{Colors.RESET}   - 断开摄像头
  {Colors.GREEN}/ptz{Colors.RESET}          - PTZ云台控制 (用法: /ptz up|down|left|right [速度])
  {Colors.GREEN}/ptz_stop{Colors.RESET}    - 停止PTZ移动
  {Colors.GREEN}/ptz_zoom{Colors.RESET}    - PTZ缩放 (用法: /ptz_zoom in|out)
  {Colors.GREEN}/presets{Colors.RESET}      - 列出PTZ预置位
  {Colors.GREEN}/devinfo{Colors.RESET}      - 获取ONVIF设备详细信息
  {Colors.GREEN}/models{Colors.RESET}       - 查看可用大模型
  {Colors.GREEN}/clear{Colors.RESET}        - 清空对话历史
  {Colors.GREEN}/events{Colors.RESET}       - 查看最近事件
  {Colors.GREEN}/probe_all{Colors.RESET}   - 逐个探测所有摄像头，汇总连接结果
  {Colors.GREEN}/help{Colors.RESET}         - 显示帮助信息
  {Colors.GREEN}/quit{Colors.RESET}         - 退出程序

{Colors.BLUE}直接输入自然语言即可与 AI 对话控制摄像头。{Colors.RESET}
{Colors.BLUE}例如："扫描局域网摄像头"、"摄像头向左转"、"放大画面"、"自动设置"{Colors.RESET}
"""

    def __init__(self, camera_manager: CameraManager, llm_client, event_bus: EventBus, app_config: AppConfig = None):
        super().__init__(camera_manager, llm_client, event_bus)
        self._running = False
        self._last_discovered_devices = []  # 缓存最近发现的网络设备
        self._default_password = ""          # 用户设置的默认连接密码
        self._app_config = app_config        # 保存 AppConfig 引用以便持久化

        # 注册全局事件监听 - 在 CLI 中打印事件通知
        self.event_bus.subscribe_all(self._on_event)

    # ── 主循环 ──────────────────────────────────

    def start(self) -> None:
        """启动 CLI 主循环- 自动扫描后进入 LLM 对话"""
        self._running = True
        print(self.BANNER)
    
        # 启动时自动扫描网络摄像头
        self._auto_scan_on_startup()
        
        while self._running:
            try:
                user_input = self.get_user_input()
                if not user_input.strip():
                    continue
                self._handle_input(user_input.strip())
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[提示] 按 Ctrl+C 再次退出，或输入 /quit{Colors.RESET}")
            except EOFError:
                self.stop()
            except Exception as e:
                # 捕获 utf-8 解码错误等意外异常，避免程序崩溃
                print(f"\n{Colors.RED}[错误] {e}{Colors.RESET}")

    def stop(self) -> None:
        """停止 CLI"""
        self._running = False
        self.display_message("正在退出...", "info")
        self.camera_manager.disconnect_all()
        self.llm_client.close()
        print(f"{Colors.CYAN}再见！{Colors.RESET}")

    # ── UI 接口实现 ─────────────────────────────

    def display_message(self, message: str, level: str = "info") -> None:
        color_map = {
            "info": Colors.BLUE,
            "warning": Colors.YELLOW,
            "error": Colors.RED,
            "success": Colors.GREEN,
        }
        color = color_map.get(level, Colors.RESET)
        prefix = {"info": "ℹ", "warning": "⚠", "error": "✗", "success": "✓"}.get(level, "•")
        print(f"{color}{prefix} {message}{Colors.RESET}")

    def get_user_input(self, prompt: str = "") -> str:
        prompt = prompt or f"{Colors.BOLD}{Colors.CYAN}📷 > {Colors.RESET}"
        try:
            return input(prompt)
        except UnicodeDecodeError:
            # Windows 控制台编码异常（如 OpenCV 关闭后 stdin 残留二进制数据）
            print(f"{Colors.YELLOW}[提示] 输入编码异常，请重新输入{Colors.RESET}")
            return ""

    def display_stream(self, camera_name: str, stream_url: str) -> None:
        print(f"\n{Colors.GREEN}═══ 视频流信息 ═══{Colors.RESET}")
        print(f"  摄像头: {camera_name}")
        print(f"  RTSP地址: {Colors.BOLD}{stream_url}{Colors.RESET}")
        print(f"\n  {Colors.BLUE}提示: 可使用 VLC/ffplay 播放：{Colors.RESET}")
        print(f"    ffplay {stream_url}")
        print(f"    vlc {stream_url}")
        print()

    def display_camera_status(self, camera_name: str) -> None:
        try:
            status = self.camera_manager.get_status(camera_name)
            self._print_status(status)
        except KeyError as e:
            self.display_message(str(e), "error")

    def display_event(self, event_message: str) -> None:
        print(f"{Colors.YELLOW}  ⚡ {event_message}{Colors.RESET}")

    # ── 输入处理 ────────────────────────────────

    def _auto_scan_on_startup(self) -> None:
        """启动时自动扫描网络摄像头并注册"""
        print(f"\n{Colors.CYAN}{'═' * 50}{Colors.RESET}")
        print(f"{Colors.CYAN}  \U0001F50D 自动扫描局域网摄像头...{Colors.RESET}")
        print(f"{Colors.CYAN}{'═' * 50}{Colors.RESET}\n")

        devices = discover_network_cameras()
        if devices:
            self.display_message(f"发现 {len(devices)} 个网络摄像头", "success")
            self._last_discovered_devices = devices
            self._register_discovered_devices(devices)
        else:
            existing = self.camera_manager.list_cameras()
            if existing:
                self.display_message(f"扫描未发现新设备，使用配置中的 {len(existing)} 个摄像头", "info")
            else:
                self.display_message("未发现任何摄像头，请用 /discover_net 手动扫描", "warning")
        print()

    def _connect_and_stream_all(self) -> None:
        """连接所有可用摄像头并打开所有视频流预览"""
        names = self.camera_manager.get_camera_names()
        if not names:
            self.display_message("没有可用的摄像头", "error")
            return

        connected_names = []
        for name in names:
            try:
                status = self.camera_manager.get_status(name)
                if status.is_connected:
                    connected_names.append(name)
                    continue
            except Exception:
                pass
            self.display_message(f"正在连接 {name} ...", "info")
            if self.camera_manager.connect(name):
                # 连接成功后，尝试从 ONVIF 获取真实 RTSP 路径并更新配置
                self._update_rtsp_path_from_onvif(name)
                connected_names.append(name)
                self.display_message(f"{name} 连接成功", "success")
            else:
                self.display_message(f"{name} 连接失败，跳过", "warning")

        if not connected_names:
            self.display_message("所有摄像头均连接失败", "error")
            return

        # 显示所有连接摄像头的流信息
        print(f"\n{Colors.GREEN}═══ 视频流信息 ({len(connected_names)} 个) ═══{Colors.RESET}")
        rtsp_urls = []
        for name in connected_names:
            try:
                url = self.camera_manager.get_stream_url(name)
                print(f"  摄像头: {name}")
                print(f"  RTSP地址: {Colors.BOLD}{url}{Colors.RESET}")
                print()
                rtsp_urls.append((name, url))
            except Exception as e:
                print(f"  {Colors.RED}{name}: 获取流地址失败 - {e}{Colors.RESET}")

        # 逐个打开预览窗口（每个窗口可独立关闭）
        for name, url in rtsp_urls:
            if url.startswith("rtsp://"):
                self.display_message(f"正在打开 {name} 实时预览 (按 'q' 关闭)...", "info")
                self._open_rtsp_preview(name, url)
            else:
                self.display_message(f"正在打开 {name} 实时预览 (按 'q' 关闭)...", "info")
                self._open_usb_preview(name)

    def _handle_input(self, user_input: str) -> None:
        """处理用户输入：斜杠命令 or 自然语言"""
        if user_input.startswith("/"):
            self._handle_slash_command(user_input)
        else:
            self._handle_natural_language(user_input)

    def _handle_slash_command(self, command: str) -> None:
        """处理斜杠命令"""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        command_map = {
            "/stream":      self._cmd_stream,
            "/snapshot":    self._cmd_snapshot,
            "/preview":     self._cmd_preview,
            "/status":      self._cmd_status,
            "/list":        self._cmd_list,
            "/discover":    self._cmd_discover,
            "/discover_net": self._cmd_discover_network,
            "/connect":     self._cmd_connect,
            "/password":    self._cmd_password,
            "/disconnect":  self._cmd_disconnect,
            "/ptz":         self._cmd_ptz,
            "/ptz_stop":    self._cmd_ptz_stop,
            "/ptz_zoom":    self._cmd_ptz_zoom,
            "/presets":     self._cmd_presets,
            "/devinfo":     self._cmd_devinfo,
            "/models":      self._cmd_models,
            "/clear":       self._cmd_clear,
            "/events":      self._cmd_events,
            "/probe_all":   self._cmd_probe_all,
            "/help":        self._cmd_help,
            "/quit":        self._cmd_quit,
            "/exit":        self._cmd_quit,
        }

        handler = command_map.get(cmd)
        if handler:
            handler(arg)
        else:
            self.display_message(f"未知命令: {cmd}，输入 /help 查看帮助", "warning")

    def _handle_natural_language(self, user_input: str) -> None:
        """将自然语言交给大模型处理（两阶段：对话 + 命令提取）"""
        context = self._build_camera_context()
        enriched_input = f"{context}\n用户：{user_input}" if context else user_input

        # ── Pass 1: 流式对话（用户体验）──
        print(f"{Colors.BLUE}🤖 思考中...{Colors.RESET}", end="", flush=True)

        def on_chunk(token: str):
            if on_chunk._first:
                print(f"\r{Colors.BLUE}🤖 > {Colors.RESET}", end="")
                on_chunk._first = False
            print(token, end="", flush=True)
        on_chunk._first = True

        try:
            response = self.llm_client.stream_chat(enriched_input, on_chunk)
            print()

            # 尝试从对话回复中提取 JSON 命令
            parsed = self.llm_client._extract_command(response)

            if parsed.command == "chat":
                # ── Pass 2: 专用命令提取（小模型在对话中易输出纯文本，需强制提取）──
                print(f"\n{Colors.BLUE}  ⚙ 解析意图...{Colors.RESET}", end="", flush=True)
                # Pass 2 使用极简上下文（只包含当前用户输入），避免过长 context 干扰小模型
                parsed = self.llm_client.extract_command(user_input, context="")
                if parsed.command == "chat":
                    return  # 纯聊天，无需执行
                print(f"\r  {Colors.CYAN}✓ 识别为: {parsed.command}{Colors.RESET}{' ' * 30}")
                print()  # 换行

            # LLM 只负责意图识别，参数由代码自动填充
            # 清空小模型编造的垃圾参数（set_password 除外，它需要 password 字段）
            if parsed.command not in ("set_password", "chat"):
                parsed.params = {}

            # 执行识别出的命令
            self._execute_command(parsed)

        except Exception as e:
            print()
            self.display_message(f"AI 回复出错: {e}", "error")

    def _build_camera_context(self) -> str:
        """构建当前摄像头状态上下文（极简版，避免小模型混乱）"""
        cameras = self.camera_manager.list_cameras()

        if not cameras:
            return "系统已扫描并注册了摄像头，无需指定IP或名称，系统会自动选择"

        connected = [c for c in cameras if c.is_connected]
        lines = []
        if connected:
            lines.append(f"已有 {len(connected)} 个摄像头已连接，无需指定名称，系统自动选择")
        else:
            lines.append(f"已注册 {len(cameras)} 个摄像头，均未连接")

        if not self._default_password:
            lines.append("注意: 尚未设置连接密码")

        return "\n".join(lines)

    # ── 斜杠命令实现 ────────────────────────────

    def _cmd_stream(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        try:
            status = self.camera_manager.get_status(name)
            if status.connection_type == "usb":
                # USB 摄像头：直接打开预览窗口
                self.display_message(f"正在打开 {name} 实时预览 (按 'q' 关闭)...", "info")
                self._open_usb_preview(name)
            else:
                # ONVIF 摄像头：获取 RTSP 地址并打开预览窗口
                url = self.camera_manager.get_stream_url(name)
                self.display_stream(name, url)
                # 同时打开 OpenCV 预览窗口
                self.display_message(f"正在打开 {name} 实时预览 (按 'q' 关闭)...", "info")
                self._open_rtsp_preview(name, url)
        except Exception as e:
            self.display_message(f"获取视频流失败: {e}", "error")

    def _cmd_snapshot(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        try:
            frame = self.camera_manager.get_snapshot(name)
            if frame is not None:
                # 保存到 snapshots 目录
                snap_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")
                os.makedirs(snap_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{name}_{timestamp}.jpg"
                filepath = os.path.join(snap_dir, filename)
                cv2.imwrite(filepath, frame)
                self.display_message(f"截图已保存: {filepath}", "success")
            else:
                self.display_message("获取截图失败，请确认摄像头已连接", "error")
        except Exception as e:
            self.display_message(f"获取快照失败: {e}", "error")

    def _cmd_preview(self, arg: str) -> None:
        """打开摄像头实时预览窗口 (USB 和 ONVIF 均支持)"""
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        try:
            status = self.camera_manager.get_status(name)
            if status.connection_type == "usb":
                self.display_message(f"正在打开 {name} 实时预览 (按 'q' 关闭)...", "info")
                self._open_usb_preview(name)
            else:
                url = self.camera_manager.get_stream_url(name)
                self.display_message(f"正在打开 {name} 实时预览 (按 'q' 关闭)...", "info")
                self._open_rtsp_preview(name, url)
        except Exception as e:
            self.display_message(f"打开预览失败: {e}", "error")

    def _cmd_discover_network(self, _arg: str) -> None:
        """扫描局域网 ONVIF/RTSP 摄像头，并自动注册到 CameraManager"""
        self.display_message("正在扫描局域网摄像头...", "info")
        devices = discover_network_cameras()
        if devices:
            self.display_message(f"发现 {len(devices)} 个网络摄像头", "success")
            self._last_discovered_devices = devices
            self._register_discovered_devices(devices)
        else:
            self.display_message("未发现局域网内的摄像头设备", "warning")
            self._last_discovered_devices = []

    def _register_discovered_devices(self, devices) -> None:
        """将扫描发现的设备自动注册到 CameraManager 并持久化到 config.yaml。
        只注册通过 WS-Discovery 发现并经 ONVIF 验证的真实摄像头，过滤掉路由器/NAS/打印机等非摄像头设备。"""
        from phase1.core.config import CameraConfig

        # 先清理旧的动态注册设备（以 discovered_ 开头的）
        for name in list(self.camera_manager.get_camera_names()):
            if name.startswith("discovered_"):
                self.camera_manager.remove_camera(name)

        # 只保留 WS-Discovery 发现的设备（真正的 ONVIF 设备）
        ws_devices = [d for d in devices if d.ws_discovered]
        non_ws = [d for d in devices if not d.ws_discovered]

        if non_ws:
            self.display_message(
                f"已过滤 {len(non_ws)} 个非摄像头设备（仅端口扫描发现，未响应 WS-Discovery）", "info"
            )

        registered = []
        for dev in ws_devices:
            # ONVIF 验证：确认是真正的摄像头（排除 NAS、打印机等）
            print(f"  [验证] {dev.ip}:{dev.onvif_port} ... ", end="", flush=True)
            verify_result = verify_onvif_camera(
                dev.ip, dev.onvif_port, username="admin", password=self._default_password
            )
            if not verify_result:
                print(f"✗ 非 ONVIF 摄像头，跳过")
                continue

            mfr = verify_result.get('manufacturer', '')
            model = verify_result.get('model', '')
            print(f"✓ {mfr} {model}")

            cam_name = f"discovered_{dev.ip.replace('.', '_')}"
            # 如果已经以其他名称注册了同IP，跳过
            existing_ips = [
                getattr(conn, 'config', None)
                for conn in self.camera_manager._connections.values()
                if hasattr(conn, 'config') and getattr(conn.config, 'ip', '') == dev.ip
            ]
            if existing_ips:
                continue

            # 优先使用 ONVIF 验证获取的真实品牌/型号
            device_brand = dev.brand or mfr or ""
            device_model = dev.model or model or ""

            cam_config = CameraConfig(
                name=cam_name,
                connection_type="onvif",
                ip=dev.ip,
                port=dev.onvif_port,
                username="admin",
                password=self._default_password,
                rtsp_port=dev.rtsp_port,
                rtsp_path="/stream1",
                rtsp_sub_path="/stream2",
                device_model=device_brand,
                product_version=device_model,
            )
            self.camera_manager.add_camera(cam_config)
            registered.append(cam_name)

        if registered:
            self.display_message(
                f"已注册 {len(registered)} 个摄像头: {', '.join(registered)}", "success"
            )
            # 持久化到 config.yaml
            self._persist_cameras_to_config()
            if not self._default_password:
                self.display_message(
                    "提示: 未设置密码，请用 /password <密码> 设置后连接", "warning"
                )
        else:
            self.display_message("未发现通过 ONVIF 验证的摄像头", "warning")

    def _update_rtsp_path_from_onvif(self, name: str) -> None:
        """连接成功后，从 ONVIF 获取真实 RTSP 路径并更新配置"""
        try:
            conn = self.camera_manager._connections.get(name)
            if not conn or not hasattr(conn, '_camera') or conn._camera is None:
                return  # RTSP-only 模式，无法从 ONVIF 获取
            media = conn._camera.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                return
            stream_uri = media.GetStreamUri({
                'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
                'ProfileToken': profiles[0].token,
            })
            if stream_uri and stream_uri.Uri:
                from urllib.parse import urlparse
                parsed = urlparse(stream_uri.Uri)
                real_path = parsed.path
                if real_path and real_path != conn.config.rtsp_path:
                    old_path = conn.config.rtsp_path
                    conn.config.rtsp_path = real_path
                    print(f"  [ONVIF] {name}: RTSP 路径已更新 {old_path} → {real_path}")
                    # 同步到 AppConfig 并持久化
                    self._persist_cameras_to_config()
        except Exception as e:
            print(f"  [ONVIF] {name}: 获取 RTSP 路径失败: {e}")

    def _persist_cameras_to_config(self) -> None:
        """将当前 CameraManager 中所有摄像头同步到 AppConfig 并保存到 config.yaml"""
        if not self._app_config:
            return
        # 清空旧的 cameras 列表
        self._app_config.cameras.clear()
        # 将当前所有注册的摄像头写入
        for name, conn in self.camera_manager._connections.items():
            if hasattr(conn, 'config'):
                self._app_config.cameras.append(conn.config)
        try:
            save_config(self._app_config)
            print(f"[配置] 已保存 {len(self._app_config.cameras)} 个摄像头到 config.yaml")
        except Exception as e:
            print(f"[配置] 保存失败: {e}")

    def _cmd_password(self, arg: str) -> None:
        """设置默认连接密码"""
        pwd = arg.strip()
        if not pwd:
            if self._default_password:
                self.display_message(f"当前密码: {'*' * len(self._default_password)}", "info")
            else:
                self.display_message("用法: /password <密码>", "warning")
            return
        self._default_password = pwd
        # 同步更新所有已注册摄像头的密码
        updated = self.camera_manager.update_all_passwords(pwd)
        self.display_message(f"默认密码已设置 ({len(pwd)} 位)，已同步到 {updated} 个摄像头", "success")

    def _cmd_ptz(self, arg: str) -> None:
        """PTZ 云台控制斜杠命令: /ptz up|down|left|right [速度]"""
        parts = arg.strip().split()
        if not parts:
            self.display_message("用法: /ptz up|down|left|right [速度0.1-1.0]", "warning")
            return
        direction = parts[0].lower()
        speed = float(parts[1]) if len(parts) > 1 else 0.5
        self._exec_ptz_move({"direction": direction, "speed": speed})

    def _cmd_ptz_stop(self, _arg: str) -> None:
        """停止 PTZ 移动"""
        self._exec_ptz_stop({})

    def _cmd_ptz_zoom(self, arg: str) -> None:
        """PTZ 缩放: /ptz_zoom in|out"""
        action = arg.strip() or "in"
        self._exec_ptz_zoom({"action": action, "speed": 0.5})

    def _cmd_presets(self, _arg: str) -> None:
        """列出 PTZ 预置位"""
        self._exec_list_presets({})

    def _cmd_devinfo(self, _arg: str) -> None:
        """获取 ONVIF 设备详细信息"""
        self._exec_get_device_info({})

    def _cmd_discover(self, _arg: str) -> None:
        """扫描可用的 USB 摄像头"""
        cameras = discover_usb_cameras()
        if cameras:
            print(f"\n{Colors.BOLD}═══ 发现的 USB 摄像头 ═══{Colors.RESET}")
            for cam in cameras:
                print(f"  {Colors.GREEN}●{Colors.RESET} 索引 {cam.device_index}: "
                      f"{cam.width}x{cam.height} @ {cam.fps:.0f}fps ({cam.backend})")
            print(f"\n  {Colors.BLUE}提示: 可在 config.yaml 中设置 device_index 来指定摄像头{Colors.RESET}\n")
        else:
            self.display_message("未发现可用的 USB 摄像头，请检查设备连接", "warning")

    def _cmd_status(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        self.display_camera_status(name)

    def _cmd_list(self, _arg: str) -> None:
        cameras = self.camera_manager.list_cameras()
        if not cameras:
            self.display_message("没有注册任何摄像头", "warning")
            return
        print(f"\n{Colors.BOLD}═══ 摄像头列表 ═══{Colors.RESET}")
        for cam in cameras:
            icon = f"{Colors.GREEN}●{Colors.RESET}" if cam.is_connected else f"{Colors.RED}●{Colors.RESET}"
            mode_tag = f"{Colors.CYAN}[USB]{Colors.RESET}" if cam.connection_type == "usb" else f"{Colors.YELLOW}[ONVIF]{Colors.RESET}"
            addr = f"索引:{cam.device_index}" if cam.connection_type == "usb" else cam.ip
            print(f"  {icon} {cam.name} {mode_tag} ({addr}) - {'已连接' if cam.is_connected else '未连接'}")
        print()

    def _cmd_connect(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有已注册的摄像头", "error")
            return
        self.display_message(f"正在连接 {name} ...", "info")
        success = self.camera_manager.connect(name)
        if success:
            self.display_message(f"{name} 连接成功", "success")
        else:
            self.display_message(f"{name} 连接失败", "error")

    def _cmd_disconnect(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            return
        self.camera_manager.disconnect(name)
        self.display_message(f"{name} 已断开", "success")

    def _cmd_models(self, _arg: str) -> None:
        models = self.llm_client.list_models()
        if models:
            print(f"\n{Colors.BOLD}═══ 可用模型 ═══{Colors.RESET}")
            for m in models:
                marker = " ← 当前使用" if m == self.llm_client.config.model else ""
                print(f"  • {m}{Colors.GREEN}{marker}{Colors.RESET}")
            print()
        else:
            self.display_message("无法获取模型列表，请检查 Ollama 服务", "warning")

    def _cmd_clear(self, _arg: str) -> None:
        self.llm_client.clear_history()
        self.display_message("对话历史已清空", "success")

    def _cmd_probe_all(self, _arg: str) -> None:
        """逐个尝试连接所有摄像头，汇总成功/失败结果"""
        names = self.camera_manager.get_camera_names()
        if not names:
            self.display_message("没有已注册的摄像头", "warning")
            return

        print(f"\n{Colors.BOLD}═══ 探测所有摄像头 ({len(names)} 个) ═══{Colors.RESET}")
        success_list = []
        fail_list = []

        for i, name in enumerate(names, 1):
            # 检查是否已连接
            try:
                status = self.camera_manager.get_status(name)
                if status.is_connected:
                    url = self.camera_manager.get_stream_url(name)
                    print(f"  {Colors.GREEN}[{i}/{len(names)}] ✓ {name} — 已连接{Colors.RESET}")
                    print(f"           流地址: {url}")
                    success_list.append((name, url))
                    continue
            except Exception:
                pass

            print(f"  {Colors.YELLOW}[{i}/{len(names)}] ... {name} 连接中{Colors.RESET}", end="", flush=True)
            try:
                ok = self.camera_manager.connect(name)
                if ok:
                    status = self.camera_manager.get_status(name)
                    url = self.camera_manager.get_stream_url(name)
                    res = f"{status.frame_width}x{status.frame_height}" if status.frame_width else ""
                    print(f"\r  {Colors.GREEN}[{i}/{len(names)}] ✓ {name} — 连接成功 {res}{Colors.RESET}")
                    print(f"           流地址: {url}")
                    success_list.append((name, url))
                else:
                    status = self.camera_manager.get_status(name)
                    err = status.last_error or "未知原因"
                    print(f"\r  {Colors.RED}[{i}/{len(names)}] ✗ {name} — {err}{Colors.RESET}")
                    fail_list.append((name, err))
            except Exception as e:
                print(f"\r  {Colors.RED}[{i}/{len(names)}] ✗ {name} — 异常: {e}{Colors.RESET}")
                fail_list.append((name, str(e)))

        # 汇总
        print(f"\n{Colors.BOLD}═══ 探测结果 ═══{Colors.RESET}")
        print(f"  {Colors.GREEN}成功: {len(success_list)}/{len(names)}{Colors.RESET}")
        for name, url in success_list:
            print(f"    ✓ {name}")
        if fail_list:
            print(f"  {Colors.RED}失败: {len(fail_list)}/{len(names)}{Colors.RESET}")
            for name, err in fail_list:
                print(f"    ✗ {name} — {err}")
        print()

    def _cmd_events(self, _arg: str) -> None:
        events = self.event_bus.get_history(limit=20)
        if not events:
            self.display_message("暂无事件记录", "info")
            return
        print(f"\n{Colors.BOLD}═══ 最近事件 ═══{Colors.RESET}")
        for evt in events:
            print(f"  {evt}")
        print()

    def _cmd_help(self, _arg: str) -> None:
        print(self.HELP_TEXT)

    def _cmd_quit(self, _arg: str) -> None:
        self.stop()

    # ── 命令执行器 ──────────────────────────────

    def _execute_command(self, cmd: ParsedCommand) -> None:
        """执行大模型解析出的命令"""
        executors = {
            "watch_camera":      self._exec_watch_camera,
            "take_photo":        self._exec_take_photo,
            "get_stream":        self._exec_get_stream,
            "get_snapshot":      self._exec_get_snapshot,
            "get_status":        self._exec_get_status,
            "list_cameras":      self._exec_list_cameras,
            "discover_network":  self._exec_discover_network,
            "discover_usb":      self._exec_discover_usb,
            "connect_camera":    self._exec_connect_camera,
            "disconnect_camera": self._exec_disconnect_camera,
            "open_preview":      self._exec_open_preview,
            "auto_setup":        self._exec_auto_setup,
            "set_password":      self._exec_set_password,
            "ptz_move":          self._exec_ptz_move,
            "ptz_stop":          self._exec_ptz_stop,
            "ptz_zoom":          self._exec_ptz_zoom,
            "ptz_preset":        self._exec_ptz_preset,
            "list_presets":      self._exec_list_presets,
            "get_device_info":   self._exec_get_device_info,
        }

        executor = executors.get(cmd.command)
        if executor:
            print(f"\n{Colors.CYAN}⚙ 执行命令: {cmd.command}{Colors.RESET}")
            executor(cmd.params)
        else:
            self.display_message(f"未知命令: {cmd.command}", "warning")

    # ── 智能辅助方法 ────────────────────────

    def _resolve_camera_name(self, params: dict) -> Optional[str]:
        """解析摄像头名称参数，智能纠正 IP/名称 → 已注册的摄像头名称"""
        raw = params.get("camera", "")
        if not raw:
            return self.camera_manager.get_default_camera_name()

        # 如果直接是已注册的名称，直接使用
        if raw in self.camera_manager.get_camera_names():
            return raw

        # 如果看起来像 IP 地址，转换为 discovered_ 前缀名称
        import re as _re
        if _re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', raw):
            converted = f"discovered_{raw.replace('.', '_')}"
            if converted in self.camera_manager.get_camera_names():
                return converted

        # 回退到默认摄像头
        return self.camera_manager.get_default_camera_name()

    def _ensure_connected(self, name: str) -> bool:
        """确保摄像头已连接，如果未连接则自动连接"""
        try:
            status = self.camera_manager.get_status(name)
            if status.is_connected:
                return True
            self.display_message(f"{name} 未连接，正在自动连接...", "info")
            ok = self.camera_manager.connect(name)
            if ok:
                self.display_message(f"{name} 自动连接成功", "success")
            else:
                self.display_message(f"{name} 自动连接失败", "error")
            return ok
        except Exception as e:
            self.display_message(f"检查连接状态失败: {e}", "error")
            return False

    def _ensure_any_connected(self) -> Optional[str]:
        """遍历所有摄像头，返回第一个成功连接的名称；已全部失败则返回 None"""
        names = self.camera_manager.get_camera_names()
        if not names:
            self.display_message("没有可用的摄像头", "error")
            return None

        # 优先尝试已连接的
        for name in names:
            try:
                status = self.camera_manager.get_status(name)
                if status.is_connected:
                    return name
            except Exception:
                pass

        # 逐个尝试连接
        for name in names:
            self.display_message(f"正在尝试连接 {name} ...", "info")
            if self.camera_manager.connect(name):
                self.display_message(f"{name} 连接成功", "success")
                return name
            self.display_message(f"{name} 连接失败，尝试下一个...", "warning")

        self.display_message("所有摄像头均连接失败，请检查密码和网络", "error")
        return None

    # ── 复合命令执行器 ────────────────────

    def _exec_watch_camera(self, params: dict) -> None:
        """复合命令：自动连接所有摄像头 + 拉流 + 打开预览"""
        self._connect_and_stream_all()

    def _exec_take_photo(self, params: dict) -> None:
        """复合命令：自动连接 + 截图"""
        name = self._ensure_any_connected()
        if not name:
            return
        self._cmd_snapshot(name)

    # ── 单步命令执行器 ────────────────────

    def _exec_get_stream(self, params: dict) -> None:
        """获取所有可用摄像头的视频流"""
        self._connect_and_stream_all()

    def _exec_get_snapshot(self, params: dict) -> None:
        name = self._ensure_any_connected()
        if name:
            self._cmd_snapshot(name)

    def _exec_get_status(self, params: dict) -> None:
        name = self._resolve_camera_name(params)
        self._cmd_status(name or "")

    def _exec_list_cameras(self, _params: dict) -> None:
        self._cmd_list("")

    def _exec_discover_network(self, _params: dict) -> None:
        """LLM 触发：扫描局域网摄像头"""
        self._cmd_discover_network("")

    def _exec_discover_usb(self, _params: dict) -> None:
        """LLM 触发：扫描 USB 摄像头"""
        self._cmd_discover("")

    def _exec_connect_camera(self, params: dict) -> None:
        """LLM 触发：连接摄像头"""
        name = self._resolve_camera_name(params)
        self._cmd_connect(name or "")

    def _exec_disconnect_camera(self, params: dict) -> None:
        """LLM 触发：断开摄像头"""
        name = self._resolve_camera_name(params)
        self._cmd_disconnect(name or "")

    def _exec_open_preview(self, params: dict) -> None:
        """LLM 触发：打开预览"""
        name = self._ensure_any_connected()
        if name:
            self._cmd_preview(name)

    def _exec_auto_setup(self, _params: dict) -> None:
        """LLM 触发：自动完成 发现→注册→连接→拉流 全流程"""
        print(f"\n{Colors.CYAN}{'═' * 50}{Colors.RESET}")
        print(f"{Colors.CYAN}  🚀 自动设置：发现 → 注册 → 连接 → 拉流{Colors.RESET}")
        print(f"{Colors.CYAN}{'═' * 50}{Colors.RESET}\n")

        # Step 1: 扫描局域网摄像头
        print(f"\n{Colors.BOLD}[Step 1/4] 扫描局域网摄像头...{Colors.RESET}")
        devices = discover_network_cameras()
        if not devices:
            self.display_message("未发现局域网内的摄像头，请检查网络和设备", "warning")
            return
        self.display_message(f"发现 {len(devices)} 个网络摄像头", "success")

        # Step 2: 注册所有发现的设备
        print(f"\n{Colors.BOLD}[Step 2/4] 注册发现的摄像头...{Colors.RESET}")
        self._register_discovered_devices(devices)

        # Step 3: 连接第一个注册成功的摄像头
        print(f"\n{Colors.BOLD}[Step 3/4] 尝试连接...{Colors.RESET}")
        cam_name = None
        for dev in devices:
            name = f"discovered_{dev.ip.replace('.', '_')}"
            if name in self.camera_manager.get_camera_names():
                if self.camera_manager.connect(name):
                    cam_name = name
                    self.display_message(f"{cam_name} 连接成功！", "success")
                    break
                else:
                    self.display_message(f"{name} 连接失败，尝试下一个...", "warning")

        if not cam_name:
            self.display_message("所有发现的摄像头均连接失败，请检查密码和网络", "error")
            return

        # Step 4: 拉流并打开预览
        print(f"\n{Colors.BOLD}[Step 4/4] 获取视频流并打开预览...{Colors.RESET}")
        self._cmd_stream(cam_name)

    # ── 辅助方法 ────────────────────────────────

    def _print_status(self, status: CameraStatus) -> None:
        """打印摄像头状态详情"""
        connected_color = Colors.GREEN if status.is_connected else Colors.RED
        connected_text = "已连接" if status.is_connected else "未连接"
        mode_tag = "USB" if status.connection_type == "usb" else "ONVIF"

        print(f"\n{Colors.BOLD}═══ {status.name} 状态 [{mode_tag}] ═══{Colors.RESET}")
        print(f"  连接类型:    {mode_tag}")
        print(f"  连接状态:    {connected_color}{connected_text}{Colors.RESET}")

        if status.connection_type == "usb":
            print(f"  设备索引:    {status.device_index}")
            print(f"  分辨率:      {status.frame_width}x{status.frame_height}")
            print(f"  帧率:        {status.fps:.0f} fps")
        else:
            print(f"  IP地址:      {status.ip}")
            print(f"  制造商:      {status.manufacturer or '未知'}")
            print(f"  固件版本:    {status.firmware_version or '未知'}")
            print(f"  序列号:      {status.serial_number or '未知'}")
            print(f"  流地址:      {status.stream_source or '未获取'}")

        print(f"  型号:        {status.model or '未知'}")
        print(f"  产品版本:    {status.product_version or '未知'}")
        if status.last_error:
            print(f"  {Colors.RED}最近错误:    {status.last_error}{Colors.RESET}")
        print()

    def _check_system_status(self) -> None:
        """启动时检查系统各组件状态"""
        # 检查 LLM
        backend = "本地推理" if isinstance(self.llm_client, LocalLLMClient) else "Ollama"
        if self.llm_client.is_available():
            model_info = self.llm_client.list_models()
            model_str = model_info[0] if model_info else "未知"
            self.display_message(f"LLM 后端: {backend} ({model_str})", "success")
        else:
            self.display_message(f"LLM 后端不可用 ({backend})，请检查配置", "error")

        # 检查摄像头配置
        cameras = self.camera_manager.list_cameras()
        if cameras:
            self.display_message(f"已注册 {len(cameras)} 台摄像头", "success")
        else:
            self.display_message("未注册任何摄像头，请检查 config.yaml", "warning")

    def _on_event(self, event: CameraEvent) -> None:
        """事件总线回调 - 在 CLI 中展示事件"""
        self.display_event(str(event))

    def _exec_set_password(self, params: dict) -> None:
        """LLM 触发：设置连接密码"""
        pwd = params.get("password", "")
        # 兼容嵌套格式 {"params":{"password":"xxx"}}
        if not pwd and "params" in params and isinstance(params["params"], dict):
            pwd = params["params"].get("password", "")
        if pwd:
            self._cmd_password(pwd)
        else:
            self.display_message("请告诉我密码，例如：\"密码是 123456\"", "warning")

    # ── PTZ 命令执行器 ────────────────────────

    _PTZ_DIRECTION_MAP = {
        "up":    (0.0, 1.0),
        "down":  (0.0, -1.0),
        "left":  (-1.0, 0.0),
        "right": (1.0, 0.0),
        "上": (0.0, 1.0),
        "下": (0.0, -1.0),
        "左": (-1.0, 0.0),
        "右": (1.0, 0.0),
    }

    def _exec_ptz_move(self, params: dict) -> None:
        """PTZ 云台移动：方向 + 速度"""
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        direction = params.get("direction", "").lower()
        speed = float(params.get("speed", 0.5))
        speed = max(0.1, min(1.0, speed))

        pan_tilt = self._PTZ_DIRECTION_MAP.get(direction)
        if not pan_tilt:
            self.display_message(
                f"无效方向 '{direction}'，可用: up/down/left/right/上/下/左/右", "warning"
            )
            return
        pan, tilt = pan_tilt
        ok = self.camera_manager.ptz_move(name, pan=pan, tilt=tilt, speed=speed)
        if ok:
            self.display_message(f"PTZ 移动: {direction} (速度 {speed})", "success")
            # 移动 1 秒后自动停止
            import time
            time.sleep(1.0)
            self.camera_manager.ptz_stop(name)
            self.display_message("PTZ 已自动停止", "info")
        else:
            self.display_message("PTZ 移动失败，请检查摄像头是否支持 PTZ", "error")

    def _exec_ptz_stop(self, params: dict) -> None:
        """PTZ 停止移动"""
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name:
            return
        ok = self.camera_manager.ptz_stop(name)
        if ok:
            self.display_message(f"{name} PTZ 已停止", "success")
        else:
            self.display_message("PTZ 停止失败", "error")

    def _exec_ptz_zoom(self, params: dict) -> None:
        """PTZ 缩放：放大(in) / 缩小(out)"""
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        action = params.get("action", "").lower()
        speed = float(params.get("speed", 0.5))
        speed = max(0.1, min(1.0, speed))

        if action in ("in", "放大", "zoom_in"):
            zoom = 1.0
        elif action in ("out", "缩小", "zoom_out"):
            zoom = -1.0
        else:
            self.display_message(f"无效缩放 '{action}'，可用: in/out/放大/缩小", "warning")
            return
        ok = self.camera_manager.ptz_move(name, zoom=zoom, speed=speed)
        if ok:
            self.display_message(f"PTZ 缩放: {action} (速度 {speed})", "success")
            import time
            time.sleep(1.5)
            self.camera_manager.ptz_stop(name)
            self.display_message("PTZ 已自动停止", "info")
        else:
            self.display_message("PTZ 缩放失败", "error")

    def _exec_ptz_preset(self, params: dict) -> None:
        """PTZ 跳转预置位"""
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        preset = params.get("preset", "")
        if not preset:
            self.display_message("请指定预置位名称", "warning")
            return
        ok = self.camera_manager.ptz_goto_preset(name, preset)
        if ok:
            self.display_message(f"已跳转到预置位: {preset}", "success")
        else:
            self.display_message(f"跳转预置位 '{preset}' 失败", "error")

    def _exec_list_presets(self, params: dict) -> None:
        """列出 PTZ 预置位"""
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        presets = self.camera_manager.ptz_get_presets(name)
        if not presets:
            self.display_message(f"{name} 没有预置位或不支持 PTZ", "info")
            return
        print(f"\n{Colors.BOLD}═══ {name} 预置位 ═══{Colors.RESET}")
        for p in presets:
            print(f"  {Colors.GREEN}●{Colors.RESET} {p['name']} (token: {p['token']})")
        print()

    def _exec_get_device_info(self, params: dict) -> None:
        """获取 ONVIF 设备详细信息"""
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        info = self.camera_manager.get_device_info(name)
        if not info:
            self.display_message(f"{name} 无法获取设备信息", "warning")
            return
        print(f"\n{Colors.BOLD}═══ {name} 设备信息 ═══{Colors.RESET}")
        for k, v in info.items():
            print(f"  {k}: {v}")
        print()

    def _open_usb_preview(self, camera_name: str) -> None:
        """
        打开 USB 摄像头实时预览窗口 (OpenCV imshow)。
        按 'q' 关闭窗口，按 's' 截图保存。
        """
        snap_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")
        os.makedirs(snap_dir, exist_ok=True)

        window_name = f"Camera: {camera_name}  (q:关闭  s:截图)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        frame_count = 0
        while True:
            frame = self.camera_manager.read_frame(camera_name)
            if frame is None:
                self.display_message("读取帧失败，摄像头可能已断开", "error")
                break

            cv2.imshow(window_name, frame)
            frame_count += 1

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # q 或 ESC
                break
            elif key == ord('s'):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filepath = os.path.join(snap_dir, f"{camera_name}_{timestamp}.jpg")
                cv2.imwrite(filepath, frame)
                print(f"\n  {Colors.GREEN}✓ 截图已保存: {filepath}{Colors.RESET}")

        cv2.destroyWindow(window_name)
        self.display_message(f"预览已关闭 (共读取 {frame_count} 帧)", "info")

    def _open_rtsp_preview(self, camera_name: str, rtsp_url: str) -> None:
        """
        通过 RTSP 流打开实时预览窗口。
        适用于 ONVIF / 网络摄像头。
        按 'q' 关闭窗口，按 's' 截图保存。
        """
        snap_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")
        os.makedirs(snap_dir, exist_ok=True)

        window_name = f"RTSP: {camera_name}  (q:关闭  s:截图)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            self.display_message(f"无法打开 RTSP 流: {rtsp_url}", "error")
            cv2.destroyWindow(window_name)
            return

        frame_count = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    self.display_message("读取帧失败，RTSP 流可能已断开", "error")
                    break

                cv2.imshow(window_name, frame)
                frame_count += 1

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:
                    break
                elif key == ord('s'):
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filepath = os.path.join(snap_dir, f"{camera_name}_{timestamp}.jpg")
                    cv2.imwrite(filepath, frame)
                    print(f"\n  {Colors.GREEN}✓ 截图已保存: {filepath}{Colors.RESET}")
        except Exception as e:
            self.display_message(f"预览异常: {e}", "error")
        finally:
            cap.release()
            cv2.destroyWindow(window_name)
            self.display_message(f"预览已关闭 (共读取 {frame_count} 帧)", "info")
