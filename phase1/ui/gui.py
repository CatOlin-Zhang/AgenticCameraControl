"""
GUI 界面 - Agent 风格的智能摄像头控制界面
基于 PySide6 实现，支持：
  - 对话式 AI 交互（流式输出）
  - 思考过程展示（可折叠，淡灰色）
  - 工具调用可视化
  - Todo/Workflow 状态追踪
  - 摄像头状态侧边栏
"""
import io
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import (
    Qt, Signal, QThread, QObject, QTimer, QSize, QUrl
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QIcon, QAction, QTextCursor, QKeySequence
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QSplitter,
    QScrollArea, QFrame, QStatusBar, QMessageBox, QInputDialog,
    QSizePolicy, QMenu
)

from phase1.core.camera import CameraManager, CameraStatus
from phase1.core.config import save_config, AppConfig, CameraConfig
from phase1.core.events import EventBus, CameraEvent
from phase1.core.llm import OllamaClient, LocalLLMClient, ParsedCommand
from phase1.network.discovery import (
    discover_network_cameras, discover_usb_cameras, verify_onvif_camera,
)
from phase1.ui.base import BaseUI


# ──────────────────────────────────────────────
#  样式表
# ──────────────────────────────────────────────
STYLESHEET = """
QMainWindow {
    background-color: #f7f8fa;
}
QSplitter::handle {
    background-color: #e2e4e8;
    width: 1px;
}
#ChatDisplay {
    background-color: #ffffff;
    border: none;
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13.5px;
    line-height: 1.65;
    padding: 16px 20px;
    color: #1a1a1a;
    selection-background-color: #c8d6f8;
}
#InputField {
    background-color: #ffffff;
    border: 1.5px solid #d0d4da;
    border-radius: 10px;
    padding: 11px 16px;
    font-size: 13.5px;
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
    color: #1a1a1a;
}
#InputField:focus {
    border: 1.5px solid #4a8af4;
}
#SendBtn {
    background-color: #4a8af4;
    color: white;
    border: none;
    border-radius: 10px;
    padding: 10px 22px;
    font-size: 13.5px;
    font-weight: 500;
    min-width: 76px;
}
#SendBtn:hover { background-color: #3b7ae0; }
#SendBtn:pressed { background-color: #2e6bd0; }
#SendBtn:disabled { background-color: #bcc3cf; }
#Sidebar {
    background-color: #f0f2f5;
    border-left: 1px solid #e2e4e8;
}
#SidebarTitle {
    font-size: 14px;
    font-weight: 600;
    color: #2c3e50;
    padding: 18px 16px 8px 16px;
}
.SidebarBtn {
    background-color: transparent;
    border: 1px solid #d0d4da;
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 12.5px;
    color: #34495e;
    text-align: left;
}
.SidebarBtn:hover {
    background-color: #e8ecf0;
    border-color: #4a8af4;
    color: #4a8af4;
}
#HeaderBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e2e4e8;
    padding: 10px 20px;
}
#HeaderTitle {
    font-size: 16px;
    font-weight: 700;
    color: #1a1a2e;
}
#HeaderSub {
    font-size: 11.5px;
    color: #8899aa;
}
#InputBar {
    background-color: #ffffff;
    border-top: 1px solid #e2e4e8;
    padding: 12px 20px;
}
#StatusBar {
    background-color: #f0f2f5;
    border-top: 1px solid #e2e4e8;
    color: #7f8c8d;
    font-size: 11.5px;
    padding: 4px 16px;
}
#CameraCard {
    background-color: #ffffff;
    border: 1px solid #e2e4e8;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 4px 12px;
}
#CameraName {
    font-size: 12.5px;
    font-weight: 600;
    color: #2c3e50;
}
#CameraStatus {
    font-size: 11px;
    color: #7f8c8d;
}
"""


# ──────────────────────────────────────────────
#  HTML 工具
# ──────────────────────────────────────────────
def _esc(text: str) -> str:
    """HTML 转义"""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
            .replace("  ", "&nbsp;&nbsp;"))


def _user_bubble_html(text: str) -> str:
    """用户消息 - 右对齐蓝色气泡（用 table 实现右对齐）"""
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="margin:8px 0 6px 0; border:none;">'
        '<tr><td width="25%"></td>'
        '<td align="right" style="padding:0;">'
        '<table cellpadding="0" cellspacing="0" style="border:none;">'
        '<tr><td style="'
        'background-color:#4a8af4; color:#ffffff; '
        'padding:10px 16px; border-radius:16px 16px 4px 16px; '
        'font-size:13.5px; line-height:1.6; '
        'word-wrap:break-word;">'
        f'{_esc(text)}'
        '</td></tr></table>'
        '</td></tr></table>'
    )


def _ai_wrapper_start() -> str:
    """AI 回复区域开始 - 左对齐（用 table 实现左对齐）"""
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="margin:6px 0 4px 0; border:none;">'
        '<tr><td width="85%" style="padding:0; vertical-align:top;">'
    )


def _ai_wrapper_end() -> str:
    """AI 回复区域结束"""
    return '</td><td width="15%"></td></tr></table>'


def _debug_block_html(title: str, body: str, icon: str = "\u2699") -> str:
    """调试信息块 - 淡灰色小字，用简单 div 代替 details/summary"""
    safe_title = _esc(title)
    if body:
        safe_body = _esc(body)
        return (
            f'<div style="color:#9ca3af; font-size:11.5px; '
            f'margin:3px 0; padding:4px 10px; '
            f'border-left:2px solid #e5e7eb; '
            f'font-family:Consolas,monospace;">'
            f'{icon} <b>{safe_title}</b><br>'
            f'{safe_body}</div>'
        )
    else:
        return (
            f'<div style="color:#9ca3af; font-size:11.5px; '
            f'margin:3px 0; padding:2px 0;">'
            f'{icon} {safe_title} <span style="color:#d1d5db;">\u2713</span></div>'
        )


def _todo_html(todos: list) -> str:
    """Todo/Workflow 列表"""
    if not todos:
        return ""
    items = []
    for t in todos:
        status = t.get("status", "pending")
        label = t.get("label", "")
        if status == "done":
            items.append(
                f'<font color="#22c55e">\u2713</font> '
                f'<font color="#9ca3af"><s>{_esc(label)}</s></font>')
        elif status == "running":
            items.append(
                f'<font color="#f59e0b">\u23f3</font> '
                f'<font color="#6b7280">{_esc(label)}</font>')
        elif status == "error":
            items.append(
                f'<font color="#ef4444">\u2717</font> '
                f'<font color="#ef4444">{_esc(label)}</font>')
        else:
            items.append(
                f'<font color="#94a3b8">\u25cb</font> '
                f'<font color="#94a3b8">{_esc(label)}</font>')
    return (
        '<div style="background-color:#f8fafc; border:1px solid #e2e8f0; '
        'padding:8px 12px; margin:4px 0 6px 0; font-size:12px;">'
        '<b><font color="#475569">\U0001f4cb Workflow</font></b><br>'
        + '<br>'.join(items) +
        '</div>'
    )


def _response_html(text: str) -> str:
    """AI 正式回复内容 - 黑色字体"""
    return (
        f'<div style="color:#1a1a1a; font-size:13.5px; line-height:1.7; '
        f'margin:4px 0 2px 0; word-wrap:break-word;">'
        f'{_esc(text)}</div>'
    )


def _system_msg_html(text: str, color: str = "#94a3b8") -> str:
    """系统消息 - 居中显示"""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:6px 0; border:none;">'
        f'<tr><td align="center" style="font-size:11.5px; '
        f'color:{color}; padding:2px 0;">'
        f'{_esc(text)}</td></tr></table>'
    )


# ──────────────────────────────────────────────
#  命令名称中文映射
# ──────────────────────────────────────────────
COMMAND_LABELS = {
    "discover_network": "扫描局域网摄像头",
    "connect_camera": "连接摄像头",
    "disconnect_camera": "断开摄像头",
    "watch_camera": "连接并拉流预览",
    "get_stream": "获取视频流",
    "take_photo": "截图保存",
    "open_preview": "打开预览",
    "get_status": "查看状态",
    "list_cameras": "列出摄像头",
    "set_password": "设置密码",
    "auto_setup": "自动设置全流程",
    "ptz_move": "PTZ 云台移动",
    "ptz_stop": "PTZ 停止",
    "ptz_zoom": "PTZ 缩放",
    "ptz_preset": "PTZ 预置位",
    "list_presets": "列出预置位",
    "get_device_info": "获取设备信息",
    "discover_usb": "扫描 USB 摄像头",
    "chat": "对话",
}


# ──────────────────────────────────────────────
#  LLM Worker（后台线程）
# ──────────────────────────────────────────────
class LLMWorker(QObject):
    """后台处理 LLM 推理 + 命令执行，通过信号驱动 UI 更新"""
    thinking_started = Signal()
    thinking_chunk = Signal(str)
    thinking_done = Signal()
    response_chunk = Signal(str)
    response_done = Signal(str)
    tool_call = Signal(str, str)           # (cmd_name, detail)
    tool_result = Signal(str, bool)        # (result_text, success)
    todos_updated = Signal(list)           # [{status, label}]
    message = Signal(str, str)             # (text, level)
    finished = Signal()

    def __init__(self, llm_client, camera_manager, gui_app,
                 user_input: str, context: str):
        super().__init__()
        self.llm_client = llm_client
        self.camera_manager = camera_manager
        self.gui_app = gui_app
        self.user_input = user_input
        self.context = context

    def run(self):
        try:
            self._process()
        except Exception as e:
            self.message.emit(f"处理出错: {e}", "error")
        finally:
            self.finished.emit()

    def _process(self):
        enriched = (f"{self.context}\n用户：{self.user_input}"
                    if self.context else self.user_input)

        # ── Phase 1: 流式对话 ──
        self.thinking_started.emit()
        full_response = ""
        try:
            def on_chunk(token: str):
                nonlocal full_response
                full_response += token
                self.thinking_chunk.emit(token)

            full_response = self.llm_client.stream_chat(enriched, on_chunk)
        except Exception as e:
            self.thinking_done.emit()
            self.message.emit(f"AI 回复出错: {e}", "error")
            return

        self.thinking_done.emit()

        # ── Phase 2: 命令提取 ──
        parsed = self.llm_client._extract_command(full_response)

        if parsed.command == "chat":
            # 尝试 Pass 2 专用提取
            self.tool_call.emit("解析意图", "二次提取命令...")
            try:
                parsed = self.llm_client.extract_command(self.user_input, context="")
            except Exception:
                pass

        if parsed.command == "chat":
            # 纯对话，将流式内容作为最终回复
            self.response_done.emit(full_response)
            return

        # 清空非密码类命令的参数（由代码自动填充）
        if parsed.command not in ("set_password", "chat"):
            parsed.params = {}

        # ── Phase 3: 执行命令 ──
        label = COMMAND_LABELS.get(parsed.command, parsed.command)
        self.todos_updated.emit([
            {"status": "done", "label": "理解用户意图"},
            {"status": "done", "label": f"识别命令: {label}"},
            {"status": "running", "label": f"执行: {label}"},
        ])

        self.tool_call.emit(f"执行 {label}", str(parsed.params) if parsed.params else "")

        # 捕获执行输出
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            self.gui_app.execute_command(parsed)
            sys.stdout = old_stdout
            result = captured.getvalue().strip()
            success = True
        except Exception as e:
            sys.stdout = old_stdout
            result = str(e)
            success = False

        # 截断过长输出
        if len(result) > 600:
            result = result[:600] + "\n...（已截断）"

        self.tool_result.emit(result, success)

        self.todos_updated.emit([
            {"status": "done", "label": "理解用户意图"},
            {"status": "done", "label": f"识别命令: {label}"},
            {"status": "done" if success else "error", "label": f"执行: {label}"},
        ])

        # ── Phase 4: 生成摘要回复 ──
        if success:
            summary = f"已完成: {label}"
            if result and len(result) < 200:
                summary += f"\n\n{result}"
        else:
            summary = f"执行 {label} 时出错:\n{result}"

        self.response_done.emit(summary)


# ──────────────────────────────────────────────
#  网络扫描 Worker
# ──────────────────────────────────────────────
class ScanWorker(QObject):
    scan_started = Signal()
    scan_progress = Signal(str)
    scan_done = Signal(list)  # list of discovered devices

    def __init__(self, gui_app):
        super().__init__()
        self.gui_app = gui_app

    def run(self):
        self.scan_started.emit()
        try:
            self.scan_progress.emit("正在扫描局域网...")
            devices = discover_network_cameras()
            self.scan_done.emit(devices)
        except Exception as e:
            self.scan_progress.emit(f"扫描出错: {e}")
            self.scan_done.emit([])


# ──────────────────────────────────────────────
#  信号桥（QObject 子类，持有所有跨线程信号）
# ──────────────────────────────────────────────
class _SignalBridge(QObject):
    """持有所有跨线程信号，供 GUIApp 使用"""
    thinking_started = Signal()
    thinking_chunk = Signal(str)
    thinking_done = Signal()
    response_chunk = Signal(str)
    response_done = Signal(str)
    tool_call = Signal(str, str)           # (cmd_name, detail)
    tool_result = Signal(str, bool)        # (result_text, success)
    todos_updated = Signal(list)           # [{status, label}]
    message = Signal(str, str)             # (text, level)
    finished = Signal()
    scan_started = Signal()
    scan_progress = Signal(str)
    scan_done = Signal(list)               # list of discovered devices


class _InputKeyFilter(QObject):
    """输入框键盘事件过滤器：Enter 发送，Shift+Enter 换行"""
    send_triggered = Signal()
    height_grow = Signal()

    def eventFilter(self, obj, event):
        if event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    self.height_grow.emit()
                    return False
                else:
                    self.send_triggered.emit()
                    return True
        return False


# ──────────────────────────────────────────────
#  GUIApp 主窗口
# ──────────────────────────────────────────────
class GUIApp(BaseUI):
    """Agent 风格的摄像头控制 GUI"""

    def __init__(self, camera_manager: CameraManager, llm_client,
                 event_bus: EventBus, app_config: AppConfig = None):
        super().__init__(camera_manager, llm_client, event_bus)
        self._app_config = app_config
        self._default_password = ""
        self._last_discovered_devices = []
        self._running = False

        # 当前 AI 气泡状态
        self._current_bubble_parts: list = []
        self._thinking_text = ""
        self._todos: list = []

        # 信号桥（QObject 实例，持有所有跨线程信号）
        self._sig = _SignalBridge()

        # 键盘事件过滤器
        self._key_filter = _InputKeyFilter()

        # 事件监听
        self.event_bus.subscribe_all(self._on_event)

        # 跨线程信号连接
        self._connect_signals()

    def _connect_signals(self):
        """连接所有跨线程信号到主线程槽"""
        s = self._sig
        s.thinking_started.connect(self._on_thinking_started)
        s.thinking_chunk.connect(self._on_thinking_chunk)
        s.thinking_done.connect(self._on_thinking_done)
        s.response_chunk.connect(self._on_response_chunk)
        s.response_done.connect(self._on_response_done)
        s.tool_call.connect(self._on_tool_call)
        s.tool_result.connect(self._on_tool_result)
        s.todos_updated.connect(self._on_todos_updated)
        s.message.connect(self._on_worker_message)
        s.finished.connect(self._on_llm_finished)
        s.scan_started.connect(self._on_scan_started)
        s.scan_progress.connect(self._on_scan_progress)
        s.scan_done.connect(self._on_scan_done)

    # ── BaseUI 接口 ──

    def start(self) -> None:
        self._running = True
        app = QApplication.instance() or QApplication(sys.argv)
        self._build_ui()
        self._main_window.show()

        # 启动后自动扫描
        QTimer.singleShot(500, self._start_auto_scan)

        sys.exit(app.exec())

    def stop(self) -> None:
        self._running = False
        self.camera_manager.disconnect_all()
        self.llm_client.close()

    def display_message(self, message: str, level: str = "info") -> None:
        self._sig_message.emit(message, level)

    def get_user_input(self, prompt: str = "") -> str:
        return ""

    def display_stream(self, camera_name: str, stream_url: str) -> None:
        self._sig_message.emit(
            f"{camera_name} 流地址: {stream_url}", "info")

    def display_camera_status(self, camera_name: str) -> None:
        pass

    def display_event(self, event_message: str) -> None:
        pass

    # ── UI 构建 ──

    def _build_ui(self):
        self._main_window = QMainWindow()
        self._main_window.setWindowTitle("Agentic Camera Control")
        self._main_window.setMinimumSize(960, 640)
        self._main_window.resize(1120, 740)
        self._main_window.setStyleSheet(STYLESHEET)

        central = QWidget()
        self._main_window.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header
        header = self._build_header()
        root_layout.addWidget(header)

        # Main content: splitter
        splitter = QSplitter(Qt.Horizontal)

        # Left: chat area
        chat_widget = self._build_chat_area()
        splitter.addWidget(chat_widget)

        # Right: sidebar
        sidebar = self._build_sidebar()
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([760, 340])

        root_layout.addWidget(splitter, 1)

        # Input bar
        input_bar = self._build_input_bar()
        root_layout.addWidget(input_bar)

        # 连接键盘过滤器信号
        self._key_filter.send_triggered.connect(self._on_send)
        self._key_filter.height_grow.connect(self._on_input_grow)

        # Status bar
        self._status_bar = QStatusBar()
        self._status_bar.setObjectName("StatusBar")
        self._main_window.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就绪")

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("HeaderBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 8, 20, 8)

        title = QLabel("📷 Agentic Camera Control")
        title.setObjectName("HeaderTitle")
        layout.addWidget(title)

        layout.addStretch()

        model_label = QLabel(f"模型: {self.llm_client.config.model}")
        model_label.setObjectName("HeaderSub")
        layout.addWidget(model_label)

        return bar

    def _build_chat_area(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self._chat_display = QTextEdit()
        self._chat_display.setObjectName("ChatDisplay")
        self._chat_display.setReadOnly(True)
        self._chat_display.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._chat_display.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self._chat_display)

        # 初始欢迎消息
        welcome = (
            '<div style="text-align:center; margin:40px 20px; color:#94a3b8;">'
            '<div style="font-size:28px; margin-bottom:8px;">📷</div>'
            '<div style="font-size:16px; font-weight:600; color:#475569; '
            'margin-bottom:6px;">Agentic Camera Control</div>'
            '<div style="font-size:13px;">智能摄像头控制系统 · AI 对话式交互</div>'
            '<div style="font-size:12px; margin-top:12px; color:#b0b8c4;">'
            '直接输入你想做什么，例如："扫描局域网摄像头"、"连接摄像头并拉流"、'
            '"截图"、"自动设置"</div></div>'
        )
        self._chat_display.setHtml(welcome)

        return widget

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title
        title = QLabel("摄像头管理")
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        # Scrollable camera list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._camera_list_widget = QWidget()
        self._camera_list_layout = QVBoxLayout(self._camera_list_widget)
        self._camera_list_layout.setContentsMargins(8, 4, 8, 4)
        self._camera_list_layout.setSpacing(4)
        self._camera_list_layout.addStretch()
        scroll.setWidget(self._camera_list_widget)
        layout.addWidget(scroll, 1)

        # Quick actions
        actions_frame = QFrame()
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.setContentsMargins(12, 8, 12, 12)
        actions_layout.setSpacing(6)

        btn_scan = QPushButton("🔍  扫描局域网摄像头")
        btn_scan.setProperty("class", "SidebarBtn")
        btn_scan.clicked.connect(self._on_btn_scan)
        actions_layout.addWidget(btn_scan)

        btn_connect = QPushButton("🔗  连接所有摄像头")
        btn_connect.setProperty("class", "SidebarBtn")
        btn_connect.clicked.connect(self._on_btn_connect_all)
        actions_layout.addWidget(btn_connect)

        btn_status = QPushButton("📊  查看摄像头状态")
        btn_status.setProperty("class", "SidebarBtn")
        btn_status.clicked.connect(self._on_btn_status)
        actions_layout.addWidget(btn_status)

        btn_list = QPushButton("📋  列出所有摄像头")
        btn_list.setProperty("class", "SidebarBtn")
        btn_list.clicked.connect(self._on_btn_list)
        actions_layout.addWidget(btn_list)

        btn_clear = QPushButton("🗑  清空对话历史")
        btn_clear.setProperty("class", "SidebarBtn")
        btn_clear.clicked.connect(self._on_btn_clear)
        actions_layout.addWidget(btn_clear)

        layout.addWidget(actions_frame)

        return sidebar

    def _build_input_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("InputBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        self._input_field = QTextEdit()
        self._input_field.setObjectName("InputField")
        self._input_field.setAcceptRichText(False)
        self._input_field.setPlaceholderText(
            "输入消息... (Enter 发送, Shift+Enter 换行)")
        self._input_field.setMaximumHeight(80)
        self._input_field.setFixedHeight(48)
        self._input_field.installEventFilter(self._key_filter)
        layout.addWidget(self._input_field, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setObjectName("SendBtn")
        self._send_btn.clicked.connect(self._on_send)
        layout.addWidget(self._send_btn)

        return bar

    def _on_input_grow(self):
        """Shift+Enter 时增高输入框"""
        h = self._input_field.height()
        if h < 80:
            self._input_field.setFixedHeight(min(h + 22, 80))

    # ── 消息渲染 ──

    def _append_html(self, html: str, scroll=True):
        """追加 HTML 到聊天区域"""
        self._chat_display.moveCursor(QTextCursor.End)
        self._chat_display.insertHtml(html)
        if scroll:
            self._chat_display.moveCursor(QTextCursor.End)

    def _append_user_message(self, text: str):
        self._append_html(_user_bubble_html(text))

    def _start_ai_bubble(self):
        """开始一个新的 AI 回复气泡"""
        self._current_bubble_parts = []
        self._thinking_text = ""
        self._todos = []
        self._append_html(_ai_wrapper_start())
        # 占位：后续通过 _update_ai_bubble 替换
        self._bubble_start_cursor = self._chat_display.textCursor()

    def _update_ai_bubble(self):
        """重新渲染当前 AI 气泡内容"""
        # 构建完整 HTML
        parts_html = ""
        # 思考过程
        if self._thinking_text:
            thinking_preview = (self._thinking_text[:300] + "..."
                                if len(self._thinking_text) > 300
                                else self._thinking_text)
            parts_html += _debug_block_html(
                "思考过程", thinking_preview, "🧠")

        # Todos
        if self._todos:
            parts_html += _todo_html(self._todos)

        # 工具调用和结果（在 _current_bubble_parts 中）
        for part in self._current_bubble_parts:
            if part["type"] == "tool_call":
                parts_html += _debug_block_html(
                    part["title"], part.get("detail", ""), "🔧")
            elif part["type"] == "tool_result":
                color_icon = "✅" if part.get("success") else "❌"
                parts_html += _debug_block_html(
                    f"{color_icon} 执行结果", part.get("text", ""), "📋")
            elif part["type"] == "response":
                parts_html += _response_html(part["text"])

        # 用完整 HTML 替换 —— 由于 QTextEdit 的限制，
        # 我们采用清空后重新追加的方式
        full_html = self._chat_display.toHtml()
        # 简单策略：直接追加更新块
        # (QTextEdit 的 HTML 替换比较复杂，这里用 append 方式)

    def _finish_ai_bubble(self):
        """完成当前 AI 气泡"""
        self._append_html(_ai_wrapper_end())

    def _rebuild_chat_html(self, user_html_before: str):
        """重建聊天区域（用于更新 AI 气泡）—— 保留用户消息之前的内容"""
        # 由于 QTextEdit 的复杂 HTML 操作限制，
        # 我们采用直接追加策略，不重建整个文档

    # ── 信号槽：LLM Worker ──

    def _on_thinking_started(self):
        self._start_ai_bubble()
        self._thinking_text = ""
        # 显示思考中指示器
        self._append_html(
            '<div id="thinking-indicator" style="color:#9ca3af; '
            'font-size:12.5px; margin:4px 0;">'
            '🧠 <em>思考中...</em></div>')

    def _on_thinking_chunk(self, token: str):
        self._thinking_text += token

    def _on_thinking_done(self):
        # 移除思考指示器，插入折叠的思考内容
        thinking_preview = (self._thinking_text[:400] + "..."
                            if len(self._thinking_text) > 400
                            else self._thinking_text)
        # 先插入一个换行以结束指示器行
        self._append_html(
            '<div style="font-size:1px; line-height:1px;">&nbsp;</div>')
        self._append_html(
            _debug_block_html("思考过程", thinking_preview, "🧠"))

    def _on_tool_call(self, title: str, detail: str):
        self._current_bubble_parts.append({
            "type": "tool_call", "title": title, "detail": detail})
        self._append_html(_debug_block_html(title, detail, "🔧"))

    def _on_tool_result(self, text: str, success: bool):
        self._current_bubble_parts.append({
            "type": "tool_result", "text": text, "success": success})
        icon = "✅" if success else "❌"
        self._append_html(
            _debug_block_html(f"{icon} 执行结果", text, "📋"))

    def _on_todos_updated(self, todos: list):
        self._todos = todos
        self._append_html(_todo_html(todos))

    def _on_response_chunk(self, token: str):
        """流式响应片段（保留扩展）"""
        pass

    def _on_response_done(self, text: str):
        if not self._current_bubble_parts:
            self._start_ai_bubble()
        self._current_bubble_parts.append({"type": "response", "text": text})
        self._append_html(_response_html(text))
        self._finish_ai_bubble()

    def _on_worker_message(self, text: str, level: str):
        color_map = {
            "info": "#6b7280",
            "warning": "#d97706",
            "error": "#dc2626",
            "success": "#16a34a",
        }
        color = color_map.get(level, "#6b7280")
        self._append_html(_system_msg_html(text, color))

    def _on_llm_finished(self):
        self._send_btn.setEnabled(True)
        self._input_field.setEnabled(True)
        self._input_field.setFocus()
        self._status_bar.showMessage("就绪")

    # ── 信号槽：Scan Worker ──

    def _on_scan_started(self):
        self._append_html(
            _system_msg_html("🔍 正在扫描局域网摄像头...", "#4a8af4"))

    def _on_scan_progress(self, text: str):
        self._append_html(_system_msg_html(text, "#6b7280"))

    def _on_scan_done(self, devices: list):
        if devices:
            self._last_discovered_devices = devices
            self._register_discovered_devices(devices)
        else:
            self._append_html(
                _system_msg_html("未发现局域网内的摄像头设备", "#d97706"))
        self._refresh_sidebar()

    # ── 用户操作 ──

    def _on_send(self):
        text = self._input_field.toPlainText().strip()
        if not text:
            return
        self._input_field.clear()
        self._input_field.setFixedHeight(48)

        # 斜杠命令 or 自然语言
        if text.startswith("/"):
            self._handle_slash_command(text)
        else:
            self._handle_natural_language(text)

    def _handle_natural_language(self, user_input: str):
        """发送自然语言给 LLM Worker"""
        self._append_user_message(user_input)
        self._send_btn.setEnabled(False)
        self._input_field.setEnabled(False)
        self._status_bar.showMessage("AI 处理中...")

        context = self._build_camera_context()

        # 创建 Worker
        worker = LLMWorker(
            self.llm_client, self.camera_manager, self,
            user_input, context)

        # 连接 Worker 信号到 GUIApp 的跨线程信号
        sig = self._sig
        worker.thinking_started.connect(sig.thinking_started)
        worker.thinking_chunk.connect(sig.thinking_chunk)
        worker.thinking_done.connect(sig.thinking_done)
        worker.response_chunk.connect(sig.response_chunk)
        worker.response_done.connect(sig.response_done)
        worker.tool_call.connect(sig.tool_call)
        worker.tool_result.connect(sig.tool_result)
        worker.todos_updated.connect(sig.todos_updated)
        worker.message.connect(sig.message)
        worker.finished.connect(sig.finished)

        # 启动线程
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        # 保持引用防止 GC
        self._current_thread = thread
        self._current_worker = worker
        thread.start()

    def _build_camera_context(self) -> str:
        cameras = self.camera_manager.list_cameras()
        if not cameras:
            return "系统已扫描并注册了摄像头，无需指定IP或名称，系统会自动选择"
        connected = [c for c in cameras if c.is_connected]
        lines = []
        if connected:
            lines.append(
                f"已有 {len(connected)} 个摄像头已连接，无需指定名称，系统自动选择")
        else:
            lines.append(
                f"已注册 {len(cameras)} 个摄像头，均未连接")
        if not self._default_password:
            lines.append("注意: 尚未设置连接密码")
        return "\n".join(lines)

    # ── 斜杠命令 ──

    def _handle_slash_command(self, command: str):
        self._append_user_message(command)
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/stream": self._cmd_stream,
            "/snapshot": self._cmd_snapshot,
            "/status": self._cmd_status,
            "/list": self._cmd_list,
            "/discover": self._cmd_discover,
            "/discover_net": self._cmd_discover_network,
            "/connect": self._cmd_connect,
            "/password": self._cmd_password,
            "/disconnect": self._cmd_disconnect,
            "/ptz": self._cmd_ptz,
            "/ptz_stop": self._cmd_ptz_stop,
            "/ptz_zoom": self._cmd_ptz_zoom,
            "/models": self._cmd_models,
            "/clear": self._cmd_clear,
            "/events": self._cmd_events,
            "/probe_all": self._cmd_probe_all,
            "/help": self._cmd_help,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
        }
        handler = handlers.get(cmd)
        if handler:
            try:
                handler(arg)
            except Exception as e:
                self._append_html(
                    _system_msg_html(f"命令执行出错: {e}", "#dc2626"))
        else:
            self._append_html(
                _system_msg_html(f"未知命令: {cmd}，输入 /help 查看帮助", "#d97706"))

    def _cmd_stream(self, arg: str):
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self._msg("没有可用的摄像头", "warning"); return
        try:
            url = self.camera_manager.get_stream_url(name)
            self._msg(f"{name} 流地址: {url}", "success")
        except Exception as e:
            self._msg(f"获取流地址失败: {e}", "error")

    def _cmd_snapshot(self, arg: str):
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self._msg("没有可用的摄像头", "warning"); return
        try:
            import cv2
            frame = self.camera_manager.get_snapshot(name)
            if frame is not None:
                snap_dir = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "snapshots")
                os.makedirs(snap_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                fp = os.path.join(snap_dir, f"{name}_{ts}.jpg")
                cv2.imwrite(fp, frame)
                self._msg(f"截图已保存: {fp}", "success")
            else:
                self._msg("获取截图失败", "error")
        except Exception as e:
            self._msg(f"截图失败: {e}", "error")

    def _cmd_status(self, arg: str):
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self._msg("没有可用的摄像头", "warning"); return
        try:
            s = self.camera_manager.get_status(name)
            mode = "USB" if s.connection_type == "usb" else "ONVIF"
            status = "已连接 ✅" if s.is_connected else "未连接 ❌"
            info = (f"名称: {s.name}\n类型: {mode}\n状态: {status}")
            if s.connection_type == "usb":
                info += f"\n分辨率: {s.frame_width}x{s.frame_height}"
                info += f"\n帧率: {s.fps:.0f}fps"
            else:
                info += f"\nIP: {s.ip}"
                info += f"\n厂商: {s.manufacturer or '未知'}"
                info += f"\n型号: {s.model or '未知'}"
            if s.last_error:
                info += f"\n最近错误: {s.last_error}"
            self._msg(info, "info")
        except Exception as e:
            self._msg(f"获取状态失败: {e}", "error")

    def _cmd_list(self, _arg: str):
        cameras = self.camera_manager.list_cameras()
        if not cameras:
            self._msg("没有注册任何摄像头", "warning"); return
        lines = []
        for c in cameras:
            icon = "🟢" if c.is_connected else "🔴"
            mode = "[USB]" if c.connection_type == "usb" else "[ONVIF]"
            addr = (f"索引:{c.device_index}"
                    if c.connection_type == "usb" else c.ip)
            state = "已连接" if c.is_connected else "未连接"
            lines.append(f"{icon} {c.name} {mode} ({addr}) - {state}")
        self._msg("\n".join(lines), "info")

    def _cmd_discover_network(self, _arg: str):
        self._start_auto_scan()

    def _cmd_discover(self, _arg: str):
        cameras = discover_usb_cameras()
        if cameras:
            lines = []
            for cam in cameras:
                lines.append(
                    f"● 索引 {cam.device_index}: "
                    f"{cam.width}x{cam.height} @ {cam.fps:.0f}fps")
            self._msg("USB 摄像头:\n" + "\n".join(lines), "success")
        else:
            self._msg("未发现 USB 摄像头", "warning")

    def _cmd_connect(self, arg: str):
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            self._msg("没有已注册的摄像头", "error"); return
        self._msg(f"正在连接 {name}...", "info")
        if self.camera_manager.connect(name):
            self._msg(f"{name} 连接成功 ✅", "success")
        else:
            self._msg(f"{name} 连接失败 ❌", "error")
        self._refresh_sidebar()

    def _cmd_password(self, arg: str):
        pwd = arg.strip()
        if not pwd:
            self._msg("用法: /password <密码>", "warning"); return
        self._default_password = pwd
        updated = self.camera_manager.update_all_passwords(pwd)
        self._msg(
            f"密码已设置 ({len(pwd)} 位)，同步到 {updated} 个摄像头",
            "success")

    def _cmd_disconnect(self, arg: str):
        name = arg or self.camera_manager.get_default_camera_name()
        if not name:
            return
        self.camera_manager.disconnect(name)
        self._msg(f"{name} 已断开", "success")
        self._refresh_sidebar()

    def _cmd_ptz(self, arg: str):
        parts = arg.strip().split()
        if not parts:
            self._msg("用法: /ptz up|down|left|right [速度]", "warning"); return
        direction = parts[0].lower()
        speed = float(parts[1]) if len(parts) > 1 else 0.5
        name = self.camera_manager.get_default_camera_name()
        if not name:
            self._msg("没有可用的摄像头", "error"); return
        direction_map = {
            "up": (0, 1), "down": (0, -1),
            "left": (-1, 0), "right": (1, 0),
        }
        pt = direction_map.get(direction)
        if not pt:
            self._msg(f"无效方向: {direction}", "warning"); return
        ok = self.camera_manager.ptz_move(
            name, pan=pt[0], tilt=pt[1], speed=speed)
        if ok:
            self._msg(f"PTZ 移动: {direction} (速度 {speed})", "success")
        else:
            self._msg("PTZ 移动失败", "error")

    def _cmd_ptz_stop(self, _arg: str):
        name = self.camera_manager.get_default_camera_name()
        if name:
            self.camera_manager.ptz_stop(name)
            self._msg("PTZ 已停止", "info")

    def _cmd_ptz_zoom(self, arg: str):
        name = self.camera_manager.get_default_camera_name()
        if not name:
            self._msg("没有可用的摄像头", "error"); return
        action = arg.strip() or "in"
        zoom = 1.0 if action in ("in", "放大") else -1.0
        ok = self.camera_manager.ptz_move(name, zoom=zoom, speed=0.5)
        self._msg(f"PTZ 缩放: {action}" +
                  (" ✅" if ok else " ❌"), "info")

    def _cmd_models(self, _arg: str):
        models = self.llm_client.list_models()
        if models:
            self._msg("可用模型:\n" + "\n".join(
                f"• {m}" for m in models), "info")
        else:
            self._msg("无法获取模型列表", "warning")

    def _cmd_clear(self, _arg: str):
        self.llm_client.clear_history()
        self._chat_display.clear()
        self._msg("对话历史已清空", "success")

    def _cmd_events(self, _arg: str):
        events = self.event_bus.get_history(limit=20)
        if not events:
            self._msg("暂无事件记录", "info"); return
        self._msg("最近事件:\n" + "\n".join(str(e) for e in events), "info")

    def _cmd_probe_all(self, _arg: str):
        """在后台线程逐个探测所有摄像头"""
        names = self.camera_manager.get_camera_names()
        if not names:
            self._msg("没有已注册的摄像头", "warning"); return
        self._msg(f"开始探测 {len(names)} 个摄像头...", "info")

        def _probe():
            ok, fail = 0, 0
            for name in names:
                try:
                    s = self.camera_manager.get_status(name)
                    if s.is_connected:
                        ok += 1; continue
                except Exception:
                    pass
                if self.camera_manager.connect(name):
                    ok += 1
                else:
                    fail += 1
            self._sig.message.emit(
                f"探测完成: 成功 {ok}, 失败 {fail}", "success")
            self._sig.scan_done.emit([])  # 触发侧边栏刷新

        t = threading.Thread(target=_probe, daemon=True)
        t.start()

    def _cmd_help(self, _arg: str):
        help_text = (
            "可用命令:\n"
            "/stream       - 获取视频流\n"
            "/snapshot     - 截图保存\n"
            "/status       - 查看摄像头状态\n"
            "/list         - 列出所有摄像头\n"
            "/discover     - 扫描 USB 摄像头\n"
            "/discover_net - 扫描局域网摄像头\n"
            "/connect      - 连接摄像头\n"
            "/password     - 设置密码\n"
            "/disconnect   - 断开摄像头\n"
            "/ptz          - PTZ 云台控制\n"
            "/ptz_stop     - 停止 PTZ\n"
            "/ptz_zoom     - PTZ 缩放\n"
            "/models       - 查看模型\n"
            "/clear        - 清空对话\n"
            "/events       - 查看事件\n"
            "/probe_all    - 探测所有摄像头\n"
            "/help         - 帮助\n"
            "/quit         - 退出"
        )
        self._msg(help_text, "info")

    def _cmd_quit(self, _arg: str):
        self.stop()
        QApplication.quit()

    # ── 命令执行器（供 LLM Worker 调用）──

    def execute_command(self, cmd: ParsedCommand):
        """执行 LLM 解析出的命令（在 Worker 线程中调用，stdout 被重定向）"""
        executors = {
            "watch_camera": self._exec_watch_camera,
            "take_photo": self._exec_take_photo,
            "get_stream": self._exec_get_stream,
            "get_snapshot": self._exec_get_snapshot,
            "get_status": self._exec_get_status,
            "list_cameras": self._exec_list_cameras,
            "discover_network": self._exec_discover_network,
            "discover_usb": self._exec_discover_usb,
            "connect_camera": self._exec_connect_camera,
            "disconnect_camera": self._exec_disconnect_camera,
            "open_preview": self._exec_open_preview,
            "auto_setup": self._exec_auto_setup,
            "set_password": self._exec_set_password,
            "ptz_move": self._exec_ptz_move,
            "ptz_stop": self._exec_ptz_stop,
            "ptz_zoom": self._exec_ptz_zoom,
            "list_presets": self._exec_list_presets,
            "get_device_info": self._exec_get_device_info,
        }
        executor = executors.get(cmd.command)
        if executor:
            executor(cmd.params)
        else:
            print(f"未知命令: {cmd.command}")

    # ── 命令执行实现 ──

    def _resolve_camera_name(self, params: dict) -> Optional[str]:
        raw = params.get("camera", "")
        if not raw:
            return self.camera_manager.get_default_camera_name()
        if raw in self.camera_manager.get_camera_names():
            return raw
        import re
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', raw):
            converted = f"discovered_{raw.replace('.', '_')}"
            if converted in self.camera_manager.get_camera_names():
                return converted
        return self.camera_manager.get_default_camera_name()

    def _ensure_connected(self, name: str) -> bool:
        try:
            s = self.camera_manager.get_status(name)
            if s.is_connected:
                return True
            print(f"{name} 未连接，正在自动连接...")
            return self.camera_manager.connect(name)
        except Exception as e:
            print(f"检查连接失败: {e}")
            return False

    def _ensure_any_connected(self) -> Optional[str]:
        names = self.camera_manager.get_camera_names()
        if not names:
            print("没有可用的摄像头")
            return None
        for name in names:
            try:
                s = self.camera_manager.get_status(name)
                if s.is_connected:
                    return name
            except Exception:
                pass
        for name in names:
            print(f"正在尝试连接 {name}...")
            if self.camera_manager.connect(name):
                print(f"{name} 连接成功")
                return name
        print("所有摄像头均连接失败")
        return None

    def _exec_watch_camera(self, params):
        self._connect_and_stream_all()

    def _exec_take_photo(self, params):
        name = self._ensure_any_connected()
        if name:
            self._cmd_snapshot(name)

    def _exec_get_stream(self, params):
        self._connect_and_stream_all()

    def _exec_get_snapshot(self, params):
        name = self._ensure_any_connected()
        if name:
            self._cmd_snapshot(name)

    def _exec_get_status(self, params):
        name = self._resolve_camera_name(params)
        if name:
            self._cmd_status(name)

    def _exec_list_cameras(self, params):
        self._cmd_list("")

    def _exec_discover_network(self, params):
        self._cmd_discover_network("")

    def _exec_discover_usb(self, params):
        self._cmd_discover("")

    def _exec_connect_camera(self, params):
        name = self._resolve_camera_name(params)
        if name:
            self._cmd_connect(name)

    def _exec_disconnect_camera(self, params):
        name = self._resolve_camera_name(params)
        if name:
            self._cmd_disconnect(name)

    def _exec_open_preview(self, params):
        name = self._ensure_any_connected()
        if name:
            self._msg(f"预览功能请在 CLI 模式下使用", "info")

    def _exec_auto_setup(self, params):
        print("🚀 自动设置: 发现 → 注册 → 连接 → 拉流")
        print("\n[Step 1/4] 扫描局域网摄像头...")
        devices = discover_network_cameras()
        if not devices:
            print("未发现摄像头")
            return
        print(f"发现 {len(devices)} 个设备")

        print("\n[Step 2/4] 注册摄像头...")
        self._register_discovered_devices(devices)

        print("\n[Step 3/4] 连接...")
        cam_name = None
        for dev in devices:
            name = f"discovered_{dev.ip.replace('.', '_')}"
            if name in self.camera_manager.get_camera_names():
                if self.camera_manager.connect(name):
                    cam_name = name
                    print(f"{name} 连接成功")
                    break
        if not cam_name:
            print("所有摄像头连接失败")
            return

        print("\n[Step 4/4] 获取视频流...")
        url = self.camera_manager.get_stream_url(cam_name)
        print(f"流地址: {url}")

    def _exec_set_password(self, params):
        pwd = params.get("password", "")
        if not pwd and "params" in params and isinstance(params["params"], dict):
            pwd = params["params"].get("password", "")
        if pwd:
            self._cmd_password(pwd)
        else:
            print("请提供密码")

    def _exec_ptz_move(self, params):
        name = params.get("camera") or self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        direction = params.get("direction", "").lower()
        speed = float(params.get("speed", 0.5))
        dm = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}
        pt = dm.get(direction)
        if not pt:
            print(f"无效方向: {direction}")
            return
        ok = self.camera_manager.ptz_move(name, pan=pt[0], tilt=pt[1], speed=speed)
        if ok:
            print(f"PTZ: {direction} 速度 {speed}")
            import time; time.sleep(1.0)
            self.camera_manager.ptz_stop(name)
            print("PTZ 已自动停止")
        else:
            print("PTZ 移动失败")

    def _exec_ptz_stop(self, params):
        name = self.camera_manager.get_default_camera_name()
        if name:
            self.camera_manager.ptz_stop(name)
            print("PTZ 已停止")

    def _exec_ptz_zoom(self, params):
        name = self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        action = params.get("action", "in").lower()
        zoom = 1.0 if action in ("in", "放大") else -1.0
        ok = self.camera_manager.ptz_move(name, zoom=zoom, speed=0.5)
        if ok:
            import time; time.sleep(1.5)
            self.camera_manager.ptz_stop(name)
            print(f"PTZ 缩放: {action}")
        else:
            print("PTZ 缩放失败")

    def _exec_list_presets(self, params):
        name = self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        presets = self.camera_manager.ptz_get_presets(name)
        if presets:
            for p in presets:
                print(f"  ● {p['name']} (token: {p['token']})")
        else:
            print("没有预置位")

    def _exec_get_device_info(self, params):
        name = self.camera_manager.get_default_camera_name()
        if not name or not self._ensure_connected(name):
            return
        info = self.camera_manager.get_device_info(name)
        if info:
            for k, v in info.items():
                print(f"  {k}: {v}")
        else:
            print("无法获取设备信息")

    def _connect_and_stream_all(self):
        names = self.camera_manager.get_camera_names()
        if not names:
            print("没有可用的摄像头")
            return
        connected = []
        for name in names:
            try:
                s = self.camera_manager.get_status(name)
                if s.is_connected:
                    connected.append(name)
                    continue
            except Exception:
                pass
            print(f"正在连接 {name}...")
            if self.camera_manager.connect(name):
                connected.append(name)
                print(f"{name} 连接成功")
            else:
                print(f"{name} 连接失败")
        if not connected:
            print("所有摄像头连接失败")
            return
        for name in connected:
            try:
                url = self.camera_manager.get_stream_url(name)
                print(f"{name}: {url}")
            except Exception as e:
                print(f"{name}: 获取流地址失败 - {e}")

    # ── 设备注册 ──

    def _register_discovered_devices(self, devices):
        from phase1.core.config import CameraConfig as CC
        # 清理旧的动态设备
        for name in list(self.camera_manager.get_camera_names()):
            if name.startswith("discovered_"):
                self.camera_manager.remove_camera(name)

        ws_devices = [d for d in devices if d.ws_discovered]
        non_ws = [d for d in devices if not d.ws_discovered]
        if non_ws:
            print(f"已过滤 {len(non_ws)} 个非摄像头设备")

        registered = []
        for dev in ws_devices:
            print(f"  [验证] {dev.ip}:{dev.onvif_port}...")
            verify_result = verify_onvif_camera(
                dev.ip, dev.onvif_port,
                username="admin", password=self._default_password)
            if not verify_result:
                print("  ✗ 非 ONVIF 摄像头")
                continue
            mfr = verify_result.get('manufacturer', '')
            model = verify_result.get('model', '')
            print(f"  ✓ {mfr} {model}")

            cam_name = f"discovered_{dev.ip.replace('.', '_')}"
            existing_ips = [
                getattr(conn, 'config', None)
                for conn in self.camera_manager._connections.values()
                if hasattr(conn, 'config') and
                getattr(conn.config, 'ip', '') == dev.ip
            ]
            if existing_ips:
                continue

            cam_config = CC(
                name=cam_name, connection_type="onvif",
                ip=dev.ip, port=dev.onvif_port,
                username="admin", password=self._default_password,
                rtsp_port=dev.rtsp_port, rtsp_path="/stream1",
                rtsp_sub_path="/stream2",
                device_model=dev.brand or mfr,
                product_version=dev.model or model,
            )
            self.camera_manager.add_camera(cam_config)
            registered.append(cam_name)

        if registered:
            print(f"已注册 {len(registered)} 个摄像头: {', '.join(registered)}")
            self._persist_cameras_to_config()
        else:
            print("未发现通过 ONVIF 验证的摄像头")

    def _persist_cameras_to_config(self):
        if not self._app_config:
            return
        self._app_config.cameras.clear()
        for name, conn in self.camera_manager._connections.items():
            if hasattr(conn, 'config'):
                self._app_config.cameras.append(conn.config)
        try:
            save_config(self._app_config)
            print(f"已保存 {len(self._app_config.cameras)} 个摄像头到 config.yaml")
        except Exception as e:
            print(f"保存配置失败: {e}")

    # ── 侧边栏 ──

    def _refresh_sidebar(self):
        """刷新摄像头列表侧边栏"""
        # 清空现有
        while self._camera_list_layout.count() > 1:
            item = self._camera_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        cameras = self.camera_manager.list_cameras()
        if not cameras:
            empty_label = QLabel("暂无摄像头\n扫描后自动添加")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("color: #94a3b8; font-size: 12px; padding: 20px;")
            self._camera_list_layout.insertWidget(0, empty_label)
        else:
            for i, cam in enumerate(cameras):
                card = QFrame()
                card.setObjectName("CameraCard")
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(10, 8, 10, 8)
                card_layout.setSpacing(2)

                name_row = QHBoxLayout()
                icon = "🟢" if cam.is_connected else "🔴"
                name_label = QLabel(f"{icon} {cam.name}")
                name_label.setObjectName("CameraName")
                name_row.addWidget(name_label)
                name_row.addStretch()
                card_layout.addLayout(name_row)

                mode = "USB" if cam.connection_type == "usb" else "ONVIF"
                addr = (f"索引:{cam.device_index}"
                        if cam.connection_type == "usb" else cam.ip)
                detail = QLabel(f"{mode} · {addr}")
                detail.setObjectName("CameraStatus")
                card_layout.addWidget(detail)

                self._camera_list_layout.insertWidget(i, card)

        self._camera_list_layout.update()

    # ── 侧边栏按钮 ──

    def _on_btn_scan(self):
        self._start_auto_scan()

    def _on_btn_connect_all(self):
        def _connect():
            names = self.camera_manager.get_camera_names()
            ok = 0
            for name in names:
                try:
                    s = self.camera_manager.get_status(name)
                    if s.is_connected:
                        ok += 1; continue
                except Exception:
                    pass
                if self.camera_manager.connect(name):
                    ok += 1
            self._sig.message.emit(f"连接完成: {ok}/{len(names)} 成功", "success")
            self._sig.scan_done.emit([])  # 刷新侧边栏

        t = threading.Thread(target=_connect, daemon=True)
        t.start()

    def _on_btn_status(self):
        cameras = self.camera_manager.list_cameras()
        if not cameras:
            self._msg("没有摄像头", "warning"); return
        lines = []
        for c in cameras:
            state = "已连接" if c.is_connected else "未连接"
            mode = "USB" if c.connection_type == "usb" else "ONVIF"
            lines.append(f"{'🟢' if c.is_connected else '🔴'} {c.name} [{mode}] - {state}")
        self._msg("\n".join(lines), "info")

    def _on_btn_list(self):
        self._cmd_list("")

    def _on_btn_clear(self):
        self._cmd_clear("")

    def _start_auto_scan(self):
        """在后台线程扫描网络摄像头"""
        worker = ScanWorker(self)
        worker.scan_started.connect(self._sig.scan_started)
        worker.scan_progress.connect(self._sig.scan_progress)
        worker.scan_done.connect(self._sig.scan_done)

        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.scan_done.connect(thread.quit)
        worker.scan_done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    # ── 事件回调 ──

    def _on_event(self, event: CameraEvent):
        self._sig.message.emit(str(event), "info")

    # ── 工具方法 ──

    def _msg(self, text: str, level: str = "info"):
        """直接在主线程追加系统消息"""
        color_map = {
            "info": "#6b7280",
            "warning": "#d97706",
            "error": "#dc2626",
            "success": "#16a34a",
        }
        color = color_map.get(level, "#6b7280")
        self._append_html(_system_msg_html(text, color))
