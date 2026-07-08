"""
phase2 - CLI 界面 - 命令行对话式摄像头控制 + SN 码认证
"""
import sys
import os
from datetime import datetime
from typing import Optional

import cv2

from phase2.core.camera import CameraManager, CameraStatus
from phase2.network.discovery import discover_usb_cameras, discover_network_cameras
from phase2.core.events import EventBus, CameraEvent, EventType
from phase2.core.auth import SNDecoder
from phase2.core.llm import LocalLLMClient, OllamaClient, ParsedCommand
from phase2.ui.base import BaseUI
from phase2.core.config import CameraConfig
from phase2.core.registration import CameraRegistrar


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
    """命令行交互界面 - Phase2"""

    BANNER = f"""
{Colors.CYAN}{Colors.BOLD}╔══════════════════════════════════════════════╗
║       Agentic Camera Control System          ║
║        智能摄像头控制系统 v0.2.0              ║
║           Phase2: SN 码认证                  ║
╚══════════════════════════════════════════════╝{Colors.RESET}
"""

    HELP_TEXT = f"""
{Colors.BOLD}可用命令：{Colors.RESET}
  {Colors.GREEN}/sn{Colors.RESET}           - 输入设备 SN 码，解码获取摄像头密码
  {Colors.GREEN}/register{Colors.RESET}     - 向远程授权服务器注册摄像头（输入SN码+发送本机IP）
  {Colors.GREEN}/stream{Colors.RESET}       - 获取视频流
  {Colors.GREEN}/snapshot{Colors.RESET}     - 截图并保存
  {Colors.GREEN}/preview{Colors.RESET}      - 打开摄像头实时预览窗口
  {Colors.GREEN}/status{Colors.RESET}       - 查看摄像头状态
  {Colors.GREEN}/list{Colors.RESET}         - 列出所有摄像头
  {Colors.GREEN}/discover{Colors.RESET}     - 扫描可用 USB 摄像头
  {Colors.GREEN}/discover_net{Colors.RESET} - 扫描局域网 ONVIF/RTSP 摄像头
  {Colors.GREEN}/connect{Colors.RESET}      - 连接摄像头
  {Colors.GREEN}/disconnect{Colors.RESET}   - 断开摄像头
  {Colors.GREEN}/models{Colors.RESET}       - 查看可用大模型
  {Colors.GREEN}/clear{Colors.RESET}        - 清空对话历史
  {Colors.GREEN}/events{Colors.RESET}       - 查看最近事件
  {Colors.GREEN}/help{Colors.RESET}         - 显示帮助信息
  {Colors.GREEN}/quit{Colors.RESET}         - 退出程序

{Colors.BLUE}直接输入自然语言即可与 AI 对话控制摄像头。{Colors.RESET}
{Colors.BLUE}输入 SN 码格式示例："我的设备SN码是 ABC123456"{Colors.RESET}
"""

    def __init__(self, camera_manager: CameraManager, llm_client,
                 event_bus: EventBus, sn_decoder: SNDecoder):
        super().__init__(camera_manager, llm_client, event_bus, sn_decoder)
        self._running = False
        self._last_discovered_devices = []
        self.registrar = CameraRegistrar()
        self.event_bus.subscribe_all(self._on_event)

    # ── 主循环 ──────────────────────────────────

    def start(self) -> None:
        self._running = True
        print(self.BANNER)

        # Phase2: 启动时提示用户输入 SN 码
        self._prompt_sn_code()

        # 摄像头远程注册提示
        self._prompt_register()

        self._check_system_status()
        print(self.HELP_TEXT)

        while self._running:
            try:
                user_input = self.get_user_input()
                if not user_input.strip():
                    continue
                self._handle_input(user_input.strip())
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[提示] 按 Ctrl+C 再次退出{Colors.RESET}")
            except EOFError:
                self.stop()

    def stop(self) -> None:
        self._running = False
        self.display_message("正在退出...", "info")
        self.camera_manager.disconnect_all()
        self.llm_client.close()
        print(f"{Colors.CYAN}再见！{Colors.RESET}")

    # ── Phase2: SN 码输入流程 ────────────────────

    def _prompt_sn_code(self) -> None:
        """启动时提示用户输入 SN 码"""
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'─' * 50}{Colors.RESET}")
        print(f"{Colors.BOLD}  Phase2: SN 码认证{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'─' * 50}{Colors.RESET}")
        print(f"  请输入设备 SN 码以获取摄像头权限。")
        print(f"  输入 {Colors.YELLOW}skip{Colors.RESET} 跳过此步骤。\n")

        while True:
            sn = input(f"  {Colors.BOLD}设备 SN 码 > {Colors.RESET}").strip()
            if not sn:
                continue
            if sn.lower() == "skip":
                self.display_message("已跳过 SN 码输入", "warning")
                break

            try:
                password = self.sn_decoder.decode(sn)
                self.display_message(f"SN 码 {sn} 解码成功 → 密码: {password}", "success")

                # 将解码的密码应用到所有未认证的摄像头
                count = self.camera_manager.apply_sn_to_all(sn)
                if count > 0:
                    self.display_message(f"已将密码应用到 {count} 台摄像头", "success")
                else:
                    self.display_message("当前没有需要认证的摄像头（可通过 /discover_net 扫描后应用）", "info")
                break
            except ValueError as e:
                self.display_message(str(e), "error")
            except Exception as e:
                self.display_message(f"SN 码解码失败: {e}", "error")

        print(f"{Colors.CYAN}{'─' * 50}{Colors.RESET}\n")

    def _cmd_input_sn(self, arg: str) -> None:
        """斜杠命令：手动输入 SN 码"""
        sn = arg.strip() if arg.strip() else ""
        if not sn:
            sn = input(f"  {Colors.BOLD}请输入设备 SN 码 > {Colors.RESET}").strip()
        if not sn:
            self.display_message("SN 码不能为空", "error")
            return
        try:
            password = self.sn_decoder.decode(sn)
            self.display_message(f"SN 码 {sn} 解码成功 → 密码: {password}", "success")
            count = self.camera_manager.apply_sn_to_all(sn)
            if count > 0:
                self.display_message(f"已将密码应用到 {count} 台摄像头", "success")
            else:
                self.display_message("当前没有需要认证的摄像头", "info")
        except Exception as e:
            self.display_message(f"SN 码处理失败: {e}", "error")

    # ── 摄像头远程注册 ──────────────────────────

    def _prompt_register(self) -> None:
        """启动时提示用户是否注册摄像头到远程授权服务器"""
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'─' * 50}{Colors.RESET}")
        print(f"{Colors.BOLD}  摄像头远程注册{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'─' * 50}{Colors.RESET}")
        print(f"  向远程授权服务器注册摄像头设备（发送本机IP和设备SN码）。")
        print(f"  输入 {Colors.YELLOW}skip{Colors.RESET} 跳过此步骤。\n")

        while True:
            choice = input(f"  {Colors.BOLD}是否注册摄像头？(y/skip) > {Colors.RESET}").strip().lower()
            if choice in ("skip", "n", ""):
                self.display_message("已跳过摄像头注册", "info")
                break
            if choice in ("y", "yes"):
                self._cmd_register("")
                break
            self.display_message("请输入 y 或 skip", "warning")

        print(f"{Colors.CYAN}{'─' * 50}{Colors.RESET}\n")

    def _cmd_register(self, arg: str) -> None:
        """斜杠命令：向远程授权服务器注册摄像头"""
        sn = arg.strip() if arg.strip() else ""
        if not sn:
            sn = input(f"  {Colors.BOLD}请输入设备 SN 码 > {Colors.RESET}").strip()
        if not sn:
            self.display_message("SN 码不能为空", "error")
            return
        try:
            result = self.registrar.register(sn)
            self.display_message("摄像头注册成功！", "success")
            if isinstance(result, dict):
                for k, v in result.items():
                    print(f"  {Colors.CYAN}{k}{Colors.RESET}: {v}")
        except ValueError as e:
            self.display_message(str(e), "error")
        except Exception as e:
            self.display_message(f"注册失败: {e}", "error")

    # ── UI 接口实现 ─────────────────────────────

    def display_message(self, message: str, level: str = "info") -> None:
        color_map = {"info": Colors.BLUE, "warning": Colors.YELLOW,
                     "error": Colors.RED, "success": Colors.GREEN}
        color = color_map.get(level, Colors.RESET)
        prefix = {"info": "ℹ", "warning": "⚠", "error": "✗", "success": "✓"}.get(level, "•")
        print(f"{color}{prefix} {message}{Colors.RESET}")

    def get_user_input(self, prompt: str = "") -> str:
        prompt = prompt or f"{Colors.BOLD}{Colors.CYAN}📷 > {Colors.RESET}"
        return input(prompt)

    def display_stream(self, camera_name: str, stream_url: str) -> None:
        print(f"\n{Colors.GREEN}═══ 视频流信息 ═══{Colors.RESET}")
        print(f"  摄像头: {camera_name}")
        print(f"  RTSP地址: {Colors.BOLD}{stream_url}{Colors.RESET}")
        print(f"\n  {Colors.BLUE}提示: 可使用 VLC/ffplay 播放{Colors.RESET}\n")

    def display_camera_status(self, camera_name: str) -> None:
        try:
            status = self.camera_manager.get_status(camera_name)
            self._print_status(status)
        except KeyError as e:
            self.display_message(str(e), "error")

    def display_event(self, event_message: str) -> None:
        print(f"{Colors.YELLOW}  ⚡ {event_message}{Colors.RESET}")

    # ── 输入处理 ────────────────────────────────

    def _handle_input(self, user_input: str) -> None:
        if user_input.startswith("/"):
            self._handle_slash_command(user_input)
        else:
            self._handle_natural_language(user_input)

    def _handle_slash_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        command_map = {
            "/sn":          self._cmd_input_sn,
            "/register":    self._cmd_register,
            "/stream":      self._cmd_stream,
            "/snapshot":    self._cmd_snapshot,
            "/preview":     self._cmd_preview,
            "/status":      self._cmd_status,
            "/list":        self._cmd_list,
            "/discover":    self._cmd_discover,
            "/discover_net": self._cmd_discover_network,
            "/connect":     self._cmd_connect,
            "/disconnect":  self._cmd_disconnect,
            "/models":      self._cmd_models,
            "/clear":       self._cmd_clear,
            "/events":      self._cmd_events,
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
        context = self._build_camera_context()
        enriched_input = f"{context}\n用户：{user_input}" if context else user_input

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
            parsed = self.llm_client._extract_command(response)
            if parsed.command != "chat":
                self._execute_command(parsed)
        except Exception as e:
            print()
            self.display_message(f"AI 回复出错: {e}", "error")

    def _build_camera_context(self) -> str:
        cameras = self.camera_manager.list_cameras()
        if not cameras:
            return ""
        lines = ["当前摄像头状态："]
        for cam in cameras:
            status = "已连接" if cam.is_connected else "未连接"
            auth = "已认证" if cam.is_authenticated else "未认证"
            lines.append(f"- {cam.name} [{cam.connection_type}] {status} {auth}")
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
                self.display_message(f"正在打开 {name} 实时预览 (按 'q' 关闭)...", "info")
                self._open_usb_preview(name)
            else:
                url = self.camera_manager.get_stream_url(name)
                self.display_stream(name, url)
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
                snap_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")
                os.makedirs(snap_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filepath = os.path.join(snap_dir, f"{name}_{timestamp}.jpg")
                cv2.imwrite(filepath, frame)
                self.display_message(f"截图已保存: {filepath}", "success")
            else:
                self.display_message("获取截图失败，请确认摄像头已连接", "error")
        except Exception as e:
            self.display_message(f"获取快照失败: {e}", "error")

    def _cmd_preview(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        try:
            status = self.camera_manager.get_status(name)
            if status.connection_type == "usb":
                self._open_usb_preview(name)
            else:
                url = self.camera_manager.get_stream_url(name)
                self._open_rtsp_preview(name, url)
        except Exception as e:
            self.display_message(f"打开预览失败: {e}", "error")

    def _cmd_discover_network(self, _arg: str) -> None:
        self.display_message("正在扫描局域网摄像头...", "info")
        devices = discover_network_cameras()
        if devices:
            self.display_message(f"发现 {len(devices)} 个网络摄像头", "success")
            self._last_discovered_devices = devices
            # 提示输入 SN 码
            print(f"\n  {Colors.BLUE}提示: 发现摄像头后需要输入 SN 码获取密码{Colors.RESET}")
            print(f"  使用 {Colors.GREEN}/sn <SN码>{Colors.RESET} 或自然语言告诉 AI\n")
        else:
            self.display_message("未发现局域网内的摄像头设备", "warning")
            self._last_discovered_devices = []

    def _cmd_discover(self, _arg: str) -> None:
        cameras = discover_usb_cameras()
        if not cameras:
            self.display_message("未发现可用的 USB 摄像头", "warning")

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
            auth_tag = f"{Colors.GREEN}[已认证]{Colors.RESET}" if cam.is_authenticated else f"{Colors.RED}[未认证]{Colors.RESET}"
            addr = f"索引:{cam.device_index}" if cam.connection_type == "usb" else cam.ip
            print(f"  {icon} {cam.name} {mode_tag} {auth_tag} ({addr}) - {'已连接' if cam.is_connected else '未连接'}")
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
            self.display_message(f"{name} 连接失败，请检查 SN 码和密码", "error")

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
                print(f"  • {m}")
            print()
        else:
            self.display_message("无法获取模型列表", "warning")

    def _cmd_clear(self, _arg: str) -> None:
        self.llm_client.clear_history()
        self.display_message("对话历史已清空", "success")

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
        executors = {
            "input_sn":          self._exec_input_sn,
            "register_camera":   self._exec_register_camera,
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
        }
        executor = executors.get(cmd.command)
        if executor:
            print(f"\n{Colors.CYAN}⚙ 执行命令: {cmd.command}{Colors.RESET}")
            executor(cmd.params)
        else:
            self.display_message(f"未知命令: {cmd.command}", "warning")

    # ── 智能辅助 ──────────────────────────────

    def _ensure_connected(self, name: str) -> bool:
        try:
            status = self.camera_manager.get_status(name)
            if status.is_connected:
                return True
            self.display_message(f"{name} 未连接，正在自动连接...", "info")
            ok = self.camera_manager.connect(name)
            if ok:
                self.display_message(f"{name} 自动连接成功", "success")
            else:
                self.display_message(f"{name} 自动连接失败，请检查 SN 码认证", "error")
            return ok
        except Exception as e:
            self.display_message(f"检查连接状态失败: {e}", "error")
            return False

    # ── Phase2: SN 码 LLM 命令执行器 ────────────

    def _exec_input_sn(self, params: dict) -> None:
        """LLM 触发：用户通过自然语言输入 SN 码"""
        sn = params.get("sn", "").strip()
        if not sn:
            # 交互式提示用户输入
            sn = input(f"\n  {Colors.BOLD}请输入设备 SN 码 > {Colors.RESET}").strip()
        if not sn:
            self.display_message("SN 码不能为空", "error")
            return
        try:
            password = self.sn_decoder.decode(sn)
            self.display_message(f"SN 码解码成功 → 密码: {password}", "success")
            # 缓存
            self.sn_decoder.decode_and_cache(sn)
            # 应用到所有摄像头
            count = self.camera_manager.apply_sn_to_all(sn)
            if count > 0:
                self.display_message(f"已将密码应用到 {count} 台摄像头", "success")
            else:
                # 如果没有已注册的摄像头，提示扫描
                self.display_message("当前没有需要认证的摄像头。是否扫描局域网？", "info")
                if self._last_discovered_devices:
                    self._register_discovered_devices(sn)
        except Exception as e:
            self.display_message(f"SN 码处理失败: {e}", "error")

    def _exec_register_camera(self, params: dict) -> None:
        """LLM 触发：用户通过自然语言注册摄像头到远程授权服务器"""
        sn = params.get("sn", "").strip()
        self._cmd_register(sn)

    def _register_discovered_devices(self, sn_code: str) -> None:
        """将扫描到的设备注册到 CameraManager，并应用 SN 密码"""
        password = self.sn_decoder.get_password(sn_code)
        for dev in self._last_discovered_devices:
            cam_name = f"camera_{dev.ip.replace('.', '_')}"
            if cam_name not in self.camera_manager.get_camera_names():
                cam_config = CameraConfig(
                    name=cam_name, connection_type="onvif",
                    ip=dev.ip, port=dev.onvif_port,
                    username="admin", password=password,
                    sn_code=sn_code,
                    rtsp_port=dev.rtsp_port,
                    rtsp_path="/stream1", rtsp_sub_path="/stream2",
                )
                self.camera_manager.add_camera(cam_config)
                self.display_message(f"已注册: {cam_name} ({dev.ip})", "success")

    # ── 复合命令执行器 ────────────────────

    def _exec_watch_camera(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        if not self._ensure_connected(name):
            return
        self._cmd_stream(name)

    def _exec_take_photo(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        if not self._ensure_connected(name):
            return
        self._cmd_snapshot(name)

    def _exec_get_stream(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        self._cmd_stream(name)

    def _exec_get_snapshot(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        self._cmd_snapshot(name)

    def _exec_get_status(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        self._cmd_status(name or "")

    def _exec_list_cameras(self, _params: dict) -> None:
        self._cmd_list("")

    def _exec_discover_network(self, _params: dict) -> None:
        self._cmd_discover_network("")

    def _exec_discover_usb(self, _params: dict) -> None:
        self._cmd_discover("")

    def _exec_connect_camera(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        self._cmd_connect(name or "")

    def _exec_disconnect_camera(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        self._cmd_disconnect(name or "")

    def _exec_open_preview(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        self._cmd_preview(name)

    def _exec_auto_setup(self, _params: dict) -> None:
        """自动完成 发现→SN认证→连接→拉流 全流程"""
        print(f"\n{Colors.CYAN}{'═' * 50}{Colors.RESET}")
        print(f"{Colors.CYAN}  🚀 自动设置：发现 → SN认证 → 连接 → 拉流{Colors.RESET}")
        print(f"{Colors.CYAN}{'═' * 50}{Colors.RESET}\n")

        # Step 1: 扫描
        print(f"\n{Colors.BOLD}[Step 1/4] 扫描局域网摄像头...{Colors.RESET}")
        devices = discover_network_cameras()
        if not devices:
            self.display_message("未发现局域网内的摄像头", "warning")
            return
        self.display_message(f"发现 {len(devices)} 个网络摄像头", "success")

        # Step 2: SN 认证
        print(f"\n{Colors.BOLD}[Step 2/4] SN 码认证...{Colors.RESET}")
        sn_code = ""
        cached = self.sn_decoder.list_cached()
        if cached:
            sn_code = next(iter(cached))
            self.display_message(f"使用已缓存的 SN 码: {sn_code}", "info")
        else:
            sn_code = input(f"  {Colors.BOLD}请输入设备 SN 码 > {Colors.RESET}").strip()
            if not sn_code:
                self.display_message("SN 码不能为空，自动设置终止", "error")
                return

        password = self.sn_decoder.decode(sn_code)
        self.sn_decoder.decode_and_cache(sn_code)
        self.display_message(f"SN 码解码成功", "success")

        # Step 3: 注册并连接
        print(f"\n{Colors.BOLD}[Step 3/4] 注册并连接摄像头...{Colors.RESET}")
        target = devices[0]
        cam_name = f"camera_{target.ip.replace('.', '_')}"
        cam_config = CameraConfig(
            name=cam_name, connection_type="onvif",
            ip=target.ip, port=target.onvif_port,
            username="admin", password=password,
            sn_code=sn_code,
            rtsp_port=target.rtsp_port,
            rtsp_path="/stream1", rtsp_sub_path="/stream2",
        )
        if cam_name not in self.camera_manager.get_camera_names():
            self.camera_manager.add_camera(cam_config)

        success = self.camera_manager.connect(cam_name)
        if not success:
            self.display_message(f"连接 {cam_name} 失败，尝试其他设备...", "warning")
            for dev in devices[1:]:
                alt_name = f"camera_{dev.ip.replace('.', '_')}"
                alt_config = CameraConfig(
                    name=alt_name, connection_type="onvif",
                    ip=dev.ip, port=dev.onvif_port,
                    username="admin", password=password,
                    sn_code=sn_code,
                    rtsp_port=dev.rtsp_port,
                    rtsp_path="/stream1", rtsp_sub_path="/stream2",
                )
                if alt_name not in self.camera_manager.get_camera_names():
                    self.camera_manager.add_camera(alt_config)
                if self.camera_manager.connect(alt_name):
                    cam_name = alt_name
                    success = True
                    break
            if not success:
                self.display_message("所有发现的摄像头均连接失败", "error")
                return

        self.display_message(f"{cam_name} 连接成功！", "success")

        # Step 4: 拉流
        print(f"\n{Colors.BOLD}[Step 4/4] 获取视频流并打开预览...{Colors.RESET}")
        self._cmd_stream(cam_name)

    # ── 辅助方法 ────────────────────────────────

    def _print_status(self, status: CameraStatus) -> None:
        connected_color = Colors.GREEN if status.is_connected else Colors.RED
        connected_text = "已连接" if status.is_connected else "未连接"
        auth_color = Colors.GREEN if status.is_authenticated else Colors.RED
        auth_text = "已认证" if status.is_authenticated else "未认证"
        mode_tag = "USB" if status.connection_type == "usb" else "ONVIF"

        print(f"\n{Colors.BOLD}═══ {status.name} 状态 [{mode_tag}] ═══{Colors.RESET}")
        print(f"  连接类型:    {mode_tag}")
        print(f"  连接状态:    {connected_color}{connected_text}{Colors.RESET}")
        print(f"  认证状态:    {auth_color}{auth_text}{Colors.RESET}")

        if status.connection_type == "usb":
            print(f"  设备索引:    {status.device_index}")
            print(f"  分辨率:      {status.frame_width}x{status.frame_height}")
            print(f"  帧率:        {status.fps:.0f} fps")
        else:
            print(f"  IP地址:      {status.ip}")
            print(f"  制造商:      {status.manufacturer or '未知'}")
            print(f"  序列号:      {status.serial_number or '未知'}")
            print(f"  流地址:      {status.stream_source or '未获取'}")

        print(f"  型号:        {status.model or '未知'}")
        if status.last_error:
            print(f"  {Colors.RED}最近错误:    {status.last_error}{Colors.RESET}")
        print()

    def _check_system_status(self) -> None:
        backend = "本地推理" if isinstance(self.llm_client, LocalLLMClient) else "Ollama"
        if self.llm_client.is_available():
            model_info = self.llm_client.list_models()
            model_str = model_info[0] if model_info else "未知"
            self.display_message(f"LLM 后端: {backend} ({model_str})", "success")
        else:
            self.display_message(f"LLM 后端不可用 ({backend})", "error")

        cameras = self.camera_manager.list_cameras()
        if cameras:
            self.display_message(f"已注册 {len(cameras)} 台摄像头", "success")
        else:
            self.display_message("未注册任何摄像头（可通过 /discover_net 扫描）", "warning")

        # SN 解码器状态
        cached = self.sn_decoder.list_cached()
        if cached:
            self.display_message(f"SN 缓存: {len(cached)} 条记录", "success")

        # 注册服务器状态
        if self.registrar.is_configured():
            self.display_message(f"授权服务器: {self.registrar.server_url}", "success")
        else:
            self.display_message("授权服务器未配置（编辑 auth_server.yaml）", "warning")

    def _on_event(self, event: CameraEvent) -> None:
        self.display_event(str(event))

    def _open_usb_preview(self, camera_name: str) -> None:
        snap_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        window_name = f"Camera: {camera_name}  (q:关闭  s:截图)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        frame_count = 0
        while True:
            frame = self.camera_manager.read_frame(camera_name)
            if frame is None:
                self.display_message("读取帧失败", "error")
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
        cv2.destroyWindow(window_name)

    def _open_rtsp_preview(self, camera_name: str, rtsp_url: str) -> None:
        snap_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        window_name = f"RTSP: {camera_name}  (q:关闭  s:截图)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            self.display_message(f"无法打开 RTSP 流: {rtsp_url}", "error")
            return
        frame_count = 0
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
        cap.release()
        cv2.destroyWindow(window_name)
