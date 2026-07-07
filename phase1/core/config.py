"""
配置模块 - 管理摄像头连接参数和 LLM 推理配置
支持 USB(UVC) 和 ONVIF/RTSP(局域网) 两种连接方式
LLM 后端: local (llama-cpp-python) 或 ollama

协议类型:
  - USB: 本地 UVC 设备直连
  - ONVIF: 局域网 ONVIF 协议 (HTTP + RTSP)
"""
import os
import yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# 项目根目录（phase1/ 目录，即 core/ 的上两级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.yaml")


class ConnectionType(Enum):
    """摄像头连接类型"""
    USB = "usb"           # USB(UVC) 直连
    ONVIF = "onvif"       # ONVIF 局域网协议 (RTSP 视频流)


@dataclass
class CameraConfig:
    """单个摄像头配置"""
    name: str                                  # 摄像头名称标识
    connection_type: str = "usb"               # 连接类型: usb / onvif
    # ── USB 连接参数 ──
    device_index: int = 0                      # USB 设备索引（OpenCV VideoCapture）
    device_model: str = ""                     # 设备型号（如 LC2418）
    product_version: str = ""                  # 产品版本（如 ZCR461）
    # ── ONVIF/RTSP 局域网参数 ──
    ip: str = ""                               # 摄像头 IP 地址
    port: int = 80                             # ONVIF 服务端口
    username: str = "admin"                    # 登录用户名
    password: str = ""                         # 登录密码（必填）
    rtsp_port: int = 554                       # RTSP 端口
    rtsp_path: str = "/stream1"                # RTSP 流路径（主码流）
    rtsp_sub_path: str = "/stream2"            # RTSP 子码流路径

    @property
    def is_usb(self) -> bool:
        return self.connection_type == ConnectionType.USB.value

    @property
    def is_onvif(self) -> bool:
        return self.connection_type == ConnectionType.ONVIF.value

    def get_rtsp_url(self, sub_stream: bool = False) -> str:
        """
        构造 RTSP 流地址（仅 ONVIF 模式有效）
        :param sub_stream: True 使用子码流, False 使用主码流
        :return: 完整的 RTSP URL
        """
        path = self.rtsp_sub_path if sub_stream else self.rtsp_path
        pwd = self.password if self.password else ""
        return f"rtsp://{self.username}:{pwd}@{self.ip}:{self.rtsp_port}{path}"

    def get_onvif_url(self) -> str:
        """获取 ONVIF 服务地址（仅 ONVIF 模式有效）"""
        return f"http://{self.ip}:{self.port}/onvif/device_service"


@dataclass
class LLMConfig:
    """LLM 推理配置（支持本地 llama-cpp-python 和 Ollama）"""
    backend: str = "local"                       # 推理后端: "local" (llama-cpp-python) 或 "ollama"
    model_path: str = "D:\\OllamaModels\\qwen2.5-0.5b-instruct-q4_k_m.gguf"  # 本地 GGUF 模型路径
    base_url: str = "http://localhost:11434"     # Ollama 服务地址（仅 ollama 后端使用）
    model: str = "qwen2.5:0.5b"                 # Ollama 模型名称（仅 ollama 后端使用）
    timeout: int = 60                          # 请求超时时间（秒）
    temperature: float = 0.3                   # 生成温度（控制指令场景用低温度）
    system_prompt: str = (
        "你是智能摄像头控制助手。根据用户意图返回JSON命令或对话。\n"
        "\n"
        "操作命令格式: {\"command\":\"命令名\"}\n"
        "系统会自动处理所有参数，你不需要填写任何参数。\n"
        "\n"
        "可用命令：\n"
        "- discover_network: 扫描局域网摄像头\n"
        "- connect_camera: 连接摄像头\n"
        "- watch_camera: 连接并拉流预览\n"
        "- get_stream: 获取视频流\n"
        "- take_photo: 截图保存\n"
        "- open_preview: 打开预览\n"
        "- get_status: 查看状态\n"
        "- list_cameras: 列出摄像头\n"
        "- set_password: 设置密码\n"
        "- auto_setup: 自动扫描+连接+拉流\n"
        "\n"
        "规则：\n"
        "1. 执行操作时只返回 {\"command\":\"命令名\"}\n"
        "2. 闲聊/回答问题时直接返回文字\n"
        "\n"
        "示例：\n"
        "用户：你好\n"
        "助手：你好！有什么可以帮你的？\n"
        "\n"
        "用户：扫描摄像头\n"
        "{\"command\":\"discover_network\"}\n"
        "\n"
        "用户：拉流\n"
        "{\"command\":\"watch_camera\"}\n"
    )


@dataclass
class AppConfig:
    """应用全局配置"""
    cameras: list = field(default_factory=list)   # 摄像头列表 (CameraConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @property
    def ollama(self) -> LLMConfig:
        """向后兼容：config.ollama → config.llm"""
        return self.llm

    def get_camera(self, name: str) -> Optional[CameraConfig]:
        """按名称获取摄像头配置"""
        for cam in self.cameras:
            if cam.name == name:
                return cam
        return None

    def add_camera(self, camera: CameraConfig) -> None:
        """添加摄像头配置"""
        self.cameras.append(camera)


def save_config(config: AppConfig, config_path: str = CONFIG_FILE) -> None:
    """将当前配置持久化到 YAML 文件"""
    data = {}
    # 序列化摄像头列表
    cameras_data = []
    for cam in config.cameras:
        cameras_data.append({
            "name": cam.name,
            "connection_type": cam.connection_type,
            "ip": cam.ip,
            "port": cam.port,
            "username": cam.username,
            "password": cam.password,
            "rtsp_port": cam.rtsp_port,
            "rtsp_path": cam.rtsp_path,
            "rtsp_sub_path": cam.rtsp_sub_path,
            "device_model": cam.device_model,
            "product_version": cam.product_version,
        })
    data["cameras"] = cameras_data

    # 序列化 LLM 配置
    llm = config.llm
    data["llm"] = {
        "backend": llm.backend,
        "model_path": llm.model_path,
        "base_url": llm.base_url,
        "model": llm.model,
        "timeout": llm.timeout,
        "temperature": llm.temperature,
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_config(config_path: str = CONFIG_FILE) -> AppConfig:
    """
    从 YAML 文件加载配置。
    若配置文件不存在，则返回默认配置并提示用户创建配置文件。
    """
    if not os.path.exists(config_path):
        print(f"[配置] 未找到配置文件: {config_path}")
        print("[配置] 已生成默认配置模板，请编辑后重新运行。")
        _create_default_config(config_path)
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # 解析摄像头列表
    cameras = []
    for cam_data in data.get("cameras", []):
        cameras.append(CameraConfig(**cam_data))

    # 解析 LLM 配置（兼容旧的 ollama 字段）
    llm_data = data.get("llm", data.get("ollama", {}))
    llm = LLMConfig(**llm_data)

    return AppConfig(cameras=cameras, llm=llm)


def _create_default_config(config_path: str) -> None:
    """生成默认配置模板文件"""
    default = {
        "cameras": [
            {
                "name": "M50_main",
                "connection_type": "onvif",
                "ip": "172.28.234.22",
                "port": 80,
                "username": "admin",
                "password": "1c3589",
                "rtsp_port": 554,
                "rtsp_path": "/stream1",
                "rtsp_sub_path": "/stream2",
                "device_model": "LC2418",
                "product_version": "ZCR461",
            }
        ],
        "llm": {
            "backend": "local",
            "model_path": "D:\\OllamaModels\\qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5:0.5b",
            "timeout": 60,
            "temperature": 0.3,
        },
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(default, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"[配置] 默认配置已写入: {config_path}")
