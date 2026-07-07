"""
phase2 - 配置模块 - 管理摄像头连接参数、LLM 推理配置、SN 认证配置
支持 USB(UVC) 和 ONVIF/RTSP(局域网) 两种连接方式
LLM 后端: local (llama-cpp-python) 或 ollama

协议类型:
  - USB: 本地 UVC 设备直连
  - ONVIF: 局域网 ONVIF 协议 (HTTP + RTSP)

Phase2 新增:
  - 摄像头配置中添加 SN 码字段
  - 密码字段可为空（运行时由 SN 解码填充）
  - 全局 SN 缓存文件配置
"""
import os
import yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# 项目根目录（phase2/ 的上一级 → 项目根目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PHASE2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PHASE2_ROOT, "config.yaml")
SN_CACHE_FILE = os.path.join(PHASE2_ROOT, "sn_cache.json")


class ConnectionType(Enum):
    """摄像头连接类型"""
    USB = "usb"           # USB(UVC) 直连
    ONVIF = "onvif"       # ONVIF 局域网协议 (RTSP 视频流)


@dataclass
class CameraConfig:
    """单个摄像头配置"""
    name: str                                  # 摄像头名称标识
    connection_type: str = "onvif"             # 连接类型: usb / onvif
    # ── USB 连接参数 ──
    device_index: int = 0                      # USB 设备索引（OpenCV VideoCapture）
    device_model: str = ""                     # 设备型号
    product_version: str = ""                  # 产品版本
    # ── ONVIF/RTSP 局域网参数 ──
    ip: str = ""                               # 摄像头 IP 地址
    port: int = 80                             # ONVIF 服务端口
    username: str = "admin"                    # 登录用户名
    password: str = ""                         # 登录密码（可为空，运行时由 SN 解码填充）
    rtsp_port: int = 554                       # RTSP 端口
    rtsp_path: str = "/stream1"                # RTSP 流路径（主码流）
    rtsp_sub_path: str = "/stream2"            # RTSP 子码流路径
    # ── Phase2 新增: SN 码认证 ──
    sn_code: str = ""                          # 设备 SN 码（输入后自动解码为密码）

    @property
    def is_usb(self) -> bool:
        return self.connection_type == ConnectionType.USB.value

    @property
    def is_onvif(self) -> bool:
        return self.connection_type == ConnectionType.ONVIF.value

    def get_rtsp_url(self, sub_stream: bool = False) -> str:
        """构造 RTSP 流地址"""
        path = self.rtsp_sub_path if sub_stream else self.rtsp_path
        if self.password:
            return f"rtsp://{self.username}:{self.password}@{self.ip}:{self.rtsp_port}{path}"
        else:
            return f"rtsp://{self.ip}:{self.rtsp_port}{path}"

    def get_onvif_url(self) -> str:
        """获取 ONVIF 服务地址"""
        return f"http://{self.ip}:{self.port}/onvif/device_service"


@dataclass
class LLMConfig:
    """LLM 推理配置"""
    backend: str = "local"
    model_path: str = "D:\\OllamaModels\\qwen2.5-0.5b-instruct-q4_k_m.gguf"
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:0.5b"
    timeout: int = 60
    temperature: float = 0.3
    system_prompt: str = (
        "你是摄像头控制助手。用户用自然语言告诉你想要什么，你返回一个JSON命令。\n"
        "\n"
        "可用命令：\n"
        "- watch_camera: 连接摄像头并打开实时视频（自动连接+拉流+预览）\n"
        "- take_photo: 连接摄像头并截图保存\n"
        "- discover_network: 扫描局域网摄像头\n"
        "- discover_usb: 扫描本机USB摄像头\n"
        "- connect_camera: 连接摄像头\n"
        "- disconnect_camera: 断开摄像头\n"
        "- get_status: 查看摄像头状态\n"
        "- list_cameras: 列出所有摄像头\n"
        "- input_sn: 用户想要输入设备SN码来获取摄像头权限\n"
        "- auto_setup: 自动扫描+连接+拉流全流程\n"
        "\n"
        "规则：只返回JSON，不要解释。\n"
        "格式：{\"command\":\"命令名\",\"params\":{}}\n"
        "如果不指定摄像头，params可以为空对象{}。\n"
        "如果只是聊天，返回文字即可。\n"
        "\n"
        "示例：\n"
        "用户：我想看看摄像头的视频\n"
        "{\"command\":\"watch_camera\",\"params\":{}}\n"
        "\n"
        "用户：帮我截个图\n"
        "{\"command\":\"take_photo\",\"params\":{}}\n"
        "\n"
        "用户：扫描一下局域网里有什么摄像头\n"
        "{\"command\":\"discover_network\",\"params\":{}}\n"
        "\n"
        "用户：我的设备SN码是ABC123456\n"
        "{\"command\":\"input_sn\",\"params\":{\"sn\":\"ABC123456\"}}\n"
        "\n"
        "用户：帮我搞定一切\n"
        "{\"command\":\"auto_setup\",\"params\":{}}\n"
    )


@dataclass
class AppConfig:
    """应用全局配置"""
    cameras: list = field(default_factory=list)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @property
    def ollama(self) -> LLMConfig:
        """向后兼容"""
        return self.llm

    def get_camera(self, name: str) -> Optional[CameraConfig]:
        for cam in self.cameras:
            if cam.name == name:
                return cam
        return None

    def add_camera(self, camera: CameraConfig) -> None:
        self.cameras.append(camera)


def load_config(config_path: str = CONFIG_FILE) -> AppConfig:
    """从 YAML 文件加载配置。"""
    if not os.path.exists(config_path):
        print(f"[配置] 未找到配置文件: {config_path}")
        print("[配置] 已生成默认配置模板，请编辑后重新运行。")
        _create_default_config(config_path)
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    cameras = []
    for cam_data in data.get("cameras", []):
        cameras.append(CameraConfig(**cam_data))

    llm_data = data.get("llm", data.get("ollama", {}))
    llm = LLMConfig(**llm_data)

    return AppConfig(cameras=cameras, llm=llm)


def _create_default_config(config_path: str) -> None:
    """生成默认配置模板文件"""
    default = {
        "cameras": [
            {
                "name": "camera_1",
                "connection_type": "onvif",
                "ip": "192.168.1.100",
                "port": 80,
                "username": "admin",
                "password": "",
                "sn_code": "",
                "rtsp_port": 554,
                "rtsp_path": "/stream1",
                "rtsp_sub_path": "/stream2",
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
