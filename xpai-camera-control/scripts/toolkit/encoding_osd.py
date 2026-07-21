"""
Toolkit 7: 视频编码与 OSD 设置

工具清单：
  - configure_video_encoding  主/子码流编码格式、分辨率、码率、帧率、I帧间隔
  - configure_osd_settings    时间/星期/设备名称/OSD名称/对齐方式
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


# ──────────────────────────────────────────────
#  枚举类型
# ──────────────────────────────────────────────

class StreamType(str, Enum):
    MAIN = "main"              # 主码流（高清）
    SUB = "sub"                # 子码流（低清/流畅）


class VideoCodec(str, Enum):
    H264 = "H.264"
    H265 = "H.265"
    MJPEG = "MJPEG"


class BitrateMode(str, Enum):
    CBR = "cbr"                # 固定码率
    VBR = "vbr"                # 可变码率


class OSDAlignment(str, Enum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    CENTER = "center"


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class EncodingSettings:
    """编码参数"""
    stream_type: StreamType = StreamType.MAIN
    codec: VideoCodec = VideoCodec.H264
    resolution: str = ""                # 如 "1920x1080"
    bitrate_kbps: int = 0               # 码率 (kbps)
    fps: int = 0                        # 帧率
    gop: int = 0                        # I帧间隔 (GOP)
    bitrate_mode: BitrateMode = BitrateMode.VBR


@dataclass
class EncodingResult:
    """编码设置返回结果"""
    success: bool
    current_settings: Optional[EncodingSettings] = None
    error_message: str = ""


@dataclass
class OSDSettings:
    """OSD 参数"""
    show_time: bool = True
    show_weekday: bool = False
    device_name: str = ""
    osd_name: str = ""
    alignment: OSDAlignment = OSDAlignment.TOP_LEFT


@dataclass
class OSDResult:
    """OSD 设置返回结果"""
    success: bool
    current_settings: Optional[OSDSettings] = None
    error_message: str = ""


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def configure_video_encoding(
    camera_name: str,
    stream_type: StreamType = StreamType.MAIN,
    codec: Optional[VideoCodec] = None,
    resolution: Optional[str] = None,
    bitrate_kbps: Optional[int] = None,
    fps: Optional[int] = None,
    gop: Optional[int] = None,
    bitrate_mode: Optional[BitrateMode] = None,
) -> EncodingResult:
    """
    配置主码流/子码流编码格式、分辨率、码率控制、帧率控制、I帧间隔。

    仅传入需要修改的参数，未传入的参数保持不变。
    通过 ONVIF Media Service SetVideoEncoderConfiguration 实现。

    常见分辨率:
      - "1920x1080" (1080P)
      - "1280x720"  (720P)
      - "640x480"   (VGA)
      - "352x288"   (CIF)

    安全约束: 显式提示 + 代码校验（校验参数组合合法性，如分辨率与码率的匹配）

    Args:
        camera_name:  摄像头名称（自动填充）
        stream_type:  码流类型 (StreamType.MAIN / StreamType.SUB)
        codec:        编码格式 (VideoCodec)，None 表示不修改
        resolution:   分辨率字符串 "WxH"，None 表示不修改
        bitrate_kbps: 码率 (kbps)，None 表示不修改
        fps:          帧率，None 表示不修改
        gop:          I帧间隔 (Group of Pictures)，None 表示不修改
        bitrate_mode: 码率模式 (BitrateMode.CBR / BitrateMode.VBR)，None 表示不修改

    Returns:
        EncodingResult:
            - success: 操作是否成功
            - current_settings: 修改后的完整编码参数
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_video_encoding 待实现")


def configure_osd_settings(
    camera_name: str,
    show_time: Optional[bool] = None,
    show_weekday: Optional[bool] = None,
    device_name: Optional[str] = None,
    osd_name: Optional[str] = None,
    alignment: Optional[OSDAlignment] = None,
) -> OSDResult:
    """
    配置 OSD（On-Screen Display）叠加信息。

    控制画面中叠加显示的文字信息：
    - 时间戳显示/隐藏
    - 星期显示/隐藏
    - 设备名称
    - 自定义 OSD 名称
    - 文字对齐方式

    仅传入需要修改的参数，未传入的参数保持不变。
    通过 ONVIF Media Service SetOSD 实现。

    安全约束: 显式提示 + 代码校验

    Args:
        camera_name:  摄像头名称（自动填充）
        show_time:    是否显示时间戳（None 表示不修改）
        show_weekday: 是否显示星期（None 表示不修改）
        device_name:  设备名称（None 表示不修改）
        osd_name:     自定义 OSD 名称（None 表示不修改）
        alignment:    文字对齐方式 (OSDAlignment)，None 表示不修改

    Returns:
        OSDResult:
            - success: 操作是否成功
            - current_settings: 修改后的完整 OSD 参数
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_osd_settings 待实现")
