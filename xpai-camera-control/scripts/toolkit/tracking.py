from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from . import sk_proto
except ImportError:
    import sk_proto

try:
    from .device_mgmt import resolve_target, CameraConfig
except ImportError:
    from device_mgmt import resolve_target, CameraConfig

try:
    from .illumination import (
        _envelope,
        _sk_err,
        _sk_resolve_camera,
        _coerce_int,
        _merge_capabilities,
    )
except ImportError:
    from illumination import (
        _envelope,
        _sk_err,
        _sk_resolve_camera,
        _coerce_int,
        _merge_capabilities,
    )

class TrackingAction(str, Enum):
    QUERY = "get"
    SET = "set"

class DetectType(str, Enum):
    HUMAN = "human"
    VEHICLE = "vehicle"
    AREA = "area"
    MOTION = "motion"
    LINE = "line"
    ALL = "all"

_SK_TRACKING_PORT = 9010
_SK_TRACKING_TIMEOUT = 3.0

_SETTABLE_FIELDS = {"enable", "tracking", "level"}

_TRACKING_LABELS = {
    "enable": "使能开关",
    "tracking": "追踪",
    "indoor": "场景模式",
    "thresh": "灵敏度",
    "level": "灵敏度等级",
    "screenenable": "目标标记",
    "blink": "框闪烁",
    "alarm_enable": "声音报警",
    "alarm_type": "报警类型",
    "white_light": "白光报警",
    "duration": "白光时长",
    "timestrategy": "侦测时间",
    "humandistance": "人形大小",
    "drag": "目标标记显示",
    "mbdesc": "侦测区域",
    "distance": "目标大小",
    "object": "目标类型",
    "trigger": "触发目标",
    "idenable": "车牌检测",

    "x0": "界线起点X", "y0": "界线起点Y",
    "x1": "界线终点X", "y1": "界线终点Y",
    "x2": "方向起点X", "y2": "方向起点Y",
    "x3": "方向终点X", "y3": "方向终点Y",
    "dir": "检测方向",
    "enter_alarm_enable": "进入报警",
    "enter_alarm_type": "进入报警类型",
    "leave_alarm_enable": "离开报警",
    "leave_alarm_type": "离开报警类型",

    "dx0": "方向起点X(A点)", "dy0": "方向起点Y(A点)",
    "dx1": "方向终点X(B点)", "dy1": "方向终点Y(B点)",
    "AtoB_alarm_enable": "A到B报警",
    "AtoB_alarm_type": "A到B报警类型",
    "BtoA_alarm_enable": "B到A报警",
    "BtoA_alarm_type": "B到A报警类型",
}

_TRACKING_VALUE_TEXTS = {
    "enable": {0: "关闭", 1: "打开"},
    "tracking": {0: "关闭", 1: "打开"},
    "screenenable": {0: "关闭", 1: "打开"},
    "blink": {0: "关闭", 1: "闪烁"},
    "drag": {0: "不显示", 1: "显示"},
    "alarm_enable": {0: "关闭", 1: "打开"},
    "white_light": {0: "关闭", 1: "打开"},
    "idenable": {0: "关闭", 1: "打开"},
    "enter_alarm_enable": {0: "关闭", 1: "打开"},
    "leave_alarm_enable": {0: "关闭", 1: "打开"},
    "AtoB_alarm_enable": {0: "关闭", 1: "打开"},
    "BtoA_alarm_enable": {0: "关闭", 1: "打开"},
    "indoor": {0: "室外模式", 1: "室内模式", 2: "室外人车"},
    "level": {0: "关闭", 1: "低", 2: "中", 3: "高"},
    "dir": {0: "进入区域", 1: "离开区域", 2: "双向"},
}

@dataclass
class TrackingQueryResult:
    ok: bool
    camera: str = ""
    channel: str = "sk"
    human_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    vehicle_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    area_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    motion_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    line_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    human_current: Dict[str, Any] = field(default_factory=dict)
    vehicle_current: Dict[str, Any] = field(default_factory=dict)
    area_current: Dict[str, Any] = field(default_factory=dict)
    motion_current: Dict[str, Any] = field(default_factory=dict)
    line_current: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: List[str] = field(default_factory=list)

@dataclass
class TrackingSetResult:
    ok: bool
    camera: str = ""
    channel: str = "sk"
    detect_type: str = ""
    updated: Dict[str, Any] = field(default_factory=dict)
    current: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error_code: str = ""
    hint: str = ""
    needs_input: List[str] = field(default_factory=list)

_RESP_HEAD = {"service_type", "msg_id", "cmd_name", "ver", "code", "msg",
              "channel", "sequence"}

def _sk_human_option(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get_option(
        sk_proto.DETECT_HUMAN, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    caps = resp.get("humandetect")
    _ok = sk_proto.code_ok(resp.get("code", "")) and isinstance(caps, list)
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_human_cur(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get(
        sk_proto.DETECT_HUMAN, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_human_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_set(
        sk_proto.DETECT_HUMAN, cam.ip, cam.sn_code, cam.username, cam.password,
        payload, _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}

def _sk_vehicle_option(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get_option(
        sk_proto.DETECT_VEHICLE, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    caps = resp.get("objectdetect")
    _ok = sk_proto.code_ok(resp.get("code", "")) and isinstance(caps, list)
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_vehicle_cur(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get(
        sk_proto.DETECT_VEHICLE, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_vehicle_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_set(
        sk_proto.DETECT_VEHICLE, cam.ip, cam.sn_code, cam.username, cam.password,
        payload, _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}

def _sk_area_option(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get_option(
        sk_proto.DETECT_REGION, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    caps = resp.get("vgrectdetect")
    _ok = sk_proto.code_ok(resp.get("code", "")) and isinstance(caps, list)
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_area_cur(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get(
        sk_proto.DETECT_REGION, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_area_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_set(
        sk_proto.DETECT_REGION, cam.ip, cam.sn_code, cam.username, cam.password,
        payload, _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}

def _sk_motion_option(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get_option(
        sk_proto.DETECT_MOTION, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    caps = resp.get("motiondetect")
    _ok = sk_proto.code_ok(resp.get("code", "")) and isinstance(caps, list)
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_motion_cur(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get(
        sk_proto.DETECT_MOTION, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_motion_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_set(
        sk_proto.DETECT_MOTION, cam.ip, cam.sn_code, cam.username, cam.password,
        payload, _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}

def _sk_line_option(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get_option(
        sk_proto.DETECT_LINE, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    caps = resp.get("vglinedetect")
    _ok = sk_proto.code_ok(resp.get("code", "")) and isinstance(caps, list)
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_line_cur(cam) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_get(
        sk_proto.DETECT_LINE, cam.ip, cam.sn_code, cam.username, cam.password,
        _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}

def _sk_line_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    ok, resp, status = _envelope(sk_proto.detect_set(
        sk_proto.DETECT_LINE, cam.ip, cam.sn_code, cam.username, cam.password,
        payload, _SK_TRACKING_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": status}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}

def big_tracking_query(
    name: Optional[str] = None,
    detect_type: str = "all",
    answers: Optional[Dict[str, Any]] = None,
) -> TrackingQueryResult:
    err, cam = _sk_resolve_camera(name, answers, TrackingQueryResult)
    if err:
        return err

    dt = detect_type.lower() if detect_type else "all"

    result = TrackingQueryResult(ok=True, camera=cam.name, channel="sk")

    if dt in ("all", "human"):
        opt = _sk_human_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
        else:
            cur = _sk_human_cur(cam)
            if cur["ok"]:
                result.human_capabilities = [
                    c for c in _merge_capabilities(
                        opt["capabilities"], cur["current"],
                        _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                    if c.get("name") in _SETTABLE_FIELDS]
                result.human_current = {
                    k: v for k, v in cur["current"].items() if k in _SETTABLE_FIELDS}

    if dt in ("all", "vehicle"):
        opt = _sk_vehicle_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
        else:
            cur = _sk_vehicle_cur(cam)
            if cur["ok"]:
                result.vehicle_capabilities = [
                    c for c in _merge_capabilities(
                        opt["capabilities"], cur["current"],
                        _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                    if c.get("name") in _SETTABLE_FIELDS]
                result.vehicle_current = {
                    k: v for k, v in cur["current"].items() if k in _SETTABLE_FIELDS}

    if dt in ("all", "area"):
        opt = _sk_area_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
        else:
            cur = _sk_area_cur(cam)
            if cur["ok"]:
                result.area_capabilities = [
                    c for c in _merge_capabilities(
                        opt["capabilities"], cur["current"],
                        _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                    if c.get("name") in _SETTABLE_FIELDS]
                result.area_current = {
                    k: v for k, v in cur["current"].items() if k in _SETTABLE_FIELDS}

    if dt in ("all", "motion"):
        opt = _sk_motion_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
        else:
            cur = _sk_motion_cur(cam)
            if cur["ok"]:
                result.motion_capabilities = [
                    c for c in _merge_capabilities(
                        opt["capabilities"], cur["current"],
                        _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                    if c.get("name") in _SETTABLE_FIELDS]
                result.motion_current = {
                    k: v for k, v in cur["current"].items() if k in _SETTABLE_FIELDS}

    if dt in ("all", "line"):
        opt = _sk_line_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
        else:
            cur = _sk_line_cur(cam)
            if cur["ok"]:
                result.line_capabilities = [
                    c for c in _merge_capabilities(
                        opt["capabilities"], cur["current"],
                        _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                    if c.get("name") in _SETTABLE_FIELDS]
                result.line_current = {
                    k: v for k, v in cur["current"].items() if k in _SETTABLE_FIELDS}

    result.message = (f"侦测查询完成: "
                      f"人形={len(result.human_capabilities)}项, "
                      f"车辆={len(result.vehicle_capabilities)}项, "
                      f"区域={len(result.area_capabilities)}项, "
                      f"移动={len(result.motion_capabilities)}项, "
                      f"越界={len(result.line_capabilities)}项")
    return result

def big_tracking_set(
    name: Optional[str] = None,
    detect_type: str = "human",
    enable: Optional[bool] = None,
    tracking: Optional[bool] = None,
    sensitivity_level: Optional[int] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> TrackingSetResult:

    updates: Dict[str, Any] = {}
    if enable is not None:
        updates["enable"] = 1 if enable else 0
    if tracking is not None:
        updates["tracking"] = 1 if tracking else 0
    if sensitivity_level is not None:
        updates["level"] = sensitivity_level
    if not updates:
        return _sk_err(TrackingSetResult, "NO_PARAMS",
                       "未传入任何要修改的参数",
                       "至少传 enable 或 tracking 参数；可先调 big_tracking_query 查看可设置项")

    err, cam = _sk_resolve_camera(name, answers, TrackingSetResult)
    if err:
        return err

    dt = detect_type.lower() if detect_type else "human"
    if dt not in ("human", "vehicle", "area", "motion", "line"):
        return _sk_err(TrackingSetResult, "INVALID_DETECT_TYPE",
                       f"不支持的侦测类型：{detect_type}",
                       "支持: human(人形追踪)/vehicle(车辆追踪)/area(区域检测)/motion(移动侦测)/line(越界侦测)")

    if dt in ("area", "line") and tracking is not None:
        updates.pop("tracking", None)

    if dt == "human":
        option_fn, cur_fn, set_fn = _sk_human_option, _sk_human_cur, _sk_human_set
    elif dt == "vehicle":
        option_fn, cur_fn, set_fn = _sk_vehicle_option, _sk_vehicle_cur, _sk_vehicle_set
    elif dt == "area":
        option_fn, cur_fn, set_fn = _sk_area_option, _sk_area_cur, _sk_area_set
    elif dt == "motion":
        option_fn, cur_fn, set_fn = _sk_motion_option, _sk_motion_cur, _sk_motion_set
    else:
        option_fn, cur_fn, set_fn = _sk_line_option, _sk_line_cur, _sk_line_set

    opt = option_fn(cam)
    if not opt["ok"]:
        if opt.get("status") is None:
            return _sk_err(TrackingSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                           camera=cam.name)
        return _sk_err(TrackingSetResult, "OPTION_QUERY_FAILED",
                       f"查询{dt}侦测能力失败（code={opt.get('code') or '404'}）",
                       camera=cam.name)
    cap_map: Dict[str, dict] = {}
    for item in opt["capabilities"]:
        if isinstance(item, dict) and item.get("name"):
            cap_map[str(item["name"])] = item

    for k, v in updates.items():
        item = cap_map.get(k)
        if item is None:
            return _sk_err(TrackingSetResult, "PARAM_NOT_SUPPORTED",
                           f"该摄像头不支持{dt}侦测参数 {k}",
                           f"支持的参数：{', '.join(sorted(cap_map)) or '无'}",
                           camera=cam.name)
        specs = item.get("specs") or {}
        lo, hi = _coerce_int(specs.get("min")), _coerce_int(specs.get("max"))
        if lo is not None and hi is not None and not (lo <= v <= hi):
            return _sk_err(TrackingSetResult, "PARAM_OUT_OF_RANGE",
                           f"{k}={v} 超出允许范围 {lo}-{hi}", camera=cam.name)

    base = cur_fn(cam)
    if not base["ok"]:
        if base.get("status") is None:
            return _sk_err(TrackingSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                           camera=cam.name)
        return _sk_err(TrackingSetResult, "CURRENT_QUERY_FAILED",
                       f"查询{dt}侦测当前值失败（code={base.get('code')}）",
                       camera=cam.name)

    payload = dict(base["current"])
    payload.update(updates)

    set_result = set_fn(cam, payload)
    if not set_result["ok"]:
        if set_result.get("status") is None:
            return _sk_err(TrackingSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                           camera=cam.name)
        return _sk_err(TrackingSetResult, "SET_FAILED",
                       f"{dt}侦测设置命令失败（code={set_result.get('code')} "
                       f"msg={set_result.get('msg')}）",
                       camera=cam.name)

    rb = cur_fn(cam)
    full_cur = rb["current"] if rb["ok"] else dict(payload)
    cur = {k: full_cur[k] for k in _SETTABLE_FIELDS if k in full_cur}
    updated = {k: cur[k] for k in updates if k in cur}

    type_names = {"human": "人形追踪", "vehicle": "车辆追踪", "area": "区域检测",
                  "motion": "移动侦测", "line": "越界侦测"}
    return TrackingSetResult(
        ok=True, camera=cam.name, channel="sk", detect_type=dt,
        updated=updated, current=cur,
        message=f"{type_names.get(dt, dt)}参数已生效：{updated}")

def manage_tracking(
    action: TrackingAction = TrackingAction.QUERY,
    camera_name: Optional[str] = None,
    name: Optional[str] = None,
    detect_type: Optional[str] = None,
    enable: Optional[bool] = None,
    tracking: Optional[bool] = None,
    sensitivity_level: Optional[int] = None,
    answers: Optional[Dict[str, Any]] = None,
):
    resolved_name = camera_name or name
    dt = detect_type or "all"

    if action == TrackingAction.QUERY:
        return big_tracking_query(name=resolved_name, detect_type=dt, answers=answers)
    elif action == TrackingAction.SET:

        if isinstance(enable, int) and not isinstance(enable, bool):
            enable = bool(enable)
        if isinstance(tracking, int) and not isinstance(tracking, bool):
            tracking = bool(tracking)
        return big_tracking_set(
            name=resolved_name, detect_type=dt,
            enable=enable, tracking=tracking,
            sensitivity_level=sensitivity_level, answers=answers)
    else:
        return TrackingSetResult(ok=False, error_code="INVALID_ACTION",
                                 message=f"不支持的操作：{action}")
