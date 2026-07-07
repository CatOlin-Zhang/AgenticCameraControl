"""
core - 核心模块
包含配置管理、摄像头控制、事件系统、大模型集成
"""
from core.config import AppConfig, CameraConfig, LLMConfig, ConnectionType, load_config
from core.events import EventBus, CameraEvent, EventType
from core.camera import CameraManager, CameraStatus
from core.llm import LocalLLMClient, OllamaClient, ParsedCommand
