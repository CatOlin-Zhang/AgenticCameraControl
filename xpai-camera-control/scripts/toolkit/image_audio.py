"""
Toolkit 4: 视频图像与音频设置

工具清单：
  - adjust_picture_settings  画面调节（亮度/对比度/饱和度/锐度）
  - flip_video_display       画面翻转
  - configure_night_vision   夜视设置（红外/全彩/微光）
  - set_floodlight_mode      补光灯模式（自动/常开/常关/定时）
  - configure_floodlight_type 补光灯类型（白灯/红外）
  - configure_microphone     麦克风设置
  - configure_speaker        扬声器设置
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ──────────────────────────────────────────────
#  枚举类型
# ──────────────────────────────────────────────

class FlipMode(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    BOTH = "both"
    NONE = "none"


class NightVisionMode(str, Enum):
    INFRARED = "infrared"       # 红外夜视
    FULL_COLOR = "full_color"   # 全彩夜视
    LOW_LIGHT = "low_light"     # 微光夜视


class FloodlightMode(str, Enum):
    AUTO = "auto"               # 自动
    ALWAYS_ON = "always_on"     # 常开
    ALWAYS_OFF = "always_off"   # 常关
    TIMED = "timed"             # 定时


class FloodlightType(str, Enum):
    WHITE = "white"             # 白灯
    INFRARED = "infrared"       # 红外


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class PictureSettings:
    """画面参数"""
    brightness: int = 128          # 亮度 (0–255)
    contrast: int = 128            # 对比度 (0–255)
    saturation: int = 128          # 饱和度 (0–255)
    sharpness: int = 128           # 锐度 (0–255)


@dataclass
class PictureResult:
    """画面调节返回结果"""
    success: bool
    current_settings: Optional[PictureSettings] = None
    error_message: str = ""


@dataclass
class FlipResult:
    """画面翻转返回结果"""
    success: bool
    current_mode: FlipMode = FlipMode.NONE
    error_message: str = ""


@dataclass
class NightVisionResult:
    """夜视设置返回结果"""
    success: bool
    current_mode: NightVisionMode = NightVisionMode.INFRARED
    error_message: str = ""


@dataclass
class FloodlightModeResult:
    """补光灯模式返回结果"""
    success: bool
    current_mode: FloodlightMode = FloodlightMode.AUTO
    error_message: str = ""


@dataclass
class FloodlightTypeResult:
    """补光灯类型返回结果"""
    success: bool
    current_type: FloodlightType = FloodlightType.WHITE
    error_message: str = ""


@dataclass
class MicrophoneResult:
    """麦克风设置返回结果"""
    success: bool
    enabled: bool = False
    gain: int = 0                  # 增益
    noise_reduction: bool = False  # 降噪是否开启
    error_message: str = ""


@dataclass
class SpeakerResult:
    """扬声器设置返回结果"""
    success: bool
    enabled: bool = False
    volume: int = 50               # 音量 (0–100)
    error_message: str = ""


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def adjust_picture_settings(
    camera_name: str,
    brightness: Optional[int] = None,
    contrast: Optional[int] = None,
    saturation: Optional[int] = None,
    sharpness: Optional[int] = None,
) -> PictureResult:
    """
    调节画面亮度、对比度、饱和度、锐度。

    仅传入需要修改的参数，未传入的参数保持不变。
    所有参数取值范围 0–255。
    通过 ONVIF Imaging Service SetImagingSettings 实现。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        brightness:  亮度 (0–255)，None 表示不修改
        contrast:    对比度 (0–255)，None 表示不修改
        saturation:  饱和度 (0–255)，None 表示不修改
        sharpness:   锐度 (0–255)，None 表示不修改

    Returns:
        PictureResult:
            - success: 是否成功
            - current_settings: 修改后的完整画面参数
            - error_message: 失败原因
    """
    raise NotImplementedError("adjust_picture_settings 待实现")


def flip_video_display(
    camera_name: str,
    mode: FlipMode = FlipMode.NONE,
) -> FlipResult:
    """
    翻转当前视频画面。

    支持水平翻转、垂直翻转、同时翻转、关闭翻转四种模式。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        mode:        翻转模式 (FlipMode)

    Returns:
        FlipResult:
            - success: 是否成功
            - current_mode: 当前翻转模式
            - error_message: 失败原因
    """
    raise NotImplementedError("flip_video_display 待实现")


def configure_night_vision(
    camera_name: str,
    mode: NightVisionMode = NightVisionMode.INFRARED,
) -> NightVisionResult:
    """
    切换夜视模式：红外、全彩、微光夜视。

    - infrared:   红外夜视（黑白画面，红外灯补光）
    - full_color: 全彩夜视（彩色画面，白光灯补光）
    - low_light:  微光夜视（低照度增强）

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        mode:        夜视模式 (NightVisionMode)

    Returns:
        NightVisionResult:
            - success: 是否成功
            - current_mode: 当前夜视模式
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_night_vision 待实现")


def set_floodlight_mode(
    camera_name: str,
    mode: FloodlightMode = FloodlightMode.AUTO,
) -> FloodlightModeResult:
    """
    设置补光灯工作模式。

    - auto:       自动（检测到暗光或运动时自动开启）
    - always_on:  常开
    - always_off: 常关
    - timed:      定时（需配合时间段配置）

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        mode:        补光灯模式 (FloodlightMode)

    Returns:
        FloodlightModeResult:
            - success: 是否成功
            - current_mode: 当前补光灯模式
            - error_message: 失败原因
    """
    raise NotImplementedError("set_floodlight_mode 待实现")


def configure_floodlight_type(
    camera_name: str,
    floodlight_type: FloodlightType = FloodlightType.WHITE,
) -> FloodlightTypeResult:
    """
    设置补光灯类型（白灯/红外）。

    - white:    白光灯（可见光，用于全彩夜视）
    - infrared: 红外灯（不可见光，用于红外夜视）

    安全约束: 显式提示

    Args:
        camera_name:     摄像头名称（自动填充）
        floodlight_type: 补光灯类型 (FloodlightType)

    Returns:
        FloodlightTypeResult:
            - success: 是否成功
            - current_type: 当前补光灯类型
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_floodlight_type 待实现")


def configure_microphone(
    camera_name: str,
    enabled: bool = True,
    gain: Optional[int] = None,
    noise_reduction: Optional[bool] = None,
) -> MicrophoneResult:
    """
    设置麦克风输入参数。

    控制摄像头内置麦克风的开关、增益和降噪功能。
    gain 取值范围取决于设备（通常 0–100）。

    安全约束: 显式提示 + 代码校验

    Args:
        camera_name:     摄像头名称（自动填充）
        enabled:         是否启用麦克风（默认 True）
        gain:            增益值（None 表示不修改）
        noise_reduction: 是否开启降噪（None 表示不修改）

    Returns:
        MicrophoneResult:
            - success: 是否成功
            - enabled: 当前麦克风状态
            - gain: 当前增益值
            - noise_reduction: 当前降噪状态
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_microphone 待实现")


def configure_speaker(
    camera_name: str,
    enabled: bool = True,
    volume: Optional[int] = None,
) -> SpeakerResult:
    """
    设置扬声器输出参数。

    控制摄像头内置扬声器的开关和音量。
    volume 取值范围 0–100。

    安全约束: 显式提示 + 代码校验

    Args:
        camera_name: 摄像头名称（自动填充）
        enabled:     是否启用扬声器（默认 True）
        volume:      音量 (0–100)，None 表示不修改

    Returns:
        SpeakerResult:
            - success: 是否成功
            - enabled: 当前扬声器状态
            - volume: 当前音量值
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_speaker 待实现")
