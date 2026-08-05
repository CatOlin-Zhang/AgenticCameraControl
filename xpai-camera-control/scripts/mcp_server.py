"""
XPAI Camera Control — MCP Server

Model Context Protocol server that exposes all camera control toolkit functions
as MCP tools. Supports stdio transport for seamless integration with any
MCP-compatible client.

Usage:
    python scripts/mcp_server.py                        # stdio transport (default)
    python scripts/mcp_server.py --transport stdio      # explicit stdio
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
        description="加载所有已注册摄像头配置。会话开始时必须先调用。",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="register_camera",
        description="持久化摄像头凭据到配置文件，供下次自动连接。",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "摄像头唯一名称"},
                "ip": {"type": "string", "description": "IP 地址"},
                "port": {"type": "integer", "description": "ONVIF 端口（只传验证过的真实端口；未知请省略，由 connect_device 探测后自动回写）"},
                "username": {"type": "string", "description": "登录用户名", "default": "admin"},
                "password": {"type": "string", "description": "登录密码"},
                "rtsp_port": {"type": "integer", "description": "RTSP 端口", "default": 554},
                "rtsp_path": {"type": "string", "description": "主流路径", "default": "/stream1"},
                "device_class": {"type": "string", "description": "设备类型: password_required / direct_connect"},
                "connection_type": {"type": "string", "description": "连接类型: onvif / usb", "default": "onvif"},
                "sn_code": {"type": "string", "description": "序列号"},
                "pkdk": {"type": "string", "description": "设备公钥标识"},
                "rtsp_sub_path": {"type": "string", "description": "子流路径", "default": "/stream2"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="search_devices",
        description="搜索局域网内的摄像头。自动选择最佳发现协议，返回统一结果。",
        inputSchema={
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "description": "超时秒数",
                    "default": 15.0,
                },
            },
        },
    ),
    Tool(
        name="connect_device",
        description="连接摄像头。自动加载缓存凭据；无缓存时探测是否需要密码。需要密码的设备自动发起云端授权（内部流程，无需额外工具）：云端同意则自动连接；云端不可用则返回 needs_password 让用户直接输入；云端拒绝返回 auth_rejected；云端密码不匹配返回 cloud_pwd_failed。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "password": {"type": "string", "description": "用户密码（可选）"},
                "ip": {"type": "string", "description": "设备 IP"},
                "port": {"type": "integer", "description": "ONVIF 端口（可选；不传或传错时工具会自动探测验证真实端口）"},
                "rtsp_port": {"type": "integer", "description": "RTSP 端口"},
                "rtsp_path": {"type": "string", "description": "RTSP 路径"},
                "username": {"type": "string", "description": "登录用户名"},
                "sn_code": {"type": "string", "description": "设备 SN（发现阶段获取，云端授权必需）"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="disconnect_device",
        description="断开摄像头连接，释放所有资源。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),

    # ── Cloud Auth (云端授权) ──
    # 注意: poll_auth_status / big_connect 已从 MCP 工具降为内部函数；
    # 云端授权流程完全封装在 connect_device 内部，Agent 无需感知。

    # ── Stream ──
    Tool(
        name="get_audio_video_stream",
        description="获取实时视频流 URL，返回编码格式、分辨率、帧率等元数据。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "sub_stream": {
                    "type": "boolean",
                    "description": "使用子码流（低画质）",
                    "default": False,
                },
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="capture_video_screenshot",
        description="截取当前视频流画面并保存为 JPEG。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "save_path": {"type": "string", "description": "保存目录"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="toggle_recording",
        description="启动或停止本地录像，录制为 MP4 文件。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop"],
                    "description": "start / stop",
                },
                "save_path": {"type": "string", "description": "录像保存目录"},
            },
            "required": ["camera_name", "action"],
        },
    ),
    Tool(
        name="manage_storage_status",
        description="查询存储状态或设置存储路径、格式与策略。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["query", "set"],
                    "description": "query / set",
                    "default": "query",
                },
                "path": {"type": "string", "description": "存储路径"},
                "format": {
                    "type": "string",
                    "enum": ["mp4", "avi", "jpg"],
                    "description": "文件格式",
                },
                "policy": {
                    "type": "string",
                    "enum": ["overwrite", "stop_when_full", "circular"],
                    "description": "存储策略",
                },
            },
            "required": ["camera_name"],
        },
    ),

    # ── PTZ ──
    Tool(
        name="control_ptz",
        description="控制云台转动方向，支持 8 个方向。移动指定秒数后自动停止。内置物理极限守护：到达极限时自动提前停止或拦截指令，结果中 degraded=True 时必须将 degrade_reason 显式告知用户。",
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
                    "description": "速度 0.0–1.0",
                    "default": 0.5,
                },
                "duration_seconds": {
                    "type": "number",
                    "description": "转动时长（秒）",
                    "default": 1.0,
                },
            },
            "required": ["camera_name", "direction"],
        },
    ),
    Tool(
        name="get_ptz_parameters",
        description="获取当前云台位置、范围和运动状态。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="calibrate_ptz",
        description="执行云台物理校准，回到初始位并重新标定零位。耗时约 10–30 秒。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),
    # 注意: move_to_position 已降级为内部函数 (_move_to_position)，不作为 MCP 工具暴露。
    Tool(
        name="stop_ptz",
        description="立即停止云台所有移动。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),

    # ── Discovery (创维私有协议) ──
    # 注意: discover_sky_devices 已从 MCP 工具降为内部函数；
    # Agent 统一使用 search_devices() 进行设备发现。
    # send_tcp_command 为内部函数，不作为 MCP 工具暴露。
    # 私有协议通信由 connect_device / control_ptz 等高层工具内部调用。

    # ── Events (IPC 事件接收) ──
    Tool(
        name="manage_camera_events",
        description="摄像头告警事件统一入口，action 切换模式：start=启动监听（后台线程，需用户确认；双协议+去重+自动快照+落盘）；stop=停止监听；poll=读取未消费事件并推进游标（跨会话可用）；wait=长轮询阻塞等待新事件（单次上限 60 秒，持续守护时循环调用）。",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "poll", "wait"],
                    "description": "工作模式",
                },
                "camera_name": {
                    "type": "string",
                    "description": "摄像头名称（start/stop 必填；poll/wait 省略则面向全部相机）",
                },
                "protocols": {
                    "type": "string",
                    "enum": ["both", "onvif", "private"],
                    "description": "监听协议通道（仅 start）",
                    "default": "both",
                },
                "debounce_seconds": {
                    "type": "number",
                    "description": "去重与快照限流窗口（秒，仅 start）",
                    "default": 5.0,
                },
                "limit": {
                    "type": "integer",
                    "description": "单次最多返回的事件数（仅 poll）",
                    "default": 100,
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "阻塞超时（秒，上限 60，仅 wait）",
                    "default": 60,
                },
            },
            "required": ["action"],
        },
    ),

    # ── Illumination (补光模式控制) ──
    Tool(
        name="manage_illumination",
        description="摄像头补光模式统一入口。get=查询当前设置和参数范围（含中文标签）；set=设置补光参数（仅指定需修改的参数，其余保持不变；枚举参数接受整数或字符串别名如 daynightmode='auto'）。通过 SK HTTP 动态 Token 私有协议(9010)通信。",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set"],
                    "description": "工作模式",
                },
                "camera_name": {
                    "type": "string",
                    "description": "摄像头名称",
                },
                "daynightmode": {
                    "description": "日夜模式: 0白天/1夜晚/2自动/3定时/4智能（别名: day/night/auto/timer/smart 或 白天/夜晚/自动/定时/智能）",
                },
                "filllightmode": {
                    "description": "补光方式: 0全彩/1红外/2智能夜视（别名: color/ir/smart 或 全彩/红外/智能夜视）",
                },
                "duration": {
                    "type": "integer",
                    "description": "智能夜视白光灯补光时长 (5-60 秒)",
                },
                "brightnessmode": {
                    "description": "白光灯亮度调节: 0自动/1手动（别名: auto/manual 或 自动/手动）",
                },
                "brightness": {
                    "type": "integer",
                    "description": "白光灯亮度 (1-100)",
                },
                "irmode": {
                    "description": "红外灯亮度调节: 0自动/1手动（别名: auto/manual 或 自动/手动）",
                },
                "irbrightness": {
                    "type": "integer",
                    "description": "红外灯亮度 (1-100)",
                },
                "begintime": {
                    "type": "integer",
                    "description": "定时模式开始时间 (0-86399 秒)",
                },
                "endtime": {
                    "type": "integer",
                    "description": "定时模式结束时间 (0-172799 秒)",
                },
                "repeatdays": {
                    "type": "string",
                    "description": "定时模式重复日期 (如 sun,mon,tue,wed,thu,fri,sat,)",
                },
                "enable": {
                    "description": "定时器使能: 0关/1开",
                },
                "whiteonvalue": {
                    "type": "integer",
                    "description": "白光灯开灯灵敏度 (0-100)",
                },
                "whiteoffvalue": {
                    "type": "integer",
                    "description": "白光灯关灯灵敏度 (0-100)",
                },
                "ironvalue": {
                    "type": "integer",
                    "description": "红外灯开灯灵敏度 (0-100)",
                },
                "iroffvalue": {
                    "type": "integer",
                    "description": "红外灯关灯灵敏度 (0-100)",
                },
            },
            "required": ["action", "camera_name"],
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
    from scripts.toolkit.stream import RecordingAction, StorageAction
    from scripts.toolkit.ptz import PTZDirection
    from scripts.toolkit.events import EventAction
    from scripts.toolkit.illumination import IlluminationAction

    # ── Device Management ──
    if name == "get_registered_cameras":
        return _serialize(tk.get_registered_cameras())
    elif name == "register_camera":
        return _serialize(tk.register_camera(**args))
    elif name == "search_devices":
        return _serialize(tk.search_devices(**args))
    elif name == "connect_device":
        return _serialize(tk.connect_device(**args))
    elif name == "disconnect_device":
        return _serialize(tk.disconnect_device(**args))
    # ── Cloud Auth ──
    # 注意: poll_auth_status / big_connect 已降为内部函数，
    # 云端授权由 connect_device 内部自动处理。
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
    elif name == "get_ptz_parameters":
        return _serialize(tk.get_ptz_parameters(**args))
    elif name == "calibrate_ptz":
        return _serialize(tk.calibrate_ptz(**args))
    elif name == "stop_ptz":
        return _serialize(tk.stop_ptz(**args))

    # ── Events ──
    elif name == "manage_camera_events":
        args = dict(args)
        args["action"] = EventAction(args["action"])
        return _serialize(tk.manage_camera_events(**args))

    # ── Illumination ──
    elif name == "manage_illumination":
        args = dict(args)
        args["action"] = IlluminationAction(args["action"])
        return _serialize(tk.manage_illumination(**args))

    else:
        raise ValueError(f"Unknown tool: {name}")


# ═══════════════════════════════════════════════
#  Server Setup
# ═══════════════════════════════════════════════

server = Server("xpai-camera-control", version="0.5.0")


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


def _resume_event_monitors_async() -> None:
    """Server startup hook: re-arm event listeners the user enabled but never
    stopped (persisted in events/monitor_state.json), lost when the host
    recycled the previous MCP process. Runs in a daemon thread so a slow or
    offline camera never blocks the stdio handshake."""
    import threading

    def _worker():
        try:
            from scripts.toolkit.events import resume_persisted_monitors
            resume_persisted_monitors()
        except Exception:
            pass  # resume failure must never take the server down

    threading.Thread(target=_worker, name="EventMonitorResume", daemon=True).start()


async def main():
    """Run the MCP server with stdio transport."""
    parser = argparse.ArgumentParser(description="XPAI Camera Control MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio"],
                        help="Transport to use (default: stdio)")
    args = parser.parse_args()

    _resume_event_monitors_async()

    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
