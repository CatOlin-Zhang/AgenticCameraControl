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

Demo 模式：调用 ``enable_demo_mode()`` 后，所有函数返回模拟数据，
无需真实硬件即可走通完整工作流。``capture_video_screenshot`` 会生成
真实 JPEG 图片。调用 ``disable_demo_mode()`` 恢复原始状态。
"""

import sys

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
    search_devices,
    connect_device,
    disconnect_device,
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


# ═══════════════════════════════════════════════
#  Demo Mode
# ═══════════════════════════════════════════════

_demo_mode = False

# Save originals for disable_demo_mode()
_originals = {}


def is_demo_mode() -> bool:
    """Check if demo mode is currently active."""
    return _demo_mode


def enable_demo_mode() -> None:
    """
    Enable demo mode — all toolkit functions return mock data.

    After calling this, every function in this module returns realistic
    demo data instead of raising ``NotImplementedError``. All state is
    deterministic and resettable. The ``capture_video_screenshot``
    function generates a real JPEG image file.

    Call ``disable_demo_mode()`` to restore original function references.
    This must be called again after each skill reload.
    """
    global _demo_mode
    if _demo_mode:
        return
    _demo_mode = True

    # Lazy import to avoid circular dependency
    from . import _demo as dm

    tk = sys.modules[__name__]      # scripts.toolkit namespace (this __init__.py)
    base = __name__                  # "scripts.toolkit"

    # ── Patch table ──
    # Each entry: (module_suffix, [function_names...])
    patches = [
        (".device_mgmt", [
            "search_devices", "connect_device", "disconnect_device",
            "query_device_model", "update_firmware", "system_maintenance",
        ]),
        (".stream", [
            "get_audio_video_stream", "capture_video_screenshot",
            "toggle_recording", "manage_storage_status",
        ]),
        (".ptz", [
            "control_ptz", "control_lens_zoom", "get_ptz_parameters",
            "save_ptz_preset", "go_to_preset", "calibrate_ptz",
            "start_patrol_cruise",
        ]),
        (".tracking", [
            "track_vehicles", "track_human_shapes", "monitor_zone_entry",
            "stop_tracking_service",
        ]),
        (".image_audio", [
            "adjust_picture_settings", "flip_video_display",
            "configure_night_vision", "set_floodlight_mode",
            "configure_floodlight_type", "configure_microphone",
            "configure_speaker",
        ]),
        (".alarm", [
            "configure_alarm_settings", "configure_alarm_push",
        ]),
        (".encoding_osd", [
            "configure_video_encoding", "configure_osd_settings",
        ]),
    ]

    for mod_suffix, func_names in patches:
        mod = sys.modules[base + mod_suffix]
        for name in func_names:
            demo_func = getattr(dm, f"_demo_{name}")
            # Keep a backup of the original function (only on first enable)
            if name not in _originals:
                _originals[name] = getattr(mod, name)
            # Patch source module
            setattr(mod, name, demo_func)
            # Patch __init__ exports namespace
            if hasattr(tk, name):
                setattr(tk, name, demo_func)


def disable_demo_mode() -> None:
    """
    Restore original toolkit functions, undoing ``enable_demo_mode()``.
    """
    global _demo_mode
    if not _demo_mode:
        return
    _demo_mode = False

    tk = sys.modules[__name__]
    base = __name__

    mod_suffixes = [
        ".device_mgmt", ".stream", ".ptz", ".tracking",
        ".image_audio", ".alarm", ".encoding_osd",
    ]

    for mod_suffix in mod_suffixes:
        mod = sys.modules.get(base + mod_suffix)
        if mod is None:
            continue
        for name, original in _originals.items():
            if hasattr(mod, name):
                setattr(mod, name, original)
            if hasattr(tk, name):
                setattr(tk, name, original)


def reset_demo_state() -> None:
    """
    Reset all demo internal state (PTZ position, presets, recording state, etc.)
    to initial values. Useful before starting a new test scenario.
    """
    from . import _demo as dm
    dm._demo_ptz_state.update({"pan": 0.0, "tilt": 0.0, "zoom": 1.0})
    dm._demo_presets.clear()
    dm._demo_recording_state.update({"is_recording": False, "start_time": 0.0, "file_path": ""})
    dm._demo_tracking_state.clear()
    dm._demo_connected_devices.clear()


__all__ = [
    # Demo mode
    "enable_demo_mode",
    "disable_demo_mode",
    "is_demo_mode",
    "reset_demo_state",
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
    "search_devices",
    "connect_device",
    "disconnect_device",
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
