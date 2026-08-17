"""
Toolkit: 云台控制（SK 协议实现）

协议策略:
  全部使用 SK 私有协议（SK_SETTING_SET_PTZ / SK_SETTING_GET_PTZ），
  通过 HTTP POST（端口 9010）+ 动态 Token 鉴权通信。

工具清单：
  - control_ptz          方向移动 / 角度精确移动 / 变焦（三模式）
  - get_ptz_parameters   获取云台位移与角度参数
  - calibrate_ptz        执行云台校准（set_home / go_home）
  - stop_ptz             停止云台移动

内部函数（不注册为 MCP 工具）：
  - _move_to_position    移动到指定绝对坐标

物理极限守护（Limit Guard）：
  - 移动前预检：目标方向已无行程 → 拦截
  - 移动中守护：周期轮询位置 → 到达极限/停滞 → 提前停止
  - 角度模式和 zoom 模式不走守护（固件自动到位 / 无位置反馈）

前提条件: 摄像头已注册到 config.yaml（含 sn_code）。
"""
import base64
import hashlib
import json
import sys
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None


# ──────────────────────────────────────────────
#  常量
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
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"


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

# SK 方向命令映射
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

# Zoom 方向集合
_PTZ_ZOOM = frozenset({PTZDirection.ZOOM_IN, PTZDirection.ZOOM_OUT})

# 对角方向 → 单轴方向拆分（SK stop 命令只接受单轴方向）
_DIAGONAL_TO_AXES: Dict[str, Tuple[str, str]] = {
    "upleft":    ("up", "left"),
    "upright":   ("up", "right"),
    "downleft":  ("down", "left"),
    "downright": ("down", "right"),
}

# 角度→时间换算基准（实测值：约 1 秒转动 34 度）
_DEGREES_PER_SECOND = 34.0

# SK 协议常量
_SK_PTZ_PORT = 9010
_SK_PTZ_TIMEOUT = 5.0
_SK_AUTH_KEY = bytes([0x72, 0x58, 0xea, 0xd7, 0x50, 0xd7, 0x38, 0xe6,
                      0x54, 0x25, 0x51, 0x90, 0x81, 0x4c, 0x4d, 0x68])
_SK_MAX_RETRIES = 3
_SK_RETRY_INTERVAL = 0.5

# 校准后的 Home 位（x, y），模块级变量，进程生命周期内持久
_calibrated_home: Optional[Tuple[int, int]] = None


# ──────────────────────────────────────────────
#  容错解析
# ──────────────────────────────────────────────

def _safe_int(val, default: int = 0) -> int:
    """安全转 int：空串 / None / 非数字 → default，不抛异常。"""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default: float = 0.0) -> float:
    """安全转 float：空串 / None / 非数字 → default，不抛异常。"""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _log(msg: str):
    """调试日志输出到 stderr。"""
    print(f"[ptz-sk] {msg}", file=sys.stderr)


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class PTZMoveResult:
    """云台移动操作返回结果"""
    success: bool                                # 是否成功
    protocol: str = ""                           # 使用的协议: "sky_private"
    current_pan: float = 0.0                     # 当前水平位置
    current_tilt: float = 0.0                    # 当前垂直位置
    current_zoom: float = 0.0                    # 当前变焦倍数
    error_message: str = ""                      # 失败原因
    # ── 物理极限守护（降级信息）──
    requested_duration_seconds: float = 0.0      # 用户请求的移动时长
    actual_duration_seconds: float = 0.0         # 实际移动时长
    limit_reached: bool = False                  # 是否检测到到达物理极限
    degraded: bool = False                       # 是否发生了降级
    degrade_reason: str = ""                     # 降级原因说明
    # ── 扩展字段（角度模式 / zoom）──
    degrees: float = 0.0                         # 角度模式时的请求角度
    position: str = ""                           # 角度模式时的目标坐标 "x=200,y=80"
    method: str = ""                             # "sk_time" | "sk_position" | "sk_zoom"


@dataclass
class PTZParameters:
    """云台参数"""
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
    """云台校准返回结果"""
    success: bool
    protocol: str = ""
    error_message: str = ""
    home_position: str = ""                      # 校准后的 Home 位 "x=0,y=0"
    action: str = ""                             # "set_home" | "go_home"


@dataclass
class PTZInfo:
    """PTZ 信息（预置位、巡航、扫描路线能力）"""
    preset_max: int = 0
    cruise_max: int = 0
    scan_max: int = 0
    presets_per_cruise: int = 0
    presets_per_scan: int = 0
    preset_num: int = 0
    cruise_num: int = 0
    scan_num: int = 0


# ──────────────────────────────────────────────
#  SK 协议 HTTP 通信（动态 Token 鉴权）
# ──────────────────────────────────────────────

def _sk_compute_auth_token(sn: str, username: str, password: str,
                           host: str, port: int, timeout: float) -> Optional[str]:
    """计算 SK 协议的动态 Authorization token。

    步骤：
      1. 先用 Basic Auth(username:password) 发 SK_SETTING_GET_MAGIC 拿 stamp
      2. token = Base64(SHA1(stamp + sn + KEY))
    """
    if not sn:
        _log("SK auth: sn 为空，无法计算 token")
        return None
    url = f"http://{host}:{port}/xiaopaitech/device_service"
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Basic {basic_token}",
    }

    for attempt in range(1, _SK_MAX_RETRIES + 1):
        msg_id = time.strftime("%y%m%d%H%M%S") + uuid.uuid4().hex[:6]
        body = {
            "service_type": "setting",
            "msg_id": msg_id,
            "cmd_name": "SK_SETTING_GET_MAGIC",
            "ver": "1.0",
            "channel": 2,
            "sequence": 0,
            "refresh": "0",
        }
        _log(f"SK auth: 请求 GET_MAGIC sn={sn}（第 {attempt}/{_SK_MAX_RETRIES} 次）")
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            _log(f"SK auth: GET_MAGIC 失败 {type(e).__name__}: {e}")
            return None
        if resp.status_code == 404 and attempt < _SK_MAX_RETRIES:
            _log(f"SK auth: GET_MAGIC 404（固件间歇性），{_SK_RETRY_INTERVAL}s 后重试...")
            time.sleep(_SK_RETRY_INTERVAL)
            continue
        if resp.status_code != 200:
            _log(f"SK auth: GET_MAGIC HTTP {resp.status_code}")
            return None
        try:
            data = resp.json()
        except ValueError:
            _log("SK auth: GET_MAGIC 响应非 JSON")
            return None
        stamp = data.get("stamp")
        if not stamp:
            _log(f"SK auth: GET_MAGIC 未返回 stamp (code={data.get('code')})")
            return None
        h = hashlib.sha1()
        h.update(stamp.encode("utf-8"))
        h.update(sn.encode("utf-8"))
        h.update(_SK_AUTH_KEY)
        token = base64.b64encode(h.digest()).decode("utf-8")
        _log(f"SK auth: stamp={stamp} token={token}")
        return token

    return None


def _sk_http_query_ex(host: str, port: int, cmd_name: str, payload: dict,
                      sn: str, username: str, password: str, timeout: float):
    """SK 协议 HTTP POST 查询，带动态 Token 鉴权与重试。

    Returns: (ok: bool, data: dict|None, status: int|None)
    """
    if requests is None:
        return False, None, None

    for attempt in range(1, _SK_MAX_RETRIES + 1):
        token = _sk_compute_auth_token(sn, username, password, host, port, timeout)
        if not token:
            _log(f"SK 鉴权失败: 无法计算 token（sn={sn!r}）")
            return False, None, None
        url = f"http://{host}:{port}/xiaopaitech/device_service"
        msg_id = time.strftime("%y%m%d%H%M%S") + uuid.uuid4().hex[:6]
        body = {
            "service_type": "setting",
            "msg_id": msg_id,
            "cmd_name": cmd_name,
            "ver": "1.0",
            "channel": 2,
            "sequence": 0,
        }
        body.update(payload)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Basic {token}",
        }
        _log(f"SK POST {url} cmd={cmd_name}（第 {attempt}/{_SK_MAX_RETRIES} 次）")
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            _log(f"SK 连接失败/超时: {type(e).__name__}: {e}")
            return False, None, None
        if resp.status_code == 404 and attempt < _SK_MAX_RETRIES:
            _log(f"SK HTTP 404（固件间歇性），{_SK_RETRY_INTERVAL}s 后重试...")
            time.sleep(_SK_RETRY_INTERVAL)
            continue
        if resp.status_code != 200:
            _log(f"SK HTTP {resp.status_code}")
            return False, None, resp.status_code
        try:
            data = resp.json()
            _log(f"SK 200 响应 code={data.get('code')} cmd={data.get('cmd_name')}")
            return True, data, resp.status_code
        except ValueError:
            _log("SK 200 但响应体非 JSON")
            return False, None, resp.status_code

    return False, None, None


# ──────────────────────────────────────────────
#  SK PTZ 内部封装
# ──────────────────────────────────────────────

def _get_camera(camera_name: str):
    """从 device_mgmt 获取 CameraConfig（含 sn_code，HTTP 鉴权必需）。"""
    from .device_mgmt import _find_camera
    return _find_camera(camera_name)


def _sk_ptz_get(cam) -> Optional[dict]:
    """查询 PTZ 参数（SK_SETTING_GET_PTZ）。

    成功返回规范化 dict（所有数值已通过 _safe_int/_safe_float 转换）；
    失败返回 None。兼容固件 position 嵌套格式与空串字段。
    """
    ok, data, status = _sk_http_query_ex(
        cam.ip, _SK_PTZ_PORT, "SK_SETTING_GET_PTZ", {},
        cam.sn_code, cam.username, cam.password, _SK_PTZ_TIMEOUT,
    )
    if not ok or not data:
        _log(f"SK GET_PTZ 失败 (status={status})")
        return None
    if data.get("code", "") != "C0000":
        _log(f"SK GET_PTZ 返回 code={data.get('code')} msg={data.get('msg')}")
        return None

    _log(f"SK GET_PTZ raw: {json.dumps(data, ensure_ascii=False)}")

    # 位置数据可能在顶层 (x, y) 或嵌套在 position 子对象
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
    """设置 PTZ（SK_SETTING_SET_PTZ）。返回 (success, error_message)。"""
    ok, data, status = _sk_http_query_ex(
        cam.ip, _SK_PTZ_PORT, "SK_SETTING_SET_PTZ", payload,
        cam.sn_code, cam.username, cam.password, _SK_PTZ_TIMEOUT,
    )
    if not ok or not data:
        return False, f"SK SET_PTZ 请求失败 (status={status})"
    if data.get("code", "") != "C0000":
        return False, f"SK SET_PTZ 返回 code={data.get('code')} msg={data.get('msg')}"
    _log(f"SK SET_PTZ ok: {payload}")
    return True, ""


# ──────────────────────────────────────────────
#  内部辅助
# ──────────────────────────────────────────────

def _resolve_direction(direction) -> Optional[PTZDirection]:
    """解析方向参数，支持 PTZDirection 枚举、英文字符串、中文字符串"""
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


# ──────────────────────────────────────────────
#  物理极限守护（Limit Guard）— 当前未使用
#  时间模式已回退为简单三段式（send → sleep → stop），
#  不再依赖 GET_PTZ 位置反馈。以下代码保留以备未来需要。
# ──────────────────────────────────────────────

# 方向 → (pan 位移符号, tilt 位移符号)
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

_GUARD_POLL_INTERVAL = 0.4     # 轮询间隔（秒）
_GUARD_STALL_POLLS = 2         # 连续 N 次无变化 → 判定停滞
_GUARD_EDGE_MARGIN = 1.0       # 距边界 < 1 刻度视为贴边
_GUARD_MOVE_EPS = 1e-3         # 位移检测阈值


def _query_ptz_position(cam) -> Optional[dict]:
    """查询当前云台位置（_sk_ptz_get 封装，失败返回 None）。"""
    return _sk_ptz_get(cam)


def _axis_at_limit(pos: float, rng: float, sign: int) -> bool:
    """判断单轴是否已贴住运动方向上的物理边界"""
    if sign == 0 or rng <= 0:
        return False
    if sign > 0:
        return pos >= rng - _GUARD_EDGE_MARGIN
    return pos <= _GUARD_EDGE_MARGIN


def _at_direction_limit(pos: dict, direction: PTZDirection) -> bool:
    """判断当前位置在指定方向上是否已无剩余行程。"""
    pan_sign, tilt_sign = _DIRECTION_SIGN.get(direction, (0, 0))
    pan_limited = _axis_at_limit(pos.get("x", 0), pos.get("x_range", 0), pan_sign) if pan_sign else True
    tilt_limited = _axis_at_limit(pos.get("y", 0), pos.get("y_range", 0), tilt_sign) if tilt_sign else True
    return pan_limited and tilt_limited


def _guarded_wait(
    cam,
    direction: PTZDirection,
    duration_seconds: float,
) -> tuple:
    """
    移动期间的守护等待：周期性轮询云台位置，检测到到达物理极限时提前停止。

    Returns:
        (actual_duration, limit_reached, final_pos)
    """
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


# ──────────────────────────────────────────────
#  公开工具函数（纯 SK 协议）
# ──────────────────────────────────────────────

def control_ptz(
    camera_name: str,
    direction: PTZDirection,
    speed: float = 0.5,
    duration_seconds: Optional[float] = None,
    degrees: Optional[float] = None,
) -> PTZMoveResult:
    """
    云台移动（SK 协议，三模式）。

    三种模式：
      - 时间模式：duration_seconds=N → 方向命令 + sleep(N) + stop
      - 角度模式：degrees=N → 按 1秒=34度 换算为时间，走三段式执行
      - 变焦模式：direction=zoom_in/zoom_out → SK zoom 命令 + sleep + stop

    对角方向（左上/左下/右上/右下）分步执行：先水平（左/右），再垂直（上/下），各占一半时长。

    Args:
        camera_name:      摄像头名称
        direction:        移动方向 (PTZDirection 枚举 / 英文 / 中文)
        speed:            速度系数 0.1-1.0（默认 0.5，当前 SK 方向命令不支持调速）
        duration_seconds: 转动时长（与 degrees 二选一）
        degrees:          转动角度（与 duration_seconds 二选一，按 1秒=34度换算为时间）

    Returns:
        PTZMoveResult
    """
    direction = _resolve_direction(direction)
    if not direction:
        return PTZMoveResult(
            success=False,
            error_message="无效方向，可用: up/down/left/right/upleft/upright/downleft/downright/zoom_in/zoom_out",
        )

    speed = max(0.1, min(1.0, speed))

    # ── 参数互斥校验 ──
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

    # ── 获取 CameraConfig ──
    cam = _get_camera(camera_name)
    if not cam:
        return PTZMoveResult(
            success=False,
            error_message=f"摄像头 '{camera_name}' 未注册，请先注册",
        )

    # ── zoom 模式 ──
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

    # ── 时间模式（简单三段式：send → sleep → stop，不依赖 GET_PTZ）──
    if degrees is None:
        dir_str = direction.value
        half = duration_seconds / 2.0

        if dir_str in _DIAGONAL_TO_AXES:
            # 对角方向分步执行：先水平（左/右），再垂直（上/下）
            h_axis, v_axis = _DIAGONAL_TO_AXES[dir_str]

            # Step 1: 水平方向（left / right）
            ok, err = _sk_ptz_set(cam, {"cmd": h_axis})
            if not ok:
                return PTZMoveResult(
                    success=False, protocol="sky_private",
                    error_message=f"水平方向({h_axis})移动启动失败: {err}",
                )
            time.sleep(half)
            _sk_ptz_set(cam, {"cmd": "stop", "action": h_axis})

            # Step 2: 垂直方向（up / down）
            ok, err = _sk_ptz_set(cam, {"cmd": v_axis})
            if not ok:
                return PTZMoveResult(
                    success=False, protocol="sky_private",
                    error_message=f"垂直方向({v_axis})移动启动失败: {err}",
                )
            time.sleep(half)
            _sk_ptz_set(cam, {"cmd": "stop", "action": v_axis})

        else:
            # 单轴方向：直接 send → sleep → stop
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

    # ── 角度模式（按 1 秒 = 34 度换算为时间，走三段式执行）──
    dir_str = direction.value
    duration_seconds = degrees / 34.0
    duration_seconds = max(0.1, min(10.0, duration_seconds))
    half = duration_seconds / 2.0

    if dir_str in _DIAGONAL_TO_AXES:
        # 对角方向分步执行：先水平（左/右），再垂直（上/下）
        h_axis, v_axis = _DIAGONAL_TO_AXES[dir_str]

        # Step 1: 水平方向
        ok, err = _sk_ptz_set(cam, {"cmd": h_axis})
        if not ok:
            return PTZMoveResult(
                success=False, protocol="sky_private", degrees=degrees,
                error_message=f"水平方向({h_axis})移动启动失败: {err}",
            )
        time.sleep(half)
        _sk_ptz_set(cam, {"cmd": "stop", "action": h_axis})

        # Step 2: 垂直方向
        ok, err = _sk_ptz_set(cam, {"cmd": v_axis})
        if not ok:
            return PTZMoveResult(
                success=False, protocol="sky_private", degrees=degrees,
                error_message=f"垂直方向({v_axis})移动启动失败: {err}",
            )
        time.sleep(half)
        _sk_ptz_set(cam, {"cmd": "stop", "action": v_axis})

    else:
        # 单轴方向
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
    """
    获取当前云台参数（SK_SETTING_GET_PTZ）。

    Args:
        camera_name: 摄像头名称

    Returns:
        PTZParameters
    """
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
    """
    云台校准与归位（SK 协议）。

    两种模式：
      - set_home: SK calibrate 固件校准 → GET_PTZ 读取坐标 → 存储为 Home 位
      - go_home:  已有 Home 位 → move(x,y) 精确归位；无 Home 位 → 先 calibrate

    Args:
        camera_name: 摄像头名称
        action:      "set_home"（校准并存位）/ "go_home"（回到存储的 Home 位）

    Returns:
        CalibrateResult
    """
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

    # ── set_home: calibrate + GET_PTZ + 存储 ──
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

    # ── go_home: move 到存储的 Home 位 ──
    if _calibrated_home is None:
        _log("go_home: 无存储的 Home 位，先执行 set_home 流程")
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
    """
    移动云台到指定绝对坐标（SK 协议 move 命令）。

    内部函数，不注册为 MCP 工具。
    """
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
    """
    停止云台所有移动（SK_SETTING_SET_PTZ stop）。

    Args:
        camera_name: 摄像头名称

    Returns:
        PTZMoveResult
    """
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
