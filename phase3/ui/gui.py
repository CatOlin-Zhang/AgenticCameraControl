"""
GUI 界面 - 预留实现
未来可使用 PyQt / Tkinter / DearPyGui 等框架实现此接口。
"""
from phase3.core.camera import CameraManager
from phase3.core.events import EventBus
from phase3.core.llm import OllamaClient
from phase3.ui.base import BaseUI


class GUIApp(BaseUI):
    """
    GUI 界面预留类。
    当前所有方法均为占位实现，待后续选用 GUI 框架后补充完整实现。
    """

    def __init__(self, camera_manager: CameraManager, llm_client: OllamaClient, event_bus: EventBus):
        super().__init__(camera_manager, llm_client, event_bus)
        raise NotImplementedError(
            "GUI 界面尚未实现。请使用 CLI 模式运行，或实现此类的抽象方法后使用。\n"
            "推荐的 GUI 框架：PyQt6, PySide6, DearPyGui, customtkinter"
        )

    def start(self) -> None:
        """启动 GUI 主窗口事件循环"""
        # TODO: 初始化主窗口、布局控件、启动事件循环
        pass

    def stop(self) -> None:
        """关闭 GUI 窗口，释放资源"""
        # TODO: 关闭窗口、断开连接、清理资源
        pass

    def display_message(self, message: str, level: str = "info") -> None:
        """在 GUI 中展示消息（如状态栏、消息框、通知区域）"""
        # TODO: 根据 level 显示不同颜色的消息提示
        pass

    def get_user_input(self, prompt: str = "") -> str:
        """从 GUI 输入框获取用户输入"""
        # TODO: 弹出输入对话框或从文本框读取
        pass

    def display_stream(self, camera_name: str, stream_url: str) -> None:
        """在 GUI 中播放视频流"""
        # TODO: 使用 OpenCV / GStreamer / VLC 嵌入视频播放控件
        pass

    def display_camera_status(self, camera_name: str) -> None:
        """在 GUI 面板中展示摄像头状态"""
        # TODO: 更新侧边栏或信息面板中的状态信息
        pass

    def display_event(self, event_message: str) -> None:
        """在 GUI 中展示事件通知（如 toast 弹窗、事件列表）"""
        # TODO: 在事件日志面板或通知区域显示事件
        pass
