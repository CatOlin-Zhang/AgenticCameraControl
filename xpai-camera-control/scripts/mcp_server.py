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
        description="搜索局域网可用摄像头，支持 WS-Discovery、SKY_DISCOVERY、USB 三种方式。",
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
                    "description": "超时秒数",
                    "default": 15.0,
                },
            },
        },
    ),
    Tool(
        name="connect_device",
        description="连接摄像头。自动加载缓存凭据；无缓存时探测是否需要密码。",
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
    Tool(
        name="request_cloud_auth",
        description="向本地授权服务器发起设备授权请求（模拟智慧云）。用户在浏览器中确认授权后，Agent 调用 poll_auth_status 轮询结果。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "sn": {"type": "string", "description": "设备序列号（可选，自动查找）"},
                "device_ip": {"type": "string", "description": "设备 IP（可选）"},
                "device_model": {"type": "string", "description": "设备型号（可选）"},
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="poll_auth_status",
        description="轮询本地授权服务器，检查 Agent 是否已被授权。应在 request_cloud_auth 后反复调用（间隔 5s，最长 120s）。",
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
    Tool(
        name="discover_sky_devices",
        description="搜索局域网内的创维摄像头。",
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
    # 注意: send_tcp_command 为内部函数，不作为 MCP 工具暴露。
    # 私有协议通信由 connect_device / control_ptz 等高层工具内部调用。

    # ── Events (IPC 事件接收) ──
    Tool(
        name="manage_camera_events",
        description="摄像头告警事件统一入口，action 切换模式：start=启动监听（后台线程，需用户确认；双协议+去重+自动快照+落盘）；stop=停止监听；poll=读取未消费事件并推进游标（跨会话可用）；wait=长轮询阻塞等待新事件（单次上限 60 秒，持续守护时循环调用）；debug=原始协议包转储开关（排查协议通道/事件类型问题，转储到 events/raw_packets_debug.txt，用完应关闭）。",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "poll", "wait", "debug"],
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
                "debug_mode": {
                    "type": "string",
                    "enum": ["on", "off", "status"],
                    "description": "原始包转储开关（仅 debug）：on 开启 / off 关闭 / status 查询",
                    "default": "status",
                },
            },
            "required": ["action"],
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
    from scripts.toolkit.ptz import PTZDirection
    from scripts.toolkit.events import EventAction

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
    elif name == "request_cloud_auth":
        return _serialize(tk.request_cloud_auth(**args))
    elif name == "poll_auth_status":
        return _serialize(tk.poll_auth_status(**args))

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

    # ── Discovery ──
    elif name == "discover_sky_devices":
        return _serialize(tk.discover_sky_devices(**args))

    # ── Events ──
    elif name == "manage_camera_events":
        args = dict(args)
        args["action"] = EventAction(args["action"])
        return _serialize(tk.manage_camera_events(**args))

    else:
        raise ValueError(f"Unknown tool: {name}")


# ═══════════════════════════════════════════════
#  Server Setup
# ═══════════════════════════════════════════════

server = Server("xpai-camera-control", version="0.4.5")


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
