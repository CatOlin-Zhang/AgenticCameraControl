"""
core - 核心模块
包含配置管理、摄像头控制、事件系统、大模型集成
"""
from phase1.core.config import AppConfig, CameraConfig, LLMConfig, ConnectionType, load_config
from phase1.core.events import EventBus, CameraEvent, EventType
from phase1.core.camera import CameraManager, CameraStatus
from phase1.core.llm import LocalLLMClient, OllamaClient, ParsedCommand
