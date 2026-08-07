"""
XPAI Camera Control — Toolkit 工具集

提供摄像头控制的全部工具函数，按功能分为 7 大类：
  1. stream         — 音视频流与存储（含 WebRTC go2rtc 转流）
  2. ptz            — 云台与巡航
  3. device_mgmt    — 设备管理与维护
  4. events         — IPC 事件接收（双协议告警监听 + 落盘）
  5. illumination   — 补光模式控制（SK HTTP 私有协议）
  6. image_settings — 图像参数设置（SK 私有协议优先，ONVIF Imaging 回退）
  7. tracking       — 侦测追踪控制（人形追踪/车辆追踪/区域检测，SK HTTP 私有协议）

注意: discovery.py 为内部实现模块，其函数（send_tcp_command、
discover_sky_devices 等）不在此导出，Agent 通过 MCP 工具间接使用。
"""

# ── stream ──
from .stream import (
    get_audio_video_stream,
    capture_video_screenshot,
    toggle_recording,
    manage_storage_status,
    start_webrtc_stream,
    stop_webrtc_stream,
    StreamResult,
    ScreenshotResult,
    RecordingResult,
    StorageResult,
    WebRTCResult,
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
    DiscoveredDevice,
    SearchResult,
    ConnectResult,
    DisconnectResult,
    DiscoveryMethod,
    DeviceClass,
    CameraConfig,
    RegisterResult,
    # 云端授权
    AuthStatus,
    AuthOrchestrateResult,
    AuthStatusResult,
    CloudAuthRequestResult,
    request_cloud_auth,
    poll_auth_status,
    big_connect,
    resolve_target,
)

# ── events (IPC 事件接收) ──
from .events import (
    manage_camera_events,
    EventAction,
    CameraEvent,
    EventMonitorResult,
    PendingEventsResult,
)

# ── illumination (补光模式控制) ──
from .illumination import (
    manage_illumination,
    probe_illumination_capability,
    IlluminationAction,
    IlluminationInfo,
    FilllightQueryResult,
    FilllightSetResult,
    big_filllight_query,
    big_filllight_set,
    DAYNIGHT_MODES,
    FILLLIGHT_MODES,
)

# ── image_settings (图像参数设置) ──
from .image_settings import (
    manage_image_settings,
    ImageAction,
    ImageQueryResult,
    ImageSetResult,
)

# ── tracking (侦测追踪控制) ──
from .tracking import (
    manage_tracking,
    TrackingAction,
    DetectType,
    TrackingQueryResult,
    TrackingSetResult,
)


__all__ = [
    # stream
    "get_audio_video_stream",
    "capture_video_screenshot",
    "toggle_recording",
    "manage_storage_status",
    "start_webrtc_stream",
    "stop_webrtc_stream",
    "StreamResult",
    "ScreenshotResult",
    "RecordingResult",
    "StorageResult",
    "WebRTCResult",
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
    "DiscoveredDevice",
    "SearchResult",
    "ConnectResult",
    "DisconnectResult",
    "DiscoveryMethod",
    "DeviceClass",
    "CameraConfig",
    "RegisterResult",
    # device_mgmt (云端授权)
    "AuthStatus",
    "AuthOrchestrateResult",
    "AuthStatusResult",
    "CloudAuthRequestResult",
    "request_cloud_auth",
    "poll_auth_status",
    "big_connect",
    "resolve_target",
    # events (IPC 事件接收)
    "manage_camera_events",
    "EventAction",
    "CameraEvent",
    "EventMonitorResult",
    "PendingEventsResult",
    # illumination (补光模式控制)
    "manage_illumination",
    "probe_illumination_capability",
    "IlluminationAction",
    "IlluminationInfo",
    "FilllightQueryResult",
    "FilllightSetResult",
    "big_filllight_query",
    "big_filllight_set",
    "DAYNIGHT_MODES",
    "FILLLIGHT_MODES",
    # image_settings (图像参数设置)
    "manage_image_settings",
    "ImageAction",
    "ImageQueryResult",
    "ImageSetResult",
    # tracking (侦测追踪控制)
    "manage_tracking",
    "TrackingAction",
    "DetectType",
    "TrackingQueryResult",
    "TrackingSetResult",
]
