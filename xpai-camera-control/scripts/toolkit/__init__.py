"""
XPAI Camera Control — Toolkit 工具集

提供摄像头控制的全部工具函数，按功能分为 7 大类：
  1. stream       — 音视频流与存储
  2. ptz          — 云台与巡航
  3. tracking     — 识别与追踪算法
  4. image_audio  — 视频图像与音频设置
  5. device_mgmt  — 设备管理与维护
  6. alarm        — 报警设置
  7. encoding_osd — 视频编码与 OSD 设置
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
    control_lens_zoom,
    get_ptz_parameters,
    save_ptz_preset,
    go_to_preset,
    calibrate_ptz,
    start_patrol_cruise,
    PTZMoveResult,
    PTZParameters,
    PTZPresetResult,
    CalibrateResult,
    CruiseResult,
    PTZDirection,
    ZoomAction,
)

# ── tracking ──
from .tracking import (
    track_vehicles,
    track_human_shapes,
    monitor_zone_entry,
    stop_tracking_service,
    TrackingResult,
    ZoneMonitorResult,
    StopTrackingResult,
    TrackingAction,
    ZoneAction,
)

# ── image_audio ──
from .image_audio import (
    adjust_picture_settings,
    flip_video_display,
    configure_night_vision,
    set_floodlight_mode,
    configure_floodlight_type,
    configure_microphone,
    configure_speaker,
    PictureResult,
    FlipResult,
    NightVisionResult,
    FloodlightModeResult,
    FloodlightTypeResult,
    MicrophoneResult,
    SpeakerResult,
    PictureSettings,
    FlipMode,
    NightVisionMode,
    FloodlightMode,
    FloodlightType,
)

# ── device_mgmt ──
from .device_mgmt import (
    get_registered_cameras,
    register_camera,
    search_devices,
    connect_device,
    disconnect_device,
    poll_auth_status,
    query_device_model,
    update_firmware,
    system_maintenance,
    DiscoveredDevice,
    SearchResult,
    ConnectResult,
    DisconnectResult,
    DeviceInfo,
    DeviceInfoResult,
    FirmwareResult,
    MaintenanceResult,
    DiscoveryMethod,
    DeviceClass,
    MaintenanceAction,
    CameraConfig,
    RegisterResult,
    AuthStatusResult,
    AuthStatus,
)

# ── discovery (创维私有协议) ──
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

# ── alarm ──
from .alarm import (
    configure_alarm_settings,
    configure_alarm_push,
    AlarmSettingsResult,
    AlarmPushResult,
    PushType,
)

# ── encoding_osd ──
from .encoding_osd import (
    configure_video_encoding,
    configure_osd_settings,
    EncodingSettings,
    EncodingResult,
    OSDSettings,
    OSDResult,
    StreamType,
    VideoCodec,
    BitrateMode,
    OSDAlignment,
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
    "control_lens_zoom",
    "get_ptz_parameters",
    "save_ptz_preset",
    "go_to_preset",
    "calibrate_ptz",
    "start_patrol_cruise",
    "PTZMoveResult",
    "PTZParameters",
    "PTZPresetResult",
    "CalibrateResult",
    "CruiseResult",
    "PTZDirection",
    "ZoomAction",
    # tracking
    "track_vehicles",
    "track_human_shapes",
    "monitor_zone_entry",
    "stop_tracking_service",
    "TrackingResult",
    "ZoneMonitorResult",
    "StopTrackingResult",
    "TrackingAction",
    "ZoneAction",
    # image_audio
    "adjust_picture_settings",
    "flip_video_display",
    "configure_night_vision",
    "set_floodlight_mode",
    "configure_floodlight_type",
    "configure_microphone",
    "configure_speaker",
    "PictureResult",
    "FlipResult",
    "NightVisionResult",
    "FloodlightModeResult",
    "FloodlightTypeResult",
    "MicrophoneResult",
    "SpeakerResult",
    "PictureSettings",
    "FlipMode",
    "NightVisionMode",
    "FloodlightMode",
    "FloodlightType",
    # device_mgmt
    "get_registered_cameras",
    "register_camera",
    "search_devices",
    "connect_device",
    "disconnect_device",
    "poll_auth_status",
    "query_device_model",
    "update_firmware",
    "system_maintenance",
    "DiscoveredDevice",
    "SearchResult",
    "ConnectResult",
    "DisconnectResult",
    "DeviceInfo",
    "DeviceInfoResult",
    "FirmwareResult",
    "MaintenanceResult",
    "DiscoveryMethod",
    "DeviceClass",
    "MaintenanceAction",
    "CameraConfig",
    "RegisterResult",
    "AuthStatusResult",
    "AuthStatus",
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
    # alarm
    "configure_alarm_settings",
    "configure_alarm_push",
    "AlarmSettingsResult",
    "AlarmPushResult",
    "PushType",
    # encoding_osd
    "configure_video_encoding",
    "configure_osd_settings",
    "EncodingSettings",
    "EncodingResult",
    "OSDSettings",
    "OSDResult",
    "StreamType",
    "VideoCodec",
    "BitrateMode",
    "OSDAlignment",
]
