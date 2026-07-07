"""
UI 抽象基类 - 定义所有 UI 实现必须遵循的接口
"""
from abc import ABC, abstractmethod

from core.camera import CameraManager
from core.events import EventBus
from core.llm import LocalLLMClient, OllamaClient
from typing import Union


# LLM 客户端通用类型
LLMClient = Union[LocalLLMClient, OllamaClient]


class BaseUI(ABC):
    """
    UI 抽象基类。
    CLI 和 GUI 实现均需继承此类并实现所有抽象方法。
    """

    def __init__(self, camera_manager: CameraManager, llm_client: LLMClient, event_bus: EventBus):
        self.camera_manager = camera_manager
        self.llm_client = llm_client
        self.event_bus = event_bus

    @abstractmethod
    def start(self) -> None:
        """启动 UI 主循环"""
        pass

    @abstractmethod
    def stop(self) -> None:
        """停止 UI 主循环，释放资源"""
        pass

    @abstractmethod
    def display_message(self, message: str, level: str = "info") -> None:
        """
        向用户展示一条消息
        :param message: 消息内容
        :param level: 消息级别 - info / warning / error / success
        """
        pass

    @abstractmethod
    def get_user_input(self, prompt: str = "") -> str:
        """
        获取用户输入
        :param prompt: 输入提示符
        :return: 用户输入的文本
        """
        pass

    @abstractmethod
    def display_stream(self, camera_name: str, stream_url: str) -> None:
        """
        展示视频流（CLI 下可能只是打印 URL，GUI 下会打开播放窗口）
        :param camera_name: 摄像头名称
        :param stream_url: RTSP 流地址
        """
        pass

    @abstractmethod
    def display_camera_status(self, camera_name: str) -> None:
        """展示摄像头状态信息"""
        pass

    @abstractmethod
    def display_event(self, event_message: str) -> None:
        """展示摄像头事件通知"""
        pass
