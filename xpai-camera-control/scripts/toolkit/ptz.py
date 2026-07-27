"""
Toolkit 2: 云台与巡航

工具清单：
  - control_ptz          步进式控制云台方向（ONVIF 优先，私有协议兜底）
  - control_lens_zoom    控制镜头自动变焦
  - get_ptz_parameters   获取云台位移与角度参数
  - save_ptz_preset      保存当前角度为预置点
  - go_to_preset         跳转到指定预置点
  - calibrate_ptz        执行云台物理校准（私有协议）
  - move_to_position     移动到指定绝对坐标（私有协议）
  - stop_ptz             停止云台移动
  - start_patrol_cruise  按预设路径巡航

协议策略:
  优先尝试 ONVIF PTZ Service，失败时自动降级到创维私有协议（SK_SETTING_SET_PTZ）。
  私有协议通过 TCP 通道（端口 9010）发送 JSON 命令。

前提条件: 摄像头已通过 connect_device() 连接，且存在于 _connected_devices 中。
"""
import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from .discovery import send_tcp_command, SK_TCP_PORT


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class PTZDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UPLEFT = "upleft"
    UPRIGHT = "upright"
    DOWNLEFT = "downleft"
    DOWNRIGHT = "downright"
    # 中文别名在映射层处理


# 中文 → 英文方向映射
_DIRECTION_ALIAS: Dict[str, PTZDirection] = {
    "上": PTZDirection.UP,
    "下": PTZDirection.DOWN,
    "左": PTZDirection.LEFT,
    "右": PTZDirection.RIGHT,
    "左上": PTZDirection.UPLEFT,
    "右上": PTZDirection.UPRIGHT,
    "左下": PTZDirection.DOWNLEFT,
    "右下": PTZDirection.DOWNRIGHT,
}

# ONVIF 方向 → (pan, tilt) 速度向量
_ONVIF_VELOCITY_MAP: Dict[PTZDirection, tuple] = {
    PTZDirection.UP:        (0.0, 1.0),
    PTZDirection.DOWN:      (0.0, -1.0),
    PTZDirection.LEFT:      (-1.0, 0.0),
    PTZDirection.RIGHT:     (1.0, 0.0),
    PTZDirection.UPLEFT:    (-1.0, 1.0),
    PTZDirection.UPRIGHT:   (1.0, 1.0),
    PTZDirection.DOWNLEFT:  (-1.0, -1.0),
    PTZDirection.DOWNRIGHT: (1.0, -1.0),
}

# 私有协议方向 → cmd 字符串
_SK_CMD_MAP: Dict[PTZDirection, str] = {
    PTZDirection.UP:        "up",
    PTZDirection.DOWN:      "down",
    PTZDirection.LEFT:      "left",
    PTZDirection.RIGHT:     "right",
    PTZDirection.UPLEFT:    "upleft",
    PTZDirection.UPRIGHT:   "upright",
    PTZDirection.DOWNLEFT:  "downleft",
    PTZDirection.DOWNRIGHT: "downright",
}


class ZoomAction(str, Enum):
    IN = "in"
    OUT = "out"


@dataclass
class PTZMoveResult:
    """云台移动操作返回结果"""
    success: bool                                # 是否成功
    protocol: str = ""                           # 使用的协议: "onvif" / "sky_private"
    current_pan: float = 0.0                     # 当前水平位置
    current_tilt: float = 0.0                    # 当前垂直位置
    current_zoom: float = 0.0                    # 当前变焦倍数
    error_message: str = ""                      # 失败原因


@dataclass
class PTZParameters:
    """云台参数"""
    pan: float = 0.0                             # 水平位置 / 角度
    tilt: float = 0.0                            # 垂直位置 / 角度
    zoom: float = 0.0                            # 变焦位置
    pan_range: float = 0.0                       # 水平最大值
    tilt_range: float = 0.0                      # 垂直最大值
    zoom_range: float = 0.0                      # 变倍最大值
    is_moving: bool = False                      # 是否正在移动
    protocol: str = ""                           # 使用的协议


@dataclass
class PTZPresetResult:
    """预置点操作返回结果"""
    success: bool                                # 是否成功
    preset_name: str = ""                        # 预置点名称
    preset_token: str = ""                       # 预置点 token
    protocol: str = ""                           # 使用的协议
    error_message: str = ""                      # 失败原因


@dataclass
class CalibrateResult:
    """云台校准返回结果"""
    success: bool                                # 校准是否完成
    protocol: str = ""                           # 使用的协议
    error_message: str = ""                      # 失败原因


@dataclass
class CruiseResult:
    """巡航操作返回结果"""
    success: bool                                # 巡航是否启动
    cruise_name: str = ""                        # 巡航路径名称
    preset_count: int = 0                        # 巡航经过的预置点数量
    protocol: str = ""                           # 使用的协议
    error_message: str = ""                      # 失败原因


@dataclass
class PTZInfo:
    """PTZ 信息（预置位、巡航、扫描路线能力）"""
    preset_max: int = 0                          # 预置位最大值
    cruise_max: int = 0                          # 巡航路线最大值
    scan_max: int = 0                            # 自定义扫描路线最大值
    presets_per_cruise: int = 0                  # 每巡航路线最大预置位数
    presets_per_scan: int = 0                    # 每扫描路线最大点数
    preset_num: int = 0                          # 当前预置位数量
    cruise_num: int = 0                          # 当前巡航路线数量
    scan_num: int = 0                            # 当前扫描路线数量


# ──────────────────────────────────────────────
#  内部辅助
# ──────────────────────────────────────────────

def _get_conn_info(camera_name: str) -> Optional[dict]:
    """从 device_mgmt._connected_devices 获取连接信息（延迟导入避免循环依赖）"""
    from . import device_mgmt
    return device_mgmt._connected_devices.get(camera_name)


def _resolve_direction(direction) -> Optional[PTZDirection]:
    """解析方向参数，支持 PTZDirection 枚举、英文字符串、中文字符串"""
    if isinstance(direction, PTZDirection):
        return direction
    if isinstance(direction, str):
        d = direction.strip().lower()
        # 先尝试中文映射
        if direction.strip() in _DIRECTION_ALIAS:
            return _DIRECTION_ALIAS[direction.strip()]
        # 再尝试英文枚举值
        try:
            return PTZDirection(d)
        except ValueError:
            return None
    return None


def _build_sk_msg_id() -> str:
    """生成私有协议消息 ID"""
    now = time.time()
    ts = time.strftime("%Y%m%d%H%M%S", time.localtime(now))
    frac = int((now - int(now)) * 1_000_000)
    return f"{ts}{frac:06d}"[:21]


def _send_sk_ptz_command(camera_name: str, command: dict) -> Optional[dict]:
    """通过创维 TCP 通道发送 PTZ 命令"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return None

    ip = conn.get("ip", "")
    username = conn.get("username", "admin")
    password = conn.get("password", "")
    tcp_port = conn.get("tcp_port", SK_TCP_PORT)

    if not ip:
        return None

    return send_tcp_command(
        ip=ip,
        command=command,
        username=username,
        password=password,
        timeout=5.0,
        port=tcp_port,
    )


# ──────────────────────────────────────────────
#  ONVIF PTZ 内部实现
# ──────────────────────────────────────────────

def _onvif_ptz_move(camera_name: str, direction: PTZDirection, speed: float) -> PTZMoveResult:
    """通过 ONVIF 执行云台方向移动"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return PTZMoveResult(success=False, error_message=f"设备 {camera_name} 未连接")

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return PTZMoveResult(success=False, error_message="无 ONVIF 连接对象")

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return PTZMoveResult(success=False, protocol="onvif", error_message="无 Media Profile")

        profile_token = profiles[0].token
        pan, tilt = _ONVIF_VELOCITY_MAP.get(direction, (0.0, 0.0))

        request = ptz.create_type('ContinuousMove')
        request.ProfileToken = profile_token
        request.Velocity = {
            'PanTilt': {'x': pan * speed, 'y': tilt * speed},
        }
        ptz.ContinuousMove(request)
        return PTZMoveResult(success=True, protocol="onvif")
    except Exception as e:
        return PTZMoveResult(success=False, protocol="onvif", error_message=str(e))


def _onvif_zoom(camera_name: str, action: ZoomAction, speed: float) -> PTZMoveResult:
    """通过 ONVIF 执行变焦"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return PTZMoveResult(success=False, error_message=f"设备 {camera_name} 未连接")

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return PTZMoveResult(success=False, error_message="无 ONVIF 连接对象")

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return PTZMoveResult(success=False, protocol="onvif", error_message="无 Media Profile")

        profile_token = profiles[0].token
        zoom_val = 1.0 if action == ZoomAction.IN else -1.0

        request = ptz.create_type('ContinuousMove')
        request.ProfileToken = profile_token
        request.Velocity = {
            'Zoom': {'x': zoom_val * speed},
        }
        ptz.ContinuousMove(request)
        return PTZMoveResult(success=True, protocol="onvif")
    except Exception as e:
        return PTZMoveResult(success=False, protocol="onvif", error_message=str(e))


def _onvif_stop(camera_name: str) -> PTZMoveResult:
    """通过 ONVIF 停止云台"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return PTZMoveResult(success=False, error_message=f"设备 {camera_name} 未连接")

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return PTZMoveResult(success=False, error_message="无 ONVIF 连接对象")

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return PTZMoveResult(success=False, protocol="onvif", error_message="无 Media Profile")

        profile_token = profiles[0].token
        request = ptz.create_type('Stop')
        request.ProfileToken = profile_token
        ptz.Stop(request)
        return PTZMoveResult(success=True, protocol="onvif")
    except Exception as e:
        return PTZMoveResult(success=False, protocol="onvif", error_message=str(e))


def _onvif_get_status(camera_name: str) -> PTZParameters:
    """通过 ONVIF 获取云台状态"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return PTZParameters()

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return PTZParameters()

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return PTZParameters(protocol="onvif")

        profile_token = profiles[0].token
        status = ptz.GetStatus({'ProfileToken': profile_token})

        pan = 0.0
        tilt = 0.0
        zoom = 0.0
        moving = False

        if hasattr(status, 'Position') and status.Position:
            if hasattr(status.Position, 'PanTilt') and status.Position.PanTilt:
                pan = float(status.Position.PanTilt.x)
                tilt = float(status.Position.PanTilt.y)
            if hasattr(status.Position, 'Zoom') and status.Position.Zoom:
                zoom = float(status.Position.Zoom.x)
        if hasattr(status, 'MoveStatus') and status.MoveStatus:
            if hasattr(status.MoveStatus, 'PanTilt') and status.MoveStatus.PanTilt:
                moving = str(status.MoveStatus.PanTilt) == "MOVING"

        return PTZParameters(
            pan=pan, tilt=tilt, zoom=zoom,
            is_moving=moving, protocol="onvif",
        )
    except Exception:
        return PTZParameters(protocol="onvif")


def _onvif_get_presets(camera_name: str) -> List[Dict[str, str]]:
    """通过 ONVIF 获取预置位列表"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return []

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return []

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return []
        presets = ptz.GetPresets({'ProfileToken': profiles[0].token})
        result = []
        for p in presets:
            result.append({
                'token': str(getattr(p, 'token', '')),
                'name': str(getattr(p, 'Name', '')),
            })
        return result
    except Exception:
        return []


def _onvif_goto_preset(camera_name: str, preset_name: str) -> PTZMoveResult:
    """通过 ONVIF 跳转到预置位"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return PTZMoveResult(success=False, error_message=f"设备 {camera_name} 未连接")

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return PTZMoveResult(success=False, error_message="无 ONVIF 连接对象")

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return PTZMoveResult(success=False, protocol="onvif", error_message="无 Media Profile")

        profile_token = profiles[0].token
        presets = ptz.GetPresets({'ProfileToken': profile_token})
        target = None
        for p in presets:
            if str(getattr(p, 'Name', '')) == preset_name or str(getattr(p, 'token', '')) == preset_name:
                target = p
                break
        if not target:
            available = [str(getattr(p, 'Name', getattr(p, 'token', '?'))) for p in presets]
            return PTZMoveResult(
                success=False, protocol="onvif",
                error_message=f"预置位 '{preset_name}' 不存在，可用: {available}",
            )

        request = ptz.create_type('GotoPreset')
        request.ProfileToken = profile_token
        request.PresetToken = target.token
        ptz.GotoPreset(request)
        return PTZMoveResult(success=True, protocol="onvif")
    except Exception as e:
        return PTZMoveResult(success=False, protocol="onvif", error_message=str(e))


def _onvif_save_preset(camera_name: str, preset_name: str) -> PTZPresetResult:
    """通过 ONVIF 保存当前位为预置点"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return PTZPresetResult(success=False, error_message=f"设备 {camera_name} 未连接")

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return PTZPresetResult(success=False, error_message="无 ONVIF 连接对象")

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return PTZPresetResult(success=False, protocol="onvif", error_message="无 Media Profile")

        profile_token = profiles[0].token
        request = ptz.create_type('SetPreset')
        request.ProfileToken = profile_token
        request.PresetName = preset_name
        result = ptz.SetPreset(request)
        token = str(getattr(result, 'PresetToken', ''))
        return PTZPresetResult(success=True, preset_name=preset_name, preset_token=token, protocol="onvif")
    except Exception as e:
        return PTZPresetResult(success=False, protocol="onvif", error_message=str(e))


# ──────────────────────────────────────────────
#  私有协议 PTZ 内部实现 (SK_SETTING_SET_PTZ)
# ──────────────────────────────────────────────

def _sk_ptz_move(camera_name: str, direction: PTZDirection, channel: int = 2) -> PTZMoveResult:
    """通过创维私有协议发送方向控制命令"""
    cmd = _SK_CMD_MAP.get(direction)
    if not cmd:
        return PTZMoveResult(success=False, protocol="sky_private", error_message=f"不支持的方向: {direction}")

    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_SET_PTZ",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
        "cmd": cmd,
    }

    resp = _send_sk_ptz_command(camera_name, command)
    if resp and resp.get("code") == "C0000":
        return PTZMoveResult(success=True, protocol="sky_private")
    else:
        msg = resp.get("msg", "未知错误") if resp else "TCP 通道无响应"
        return PTZMoveResult(success=False, protocol="sky_private", error_message=msg)


def _sk_ptz_stop(camera_name: str, action: str = "", channel: int = 2) -> PTZMoveResult:
    """通过创维私有协议停止云台移动"""
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_SET_PTZ",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
        "cmd": "stop",
    }
    if action:
        command["action"] = action

    resp = _send_sk_ptz_command(camera_name, command)
    if resp and resp.get("code") == "C0000":
        return PTZMoveResult(success=True, protocol="sky_private")
    else:
        msg = resp.get("msg", "未知错误") if resp else "TCP 通道无响应"
        return PTZMoveResult(success=False, protocol="sky_private", error_message=msg)


def _sk_ptz_calibrate(camera_name: str, channel: int = 2) -> CalibrateResult:
    """通过创维私有协议执行云台校准"""
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_SET_PTZ",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
        "cmd": "calibrate",
    }

    resp = _send_sk_ptz_command(camera_name, command)
    if resp and resp.get("code") == "C0000":
        return CalibrateResult(success=True, protocol="sky_private")
    else:
        msg = resp.get("msg", "未知错误") if resp else "TCP 通道无响应"
        return CalibrateResult(success=False, protocol="sky_private", error_message=msg)


def _sk_ptz_move_to(camera_name: str, x: int, y: int, z: float, channel: int = 2) -> PTZMoveResult:
    """通过创维私有协议移动到指定绝对坐标"""
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_SET_PTZ",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
        "cmd": "move",
        "x": x,
        "y": y,
        "z": z,
    }

    resp = _send_sk_ptz_command(camera_name, command)
    if resp and resp.get("code") == "C0000":
        return PTZMoveResult(success=True, protocol="sky_private", current_pan=float(x), current_tilt=float(y), current_zoom=z)
    else:
        msg = resp.get("msg", "未知错误") if resp else "TCP 通道无响应"
        return PTZMoveResult(success=False, protocol="sky_private", error_message=msg)


def _sk_get_ptz_params(camera_name: str, channel: int = 2) -> PTZParameters:
    """通过创维私有协议查询 PTZ 参数 (SK_SETTING_GET_PTZ)"""
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_GET_PTZ",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
    }

    resp = _send_sk_ptz_command(camera_name, command)
    if resp and resp.get("code") == "C0000":
        return PTZParameters(
            pan=float(resp.get("x", 0)),
            tilt=float(resp.get("y", 0)),
            zoom=float(resp.get("z", 0)),
            pan_range=float(resp.get("x_range", 0)),
            tilt_range=float(resp.get("y_range", 0)),
            zoom_range=float(resp.get("z_range", 0)),
            is_moving=False,
            protocol="sky_private",
        )
    return PTZParameters(protocol="sky_private")


def _sk_get_ptz_info(camera_name: str, channel: int = 2) -> Optional[PTZInfo]:
    """通过创维私有协议查询 PTZ 信息 (SK_PTZ_GET_INFO)"""
    command = {
        "service_type": "ptz",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_PTZ_GET_INFO",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
    }

    resp = _send_sk_ptz_command(camera_name, command)
    if resp and resp.get("code") == "C0000":
        return PTZInfo(
            preset_max=int(resp.get("preset_max", 0)),
            cruise_max=int(resp.get("cruise_max", 0)),
            scan_max=int(resp.get("scan_max", 0)),
            presets_per_cruise=int(resp.get("presets_per_cruise", 0)),
            presets_per_scan=int(resp.get("presets_per_scan", 0)),
            preset_num=int(resp.get("preset_num", 0)),
            cruise_num=int(resp.get("cruise_num", 0)),
            scan_num=int(resp.get("scan_num", 0)),
        )
    return None


def _sk_zoom(camera_name: str, action: ZoomAction, channel: int = 2) -> PTZMoveResult:
    """通过创维私有协议执行变焦"""
    cmd = "zoom+" if action == ZoomAction.IN else "zoom-"
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_SET_PTZ",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
        "cmd": cmd,
    }

    resp = _send_sk_ptz_command(camera_name, command)
    if resp and resp.get("code") == "C0000":
        return PTZMoveResult(success=True, protocol="sky_private")
    else:
        msg = resp.get("msg", "未知错误") if resp else "TCP 通道无响应"
        return PTZMoveResult(success=False, protocol="sky_private", error_message=msg)


# ──────────────────────────────────────────────
#  公开工具函数 (ONVIF 优先, 私有协议兜底)
# ──────────────────────────────────────────────

def control_ptz(
    camera_name: str,
    direction: PTZDirection,
    speed: float = 0.5,
    duration_seconds: float = 1.0,
) -> PTZMoveResult:
    """
    步进式控制云台方向移动。

    优先通过 ONVIF PTZ Service 执行 ContinuousMove，
    若 ONVIF 不可用则降级到创维私有协议（SK_SETTING_SET_PTZ）。

    移动 duration_seconds 秒后自动停止。
    方向支持英文 (up/down/left/right/upleft/upright/downleft/downright)
    和中文 (上/下/左/右/左上/右上/左下/右下)。

    安全约束: 显式提示

    Args:
        camera_name:      摄像头名称（自动填充）
        direction:        移动方向 (PTZDirection)
        speed:            速度系数 0.1-1.0（默认 0.5）
        duration_seconds: 移动时长（秒，默认 1.0）

    Returns:
        PTZMoveResult:
            - success: 是否成功
            - protocol: 实际使用的协议
            - current_pan / current_tilt / current_zoom: 移动后位置
            - error_message: 失败原因
    """
    direction = _resolve_direction(direction)
    if not direction:
        return PTZMoveResult(success=False, error_message="无效方向，可用: up/down/left/right/upleft/upright/downleft/downright")

    speed = max(0.1, min(1.0, speed))
    duration_seconds = max(0.1, min(10.0, duration_seconds))

    # ── 尝试 1: ONVIF ──
    result = _onvif_ptz_move(camera_name, direction, speed)
    if result.success:
        # 移动指定时间后自动停止
        time.sleep(duration_seconds)
        stop_result = _onvif_stop(camera_name)
        if not stop_result.success:
            print(f"[PTZ] ONVIF 自动停止失败: {stop_result.error_message}")
        return result

    # ── 尝试 2: 私有协议 ──
    result = _sk_ptz_move(camera_name, direction)
    if result.success:
        time.sleep(duration_seconds)
        sk_cmd = _SK_CMD_MAP.get(direction, "")
        stop_result = _sk_ptz_stop(camera_name, action=sk_cmd)
        if not stop_result.success:
            print(f"[PTZ] 私有协议自动停止失败: {stop_result.error_message}")
        return result

    return PTZMoveResult(
        success=False,
        error_message=f"ONVIF 和私有协议均失败。ONVIF: {result.error_message}",
    )


def control_lens_zoom(
    camera_name: str,
    zoom_action: ZoomAction,
    speed: float = 0.5,
) -> PTZMoveResult:
    """
    控制镜头自动变焦。

    zoom_action=IN 放大，OUT 缩小。变焦 1.5 秒后自动停止。
    优先 ONVIF，失败则降级到私有协议 (zoom+/zoom-)。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）
        zoom_action: ZoomAction.IN 放大 / ZoomAction.OUT 缩小
        speed:       变焦速度 0.1-1.0（默认 0.5）

    Returns:
        PTZMoveResult:
            - success: 是否成功
            - protocol: 实际使用的协议
            - current_zoom: 变焦后的位置值
            - error_message: 失败原因
    """
    if isinstance(zoom_action, str):
        try:
            zoom_action = ZoomAction(zoom_action)
        except ValueError:
            return PTZMoveResult(success=False, error_message=f"无效变焦动作: {zoom_action}")

    speed = max(0.1, min(1.0, speed))

    # ── 尝试 1: ONVIF ──
    result = _onvif_zoom(camera_name, zoom_action, speed)
    if result.success:
        time.sleep(1.5)
        _onvif_stop(camera_name)
        return result

    # ── 尝试 2: 私有协议 ──
    result = _sk_zoom(camera_name, zoom_action)
    if result.success:
        time.sleep(1.5)
        _sk_ptz_stop(camera_name)
        return result

    return PTZMoveResult(
        success=False,
        error_message=f"ONVIF 和私有协议均失败。ONVIF: {result.error_message}",
    )


def get_ptz_parameters(
    camera_name: str,
) -> PTZParameters:
    """
    获取并返回当前云台的位移数据和角度参数。

    优先通过 ONVIF PTZ Service GetStatus 获取；
    若 ONVIF 不可用则降级到私有协议 SK_SETTING_GET_PTZ。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        PTZParameters:
            - pan / tilt / zoom: 当前位置值
            - pan_range / tilt_range / zoom_range: 最大值
            - is_moving: 是否正在移动
            - protocol: 使用的协议
    """
    # ── 尝试 1: ONVIF ──
    result = _onvif_get_status(camera_name)
    if result.protocol:
        return result

    # ── 尝试 2: 私有协议 ──
    return _sk_get_ptz_params(camera_name)


def save_ptz_preset(
    camera_name: str,
    preset_name: str,
) -> PTZPresetResult:
    """
    将当前云台位置保存为收藏预置点。

    通过 ONVIF PTZ Service SetPreset 保存当前位置到指定名称的预置点。
    如果同名预置点已存在，则覆盖。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）
        preset_name: 预置点名称（如 "大门"、"客厅"）

    Returns:
        PTZPresetResult:
            - success: 是否成功
            - preset_name: 保存的预置点名称
            - preset_token: 预置点 token（用于后续 GotoPreset）
            - protocol: 使用的协议
            - error_message: 失败原因
    """
    # ONVIF only（私有协议未定义 SetPreset 命令）
    return _onvif_save_preset(camera_name, preset_name)


def go_to_preset(
    camera_name: str,
    preset_name: str,
    speed: float = 1.0,
) -> PTZMoveResult:
    """
    云台移动到指定预置点。

    通过 ONVIF PTZ Service GotoPreset 将云台移动到之前保存的预置点位置。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        preset_name: 预置点名称（如 "大门"、"客厅"）
        speed:       移动速度 0.1-1.0（默认 1.0）

    Returns:
        PTZMoveResult:
            - success: 是否移动成功
            - protocol: 使用的协议
            - error_message: 失败原因
    """
    # ONVIF only（私有协议未定义 GotoPreset 命令）
    return _onvif_goto_preset(camera_name, preset_name)


def calibrate_ptz(
    camera_name: str,
) -> CalibrateResult:
    """
    执行云台物理校准。

    通过创维私有协议发送 calibrate 命令，云台回到初始位置并重新标定零位。
    校准过程中云台会进行物理运动，耗时约 10-30 秒。
    此功能仅创维私有协议支持。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        CalibrateResult:
            - success: 校准是否完成
            - protocol: 使用的协议
            - error_message: 失败原因
    """
    result = _sk_ptz_calibrate(camera_name)
    if not result.success and not result.error_message:
        return CalibrateResult(
            success=False, protocol="sky_private",
            error_message="云台校准仅支持创维私有协议，请确认设备已通过 TCP 通道连接",
        )
    return result


def move_to_position(
    camera_name: str,
    x: int,
    y: int,
    z: float = 1.0,
) -> PTZMoveResult:
    """
    移动云台到指定绝对坐标（创维私有协议）。

    通过 SK_SETTING_SET_PTZ 的 move 命令，将云台移动到指定的 (x, y, z) 位置。
    x/y/z 的范围可通过 get_ptz_parameters() 查询。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）
        x:           水平坐标（整数，范围由 x_range 决定）
        y:           垂直坐标（整数，范围由 y_range 决定）
        z:           变焦倍数（浮点，范围由 z_range 决定）

    Returns:
        PTZMoveResult:
            - success: 是否移动成功
            - protocol: 使用的协议
            - current_pan/current_tilt/current_zoom: 目标坐标
            - error_message: 失败原因
    """
    return _sk_ptz_move_to(camera_name, x, y, z)


def stop_ptz(
    camera_name: str,
) -> PTZMoveResult:
    """
    停止云台所有移动。

    优先通过 ONVIF Stop 停止，失败则降级到私有协议 stop 命令。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        PTZMoveResult:
            - success: 是否停止成功
            - protocol: 使用的协议
            - error_message: 失败原因
    """
    # ── 尝试 1: ONVIF ──
    result = _onvif_stop(camera_name)
    if result.success:
        return result

    # ── 尝试 2: 私有协议 ──
    return _sk_ptz_stop(camera_name)


def start_patrol_cruise(
    camera_name: str,
    cruise_name: Optional[str] = None,
) -> CruiseResult:
    """
    按预设路径开启云台巡航。

    启动云台按预置点路径自动巡航。如果未指定 cruise_name，
    则使用默认巡航路径（所有已保存的预置点按顺序循环）。
    可通过循环 GotoPreset + 延时实现。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        cruise_name: 巡航路径名称（可选，默认使用预置点顺序）

    Returns:
        CruiseResult:
            - success: 巡航是否启动
            - cruise_name: 巡航路径名称
            - preset_count: 经过的预置点数量
            - protocol: 使用的协议
            - error_message: 失败原因
    """
    # 通过 ONVIF 获取预置位列表，然后按顺序循环 GotoPreset
    presets = _onvif_get_presets(camera_name)
    if not presets:
        return CruiseResult(
            success=False, protocol="onvif",
            error_message="无法获取预置位列表，或设备不支持预置位",
        )

    # 后台线程执行巡航
    def _patrol_thread():
        for preset in presets:
            try:
                _onvif_goto_preset(camera_name, preset['token'])
                time.sleep(5.0)  # 每个预置位停留 5 秒
            except Exception:
                break

    t = threading.Thread(target=_patrol_thread, name=f"PTZ-Cruise-{camera_name}", daemon=True)
    t.start()

    return CruiseResult(
        success=True,
        cruise_name=cruise_name or "default",
        preset_count=len(presets),
        protocol="onvif",
    )
