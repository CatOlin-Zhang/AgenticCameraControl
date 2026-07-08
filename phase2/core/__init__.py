"""
phase2.core - 核心模块
"""
from phase2.core.config import AppConfig, CameraConfig, LLMConfig, ConnectionType, load_config
from phase2.core.events import EventBus, CameraEvent, EventType
from phase2.core.camera import CameraManager, CameraStatus
from phase2.core.auth import SNDecoder, DeviceAuth
from phase2.core.llm import LocalLLMClient, OllamaClient, ParsedCommand
from phase2.core.registration import CameraRegistrar
