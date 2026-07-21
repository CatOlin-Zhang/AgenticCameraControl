"""
Toolkit 1: 音视频流与存储

工具清单：
  - get_audio_video_stream  拉取实时音视频流
  - capture_video_screenshot 截取当前画面并保存
  - toggle_recording        启动或停止录像
  - manage_storage_status   查询/设置存储状态、路径与策略
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class RecordingAction(str, Enum):
    START = "start"
    STOP = "stop"


class StorageAction(str, Enum):
    QUERY = "query"
    SET = "set"


@dataclass
class StreamResult:
    """拉流操作返回结果"""
    success: bool                                # 是否成功获取流
    stream_url: str = ""                         # RTSP / USB 流地址
    codec: str = ""                              # 编码格式 (H.264 / H.265 / MJPEG)
    resolution: str = ""                         # 分辨率 (如 "1920x1080")
    fps: float = 0.0                             # 帧率
    bitrate: int = 0                             # 码率 (kbps)
    error_message: str = ""                      # 失败原因


@dataclass
class ScreenshotResult:
    """截图操作返回结果"""
    success: bool                                # 是否截图成功
    file_path: str = ""                          # 截图保存的完整路径
    width: int = 0                               # 截图宽度
    height: int = 0                              # 截图高度
    error_message: str = ""                      # 失败原因


@dataclass
class RecordingResult:
    """录像操作返回结果"""
    success: bool                                # 操作是否成功
    is_recording: bool = False                   # 当前是否在录像
    file_path: str = ""                          # 录像文件路径（停止时返回）
    duration_seconds: float = 0.0                # 已录制时长（停止时返回）
    error_message: str = ""                      # 失败原因


@dataclass
class StorageResult:
    """存储管理操作返回结果"""
    success: bool                                # 操作是否成功
    used_space_mb: float = 0.0                   # 已用空间 (MB)
    available_space_mb: float = 0.0              # 可用空间 (MB)
    storage_path: str = ""                       # 当前存储路径
    format: str = ""                             # 文件格式 (mp4 / avi / jpg)
    policy: str = ""                             # 策略名称 (overwrite / stop_when_full / circular)
    error_message: str = ""                      # 失败原因


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def get_audio_video_stream(
    camera_name: str,
    sub_stream: bool = False,
) -> StreamResult:
    """
    拉取实时音视频流。

    获取当前摄像头的实时音视频流地址并打开预览。
    - ONVIF 设备：通过 ONVIF Media Service GetStreamUri 获取 RTSP URL
    - USB 设备：通过 OpenCV VideoCapture 直接读取帧
    - 自动降级：ONVIF 不可用时尝试 RTSP 直连，依次试多种常见路径

    安全约束: 显式提示 + 代码校验（校验设备已连接、流地址可用）

    Args:
        camera_name: 摄像头名称（自动填充，通常为当前连接的设备）
        sub_stream:  是否使用子码流（低画质，默认 False 使用主码流）

    Returns:
        StreamResult:
            - success: True 表示成功获取流
            - stream_url: RTSP URL 或 USB 设备标识
            - codec: 编码格式（H.264 / H.265）
            - resolution: 分辨率字符串（如 "1920x1080"）
            - fps: 帧率
            - bitrate: 码率 (kbps)
            - error_message: 失败时的错误描述
    """
    raise NotImplementedError("get_audio_video_stream 待实现")


def capture_video_screenshot(
    camera_name: str,
    save_path: Optional[str] = None,
) -> ScreenshotResult:
    """
    截取当前流画面并保存到指定路径。

    从当前视频流中截取一帧画面，保存为 JPEG 文件。
    如果 save_path 为空，则默认保存到 snapshots/ 目录，文件名含时间戳。

    安全约束: 显式提示 + 代码校验（校验设备已连接、可获取帧数据）

    Args:
        camera_name: 摄像头名称（自动填充）
        save_path:   保存目录路径（默认 snapshots/）

    Returns:
        ScreenshotResult:
            - success: True 表示截图成功
            - file_path: 截图文件完整路径
            - width / height: 截图分辨率
            - error_message: 失败时的错误描述
    """
    raise NotImplementedError("capture_video_screenshot 待实现")


def toggle_recording(
    camera_name: str,
    action: RecordingAction,
    save_path: Optional[str] = None,
) -> RecordingResult:
    """
    启动或停止本地录像。

    开始录像时创建 VideoWriter 将视频流录制到本地文件；
    停止录像时关闭 VideoWriter 并返回录像文件路径。

    安全约束: 显式提示 + 代码校验（校验设备已连接、存储空间充足）

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      RecordingAction.START 开始录像 / RecordingAction.STOP 停止录像
        save_path:   录像保存目录（默认 recordings/）

    Returns:
        RecordingResult:
            - success: 操作是否成功
            - is_recording: 当前是否在录像
            - file_path: 录像文件路径（停止时返回）
            - duration_seconds: 已录制时长（停止时返回）
            - error_message: 失败时的错误描述
    """
    raise NotImplementedError("toggle_recording 待实现")


def manage_storage_status(
    camera_name: str,
    action: StorageAction = StorageAction.QUERY,
    path: Optional[str] = None,
    format: Optional[str] = None,
    policy: Optional[str] = None,
) -> StorageResult:
    """
    查询存储状态，设置存储路径与格式，存储策略。

    action=QUERY 时仅查询当前存储使用情况和配置；
    action=SET 时更新存储路径、文件格式或存储策略。

    存储策略说明：
      - overwrite:      空间不足时自动覆盖最旧文件
      - stop_when_full: 空间不足时停止录像
      - circular:       循环缓冲区模式

    安全约束: 显式提示 + 代码校验（校验路径可写、策略参数合法）

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      StorageAction.QUERY 查询 / StorageAction.SET 设置
        path:        存储路径（action=SET 时有效）
        format:      文件格式 "mp4" / "avi" / "jpg"（action=SET 时有效）
        policy:      策略名称 "overwrite" / "stop_when_full" / "circular"（action=SET 时有效）

    Returns:
        StorageResult:
            - success: 操作是否成功
            - used_space_mb: 已用空间 (MB)
            - available_space_mb: 可用空间 (MB)
            - storage_path: 当前存储路径
            - format: 文件格式
            - policy: 策略名称
            - error_message: 失败时的错误描述
    """
    raise NotImplementedError("manage_storage_status 待实现")
