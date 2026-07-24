"""
XPAI Camera Control — MCP Server

Model Context Protocol server that exposes all camera control toolkit functions
as MCP tools. Supports stdio transport for seamless integration with MCP clients
(Claude Desktop, WorkBuddy, etc.).

Usage:
    python scripts/mcp_server.py                        # stdio transport (default)
    python scripts/mcp_server.py --transport stdio      # explicit stdio

Environment:
    XPAI_CONFIG_PATH — override config.yaml location
"""

import sys
import os
import json
import asyncio
import argparse
from typing import Any, Dict

# Ensure the parent directory is on the path
_skill_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _skill_root not in sys.path:
    sys.path.insert(0, _skill_root)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


# ═══════════════════════════════════════════════
#  Tool Definitions
# ═══════════════════════════════════════════════

TOOLS = [
    # ── Device Management ──
    Tool(
        name="get_registered_cameras",
        description="从 config.yaml 加载所有已注册摄像头配置。每次对话开始时必须先调用此函数，检查是否有缓存的摄像头信息。",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="register_camera",
        description="将摄像头信息写入 config.yaml，持久化凭据供下次自动连接。首次成功连接摄像头后调用。",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "摄像头唯一名称"},
                "ip": {"type": "string", "description": "IP 地址"},
                "port": {"type": "integer", "description": "ONVIF 端口（默认 80）", "default": 80},
                "username": {"type": "string", "description": "登录用户名（默认 admin）", "default": "admin"},
                "password": {"type": "string", "description": "登录密码"},
                "rtsp_port": {"type": "integer", "description": "RTSP 端口（默认 554）", "default": 554},
                "rtsp_path": {"type": "string", "description": "主流路径（默认 /stream1）", "default": "/stream1"},
                "device_class": {"type": "string", "description": "设备类型: password_required / direct_connect"},
                "connection_type": {"type": "string", "description": "连接类型: onvif / usb", "default": "onvif"},
                "sn_code": {"type": "string", "description": "序列号"},
                "pkdk": {"type": "string", "description": "设备公钥标识"},
                "rtsp_sub_path": {"type": "string", "description": "子流路径（默认 /stream2）", "default": "/stream2"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="search_devices",
        description="搜索局域网可用摄像头。支持 WS-Discovery、创维私有协议(SKY_DISCOVERY)、USB 三种发现方式。",
        inputSchema={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["ws_discovery", "sky_discovery", "usb"],
                    "description": "发现方式",
                    "default": "sky_discovery",
                },
                "timeout": {
                    "type": "number",
                    "description": "超时时间（秒，默认 15）",
                    "default": 15.0,
                },
            },
        },
    ),
    Tool(
        name="connect_device",
        description="连接摄像头设备。自动从 config.yaml 加载缓存的凭据；若无缓存则探测是否需要密码。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "password": {"type": "string", "description": "用户提供的密码（可选）"},
                "ip": {"type": "string", "description": "设备 IP（新发现设备时需传入）"},
                "port": {"type": "integer", "description": "ONVIF 端口（默认 80）"},
                "rtsp_port": {"type": "integer", "description": "RTSP 端口（默认 554）"},
                "rtsp_path": {"type": "string", "description": "RTSP 路径（默认 /stream1）"},
                "username": {"type": "string", "description": "登录用户名（默认 admin）"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="disconnect_device",
        description="断开与摄像头的连接，释放所有资源（停止流、释放会话、关闭连接）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="query_device_model",
        description="查询设备型号、固件版本、在线状态、网络信息。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),

    # ── Stream ──
    Tool(
        name="get_audio_video_stream",
        description="拉取实时音视频流。获取 RTSP URL 并验证流可用性，返回编码格式、分辨率、帧率等元数据。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "sub_stream": {
                    "type": "boolean",
                    "description": "是否使用子码流（低画质）",
                    "default": False,
                },
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="capture_video_screenshot",
        description="截取当前视频流画面并保存为 JPEG 文件。从 RTSP 流中捕获一帧，自动丢弃前几帧以获得稳定画面。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "save_path": {"type": "string", "description": "保存目录路径（默认 snapshots/）"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="toggle_recording",
        description="启动或停止本地录像。开始录像时将 RTSP 流录制到本地 MP4 文件。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop"],
                    "description": "start 开始录像 / stop 停止录像",
                },
                "save_path": {"type": "string", "description": "录像保存目录（默认 recordings/）"},
            },
            "required": ["camera_name", "action"],
        },
    ),
    Tool(
        name="manage_storage_status",
        description="查询存储状态或设置存储路径、格式与策略（overwrite / stop_when_full / circular）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["query", "set"],
                    "description": "query 查询 / set 设置",
                    "default": "query",
                },
                "path": {"type": "string", "description": "存储路径（action=set 时有效）"},
                "format": {
                    "type": "string",
                    "enum": ["mp4", "avi", "jpg"],
                    "description": "文件格式（action=set 时有效）",
                },
                "policy": {
                    "type": "string",
                    "enum": ["overwrite", "stop_when_full", "circular"],
                    "description": "存储策略（action=set 时有效）",
                },
            },
            "required": ["camera_name"],
        },
    ),

    # ── PTZ ──
    Tool(
        name="control_ptz",
        description="控制云台转动（上/下/左/右/左上/右下等 8 个方向）。仅 ONVIF 设备支持。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right", "upleft", "upright", "downleft", "downright"],
                    "description": "转动方向",
                },
                "speed": {
                    "type": "number",
                    "description": "转动速度 0.0–1.0（默认 0.5）",
                    "default": 0.5,
                },
                "duration_seconds": {
                    "type": "number",
                    "description": "转动时长（秒，默认 1.0）",
                    "default": 1.0,
                },
            },
            "required": ["camera_name", "direction"],
        },
    ),
    Tool(
        name="control_lens_zoom",
        description="控制镜头变焦（放大/缩小）。仅 ONVIF 设备支持。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "zoom_action": {
                    "type": "string",
                    "enum": ["in", "out", "stop"],
                    "description": "in 放大 / out 缩小 / stop 停止",
                },
                "speed": {
                    "type": "number",
                    "description": "变焦速度 0.0–1.0（默认 0.5）",
                    "default": 0.5,
                },
            },
            "required": ["camera_name", "zoom_action"],
        },
    ),
    Tool(
        name="get_ptz_parameters",
        description="获取当前云台参数（pan/tilt/zoom 位置和范围）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="save_ptz_preset",
        description="保存当前云台位置为预置点。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "preset_name": {"type": "string", "description": "预置点名称"},
            },
            "required": ["camera_name", "preset_name"],
        },
    ),
    Tool(
        name="go_to_preset",
        description="将云台移动到指定预置点位置。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "preset_name": {"type": "string", "description": "预置点名称"},
            },
            "required": ["camera_name", "preset_name"],
        },
    ),
    Tool(
        name="start_patrol_cruise",
        description="启动或停止云台巡航（按预置点序列循环转动）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop"],
                    "description": "start 启动巡航 / stop 停止巡航",
                },
                "preset_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "预置点名称列表（action=start 时使用）",
                },
                "dwell_seconds": {
                    "type": "number",
                    "description": "每个预置点停留时间（秒，默认 5）",
                    "default": 5.0,
                },
            },
            "required": ["camera_name", "action"],
        },
    ),

    # ── Tracking ──
    Tool(
        name="track_vehicles",
        description="启动或停止车辆追踪（AI 识别行驶车辆并控制云台跟随）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop"],
                    "description": "start 启动追踪 / stop 停止追踪",
                },
            },
            "required": ["camera_name", "action"],
        },
    ),
    Tool(
        name="track_human_shapes",
        description="启动或停止人形追踪（AI 识别行人并控制云台跟随）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop"],
                    "description": "start 启动追踪 / stop 停止追踪",
                },
            },
            "required": ["camera_name", "action"],
        },
    ),
    Tool(
        name="monitor_zone_entry",
        description="区域监控——启动或停止指定矩形区域的入侵检测。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop"],
                    "description": "start 启动监控 / stop 停止监控",
                },
                "zone_name": {"type": "string", "description": "监控区域名称"},
                "x1": {"type": "number", "description": "区域左上角 X 坐标"},
                "y1": {"type": "number", "description": "区域左上角 Y 坐标"},
                "x2": {"type": "number", "description": "区域右下角 X 坐标"},
                "y2": {"type": "number", "description": "区域右下角 Y 坐标"},
            },
            "required": ["camera_name", "action"],
        },
    ),

    # ── Image & Audio ──
    Tool(
        name="adjust_picture_settings",
        description="调整画面参数（亮度、对比度、饱和度、锐度、曝光值）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "brightness": {"type": "number", "description": "亮度 0–100"},
                "contrast": {"type": "number", "description": "对比度 0–100"},
                "saturation": {"type": "number", "description": "饱和度 0–100"},
                "sharpness": {"type": "number", "description": "锐度 0–100"},
                "exposure_value": {"type": "number", "description": "曝光值"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="flip_video_display",
        description="设置画面翻转模式（正常/水平翻转/垂直翻转/180°旋转）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "flip_mode": {
                    "type": "string",
                    "enum": ["normal", "horizontal", "vertical", "both"],
                    "description": "翻转模式",
                },
            },
            "required": ["camera_name", "flip_mode"],
        },
    ),
    Tool(
        name="configure_night_vision",
        description="配置夜视模式（自动/全天红外/全天全彩/定时切换）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "infrared_always", "full_color_always", "scheduled"],
                    "description": "夜视模式",
                },
            },
            "required": ["camera_name", "mode"],
        },
    ),
    Tool(
        name="set_floodlight_mode",
        description="设置补光灯模式（自动/常亮/常灭/联动报警）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "always_on", "always_off", "alarm_link"],
                    "description": "补光灯模式",
                },
            },
            "required": ["camera_name", "mode"],
        },
    ),
    Tool(
        name="configure_microphone",
        description="配置麦克风（开关、音量、降噪等级）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "enabled": {"type": "boolean", "description": "是否开启麦克风"},
                "volume": {"type": "number", "description": "音量 0–100"},
                "noise_reduction": {"type": "integer", "description": "降噪等级 0–5"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="configure_speaker",
        description="配置扬声器（开关、音量）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "enabled": {"type": "boolean", "description": "是否开启扬声器"},
                "volume": {"type": "number", "description": "音量 0–100"},
            },
            "required": ["camera_name"],
        },
    ),

    # ── Alarm ──
    Tool(
        name="configure_alarm_settings",
        description="配置报警设置（移动侦测、遮挡报警、声音报警的开关和灵敏度）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "motion_detection": {"type": "boolean", "description": "是否开启移动侦测"},
                "motion_sensitivity": {"type": "integer", "description": "移动侦测灵敏度 1–10"},
                "tamper_detection": {"type": "boolean", "description": "是否开启遮挡报警"},
                "audio_detection": {"type": "boolean", "description": "是否开启声音报警"},
                "audio_sensitivity": {"type": "integer", "description": "声音报警灵敏度 1–10"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="configure_alarm_push",
        description="配置报警推送方式（APP推送/邮件/短信/电话）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "push_type": {
                    "type": "string",
                    "enum": ["app_push", "email", "sms", "phone"],
                    "description": "推送方式",
                },
                "enabled": {"type": "boolean", "description": "是否启用该推送"},
            },
            "required": ["camera_name", "push_type", "enabled"],
        },
    ),

    # ── Encoding & OSD ──
    Tool(
        name="configure_video_encoding",
        description="配置视频编码参数（编码格式、分辨率、码率、帧率、I帧间隔）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "stream_type": {
                    "type": "string",
                    "enum": ["main", "sub"],
                    "description": "码流类型",
                },
                "codec": {
                    "type": "string",
                    "enum": ["h264", "h265", "mjpeg"],
                    "description": "编码格式",
                },
                "resolution": {"type": "string", "description": "分辨率（如 1920x1080）"},
                "bitrate": {"type": "integer", "description": "码率 (kbps)"},
                "fps": {"type": "integer", "description": "帧率"},
                "gop": {"type": "integer", "description": "I 帧间隔"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="configure_osd_settings",
        description="配置 OSD 水印设置（时间戳、摄像头名称、自定义文字的显示位置和对齐方式）。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "show_timestamp": {"type": "boolean", "description": "是否显示时间戳"},
                "show_camera_name": {"type": "boolean", "description": "是否显示摄像头名称"},
                "custom_text": {"type": "string", "description": "自定义文字"},
                "position": {
                    "type": "string",
                    "enum": ["top_left", "top_right", "bottom_left", "bottom_right"],
                    "description": "OSD 位置",
                },
            },
            "required": ["camera_name"],
        },
    ),

    # ── Discovery (创维私有协议) ──
    Tool(
        name="discover_sky_devices",
        description="通过创维私有协议（SK_DISCOVERY_SEARCH）搜索局域网内的创维摄像头。使用组播地址 239.230.236.230:9008。",
        inputSchema={
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "description": "超时时间（秒，默认 15）",
                    "default": 15.0,
                },
            },
        },
    ),
    Tool(
        name="send_tcp_command",
        description="通过创维 TCP 通道（端口 9010）向设备发送命令。需要 Basic Auth 认证。",
        inputSchema={
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "设备 IP 地址"},
                "service_type": {"type": "string", "description": "服务类型（如 device）"},
                "cmd_name": {"type": "string", "description": "命令名称（如 SK_DEVICE_GET_INFO）"},
                "username": {"type": "string", "description": "用户名", "default": "admin"},
                "password": {"type": "string", "description": "密码"},
                "timeout": {"type": "number", "description": "超时时间（秒）", "default": 5.0},
                "port": {"type": "integer", "description": "TCP 端口", "default": 9010},
            },
            "required": ["ip", "service_type", "cmd_name", "password"],
        },
    ),
]


# ═══════════════════════════════════════════════
#  MCP Server
# ═══════════════════════════════════════════════

def _serialize(obj: Any) -> Any:
    """将 dataclass 等复杂对象序列化为 JSON 兼容的 dict/list/str。"""
    if obj is None:
        return None
    if isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return {f.name: _serialize(getattr(obj, f.name)) for f in obj.__dataclass_fields__.values()}
    if hasattr(obj, "_value_"):  # Enum
        return obj.value
    return str(obj)


def _call_tool(name: str, args: Dict[str, Any]) -> Any:
    """路由工具调用到对应的 toolkit 函数。返回序列化后的结果。"""
    import scripts.toolkit as tk
    from scripts.toolkit.device_mgmt import DiscoveryMethod
    from scripts.toolkit.stream import RecordingAction, StorageAction
    from scripts.toolkit.ptz import PTZDirection, ZoomAction
    from scripts.toolkit.tracking import TrackingAction, ZoneAction
    from scripts.toolkit.image_audio import FlipMode, NightVisionMode, FloodlightMode
    from scripts.toolkit.alarm import PushType

    # ── Device Management ──
    if name == "get_registered_cameras":
        return _serialize(tk.get_registered_cameras())
    elif name == "register_camera":
        return _serialize(tk.register_camera(**args))
    elif name == "search_devices":
        args = dict(args)
        if "method" in args:
            args["method"] = DiscoveryMethod(args["method"])
        return _serialize(tk.search_devices(**args))
    elif name == "connect_device":
        return _serialize(tk.connect_device(**args))
    elif name == "disconnect_device":
        return _serialize(tk.disconnect_device(**args))
    elif name == "query_device_model":
        return _serialize(tk.query_device_model(**args))

    # ── Stream ──
    elif name == "get_audio_video_stream":
        return _serialize(tk.get_audio_video_stream(**args))
    elif name == "capture_video_screenshot":
        return _serialize(tk.capture_video_screenshot(**args))
    elif name == "toggle_recording":
        args = dict(args)
        if "action" in args:
            args["action"] = RecordingAction(args["action"])
        return _serialize(tk.toggle_recording(**args))
    elif name == "manage_storage_status":
        args = dict(args)
        if "action" in args:
            args["action"] = StorageAction(args.get("action", "query"))
        return _serialize(tk.manage_storage_status(**args))

    # ── PTZ ──
    elif name == "control_ptz":
        args = dict(args)
        if "direction" in args:
            args["direction"] = PTZDirection(args["direction"])
        return _serialize(tk.control_ptz(**args))
    elif name == "control_lens_zoom":
        args = dict(args)
        if "zoom_action" in args:
            args["zoom_action"] = ZoomAction(args["zoom_action"])
        return _serialize(tk.control_lens_zoom(**args))
    elif name == "get_ptz_parameters":
        return _serialize(tk.get_ptz_parameters(**args))
    elif name == "save_ptz_preset":
        return _serialize(tk.save_ptz_preset(**args))
    elif name == "go_to_preset":
        return _serialize(tk.go_to_preset(**args))
    elif name == "start_patrol_cruise":
        return _serialize(tk.start_patrol_cruise(**args))

    # ── Tracking ──
    elif name == "track_vehicles":
        args = dict(args)
        if "action" in args:
            args["action"] = TrackingAction(args["action"])
        return _serialize(tk.track_vehicles(**args))
    elif name == "track_human_shapes":
        args = dict(args)
        if "action" in args:
            args["action"] = TrackingAction(args["action"])
        return _serialize(tk.track_human_shapes(**args))
    elif name == "monitor_zone_entry":
        args = dict(args)
        if "action" in args:
            args["action"] = ZoneAction(args["action"])
        return _serialize(tk.monitor_zone_entry(**args))

    # ── Image & Audio ──
    elif name == "adjust_picture_settings":
        return _serialize(tk.adjust_picture_settings(**args))
    elif name == "flip_video_display":
        args = dict(args)
        if "flip_mode" in args:
            args["flip_mode"] = FlipMode(args["flip_mode"])
        return _serialize(tk.flip_video_display(**args))
    elif name == "configure_night_vision":
        args = dict(args)
        if "mode" in args:
            args["mode"] = NightVisionMode(args["mode"])
        return _serialize(tk.configure_night_vision(**args))
    elif name == "set_floodlight_mode":
        args = dict(args)
        if "mode" in args:
            args["mode"] = FloodlightMode(args["mode"])
        return _serialize(tk.set_floodlight_mode(**args))
    elif name == "configure_microphone":
        return _serialize(tk.configure_microphone(**args))
    elif name == "configure_speaker":
        return _serialize(tk.configure_speaker(**args))

    # ── Alarm ──
    elif name == "configure_alarm_settings":
        return _serialize(tk.configure_alarm_settings(**args))
    elif name == "configure_alarm_push":
        args = dict(args)
        if "push_type" in args:
            args["push_type"] = PushType(args["push_type"])
        return _serialize(tk.configure_alarm_push(**args))

    # ── Encoding & OSD ──
    elif name == "configure_video_encoding":
        return _serialize(tk.configure_video_encoding(**args))
    elif name == "configure_osd_settings":
        return _serialize(tk.configure_osd_settings(**args))

    # ── Discovery ──
    elif name == "discover_sky_devices":
        return _serialize(tk.discover_sky_devices(**args))
    elif name == "send_tcp_command":
        return _serialize(tk.send_tcp_command(**args))

    else:
        raise ValueError(f"Unknown tool: {name}")


# ═══════════════════════════════════════════════
#  Server Setup
# ═══════════════════════════════════════════════

server = Server("xpai-camera-control", version="0.2.0")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Return the list of available tools."""
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any] | None) -> list[TextContent]:
    """Handle a tool invocation and return results."""
    try:
        args = arguments or {}
        result = _call_tool(name, args)
        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": str(e),
            }, ensure_ascii=False, indent=2),
        )]


async def main():
    """Run the MCP server with stdio transport."""
    parser = argparse.ArgumentParser(description="XPAI Camera Control MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio"],
                        help="Transport to use (default: stdio)")
    args = parser.parse_args()

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
