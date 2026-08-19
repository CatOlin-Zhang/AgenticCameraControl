"""
Toolkit: 侦测追踪控制（协议 5.7/5.10/5.12 SK_SETTING_*_HUMANDETECT/VGRECTDETECT/OBJECTDETECT）

工具清单：
  - big_tracking_query     查询侦测能力清单 + 当前值（人形/车辆/区域三种）
  - big_tracking_set       开关侦测追踪功能（读-校验-合并-写-回读）
  - manage_tracking        统一侦测追踪管理入口（查询/设置）

传输通道：SK TCP HTTP（POST http://<ip>:9010/xiaopaitech/device_service，动态 Token 鉴权）

九条 SK 命令：
  人形侦测（5.7）:
    - SK_SETTING_GET_HUMANDETECT_OPTION  查询人形侦测能力
    - SK_SETTING_GET_HUMANDETECT         查询人形侦测当前参数
    - SK_SETTING_SET_HUMANDETECT         设置人形侦测参数
  车辆侦测（5.12）:
    - SK_SETTING_GET_OBJECTDETECT_OPTION  查询车辆侦测能力（需 object=vehicle）
    - SK_SETTING_GET_OBJECTDETECT         查询车辆侦测当前参数
    - SK_SETTING_SET_OBJECTDETECT         设置车辆侦测参数
  区域侦测（5.10）:
    - SK_SETTING_GET_VGRECTDETECT_OPTION  查询区域侦测能力
    - SK_SETTING_GET_VGRECTDETECT         查询区域侦测当前参数
    - SK_SETTING_SET_VGRECTDETECT         设置区域侦测参数

SET 命令是全量下发，设置前必须先 GET 读基线再合并，否则未传字段会被重置。
"""
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from .device_mgmt import resolve_target, CameraConfig
except ImportError:
    from device_mgmt import resolve_target, CameraConfig

# 复用 illumination 的 SK 协议底层基础设施
try:
    from .illumination import (
        _sk_http_query_ex,
        _sk_err,
        _sk_resolve_camera,
        _coerce_int,
        _merge_capabilities,
    )
except ImportError:
    from illumination import (
        _sk_http_query_ex,
        _sk_err,
        _sk_resolve_camera,
        _coerce_int,
        _merge_capabilities,
    )


# ──────────────────────────────────────────────
#  枚举与常量
# ──────────────────────────────────────────────

class TrackingAction(str, Enum):
    """侦测追踪管理操作类型"""
    QUERY = "get"
    SET = "set"


class DetectType(str, Enum):
    """侦测类型"""
    HUMAN = "human"
    VEHICLE = "vehicle"
    AREA = "area"
    ALL = "all"


# SK 协议常量
_SK_TRACKING_PORT = 9010
_SK_TRACKING_TIMEOUT = 3.0
_SK_OK_CODE = "C0000"

# 人形侦测命令（协议 5.7）
_SK_CMD_HUMAN_OPTION = "SK_SETTING_GET_HUMANDETECT_OPTION"
_SK_CMD_HUMAN_GET = "SK_SETTING_GET_HUMANDETECT"
_SK_CMD_HUMAN_SET = "SK_SETTING_SET_HUMANDETECT"

# 车辆侦测命令（协议 5.12）
_SK_CMD_VEHICLE_OPTION = "SK_SETTING_GET_OBJECTDETECT_OPTION"
_SK_CMD_VEHICLE_GET = "SK_SETTING_GET_OBJECTDETECT"
_SK_CMD_VEHICLE_SET = "SK_SETTING_SET_OBJECTDETECT"

# 区域侦测命令（协议 5.10）
_SK_CMD_AREA_OPTION = "SK_SETTING_GET_VGRECTDETECT_OPTION"
_SK_CMD_AREA_GET = "SK_SETTING_GET_VGRECTDETECT"
_SK_CMD_AREA_SET = "SK_SETTING_SET_VGRECTDETECT"

# 中文标签（协议字段 → 中文）
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
    # 区域侦测专有
    "x0": "界线起点X", "y0": "界线起点Y",
    "x1": "界线终点X", "y1": "界线终点Y",
    "x2": "方向起点X", "y2": "方向起点Y",
    "x3": "方向终点X", "y3": "方向终点Y",
    "dir": "检测方向",
    "enter_alarm_enable": "进入报警",
    "enter_alarm_type": "进入报警类型",
    "leave_alarm_enable": "离开报警",
    "leave_alarm_type": "离开报警类型",
}

# 多档位枚举的档位说明
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
    "indoor": {0: "室外模式", 1: "室内模式", 2: "室外人车"},
    "level": {0: "关闭", 1: "低", 2: "中", 3: "高"},
    "dir": {0: "进入区域", 1: "离开区域", 2: "双向"},
}


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class TrackingQueryResult:
    """侦测追踪查询结果"""
    ok: bool
    camera: str = ""
    channel: str = "sk"
    human_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    vehicle_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    area_capabilities: List[Dict[str, Any]] = field(default_factory=list)
    human_current: Dict[str, Any] = field(default_factory=dict)
    vehicle_current: Dict[str, Any] = field(default_factory=dict)
    area_current: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: List[str] = field(default_factory=list)


@dataclass
class TrackingSetResult:
    """侦测追踪设置结果"""
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


# ──────────────────────────────────────────────
#  日志
# ──────────────────────────────────────────────

_TRACK_DEBUG = os.environ.get("TRACK_DEBUG", "1") == "1"


def _log(*args) -> None:
    if _TRACK_DEBUG:
        print("[tracking]", *args, file=sys.stderr)


# ──────────────────────────────────────────────
#  SK 协议底层通信
# ──────────────────────────────────────────────

_RESP_HEAD = {"service_type", "msg_id", "cmd_name", "ver", "code", "msg",
              "channel", "sequence"}


# ── 人形侦测（协议 5.7）──

def _sk_human_option(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_HUMANDETECT_OPTION"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_HUMAN_OPTION, {},
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查人形侦测能力失败（status={status}）")
        return {"ok": False, "status": status}
    caps = resp.get("humandetect")
    _ok = resp.get("code") == _SK_OK_CODE and isinstance(caps, list)
    if _ok:
        _log(f"SK 人形侦测能力 {len(caps)} 项: "
             f"{[c.get('name') for c in caps if isinstance(c, dict)]}")
    else:
        _log(f"SK 人形侦测能力响应异常 code={resp.get('code')}")
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}


def _sk_human_cur(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_HUMANDETECT"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_HUMAN_GET, {},
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查人形侦测当前值失败（status={status}）")
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 人形侦测当前值 code={resp.get('code')}: "
         f"{current if _ok else '（code 非 C0000）'}")
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}


def _sk_human_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    """SK_SETTING_SET_HUMANDETECT"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_HUMAN_SET, payload,
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 人形侦测设置失败（status={status}）")
        return {"ok": False, "status": status}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 人形侦测设置 code={resp.get('code')}")
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}


# ── 车辆侦测（协议 5.12，需 object=vehicle）──

def _sk_vehicle_option(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_OBJECTDETECT_OPTION + object=vehicle"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_VEHICLE_OPTION,
        {"object": "vehicle"},
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查车辆侦测能力失败（status={status}）")
        return {"ok": False, "status": status}
    caps = resp.get("objectdetect")
    _ok = resp.get("code") == _SK_OK_CODE and isinstance(caps, list)
    if _ok:
        _log(f"SK 车辆侦测能力 {len(caps)} 项: "
             f"{[c.get('name') for c in caps if isinstance(c, dict)]}")
    else:
        _log(f"SK 车辆侦测能力响应异常 code={resp.get('code')}")
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}


def _sk_vehicle_cur(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_OBJECTDETECT + object=vehicle"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_VEHICLE_GET,
        {"object": "vehicle"},
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查车辆侦测当前值失败（status={status}）")
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 车辆侦测当前值 code={resp.get('code')}: "
         f"{current if _ok else '（code 非 C0000）'}")
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}


def _sk_vehicle_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    """SK_SETTING_SET_OBJECTDETECT + object=vehicle"""
    merged = {"object": "vehicle"}
    merged.update(payload)
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_VEHICLE_SET, merged,
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 车辆侦测设置失败（status={status}）")
        return {"ok": False, "status": status}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 车辆侦测设置 code={resp.get('code')}")
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}


# ── 区域侦测（协议 5.10）──

def _sk_area_option(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_VGRECTDETECT_OPTION"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_AREA_OPTION, {},
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查区域侦测能力失败（status={status}）")
        return {"ok": False, "status": status}
    caps = resp.get("vgrectdetect")
    _ok = resp.get("code") == _SK_OK_CODE and isinstance(caps, list)
    if _ok:
        _log(f"SK 区域侦测能力 {len(caps)} 项: "
             f"{[c.get('name') for c in caps if isinstance(c, dict)]}")
    else:
        _log(f"SK 区域侦测能力响应异常 code={resp.get('code')}")
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": status, "raw": resp}


def _sk_area_cur(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_VGRECTDETECT"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_AREA_GET, {},
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查区域侦测当前值失败（status={status}）")
        return {"ok": False, "status": status}
    current = {k: v for k, v in resp.items() if k not in _RESP_HEAD}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 区域侦测当前值 code={resp.get('code')}: "
         f"{current if _ok else '（code 非 C0000）'}")
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": status, "raw": resp}


def _sk_area_set(cam, payload: Dict[str, Any]) -> Dict[str, Any]:
    """SK_SETTING_SET_VGRECTDETECT"""
    ok, resp, status = _sk_http_query_ex(
        cam.ip, _SK_TRACKING_PORT, _SK_CMD_AREA_SET, payload,
        cam.sn_code, cam.username, cam.password, _SK_TRACKING_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 区域侦测设置失败（status={status}）")
        return {"ok": False, "status": status}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 区域侦测设置 code={resp.get('code')}")
    return {"ok": _ok, "code": resp.get("code", ""), "msg": resp.get("msg", ""),
            "status": status, "raw": resp}


# ──────────────────────────────────────────────
#  编排入口
# ──────────────────────────────────────────────

def big_tracking_query(
    name: Optional[str] = None,
    detect_type: str = "all",
    answers: Optional[Dict[str, Any]] = None,
) -> TrackingQueryResult:
    """
    查询 IPC 侦测追踪能力 + 当前值（人形/车辆/区域三种，协议 5.7/5.12/5.10）。

    SK 私有协议（动态 Token 鉴权），返回三种侦测的能力与完整当前值。
    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:        摄像头名称（None 时走 resolve_target 降级：唯一一台直接用）
        detect_type: 查询类型 human/vehicle/area/all
        answers:     NEEDS_INPUT 重调时的回答 dict

    Returns:
        TrackingQueryResult:
            ok=True:  human/vehicle/area_capabilities + current
            ok=False: error_code + message + hint
    """
    err, cam = _sk_resolve_camera(name, answers, TrackingQueryResult)
    if err:
        _log(f"侦测查询终止：resolve_target 失败 error_code={err.error_code}")
        return err

    _log(f"===== 侦测查询开始 camera={cam.name} ip={cam.ip} type={detect_type} =====")
    dt = detect_type.lower() if detect_type else "all"

    result = TrackingQueryResult(ok=True, camera=cam.name, channel="sk")

    # ── 人形侦测 ──
    if dt in ("all", "human"):
        opt = _sk_human_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
            _log(f"人形侦测能力查询失败，跳过（code={opt.get('code')}）")
        else:
            cur = _sk_human_cur(cam)
            if not cur["ok"]:
                _log(f"人形侦测当前值查询失败，跳过（code={cur.get('code')}）")
            else:
                result.human_capabilities = _merge_capabilities(
                    opt["capabilities"], cur["current"],
                    _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                result.human_current = cur["current"]

    # ── 车辆侦测 ──
    if dt in ("all", "vehicle"):
        opt = _sk_vehicle_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
            _log(f"车辆侦测能力查询失败，跳过（code={opt.get('code')}）")
        else:
            cur = _sk_vehicle_cur(cam)
            if not cur["ok"]:
                _log(f"车辆侦测当前值查询失败，跳过（code={cur.get('code')}）")
            else:
                result.vehicle_capabilities = _merge_capabilities(
                    opt["capabilities"], cur["current"],
                    _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                result.vehicle_current = cur["current"]

    # ── 区域侦测 ──
    if dt in ("all", "area"):
        opt = _sk_area_option(cam)
        if not opt["ok"]:
            if opt.get("status") is None:
                return _sk_err(TrackingQueryResult, "DEVICE_UNREACHABLE",
                                 f"无法连接 {cam.ip}:{_SK_TRACKING_PORT}（SK HTTP 无响应）",
                                 "确认摄像头在线、网络可达", camera=cam.name)
            _log(f"区域侦测能力查询失败，跳过（code={opt.get('code')}）")
        else:
            cur = _sk_area_cur(cam)
            if not cur["ok"]:
                _log(f"区域侦测当前值查询失败，跳过（code={cur.get('code')}）")
            else:
                result.area_capabilities = _merge_capabilities(
                    opt["capabilities"], cur["current"],
                    _TRACKING_LABELS, _TRACKING_VALUE_TEXTS)
                result.area_current = cur["current"]

    result.message = (f"侦测查询完成: "
                      f"人形={len(result.human_capabilities)}项, "
                      f"车辆={len(result.vehicle_capabilities)}项, "
                      f"区域={len(result.area_capabilities)}项")
    _log(f"===== 侦测查询结束 ok={result.ok} {result.message} =====")
    return result


def big_tracking_set(
    name: Optional[str] = None,
    detect_type: str = "human",
    enable: Optional[bool] = None,
    tracking: Optional[bool] = None,
    sensitivity_level: Optional[int] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> TrackingSetResult:
    """
    开关 IPC 侦测追踪功能（协议 5.7/5.12/5.10，读-校验-合并-写-回读）。

    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:             摄像头名称
        detect_type:      侦测类型 human/vehicle/area
        enable:           是否开启该侦测功能（True/False → 1/0）
        tracking:         是否开启追踪（仅 human/vehicle 有效，True/False → 1/0）
        sensitivity_level: 灵敏度等级 0-3（0关闭/1低/2中/3高）
        answers:          NEEDS_INPUT 重调时的回答 dict

    Returns:
        TrackingSetResult:
            ok=True:  updated 生效字段；current 完整当前值
            ok=False: error_code + message + hint
    """
    # 构建更新字典
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
        _log(f"侦测设置终止：resolve_target 失败 error_code={err.error_code}")
        return err

    dt = detect_type.lower() if detect_type else "human"
    if dt not in ("human", "vehicle", "area"):
        return _sk_err(TrackingSetResult, "INVALID_DETECT_TYPE",
                       f"不支持的侦测类型：{detect_type}",
                       "支持: human(人形追踪)/vehicle(车辆追踪)/area(区域检测)")

    # 区域侦测不支持 tracking 字段
    if dt == "area" and tracking is not None:
        _log("区域侦测不支持 tracking 字段，已忽略")
        updates.pop("tracking", None)

    _log(f"===== 侦测设置开始 camera={cam.name} ip={cam.ip} "
         f"type={dt} updates={updates} =====")

    # 选择对应的底层函数组
    if dt == "human":
        option_fn, cur_fn, set_fn = _sk_human_option, _sk_human_cur, _sk_human_set
    elif dt == "vehicle":
        option_fn, cur_fn, set_fn = _sk_vehicle_option, _sk_vehicle_cur, _sk_vehicle_set
    else:
        option_fn, cur_fn, set_fn = _sk_area_option, _sk_area_cur, _sk_area_set

    # 1. 查能力 → 客户端校验
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

    # 2. 读基线（SET 是全量下发）
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
    _log(f"SK {dt}侦测下发全量 payload keys={list(payload)}")

    # 3. 全量下发
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

    # 4. 回读确认
    rb = cur_fn(cam)
    cur = rb["current"] if rb["ok"] else dict(payload)
    updated = {k: cur[k] for k in updates if k in cur}
    _log(f"SK {dt}侦测回读确认 updated={updated}")

    type_names = {"human": "人形追踪", "vehicle": "车辆追踪", "area": "区域检测"}
    return TrackingSetResult(
        ok=True, camera=cam.name, channel="sk", detect_type=dt,
        updated=updated, current=cur,
        message=f"{type_names.get(dt, dt)}参数已生效：{updated}")


# ──────────────────────────────────────────────
#  高级封装：manage_tracking
# ──────────────────────────────────────────────

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
    """
    统一侦测追踪管理入口：根据 action 分发到查询或设置。

    Args:
        action:           操作类型 (TrackingAction: get / set)
        camera_name:      摄像头名称（MCP 层传入，优先使用）
        name:             摄像头名称（内部调用兼容）
        detect_type:      侦测类型 human/vehicle/area/all（查询）或 human/vehicle/area（设置）
        enable:           是否开启该侦测功能（仅 SET）
        tracking:         是否开启追踪（仅 SET，human/vehicle 有效）
        sensitivity_level: 灵敏度等级 0-3（仅 SET）
        answers:          NEEDS_INPUT 重调时的回答 dict

    Returns:
        TrackingQueryResult (action=get) 或 TrackingSetResult (action=set)
    """
    resolved_name = camera_name or name
    dt = detect_type or "all"

    if action == TrackingAction.QUERY:
        return big_tracking_query(name=resolved_name, detect_type=dt, answers=answers)
    elif action == TrackingAction.SET:
        # MCP 层可能传整数 0/1 而非 bool，统一归并
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
