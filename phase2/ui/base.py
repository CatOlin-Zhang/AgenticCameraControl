"""
phase2 - UI 抽象基类
"""
from abc import ABC, abstractmethod
from typing import Union

from phase2.core.camera import CameraManager
from phase2.core.events import EventBus
from phase2.core.llm import LocalLLMClient, OllamaClient
from phase2.core.auth import SNDecoder

LLMClient = Union[LocalLLMClient, OllamaClient]


class BaseUI(ABC):
    """UI 抽象基类。"""

    def __init__(self, camera_manager: CameraManager, llm_client: LLMClient,
                 event_bus: EventBus, sn_decoder: SNDecoder):
        self.camera_manager = camera_manager
        self.llm_client = llm_client
        self.event_bus = event_bus
        self.sn_decoder = sn_decoder

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def display_message(self, message: str, level: str = "info") -> None:
        pass

    @abstractmethod
    def get_user_input(self, prompt: str = "") -> str:
        pass

    @abstractmethod
    def display_stream(self, camera_name: str, stream_url: str) -> None:
        pass

    @abstractmethod
    def display_camera_status(self, camera_name: str) -> None:
        pass

    @abstractmethod
    def display_event(self, event_message: str) -> None:
        pass
