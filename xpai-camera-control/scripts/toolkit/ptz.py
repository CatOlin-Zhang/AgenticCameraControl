"""
Toolkit 2: 云台控制

工具清单：
  - control_ptz          步进式控制云台方向（ONVIF 优先，私有协议兜底）
  - get_ptz_parameters   获取云台位移与角度参数
  - calibrate_ptz        执行云台校准（ONVIF GotoHomePosition 优先，私有协议兆底）
  - stop_ptz             停止云台移动

内部函数（不注册为 MCP 工具）：
  - _move_to_position    移动到指定绝对坐标（私有协议，供内部/二次开发调用）

协议策略:
  优先尝试 ONVIF PTZ Service，失败时自动降级到创维私有协议（SK_SETTING_SET_PTZ）。
  私有协议通过 TCP 通道（端口 9010）发送 JSON 命令。

前提条件: 摄像头已通过 connect_device() 连接，且存在于 _connected_devices 中。
"""
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

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


@dataclass
class PTZMoveResult:
    """云台移动操作返回结果"""
    success: bool                                # 是否成功
    protocol: str = ""                           # 使用的协议: "onvif" / "sky_private"
    current_pan: float = 0.0                     # 当前水平位置
    current_tilt: float = 0.0                    # 当前垂直位置
    current_zoom: float = 0.0                    # 当前变焦倍数
    error_message: str = ""                      # 失败原因
    # ── 物理极限守护（降级信息，Agent 须在 degraded=True 时显式告知用户）──
    requested_duration_seconds: float = 0.0      # 用户请求的移动时长
    actual_duration_seconds: float = 0.0         # 实际移动时长（提前到达极限时小于请求值）
    limit_reached: bool = False                  # 是否检测到到达物理极限
    degraded: bool = False                       # 是否发生了降级（指令被截断替换为可行操作）
    degrade_reason: str = ""                     # 降级原因说明（供 Agent 转述给用户）


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
    error_message: str = ""                      # 查询失败时的错误信息


@dataclass
class CalibrateResult:
    """云台校准返回结果"""
    success: bool                                # 校准是否完成
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


def _onvif_ptz_calibrate(camera_name: str) -> CalibrateResult:
    """通过 ONVIF GotoHomePosition 实现云台软件校准（回到初始位置）"""
    conn = _get_conn_info(camera_name)
    if not conn:
        return CalibrateResult(
            success=False, protocol="onvif",
            error_message=f"设备 {camera_name} 未连接",
        )

    onvif_cam = conn.get("onvif_camera")
    if not onvif_cam:
        return CalibrateResult(
            success=False, protocol="onvif",
            error_message="ONVIF 服务未初始化",
        )

    try:
        ptz = onvif_cam.create_ptz_service()
        media = onvif_cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return CalibrateResult(
                success=False, protocol="onvif",
                error_message="无法获取 ONVIF Profile",
            )

        profile_token = profiles[0].token
        ptz.GotoHomePosition({'ProfileToken': profile_token, 'Speed': {'PanTilt': {'x': 1.0, 'y': 1.0}}})
        return CalibrateResult(success=True, protocol="onvif")
    except Exception as e:
        return CalibrateResult(
            success=False, protocol="onvif",
            error_message=f"ONVIF GotoHomePosition 失败: {e}",
        )


# ──────────────────────────────────────────────
#  私有协议 PTZ 内部实现 (SK_SETTING_SET_PTZ)
# ──────────────────────────────────────────────

# ── 私有协议 TCP 不可用统一诊断消息 ──
_SK_TCP_404_MSG = (
    "创维私有协议 (TCP 9010) 不可用：设备返回 HTTP 404，"
    "该型号固件不支持 TCP 私有协议接口"
)

_SK_TCP_UNAVAILABLE_MSGS = {
    "connection_reset": (
        "创维私有协议 (TCP 9010) 不可用：连接被重置 (RST)，"
        "该型号固件不支持 TCP 私有协议接口"
    ),
    "connection_refused": (
        "创维私有协议 (TCP 9010) 不可用：连接被拒绝，"
        "端口未监听"
    ),
    "timeout": (
        "创维私有协议 (TCP 9010) 不可用：连接超时"
    ),
}


def _is_sk_tcp_unavailable(resp: Optional[dict]) -> bool:
    """检测 send_tcp_command 返回值是否为 TCP 私有协议不可用 (HTTP 404 或 TCP 连接失败)"""
    if not resp or not isinstance(resp, dict):
        return False
    if resp.get("_http_status") == 404:
        return True
    if resp.get("_tcp_error") in _SK_TCP_UNAVAILABLE_MSGS:
        return True
    return False


def _sk_tcp_error_message(resp: Optional[dict]) -> str:
    """根据 send_tcp_command 返回值生成友好的 TCP 不可用错误消息"""
    if not resp or not isinstance(resp, dict):
        return "TCP 通道无响应"
    tcp_err = resp.get("_tcp_error", "")
    if tcp_err in _SK_TCP_UNAVAILABLE_MSGS:
        return _SK_TCP_UNAVAILABLE_MSGS[tcp_err]
    if resp.get("_http_status") == 404:
        return _SK_TCP_404_MSG
    return resp.get("msg", "TCP 通道未知错误")


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
    if _is_sk_tcp_unavailable(resp):
        return PTZMoveResult(success=False, protocol="sky_private", error_message=_sk_tcp_error_message(resp))
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
    if _is_sk_tcp_unavailable(resp):
        return PTZMoveResult(success=False, protocol="sky_private", error_message=_sk_tcp_error_message(resp))
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
    if _is_sk_tcp_unavailable(resp):
        return CalibrateResult(success=False, protocol="sky_private", error_message=_sk_tcp_error_message(resp))
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
    if _is_sk_tcp_unavailable(resp):
        return PTZMoveResult(success=False, protocol="sky_private", error_message=_sk_tcp_error_message(resp))
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
    # 诊断: HTTP 404 → 设备不支持 TCP 私有协议
    if _is_sk_tcp_unavailable(resp):
        return PTZParameters(protocol="sky_private", error_message=_sk_tcp_error_message(resp))
    return PTZParameters(
        protocol="sky_private",
        error_message=resp.get("msg", "TCP 通道无响应") if resp else "TCP 通道无响应",
    )


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


# ──────────────────────────────────────────────
#  物理极限守护（Limit Guard）
# ──────────────────────────────────────────────

# 方向 → (pan 位移符号, tilt 位移符号)；+1 表示朝范围最大值方向，-1 表示朝最小值方向
_DIRECTION_SIGN: Dict[PTZDirection, tuple] = {
    PTZDirection.UP:        (0, +1),
    PTZDirection.DOWN:      (0, -1),
    PTZDirection.LEFT:      (-1, 0),
    PTZDirection.RIGHT:     (+1, 0),
    PTZDirection.UPLEFT:    (-1, +1),
    PTZDirection.UPRIGHT:   (+1, +1),
    PTZDirection.DOWNLEFT:  (-1, -1),
    PTZDirection.DOWNRIGHT: (+1, -1),
}

# 位置轮询间隔（秒）与判定阈值
_GUARD_POLL_INTERVAL = 0.4     # 移动期间位置轮询间隔
_GUARD_STALL_POLLS = 2         # 连续 N 次位置无变化即判定到达极限
_GUARD_EDGE_MARGIN = 1.0       # 距离范围边界小于该值视为已贴边（私有协议坐标为整数刻度）
_GUARD_MOVE_EPS = 1e-3         # 位移检测阈值


def _query_ptz_position(camera_name: str, channel: int = 2) -> Optional[PTZParameters]:
    """
    查询当前云台位置与范围（私有协议 SK_SETTING_GET_PTZ）。

    与 _sk_get_ptz_params 不同：查询失败时返回 None（而非全零参数），
    以便守护逻辑区分“查询不可用”与“位置为 0”，查询不可用时安全退化为普通移动。
    """
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
            protocol="sky_private",
        )
    return None


def _axis_at_limit(pos: float, rng: float, sign: int) -> bool:
    """判断单轴位置是否已贴住运动方向上的物理边界（范围未知时无法判定）"""
    if sign == 0 or rng <= 0:
        return False
    if sign > 0:
        return pos >= rng - _GUARD_EDGE_MARGIN
    return pos <= _GUARD_EDGE_MARGIN


def _at_direction_limit(params: PTZParameters, direction: PTZDirection) -> bool:
    """判断当前位置在指定方向上是否已无剩余行程。

    对角方向只要两轴均贴边才算到达极限（任一轴仍可动则继续移动）。
    """
    pan_sign, tilt_sign = _DIRECTION_SIGN.get(direction, (0, 0))
    pan_limited = _axis_at_limit(params.pan, params.pan_range, pan_sign) if pan_sign else True
    tilt_limited = _axis_at_limit(params.tilt, params.tilt_range, tilt_sign) if tilt_sign else True
    return pan_limited and tilt_limited


def _guarded_wait(
    camera_name: str,
    direction: PTZDirection,
    duration_seconds: float,
) -> tuple:
    """
    移动期间的守护等待：周期性轮询云台位置，检测到到达物理极限时提前停止等待。

    判定依据（满足其一即视为到达极限）：
      1. 当前位置已贴住运动方向上的范围边界（x_range / y_range）
      2. 连续 _GUARD_STALL_POLLS 次轮询位置无变化（云台被物理挡住，不再位移）

    位置查询不可用时（如非创维设备无私有协议通道），安全退化为普通 sleep，
    不影响原有移动功能。

    Returns:
        (actual_duration, limit_reached, final_params)
        - actual_duration: 实际等待时长（秒）
        - limit_reached:   是否检测到到达物理极限
        - final_params:    最后一次查询到的位置参数（可能为 None）
    """
    start = time.monotonic()
    last = _query_ptz_position(camera_name)
    if last is None:
        # 无法感知位置 → 退化为原有的定时移动
        time.sleep(duration_seconds)
        return duration_seconds, False, None

    pan_sign, tilt_sign = _DIRECTION_SIGN.get(direction, (0, 0))
    stall_count = 0
    final_params = last
    limit_reached = False

    while True:
        remaining = duration_seconds - (time.monotonic() - start)
        if remaining <= 0:
            break
        time.sleep(min(_GUARD_POLL_INTERVAL, remaining))

        cur = _query_ptz_position(camera_name)
        if cur is None:
            continue  # 单次查询失败不影响移动，继续等待
        final_params = cur

        # 到达范围边界 → 立即判定
        if _at_direction_limit(cur, direction):
            limit_reached = True
            break

        # 沿运动方向的位移停滞检测
        moved = False
        if pan_sign and abs(cur.pan - last.pan) > _GUARD_MOVE_EPS:
            moved = True
        if tilt_sign and abs(cur.tilt - last.tilt) > _GUARD_MOVE_EPS:
            moved = True
        stall_count = 0 if moved else stall_count + 1
        if stall_count >= _GUARD_STALL_POLLS:
            limit_reached = True
            break
        last = cur

    return time.monotonic() - start, limit_reached, final_params


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
    步进式控制云台方向移动（带物理极限守护）。

    优先通过 ONVIF PTZ Service 执行 ContinuousMove，
    若 ONVIF 不可用则降级到创维私有协议（SK_SETTING_SET_PTZ）。

    物理极限守护（Limit Guard）：
      - 移动前预检：若云台在目标方向上已无剩余行程，直接拦截指令，
        不向设备发送移动命令，返回 degraded=True 及原因说明。
      - 移动中守护：移动期间周期性轮询云台位置（SK_SETTING_GET_PTZ），
        检测到到达范围边界或位移停滞时立即停止，实际时长可能小于请求时长。
      - 发生降级时结果中 degraded=True，Agent 必须将 degrade_reason
        显式转述给用户（例如"请求右转 5 秒，但 3.2 秒后已到达右侧极限"）。
      - 位置查询不可用的设备自动退化为原有的定时移动，功能不受影响。

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
            - requested_duration_seconds / actual_duration_seconds: 请求/实际时长
            - limit_reached: 是否到达物理极限
            - degraded: 指令是否被截断或拦截（True 时 Agent 须告知用户）
            - degrade_reason: 降级原因说明
            - error_message: 失败原因
    """
    direction = _resolve_direction(direction)
    if not direction:
        return PTZMoveResult(success=False, error_message="无效方向，可用: up/down/left/right/upleft/upright/downleft/downright")

    speed = max(0.1, min(1.0, speed))
    duration_seconds = max(0.1, min(10.0, duration_seconds))

    # ── 移动前预检：目标方向已无剩余行程 → 拦截指令，不发送移动命令 ──
    pre_params = _query_ptz_position(camera_name)
    if pre_params is not None and _at_direction_limit(pre_params, direction):
        return PTZMoveResult(
            success=True,
            protocol="sky_private",
            current_pan=pre_params.pan,
            current_tilt=pre_params.tilt,
            current_zoom=pre_params.zoom,
            requested_duration_seconds=duration_seconds,
            actual_duration_seconds=0.0,
            limit_reached=True,
            degraded=True,
            degrade_reason=(
                f"云台在 {direction.value} 方向已处于物理极限位置"
                f"（pan={pre_params.pan:.0f}/{pre_params.pan_range:.0f}, "
                f"tilt={pre_params.tilt:.0f}/{pre_params.tilt_range:.0f}），"
                f"移动指令已被拦截，未向设备发送。请告知用户无法继续朝该方向转动。"
            ),
        )

    def _finalize(result: PTZMoveResult) -> PTZMoveResult:
        """移动指令下发成功后：守护等待 → 停止 → 回填降级信息"""
        actual, limit_hit, final_params = _guarded_wait(camera_name, direction, duration_seconds)

        if result.protocol == "onvif":
            stop_result = _onvif_stop(camera_name)
        else:
            stop_result = _sk_ptz_stop(camera_name, action=_SK_CMD_MAP.get(direction, ""))
        if not stop_result.success:
            print(f"[PTZ] 自动停止失败: {stop_result.error_message}")

        result.requested_duration_seconds = duration_seconds
        result.actual_duration_seconds = round(actual, 2)
        result.limit_reached = limit_hit
        if final_params is not None:
            result.current_pan = final_params.pan
            result.current_tilt = final_params.tilt
            result.current_zoom = final_params.zoom
        if limit_hit and actual < duration_seconds - _GUARD_POLL_INTERVAL:
            result.degraded = True
            result.degrade_reason = (
                f"请求朝 {direction.value} 方向移动 {duration_seconds:.1f} 秒，"
                f"但云台在 {actual:.1f} 秒后到达物理极限，已提前自动停止。"
                f"请将该情况告知用户。"
            )
        elif limit_hit:
            result.limit_reached = True
            result.degrade_reason = f"移动结束时云台已到达 {direction.value} 方向的物理极限。"
        return result

    # ── 尝试 1: ONVIF ──
    onvif_result = _onvif_ptz_move(camera_name, direction, speed)
    if onvif_result.success:
        return _finalize(onvif_result)

    # ── 尝试 2: 私有协议 ──
    sk_result = _sk_ptz_move(camera_name, direction)
    if sk_result.success:
        return _finalize(sk_result)

    return PTZMoveResult(
        success=False,
        error_message=(
            f"ONVIF 和私有协议均失败。ONVIF: {onvif_result.error_message}；"
            f"私有协议: {sk_result.error_message}"
        ),
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
    result = _sk_get_ptz_params(camera_name)
    if result.error_message:
        # 私有协议也失败，返回带错误信息的 PTZParameters
        return PTZParameters(
            protocol="fallback",
            error_message=(
                f"ONVIF 和私有协议均无法获取云台参数。"
                f"私有协议: {result.error_message}"
            ),
        )
    return result


def calibrate_ptz(
    camera_name: str,
) -> CalibrateResult:
    """
    执行云台校准（ONVIF GotoHomePosition 优先，私有协议兆底）。

    双协议策略:
      1. 优先 ONVIF GotoHomePosition（回到初始位置）
      2. 失败则回退创维私有协议 calibrate 命令

    校准过程中云台会进行物理运动，耗时约 10-30 秒。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        CalibrateResult:
            - success: 校准是否完成
            - protocol: 使用的协议
            - error_message: 失败原因
    """
    # ── 尝试 1: ONVIF GotoHomePosition ──
    result = _onvif_ptz_calibrate(camera_name)
    if result.success:
        return result

    # ── 尝试 2: 创维私有协议 calibrate ──
    result2 = _sk_ptz_calibrate(camera_name)
    if result2.success:
        return result2

    # 两者都失败，返回更详细的错误
    return CalibrateResult(
        success=False, protocol="onvif",
        error_message=(
            f"ONVIF 校准失败: {result.error_message}; "
            f"私有协议校准失败: {result2.error_message}"
        ),
    )


def _move_to_position(
    camera_name: str,
    x: int,
    y: int,
    z: float = 1.0,
) -> PTZMoveResult:
    """
    移动云台到指定绝对坐标（创维私有协议）。

    内部函数，不注册为 MCP 工具，供模块内部或二次开发直接调用。
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
