import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

try:
    from . import sk_proto
except ImportError:
    import sk_proto

try:
    from .illumination import _envelope
except ImportError:
    from illumination import _envelope

class PTZDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UPLEFT = "upleft"
    UPRIGHT = "upright"
    DOWNLEFT = "downleft"
    DOWNRIGHT = "downright"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"

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

_SK_CMD_MAP: Dict[PTZDirection, str] = {
    PTZDirection.UP:        "up",
    PTZDirection.DOWN:      "down",
    PTZDirection.LEFT:      "left",
    PTZDirection.RIGHT:     "right",
    PTZDirection.UPLEFT:    "upleft",
    PTZDirection.UPRIGHT:   "upright",
    PTZDirection.DOWNLEFT:  "downleft",
    PTZDirection.DOWNRIGHT: "downright",
    PTZDirection.ZOOM_IN:   "zoom+",
    PTZDirection.ZOOM_OUT:  "zoom-",
}

_PTZ_ZOOM = frozenset({PTZDirection.ZOOM_IN, PTZDirection.ZOOM_OUT})

_DIAGONAL_TO_AXES: Dict[str, Tuple[str, str]] = {
    "upleft":    ("up", "left"),
    "upright":   ("up", "right"),
    "downleft":  ("down", "left"),
    "downright": ("down", "right"),
}

_DEGREES_PER_SECOND = 34.0

_SK_PTZ_TIMEOUT = 5.0

_calibrated_home: Optional[Tuple[int, int]] = None

def _safe_int(val, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default

def _safe_float(val, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

@dataclass
class PTZMoveResult:
    success: bool
    protocol: str = ""
    current_pan: float = 0.0
    current_tilt: float = 0.0
    current_zoom: float = 0.0
    error_message: str = ""

    requested_duration_seconds: float = 0.0
    actual_duration_seconds: float = 0.0
    limit_reached: bool = False
    degraded: bool = False
    degrade_reason: str = ""

    degrees: float = 0.0
    position: str = ""
    method: str = ""

@dataclass
class PTZParameters:
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0
    pan_range: float = 0.0
    tilt_range: float = 0.0
    zoom_range: float = 0.0
    is_moving: bool = False
    protocol: str = ""
    error_message: str = ""

@dataclass
class CalibrateResult:
    success: bool
    protocol: str = ""
    error_message: str = ""
    home_position: str = ""
    action: str = ""

@dataclass
class PTZInfo:
    preset_max: int = 0
    cruise_max: int = 0
    scan_max: int = 0
    presets_per_cruise: int = 0
    presets_per_scan: int = 0
    preset_num: int = 0
    cruise_num: int = 0
    scan_num: int = 0

def _get_camera(camera_name: str):
    from .device_mgmt import _find_camera
    return _find_camera(camera_name)

def _sk_ptz_get(cam) -> Optional[dict]:
    ok, data, status = _envelope(sk_proto.ptz_get(
        cam.ip, cam.sn_code, cam.username, cam.password, _SK_PTZ_TIMEOUT))
    if not ok or not data:
        return None
    if not sk_proto.code_ok(data.get("code", "")):
        return None

    pos_sub = data.get("position", {})
    if isinstance(pos_sub, dict):
        x = _safe_int(pos_sub.get("x", data.get("x", 0)))
        y = _safe_int(pos_sub.get("y", data.get("y", 0)))
        z = _safe_float(pos_sub.get("z", data.get("z", 1.0)), 1.0)
    else:
        x = _safe_int(data.get("x", 0))
        y = _safe_int(data.get("y", 0))
        z = _safe_float(data.get("z", 1.0), 1.0)

    return {
        "x": x, "y": y, "z": z,
        "x_range": _safe_int(data.get("x_range", 421), 421),
        "y_range": _safe_int(data.get("y_range", 134), 134),
        "z_range": _safe_float(data.get("z_range", 10.0), 10.0),
        "raw": data,
    }

def _sk_ptz_set(cam, payload: dict) -> Tuple[bool, str]:
    ok, data, status = _envelope(sk_proto.ptz_set(
        cam.ip, cam.sn_code, cam.username, cam.password, payload, _SK_PTZ_TIMEOUT))
    if not ok or not data:
        return False, f"SK SET_PTZ 请求失败 (status={status})"
    if not sk_proto.code_ok(data.get("code", "")):
        return False, f"SK SET_PTZ 返回 code={data.get('code')} msg={data.get('msg')}"
    return True, ""

def _resolve_direction(direction) -> Optional[PTZDirection]:
    if isinstance(direction, PTZDirection):
        return direction
    if isinstance(direction, str):
        if direction.strip() in _DIRECTION_ALIAS:
            return _DIRECTION_ALIAS[direction.strip()]
        try:
            return PTZDirection(direction.strip().lower())
        except ValueError:
            return None
    return None

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

_GUARD_POLL_INTERVAL = 0.4
_GUARD_STALL_POLLS = 2
_GUARD_EDGE_MARGIN = 1.0
_GUARD_MOVE_EPS = 1e-3

def _query_ptz_position(cam) -> Optional[dict]:
    return _sk_ptz_get(cam)

def _axis_at_limit(pos: float, rng: float, sign: int) -> bool:
    if sign == 0 or rng <= 0:
        return False
    if sign > 0:
        return pos >= rng - _GUARD_EDGE_MARGIN
    return pos <= _GUARD_EDGE_MARGIN

def _at_direction_limit(pos: dict, direction: PTZDirection) -> bool:
    pan_sign, tilt_sign = _DIRECTION_SIGN.get(direction, (0, 0))
    pan_limited = _axis_at_limit(pos.get("x", 0), pos.get("x_range", 0), pan_sign) if pan_sign else True
    tilt_limited = _axis_at_limit(pos.get("y", 0), pos.get("y_range", 0), tilt_sign) if tilt_sign else True
    return pan_limited and tilt_limited

def _guarded_wait(
    cam,
    direction: PTZDirection,
    duration_seconds: float,
) -> tuple:
    start = time.monotonic()
    last = _query_ptz_position(cam)
    if last is None:
        time.sleep(duration_seconds)
        return duration_seconds, False, None

    pan_sign, tilt_sign = _DIRECTION_SIGN.get(direction, (0, 0))
    stall_count = 0
    final_pos = last
    limit_reached = False

    while True:
        remaining = duration_seconds - (time.monotonic() - start)
        if remaining <= 0:
            break
        time.sleep(min(_GUARD_POLL_INTERVAL, remaining))

        cur = _query_ptz_position(cam)
        if cur is None:
            continue
        final_pos = cur

        if _at_direction_limit(cur, direction):
            limit_reached = True
            break

        moved = False
        if pan_sign and abs(cur.get("x", 0) - last.get("x", 0)) > _GUARD_MOVE_EPS:
            moved = True
        if tilt_sign and abs(cur.get("y", 0) - last.get("y", 0)) > _GUARD_MOVE_EPS:
            moved = True
        stall_count = 0 if moved else stall_count + 1
        if stall_count >= _GUARD_STALL_POLLS:
            limit_reached = True
            break
        last = cur

    return time.monotonic() - start, limit_reached, final_pos

def control_ptz(
    camera_name: str,
    direction: PTZDirection,
    speed: float = 0.5,
    duration_seconds: Optional[float] = None,
    degrees: Optional[float] = None,
) -> PTZMoveResult:
    direction = _resolve_direction(direction)
    if not direction:
        return PTZMoveResult(
            success=False,
            error_message="无效方向，可用: up/down/left/right/upleft/upright/downleft/downright/zoom_in/zoom_out",
        )

    speed = max(0.1, min(1.0, speed))

    if degrees is not None and duration_seconds is not None:
        return PTZMoveResult(
            success=False,
            error_message="degrees 和 duration_seconds 不能同时指定",
        )
    if degrees is None and duration_seconds is None:
        duration_seconds = 1.0
    if duration_seconds is not None:
        duration_seconds = max(0.1, min(10.0, duration_seconds))
    if degrees is not None:
        degrees = max(0.1, min(360.0, degrees))

    cam = _get_camera(camera_name)
    if not cam:
        return PTZMoveResult(
            success=False,
            error_message=f"摄像头 '{camera_name}' 未注册，请先注册",
        )

    if direction in _PTZ_ZOOM:
        sk_cmd = _SK_CMD_MAP.get(direction, "")
        duration = duration_seconds if duration_seconds is not None else 1.0
        ok, err = _sk_ptz_set(cam, {"cmd": sk_cmd})
        if not ok:
            return PTZMoveResult(
                success=False, protocol="sky_private",
                error_message=f"zoom 启动失败: {err}",
            )
        time.sleep(duration)
        ok, err = _sk_ptz_set(cam, {"cmd": "stop", "action": sk_cmd})
        if not ok:
            return PTZMoveResult(
                success=False, protocol="sky_private",
                requested_duration_seconds=duration,
                error_message=f"zoom 已启动但停止失败: {err}",
            )
        return PTZMoveResult(
            success=True, protocol="sky_private",
            requested_duration_seconds=duration,
            actual_duration_seconds=duration,
            method="sk_zoom",
        )

    dir_str = direction.value
    if degrees is None:
        half = duration_seconds / 2.0

        if dir_str in _DIAGONAL_TO_AXES:

            h_axis, v_axis = _DIAGONAL_TO_AXES[dir_str]

            ok, err = _sk_ptz_set(cam, {"cmd": h_axis})
            if not ok:
                return PTZMoveResult(
                    success=False, protocol="sky_private",
                    error_message=f"水平方向({h_axis})移动启动失败: {err}",
                )
            time.sleep(half)
            _sk_ptz_set(cam, {"cmd": "stop", "action": h_axis})

            ok, err = _sk_ptz_set(cam, {"cmd": v_axis})
            if not ok:
                return PTZMoveResult(
                    success=False, protocol="sky_private",
                    error_message=f"垂直方向({v_axis})移动启动失败: {err}",
                )
            time.sleep(half)
            _sk_ptz_set(cam, {"cmd": "stop", "action": v_axis})

        else:

            sk_cmd = _SK_CMD_MAP.get(direction, "")
            ok, err = _sk_ptz_set(cam, {"cmd": sk_cmd})
            if not ok:
                return PTZMoveResult(
                    success=False, protocol="sky_private",
                    error_message=f"方向移动启动失败: {err}",
                )
            time.sleep(duration_seconds)
            _sk_ptz_set(cam, {"cmd": "stop", "action": sk_cmd})

        return PTZMoveResult(
            success=True, protocol="sky_private",
            requested_duration_seconds=duration_seconds,
            actual_duration_seconds=duration_seconds,
            method="sk_time",
        )

    duration_seconds = degrees / 34.0
    duration_seconds = max(0.1, min(10.0, duration_seconds))
    half = duration_seconds / 2.0

    if dir_str in _DIAGONAL_TO_AXES:

        h_axis, v_axis = _DIAGONAL_TO_AXES[dir_str]

        ok, err = _sk_ptz_set(cam, {"cmd": h_axis})
        if not ok:
            return PTZMoveResult(
                success=False, protocol="sky_private", degrees=degrees,
                error_message=f"水平方向({h_axis})移动启动失败: {err}",
            )
        time.sleep(half)
        _sk_ptz_set(cam, {"cmd": "stop", "action": h_axis})

        ok, err = _sk_ptz_set(cam, {"cmd": v_axis})
        if not ok:
            return PTZMoveResult(
                success=False, protocol="sky_private", degrees=degrees,
                error_message=f"垂直方向({v_axis})移动启动失败: {err}",
            )
        time.sleep(half)
        _sk_ptz_set(cam, {"cmd": "stop", "action": v_axis})

    else:

        sk_cmd = _SK_CMD_MAP.get(direction, "")
        ok, err = _sk_ptz_set(cam, {"cmd": sk_cmd})
        if not ok:
            return PTZMoveResult(
                success=False, protocol="sky_private", degrees=degrees,
                error_message=f"方向移动启动失败: {err}",
            )
        time.sleep(duration_seconds)
        _sk_ptz_set(cam, {"cmd": "stop", "action": sk_cmd})

    return PTZMoveResult(
        success=True, protocol="sky_private",
        degrees=degrees,
        requested_duration_seconds=round(duration_seconds, 2),
        actual_duration_seconds=round(duration_seconds, 2),
        method="sk_degrees",
    )

def get_ptz_parameters(
    camera_name: str,
) -> PTZParameters:
    cam = _get_camera(camera_name)
    if not cam:
        return PTZParameters(error_message=f"摄像头 '{camera_name}' 未注册")

    pos = _sk_ptz_get(cam)
    if pos is None:
        return PTZParameters(
            protocol="sky_private",
            error_message="SK GET_PTZ 查询失败",
        )

    return PTZParameters(
        pan=float(pos.get("x", 0)),
        tilt=float(pos.get("y", 0)),
        zoom=float(pos.get("z", 0)),
        pan_range=float(pos.get("x_range", 0)),
        tilt_range=float(pos.get("y_range", 0)),
        zoom_range=float(pos.get("z_range", 0)),
        is_moving=False,
        protocol="sky_private",
    )

def calibrate_ptz(
    camera_name: str,
    action: str = "set_home",
) -> CalibrateResult:
    global _calibrated_home

    cam = _get_camera(camera_name)
    if not cam:
        return CalibrateResult(
            success=False, protocol="sky_private",
            error_message=f"摄像头 '{camera_name}' 未注册",
        )

    action = (action or "").strip()
    if action not in ("set_home", "go_home"):
        return CalibrateResult(
            success=False, protocol="sky_private",
            error_message=f"action={action!r} 无效，可选: set_home / go_home",
        )

    if action == "set_home":
        ok, err = _sk_ptz_set(cam, {"cmd": "calibrate"})
        if not ok:
            return CalibrateResult(
                success=False, protocol="sky_private",
                action=action,
                error_message=f"SK calibrate 失败: {err}",
            )
        time.sleep(2)

        pos = _sk_ptz_get(cam)
        if pos is None:
            return CalibrateResult(
                success=False, protocol="sky_private",
                action=action,
                error_message="SK calibrate 已执行，但 GET_PTZ 读取坐标失败，Home 位未存储",
            )

        home_x = pos.get("x", 0)
        home_y = pos.get("y", 0)
        _calibrated_home = (home_x, home_y)

        return CalibrateResult(
            success=True, protocol="sky_private",
            action=action,
            home_position=f"x={home_x},y={home_y}",
        )

    if _calibrated_home is None:
        ok, err = _sk_ptz_set(cam, {"cmd": "calibrate"})
        if not ok:
            return CalibrateResult(
                success=False, protocol="sky_private",
                action=action,
                error_message=f"go_home 需先校准，但 SK calibrate 失败: {err}",
            )
        time.sleep(2)
        pos = _sk_ptz_get(cam)
        if pos is None:
            return CalibrateResult(
                success=False, protocol="sky_private",
                action=action,
                error_message="SK calibrate 已执行，但 GET_PTZ 读取坐标失败",
            )
        _calibrated_home = (pos.get("x", 0), pos.get("y", 0))

    home_x, home_y = _calibrated_home
    ok, err = _sk_ptz_set(cam, {"cmd": "move", "x": home_x, "y": home_y, "z": 1.0})
    if not ok:
        return CalibrateResult(
            success=False, protocol="sky_private",
            action=action,
            error_message=f"SK move 归位失败: {err}",
        )

    return CalibrateResult(
        success=True, protocol="sky_private",
        action=action,
        home_position=f"x={home_x},y={home_y}",
    )

def _move_to_position(
    camera_name: str,
    x: int,
    y: int,
    z: float = 1.0,
) -> PTZMoveResult:
    cam = _get_camera(camera_name)
    if not cam:
        return PTZMoveResult(
            success=False,
            error_message=f"摄像头 '{camera_name}' 未注册",
        )

    ok, err = _sk_ptz_set(cam, {"cmd": "move", "x": x, "y": y, "z": z})
    if ok:
        return PTZMoveResult(
            success=True, protocol="sky_private",
            current_pan=float(x), current_tilt=float(y), current_zoom=z,
        )
    return PTZMoveResult(success=False, protocol="sky_private", error_message=err)

def stop_ptz(
    camera_name: str,
) -> PTZMoveResult:
    cam = _get_camera(camera_name)
    if not cam:
        return PTZMoveResult(
            success=False,
            error_message=f"摄像头 '{camera_name}' 未注册",
        )

    ok, err = _sk_ptz_set(cam, {"cmd": "stop"})
    if ok:
        return PTZMoveResult(success=True, protocol="sky_private")
    return PTZMoveResult(success=False, protocol="sky_private", error_message=err)
