"""
XPAI Camera Control — Toolkit 工具集

提供摄像头控制的全部工具函数，按功能分为 5 大类：
  1. stream       — 音视频流与存储
  2. ptz          — 云台与巡航
  3. device_mgmt  — 设备管理与维护
  4. discovery    — 创维私有协议发现
  5. events       — IPC 事件接收（双协议告警监听 + 落盘）
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
# 注意: _move_to_position 为内部函数，保留导出供二次开发者直接调用，
# 但不作为 MCP 工具暴露（未在 mcp_server.py 中注册）。
from .ptz import (
    control_ptz,
    get_ptz_parameters,
    calibrate_ptz,
    _move_to_position,
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
    generate_claw_id,
    get_or_create_claw_id,
    _build_rtsp_url,
)

# ── discovery (创维私有协议) ──
# 注意: send_tcp_command 保留导出供二次开发者直接调用，
# 但不作为 MCP 工具暴露（已在 mcp_server.py 中移除注册）。
from .discovery import (
    SkDiscoveredDevice,
    SkChannelInfo,
    SkyDiscoveryListener,
    discover_sky_devices,
    send_tcp_command,
    SK_MULTICAST_ADDR,
    SK_MULTICAST_PORT,
    SK_TOOL_RECV_PORT,
    SK_TCP_PORT,
    SUBTYPE_NAMES,
)

# ── events (IPC 事件接收) ──
# 注意: manage_camera_events 为唯一注册的 MCP 工具（action 切换模式）；
# start/stop/get_pending/wait 为内部实现，保留导出供二次开发直接调用。
from .events import (
    manage_camera_events,
    EventAction,
    start_event_monitor,
    stop_event_monitor,
    get_pending_events,
    wait_for_events,
    CameraEvent,
    EventMonitorResult,
    PendingEventsResult,
    EVENT_STORE_PATH,
    EVENTS_DIR,
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
    "_move_to_position",
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
    "generate_claw_id",
    "get_or_create_claw_id",
    "_build_rtsp_url",
    # discovery (创维私有协议)
    "SkDiscoveredDevice",
    "SkChannelInfo",
    "SkyDiscoveryListener",
    "discover_sky_devices",
    "send_tcp_command",
    "SK_MULTICAST_ADDR",
    "SK_MULTICAST_PORT",
    "SK_TOOL_RECV_PORT",
    "SK_TCP_PORT",
    "SUBTYPE_NAMES",
    # events (IPC 事件接收)
    "manage_camera_events",
    "EventAction",
    "start_event_monitor",
    "stop_event_monitor",
    "get_pending_events",
    "wait_for_events",
    "CameraEvent",
    "EventMonitorResult",
    "PendingEventsResult",
    "EVENT_STORE_PATH",
    "EVENTS_DIR",
]
