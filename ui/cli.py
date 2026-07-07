"""
CLI 界面 - 命令行对话式摄像头控制
"""
import sys
from typing import Optional

from camera import CameraManager, CameraStatus
from events import EventBus, CameraEvent, EventType
from llm import OllamaClient, ParsedCommand
from ui.base import BaseUI


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
"""

    HELP_TEXT = f"""
{Colors.BOLD}可用命令：{Colors.RESET}
  {Colors.GREEN}/stream{Colors.RESET}       - 获取视频流地址
  {Colors.GREEN}/snapshot{Colors.RESET}     - 获取截图地址
  {Colors.GREEN}/status{Colors.RESET}       - 查看摄像头状态
  {Colors.GREEN}/list{Colors.RESET}         - 列出所有摄像头
  {Colors.GREEN}/connect{Colors.RESET}      - 连接摄像头
  {Colors.GREEN}/disconnect{Colors.RESET}   - 断开摄像头
  {Colors.GREEN}/models{Colors.RESET}       - 查看可用大模型
  {Colors.GREEN}/clear{Colors.RESET}        - 清空对话历史
  {Colors.GREEN}/events{Colors.RESET}       - 查看最近事件
  {Colors.GREEN}/help{Colors.RESET}         - 显示帮助信息
  {Colors.GREEN}/quit{Colors.RESET}         - 退出程序

{Colors.BLUE}直接输入自然语言即可与 AI 对话控制摄像头。{Colors.RESET}
"""

    def __init__(self, camera_manager: CameraManager, llm_client: OllamaClient, event_bus: EventBus):
        super().__init__(camera_manager, llm_client, event_bus)
        self._running = False

        # 注册全局事件监听 - 在 CLI 中打印事件通知
        self.event_bus.subscribe_all(self._on_event)

    # ── 主循环 ──────────────────────────────────

    def start(self) -> None:
        """启动 CLI 主循环"""
        self._running = True
        print(self.BANNER)
        self._check_system_status()
        print(self.HELP_TEXT)

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
        return input(prompt)

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
            "/stream":     self._cmd_stream,
            "/snapshot":   self._cmd_snapshot,
            "/status":     self._cmd_status,
            "/list":       self._cmd_list,
            "/connect":    self._cmd_connect,
            "/disconnect": self._cmd_disconnect,
            "/models":     self._cmd_models,
            "/clear":      self._cmd_clear,
            "/events":     self._cmd_events,
            "/help":       self._cmd_help,
            "/quit":       self._cmd_quit,
            "/exit":       self._cmd_quit,
        }

        handler = command_map.get(cmd)
        if handler:
            handler(arg)
        else:
            self.display_message(f"未知命令: {cmd}，输入 /help 查看帮助", "warning")

    def _handle_natural_language(self, user_input: str) -> None:
        """将自然语言交给大模型处理"""
        print(f"{Colors.BLUE}🤖 思考中...{Colors.RESET}", end="", flush=True)

        def on_chunk(token: str):
            # 首次输出时换行并清掉 "思考中..."
            if on_chunk._first:
                print(f"\r{Colors.BLUE}🤖 > {Colors.RESET}", end="")
                on_chunk._first = False
            print(token, end="", flush=True)
        on_chunk._first = True

        try:
            response = self.llm_client.stream_chat(user_input, on_chunk)
            print()  # 换行

            # 尝试解析为命令并执行
            parsed = self.llm_client._extract_command(response)
            if parsed.command != "chat":
                self._execute_command(parsed)

        except Exception as e:
            print()
            self.display_message(f"AI 回复出错: {e}", "error")

    # ── 斜杠命令实现 ────────────────────────────

    def _cmd_stream(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        try:
            url = self.camera_manager.get_stream_url(name)
            self.display_stream(name, url)
        except Exception as e:
            self.display_message(f"获取视频流失败: {e}", "error")

    def _cmd_snapshot(self, arg: str) -> None:
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self.display_message("没有可用的摄像头", "error")
            return
        try:
            url = self.camera_manager.get_snapshot_url(name)
            if url:
                print(f"  快照地址: {Colors.BOLD}{url}{Colors.RESET}")
            else:
                self.display_message("该摄像头不支持快照功能", "warning")
        except Exception as e:
            self.display_message(f"获取快照失败: {e}", "error")

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
            print(f"  {icon} {cam.name} ({cam.ip}) - {'已连接' if cam.is_connected else '未连接'}")
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
            "get_stream":   self._exec_get_stream,
            "get_snapshot": self._exec_get_snapshot,
            "get_status":   self._exec_get_status,
            "list_cameras": self._exec_list_cameras,
        }

        executor = executors.get(cmd.command)
        if executor:
            print(f"\n{Colors.CYAN}⚙ 执行命令: {cmd.command}{Colors.RESET}")
            executor(cmd.params)
        else:
            self.display_message(f"未知命令: {cmd.command}", "warning")

    def _exec_get_stream(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        self._cmd_stream(name or "")

    def _exec_get_snapshot(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        self._cmd_snapshot(name or "")

    def _exec_get_status(self, params: dict) -> None:
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        self._cmd_status(name or "")

    def _exec_list_cameras(self, _params: dict) -> None:
        self._cmd_list("")

    # ── 辅助方法 ────────────────────────────────

    def _print_status(self, status: CameraStatus) -> None:
        """打印摄像头状态详情"""
        connected_color = Colors.GREEN if status.is_connected else Colors.RED
        connected_text = "已连接" if status.is_connected else "未连接"

        print(f"\n{Colors.BOLD}═══ {status.name} 状态 ═══{Colors.RESET}")
        print(f"  IP地址:      {status.ip}")
        print(f"  连接状态:    {connected_color}{connected_text}{Colors.RESET}")
        print(f"  制造商:      {status.manufacturer or '未知'}")
        print(f"  型号:        {status.model or '未知'}")
        print(f"  固件版本:    {status.firmware_version or '未知'}")
        print(f"  序列号:      {status.serial_number or '未知'}")
        print(f"  RTSP地址:    {status.rtsp_url or '未获取'}")
        if status.last_error:
            print(f"  {Colors.RED}最近错误:    {status.last_error}{Colors.RESET}")
        print()

    def _check_system_status(self) -> None:
        """启动时检查系统各组件状态"""
        # 检查 Ollama
        if self.llm_client.is_available():
            self.display_message(f"Ollama 服务已连接 ({self.llm_client.config.model})", "success")
        else:
            self.display_message(f"Ollama 服务不可用，请确认已启动: {self.llm_client.config.base_url}", "error")

        # 检查摄像头配置
        cameras = self.camera_manager.list_cameras()
        if cameras:
            self.display_message(f"已注册 {len(cameras)} 台摄像头", "success")
        else:
            self.display_message("未注册任何摄像头，请检查 config.yaml", "warning")

    def _on_event(self, event: CameraEvent) -> None:
        """事件总线回调 - 在 CLI 中展示事件"""
        self.display_event(str(event))
