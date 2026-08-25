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

import anyio
from typing import Any, Dict

# Ensure the project root is on sys.path so `scripts.xxx` imports work
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from scripts._paths import get_skill_root
_skill_root = str(get_skill_root())
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
        description="从 config.yaml 加载所有已注册摄像头的配置信息（含凭据）。不扫描网络，仅读取本地保存的记录。会话开始时首先调用，获取已注册摄像头列表。",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="register_camera",
        description="将摄像头凭据写入 config.yaml 持久化，供后续 connect_device 自动加载。支持重命名：当传入新名称但 IP 或 SN 与已有条目匹配时，自动替换旧名称。通常由 connect_device 内部自动调用，无需手动使用。",
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
        description="扫描局域网发现可用摄像头（WS-Discovery / 创维私有协议）。返回新发现的设备列表，与 get_registered_cameras（读取本地已保存配置）不同。发现多个设备时必须将全部设备逐一展示给用户，不得省略或仅展示部分结果。",
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
        description="连接摄像头。自动加载缓存凭据（TCP/ONVIF/RTSP 三通道验证，密码设备须 RTSP 验证通过）；缓存失效时先尝试云端重新授权，仍失败再请用户输入。直连设备自动获取 SN 并验证 SK HTTP 通信。返回 status 指示下一步：success=已连接；needs_password=请用户提供密码后重新调用；auth_rejected=云端拒绝；cloud_pwd_failed=云端密码验证不通过，请用户输入正确密码。",
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

    # ── Stream ──
    Tool(
        name="get_audio_video_stream",
        description="获取摄像头的 RTSP 实时视频流 URL 及元数据（编码格式、分辨率、帧率）。仅返回流地址，不抓取画面。截图用 capture_video_screenshot，录像用 toggle_recording。",
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
        description="从视频流中截取一帧画面保存为 JPEG 图片（单帧快照）。录像请用 toggle_recording。默认保存到 snapshots/ 目录。",
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
        description="启动、停止或查询本地 MP4 录像。action=start 开始录像（可选 duration 秒数自动停止）；action=stop 停止并返回文件路径和时长；action=status 查询当前录像状态。默认保存到 video/ 目录。多台设备同时录像时请逐台调用（每台间隔 2-3 秒），避免并发启动失败。长时间录像（超过 10 分钟）可能因网络或设备波动而无声中断：若宿主具备定时任务能力，长录像期间请每隔 5 分钟左右用 action=status 巡检；若不具备，启动前须告知用户此风险，且在用户询问进度时先用 action=status 核实实际状态再回答，发现已停止则重新调用 start 续录。录像异常（启动失败/中途停止）时，可查看与视频同名的 .log 文件（正常录制完成且无异常时会自动删除）获取 ffmpeg 退出原因。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status"],
                    "description": "start = 开始录像 / stop = 停止录像 / status = 查询录像状态",
                },
                "save_path": {"type": "string", "description": "录像保存目录（默认 video/）"},
                "duration": {
                    "type": "number",
                    "description": "录像时长（秒），仅 start 时有效；设置后后台自动停止，无需手动调 stop",
                },
            },
            "required": ["camera_name", "action"],
        },
    ),
    Tool(
        name="manage_storage_status",
        description="查询录像/截图的磁盘占用与可用空间，或设置存储路径、文件格式(mp4/avi/jpg)与存储策略(overwrite/stop_when_full/circular)。",
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
        description="控制云台转动方向或变焦。支持 8 方向(up/down/left/right/upleft/upright/downleft/downright)和变焦(zoom_in/zoom_out)。转动量通过 duration_seconds(秒)或 degrees(角度)二选一指定。内置物理极限保护，到达边界时自动提前停止。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right", "upleft", "upright", "downleft", "downright", "zoom_in", "zoom_out"],
                    "description": "移动方向（8方向 + 变焦）",
                },
                "speed": {
                    "type": "number",
                    "description": "速度 0.0–1.0（当前 SK 方向命令不支持调速，仅影响返回值估算）",
                    "default": 0.5,
                },
                "duration_seconds": {
                    "type": "number",
                    "description": "转动时长（秒，时间模式；与 degrees 二选一，都不传时默认 1.0）",
                },
                "degrees": {
                    "type": "number",
                    "description": "转动角度（角度模式，按 1秒=34度 换算为时间执行；与 duration_seconds 二选一）",
                },
            },
            "required": ["camera_name", "direction"],
        },
    ),
    Tool(
        name="get_ptz_parameters",
        description="读取云台当前位置坐标、运动范围和状态（只读查询）。修改云台位置请用 control_ptz。",
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
        description="云台物理校准与归位。set_home=执行固件级校准并存储初始位（约 10-30 秒）；go_home=精确移动到已存储的初始位。与 control_ptz（普通方向转动）不同，这是硬件校准操作。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "action": {
                    "type": "string",
                    "enum": ["set_home", "go_home"],
                    "description": "set_home=校准并存储初始位 / go_home=回到存储的初始位",
                    "default": "set_home",
                },
            },
            "required": ["camera_name"],
        },
    ),
    # 注意: move_to_position 已降级为内部函数 (_move_to_position)，不作为 MCP 工具暴露。
    Tool(
        name="stop_ptz",
        description="立即紧急停止云台所有正在进行的移动。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
            },
            "required": ["camera_name"],
        },
    ),

    # ── Events (IPC 事件接收) ──
    Tool(
        name="manage_camera_events",
        description="摄像头告警事件管理。action=start 启动后台告警监听（需用户确认，含移动/人形/车辆等检测 + 自动快照）；action=stop 停止监听；action=poll 读取已积累的事件；action=wait 阻塞等待新事件到达（单次最长 60 秒）。",
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
                "debounce_seconds": {
                    "type": "number",
                    "description": "去重窗口（秒，仅 start）",
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

    # ── WebRTC 实时预览 ──
    Tool(
        name="start_webrtc_stream",
        description="启动 WebRTC 实时预览，将 RTSP 流转为浏览器可直接播放的 WebRTC 流，返回 HTTP 访问地址。与 get_audio_video_stream（仅返回 RTSP URL）不同，此工具提供浏览器可视化预览。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {"type": "string", "description": "摄像头名称"},
                "sub_stream": {
                    "type": "boolean",
                    "description": "使用子码流（低画质）",
                    "default": False,
                },
                "port": {
                    "type": "integer",
                    "description": "Web UI 端口",
                    "default": 1984,
                },
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="stop_webrtc_stream",
        description="停止 WebRTC 实时预览，关闭转流进程。",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),

    # ── Illumination (补光模式控制) ──
    Tool(
        name="manage_illumination",
        description="查询或设置摄像头补光与夜视模式。仅支持日夜切换(daynightmode)与补光方式(filllightmode)两项调节（多数设备只支持这两项）。与 manage_image_settings（控制画面参数如亮度对比度）不同，本工具控制物理补光硬件。",
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
            },
            "required": ["action", "camera_name"],
        },
    ),

    # ── Image Settings (图像参数设置) ──
    Tool(
        name="manage_image_settings",
        description="查询或设置摄像头画面参数：亮度(brightness)、对比度(contrast)、饱和度(saturation)、锐度(sharpness)、图像翻转(flip: 0正常/1对角翻转/2水平翻转/3垂直翻转)。纯SK私有协议单通道，无ONVIF回退。与 manage_illumination（控制物理补光灯/夜视模式）不同，本工具调节画面成像参数。",
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
                "brightness": {
                    "type": "integer",
                    "description": "亮度",
                },
                "contrast": {
                    "type": "integer",
                    "description": "对比度",
                },
                "saturation": {
                    "type": "integer",
                    "description": "饱和度",
                },
                "sharpness": {
                    "type": "integer",
                    "description": "锐度",
                },
                "flip": {
                    "type": "integer",
                    "enum": [0, 1, 2, 3],
                    "description": "图像翻转：0-正常、1-对角翻转、2-水平翻转、3-垂直翻转",
                },
            },
            "required": ["action", "camera_name"],
        },
    ),

    # ── Tracking (侦测追踪控制) ──
    Tool(
        name="query_tracking_capabilities",
        description="查询摄像头的智能侦测与追踪能力（人形追踪/车辆追踪/区域检测/移动侦测/越界侦测），返回各侦测类型的可用参数和当前设置值。只读查询，修改设置请用 set_tracking。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {
                    "type": "string",
                    "description": "摄像头名称",
                },
                "detect_type": {
                    "type": "string",
                    "description": "侦测类型: human(人形)/vehicle(车辆)/area(区域)/motion(移动)/line(越界)/all(全部)",
                    "default": "all",
                },
            },
            "required": ["camera_name"],
        },
    ),
    Tool(
        name="set_tracking",
        description="开启或关闭摄像头的智能侦测与追踪功能（人形追踪/车辆追踪/区域检测/移动侦测/越界侦测）。修改硬件设置，需用户确认。仅传需修改的参数，未传的参数保持不变。查询能力请用 query_tracking_capabilities。",
        inputSchema={
            "type": "object",
            "properties": {
                "camera_name": {
                    "type": "string",
                    "description": "摄像头名称",
                },
                "detect_type": {
                    "type": "string",
                    "description": "侦测类型: human(人形追踪)/vehicle(车辆追踪)/area(区域检测)/motion(移动侦测)/line(越界侦测)",
                },
                "enable": {
                    "type": "boolean",
                    "description": "是否开启该侦测功能",
                },
                "tracking": {
                    "type": "boolean",
                    "description": "是否开启追踪（仅 human/vehicle/motion 有效）",
                },
                "sensitivity_level": {
                    "type": "integer",
                    "description": "灵敏度等级 0-3 (0关闭/1低/2中/3高)",
                },
            },
            "required": ["camera_name", "detect_type"],
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
    from scripts.toolkit.image_settings import ImageAction
    from scripts.toolkit.tracking import TrackingAction

    # ── Device Management ──
    if name == "get_registered_cameras":
        return _serialize(tk.get_registered_cameras())
    elif name == "register_camera":
        return _serialize(tk.register_camera(**args))
    elif name == "search_devices":
        result = _serialize(tk.search_devices(**args))
        if isinstance(result, dict):
            count = len(result.get("devices", []))
            result["device_count"] = count
            if count > 0:
                result["_display_instruction"] = (
                    f"共发现 {count} 台设备，必须将上述 {count} 台设备全部展示给用户，禁止省略"
                )
        return result
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
        args.pop("protocols", None)  # 兼容旧客户端仍传 protocols（ONVIF 已删，单私有协议通道）
        args["action"] = EventAction(args["action"])
        return _serialize(tk.manage_camera_events(**args))

    # ── WebRTC ──
    elif name == "start_webrtc_stream":
        return _serialize(tk.start_webrtc_stream(**args))
    elif name == "stop_webrtc_stream":
        return _serialize(tk.stop_webrtc_stream())

    # ── Illumination ──
    elif name == "manage_illumination":
        args = dict(args)
        args["action"] = IlluminationAction(args["action"])
        return _serialize(tk.manage_illumination(**args))

    # ── Image Settings ──
    elif name == "manage_image_settings":
        args = dict(args)
        if "action" in args:
            args["action"] = ImageAction(args["action"])
        return _serialize(tk.manage_image_settings(**args))

    # ── Tracking (侦测追踪) ──
    elif name == "query_tracking_capabilities":
        return _serialize(tk.manage_tracking(action="get", **args))
    elif name == "set_tracking":
        return _serialize(tk.manage_tracking(action="set", **args))

    else:
        raise ValueError(f"Unknown tool: {name}")


# ═══════════════════════════════════════════════
#  Server Setup
# ═══════════════════════════════════════════════

server = Server("xpai-camera-control", version="0.6.0")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Return the list of available tools."""
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any] | None) -> list[TextContent]:
    """Handle a tool invocation and return results."""
    try:
        args = arguments or {}
        # toolkit 是同步阻塞代码（ffprobe 探测、sleep 健康检查等），丢进线程池执行，
        # 避免阻塞事件循环导致无法响应宿主 ping、被误判连接死亡而强制重启进程
        result = await anyio.to_thread.run_sync(_call_tool, name, args)
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
        # MCP stdio 传输协议使用 stdout 作为 JSON-RPC 通道。
        # toolkit 模块（如 discover_sky_devices）中的 print() 会写入 stdout，
        # 污染 MCP 协议通道，导致设备发现响应丢失。
        # 将 stdout 重定向到 stderr 以保护 MCP 通信。
        sys.stdout = sys.stderr
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
