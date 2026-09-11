from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

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

class ImageAction(str, Enum):
    QUERY = "get"
    SET = "set"

_SK_IMAGE_PORT = 9010
_SK_IMAGE_TIMEOUT = 3.0

_SK_IMAGE_SUPPORTED = ("brightness", "contrast", "saturation", "sharpness", "flip")

_SK_IMAGE_LABELS = {
    "brightness": "亮度",
    "contrast": "对比度",
    "saturation": "饱和度",
    "sharpness": "锐度",
    "flip": "图像翻转",
}

_SK_IMAGE_VALUE_TEXTS = {
    "flip": {0: "正常", 1: "对角翻转", 2: "水平翻转", 3: "垂直翻转"},
}

@dataclass
class ImageQueryResult:
    ok: bool
    camera: str = ""
    channel: str = ""
    capabilities: list = field(default_factory=list)
    current: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: list = field(default_factory=list)

@dataclass
class ImageSetResult:
    ok: bool
    camera: str = ""
    channel: str = ""
    updated: Dict[str, Any] = field(default_factory=dict)
    current: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: list = field(default_factory=list)

def _sk_query_option(cam) -> Dict[str, Any]:
    ok, resp, _status = _envelope(sk_proto.image_get_option(
        cam.ip, cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": _status}
    caps = resp.get("image")
    _ok = sk_proto.code_ok(resp.get("code", "")) and isinstance(caps, list)
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": _status, "raw": resp}

def _sk_query_current(cam) -> Dict[str, Any]:
    ok, resp, _status = _envelope(sk_proto.image_get(
        cam.ip, cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT))
    if not ok or not resp:
        return {"ok": False, "status": _status}
    _head = {"service_type", "msg_id", "cmd_name", "ver", "code", "msg", "channel", "sequence"}
    current = {k: v for k, v in resp.items() if k not in _head}
    _ok = sk_proto.code_ok(resp.get("code", ""))
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": _status, "raw": resp}

def _sk_set(cam, updates: Dict[str, Any]) -> ImageSetResult:

    opt = _sk_query_option(cam)
    if not opt["ok"]:
        if opt.get("status") is None:
            return _sk_err(ImageSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_IMAGE_PORT}（SK HTTP 无响应）", camera=cam.name)
        return _sk_err(ImageSetResult, "OPTION_QUERY_FAILED",
                       f"查询图像能力失败（code={opt.get('code') or '404'}）", camera=cam.name)

    cap_map: Dict[str, dict] = {}
    for item in opt["capabilities"]:
        if isinstance(item, dict) and item.get("name"):
            cap_map[str(item["name"])] = item
    for k, v in updates.items():
        item = cap_map.get(k)
        if item is None:
            return _sk_err(ImageSetResult, "PARAM_NOT_SUPPORTED",
                           f"该摄像头不支持图像参数 {k}",
                           f"支持的参数：{', '.join(sorted(cap_map)) or '无'}", camera=cam.name)
        specs = item.get("specs") or {}
        lo, hi = _coerce_int(specs.get("min")), _coerce_int(specs.get("max"))
        if lo is not None and hi is not None and not (lo <= v <= hi):
            return _sk_err(ImageSetResult, "PARAM_OUT_OF_RANGE",
                           f"{k}={v} 超出允许范围 {lo}-{hi}", camera=cam.name)

    base = _sk_query_current(cam)
    if not base["ok"]:
        if base.get("status") is None:
            return _sk_err(ImageSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_IMAGE_PORT}（SK HTTP 无响应）", camera=cam.name)
        return _sk_err(ImageSetResult, "CURRENT_QUERY_FAILED",
                       f"查询图像当前值失败（code={base['code']}）", camera=cam.name)
    payload = dict(base["current"])
    payload.update(updates)

    ok, resp, _status = _envelope(sk_proto.image_set(
        cam.ip, cam.sn_code, cam.username, cam.password, payload, _SK_IMAGE_TIMEOUT))
    if not ok or not resp:
        return _sk_err(ImageSetResult, "DEVICE_UNREACHABLE" if _status is None else "SET_FAILED",
                       f"设置命令下发失败：{cam.ip}:{_SK_IMAGE_PORT}"
                       + ("" if _status is None else f"（HTTP {_status}）"), camera=cam.name)
    if not sk_proto.code_ok(resp.get("code", "")):
        return _sk_err(ImageSetResult, "SET_FAILED",
                       f"设备拒绝设置（code={resp.get('code')} msg={resp.get('msg')}）", camera=cam.name)

    rb = _sk_query_current(cam)
    cur = rb["current"] if rb["ok"] else dict(payload)
    cur = {k: v for k, v in cur.items() if k in _SK_IMAGE_SUPPORTED}
    updated = {k: cur[k] for k in updates if k in cur}
    return ImageSetResult(ok=True, camera=cam.name, channel="sk", updated=updated, current=cur,
                          message=f"图像参数已生效：{updated}")

def _query_cam(cam) -> ImageQueryResult:
    opt = _sk_query_option(cam)
    if not opt["ok"]:
        if opt.get("status") is None:
            return _sk_err(ImageQueryResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_IMAGE_PORT}（SK HTTP 无响应）",
                           "确认摄像头在线、网络可达，且已注册正确凭据", camera=cam.name)
        return _sk_err(ImageQueryResult, "OPTION_QUERY_FAILED",
                       f"查询图像能力失败（code={opt.get('code') or '404'}）",
                       "确认设备固件版本是否支持图像设置", camera=cam.name)
    cur = _sk_query_current(cam)
    if not cur["ok"]:
        return _sk_err(ImageQueryResult, "CURRENT_QUERY_FAILED",
                       f"查询图像当前值失败（code={cur['code']}）", camera=cam.name)

    caps = [c for c in opt["capabilities"]
            if isinstance(c, dict) and str(c.get("name", "")) in _SK_IMAGE_SUPPORTED]
    current = {k: v for k, v in cur["current"].items() if k in _SK_IMAGE_SUPPORTED}
    return ImageQueryResult(
        ok=True, camera=cam.name, channel="sk",
        capabilities=_merge_capabilities(caps, current,
                                         _SK_IMAGE_LABELS, _SK_IMAGE_VALUE_TEXTS),
        current=current,
    )

def _set_cam(cam, updates: Dict[str, Any]) -> ImageSetResult:
    return _sk_set(cam, updates)

def big_image_query(
    name: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> ImageQueryResult:
    err, cam = _sk_resolve_camera(name, answers, ImageQueryResult)
    if err:
        return err
    result = _query_cam(cam)
    return result

def big_image_set(
    name: Optional[str] = None,
    brightness: Optional[int] = None,
    contrast: Optional[int] = None,
    saturation: Optional[int] = None,
    sharpness: Optional[int] = None,
    flip: Optional[int] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> ImageSetResult:
    updates: Dict[str, Any] = {}
    for k, v in (("brightness", brightness), ("contrast", contrast),
                 ("saturation", saturation), ("sharpness", sharpness),
                 ("flip", flip)):
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, int):
                return _sk_err(ImageSetResult, "INVALID_PARAM_TYPE", f"{k} 需要整数，收到 {v!r}")
            updates[k] = v
    if not updates:
        return _sk_err(ImageSetResult, "NO_PARAMS", "未传入任何要修改的图像参数",
                       "至少传一个参数，如 brightness=150；可先调 big_image_query 查看可设置项")

    err, cam = _sk_resolve_camera(name, answers, ImageSetResult)
    if err:
        return err
    result = _set_cam(cam, updates)
    return result

def manage_image_settings(
    action: ImageAction = ImageAction.QUERY,
    camera_name: Optional[str] = None,
    name: Optional[str] = None,
    brightness: Optional[int] = None,
    contrast: Optional[int] = None,
    saturation: Optional[int] = None,
    sharpness: Optional[int] = None,
    flip: Optional[int] = None,
    answers: Optional[Dict[str, Any]] = None,
):
    resolved_name = camera_name or name

    if action == ImageAction.QUERY:
        return big_image_query(name=resolved_name, answers=answers)
    elif action == ImageAction.SET:
        return big_image_set(
            name=resolved_name,
            brightness=brightness,
            contrast=contrast,
            saturation=saturation,
            sharpness=sharpness,
            flip=flip,
            answers=answers,
        )
    else:
        return ImageSetResult(ok=False, error_code="INVALID_ACTION",
                              message=f"不支持的操作：{action}")
