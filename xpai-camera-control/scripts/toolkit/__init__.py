"""
XPAI Camera Control — Toolkit 工具集

提供摄像头控制的全部工具函数，按功能分为 4 大类：
  1. stream       — 音视频流与存储
  2. ptz          — 云台与巡航
  3. device_mgmt  — 设备管理与维护
  4. events       — IPC 事件接收（双协议告警监听 + 落盘）

注意: discovery.py / auth/ 为内部实现模块，其函数（send_tcp_command、
discover_sky_devices 等）不在此导出，Agent 通过 MCP 工具间接使用。
"""

# ── stream ──
from .stream import (
    get_audio_video_stream,
    capture_video_screenshot,
    toggle_recording,
    manage_storage_status,
    StreamResult,
    ScreenshotResult,
    RecordingResult,
    StorageResult,
    RecordingAction,
    StorageAction,
)

# ── ptz ──
from .ptz import (
    control_ptz,
    get_ptz_parameters,
    calibrate_ptz,
    stop_ptz,
    PTZMoveResult,
    PTZParameters,
    CalibrateResult,
    PTZDirection,
    PTZInfo,
)

# ── device_mgmt ──
from .device_mgmt import (
    get_registered_cameras,
    register_camera,
    search_devices,
    connect_device,
    disconnect_device,
    poll_auth_status,
    request_cloud_auth,
    DiscoveredDevice,
    SearchResult,
    ConnectResult,
    DisconnectResult,
    DiscoveryMethod,
    DeviceClass,
    CameraConfig,
    RegisterResult,
    AuthStatusResult,
    AuthStatus,
    CloudAuthRequestResult,
)

# ── events (IPC 事件接收) ──
from .events import (
    manage_camera_events,
    EventAction,
    CameraEvent,
    EventMonitorResult,
    PendingEventsResult,
)


__all__ = [
    # stream
    "get_audio_video_stream",
    "capture_video_screenshot",
    "toggle_recording",
    "manage_storage_status",
    "StreamResult",
    "ScreenshotResult",
    "RecordingResult",
    "StorageResult",
    "RecordingAction",
    "StorageAction",
    # ptz
    "control_ptz",
    "get_ptz_parameters",
    "calibrate_ptz",
    "stop_ptz",
    "PTZMoveResult",
    "PTZParameters",
    "CalibrateResult",
    "PTZDirection",
    "PTZInfo",
    # device_mgmt
    "get_registered_cameras",
    "register_camera",
    "search_devices",
    "connect_device",
    "disconnect_device",
    "poll_auth_status",
    "request_cloud_auth",
    "DiscoveredDevice",
    "SearchResult",
    "ConnectResult",
    "DisconnectResult",
    "DiscoveryMethod",
    "DeviceClass",
    "CameraConfig",
    "RegisterResult",
    "AuthStatusResult",
    "AuthStatus",
    "CloudAuthRequestResult",
    # events (IPC 事件接收)
    "manage_camera_events",
    "EventAction",
    "CameraEvent",
    "EventMonitorResult",
    "PendingEventsResult",
]
