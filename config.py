"""
配置模块 - 管理摄像头连接参数和 Ollama 服务配置
"""
import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.yaml")


@dataclass
class CameraConfig:
    """单个摄像头配置"""
    name: str                          # 摄像头名称标识
    ip: str                            # 摄像头 IP 地址
    port: int = 80                     # ONVIF 服务端口
    username: str = "admin"            # 登录用户名
    password: str = ""                 # 登录密码（必填）
    rtsp_port: int = 554               # RTSP 端口
    rtsp_path: str = "/stream1"        # RTSP 流路径（主码流）
    rtsp_sub_path: str = "/stream2"    # RTSP 子码流路径

    def get_rtsp_url(self, sub_stream: bool = False) -> str:
        """
        构造 RTSP 流地址
        :param sub_stream: True 使用子码流, False 使用主码流
        :return: 完整的 RTSP URL
        """
        path = self.rtsp_sub_path if sub_stream else self.rtsp_path
        return f"rtsp://{self.username}:{self.password}@{self.ip}:{self.rtsp_port}{path}"

    def get_onvif_url(self) -> str:
        """获取 ONVIF 服务地址"""
        return f"http://{self.ip}:{self.port}/onvif/device_service"


@dataclass
class OllamaConfig:
    """Ollama 服务配置"""
    base_url: str = "http://localhost:11434"   # Ollama 服务地址
    model: str = "qwen2.5:7b"                  # 使用的模型名称
    timeout: int = 60                          # 请求超时时间（秒）
    temperature: float = 0.3                   # 生成温度（控制指令场景用低温度）
    system_prompt: str = (
        "你是一个智能摄像头控制助手。你可以理解用户的自然语言指令，"
        "并将其转换为摄像头控制命令。当前可用的命令包括：\n"
        "- get_stream: 获取视频流\n"
        "- get_snapshot: 截图\n"
        "- get_status: 查询摄像头状态\n"
        "- list_cameras: 列出所有摄像头\n"
        "请用 JSON 格式返回命令，格式为：{\"command\": \"命令名\", \"params\": {参数}}"
    )


@dataclass
class AppConfig:
    """应用全局配置"""
    cameras: list = field(default_factory=list)   # 摄像头列表 (CameraConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)

    def get_camera(self, name: str) -> Optional[CameraConfig]:
        """按名称获取摄像头配置"""
        for cam in self.cameras:
            if cam.name == name:
                return cam
        return None

    def add_camera(self, camera: CameraConfig) -> None:
        """添加摄像头配置"""
        self.cameras.append(camera)


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

    # 解析 Ollama 配置
    ollama_data = data.get("ollama", {})
    ollama = OllamaConfig(**ollama_data)

    return AppConfig(cameras=cameras, ollama=ollama)


def _create_default_config(config_path: str) -> None:
    """生成默认配置模板文件"""
    default = {
        "cameras": [
            {
                "name": "camera_01",
                "ip": "192.168.1.100",
                "port": 80,
                "username": "admin",
                "password": "your_password_here",  # ← 请替换为实际密码
                "rtsp_port": 554,
                "rtsp_path": "/stream1",
                "rtsp_sub_path": "/stream2",
            }
        ],
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "qwen2.5:7b",
            "timeout": 60,
            "temperature": 0.3,
        },
    }
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(default, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"[配置] 默认配置已写入: {config_path}")
