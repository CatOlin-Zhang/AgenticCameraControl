"""
Toolkit: 图像参数设置（协议 5.3 SK_SETTING_*_IMAGE 三命令）

工具清单：
  - big_image_query         查询图像能力清单 + 当前值
  - big_image_set           设置图像参数（读-校验-合并-写-回读）
  - manage_image_settings   统一图像管理入口（查询/设置）

传输通道：SK TCP HTTP（POST http://<ip>:9010/xiaopaitech/device_service，动态 Token 鉴权），
纯 SK 单通道，无 ONVIF 回退（ONVIF Imaging 仅覆盖四项连续参数，flip 等档位参数实现不了，
兜底意义有限，故不实现）

三条 SK 命令：
  - SK_SETTING_GET_IMAGE_OPTION  查询图像能力（image 数组，name/type/specs）
  - SK_SETTING_GET_IMAGE         查询当前图像参数（平铺字段）
  - SK_SETTING_SET_IMAGE         设置图像参数（全量字段下发）

支持参数：brightness/contrast/saturation/sharpness/flip（多数设备仅需这五项调节；
flip 为 0-3 档位枚举），其余固件字段（whitebalance/wdr/face_mode/plate_mode 等）不上报、不可设置，
仅在 SET_IMAGE 全量下发时作为基线透传
SET_IMAGE 是全量下发，设置前必须先 GET_IMAGE 读基线再合并，否则未传字段会被重置
"""
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

try:
    from .device_mgmt import resolve_target, CameraConfig
except ImportError:
    from device_mgmt import resolve_target, CameraConfig

# 复用 illumination 的 SK 协议底层基础设施
try:
    from .illumination import (
        _sk_compute_auth_token,
        _sk_http_query_ex,
        _sk_err,
        _sk_resolve_camera,
        _coerce_int,
        _merge_capabilities,
    )
except ImportError:
    from illumination import (
        _sk_compute_auth_token,
        _sk_http_query_ex,
        _sk_err,
        _sk_resolve_camera,
        _coerce_int,
        _merge_capabilities,
    )


# ──────────────────────────────────────────────
#  枚举与常量
# ──────────────────────────────────────────────

class ImageAction(str, Enum):
    """图像管理操作类型"""
    QUERY = "get"
    SET = "set"


# SK 协议常量（端口 / 超时 / 命令名与 illumination 共享 9010 端口）
_SK_IMAGE_PORT = 9010
_SK_IMAGE_TIMEOUT = 3.0
_SK_OK_CODE = "C0000"

_SK_CMD_IMAGE_OPTION = "SK_SETTING_GET_IMAGE_OPTION"
_SK_CMD_IMAGE_GET = "SK_SETTING_GET_IMAGE"
_SK_CMD_IMAGE_SET = "SK_SETTING_SET_IMAGE"

# 对外暴露的图像参数白名单（多数设备仅需这五项调节，其余固件字段不上报）
_SK_IMAGE_SUPPORTED = ("brightness", "contrast", "saturation", "sharpness", "flip")

# 图像参数中文标签（协议字段 → 中文，协议 5.3.1 参数表）
_SK_IMAGE_LABELS = {
    "brightness": "亮度",
    "contrast": "对比度",
    "saturation": "饱和度",
    "sharpness": "锐度",
    "flip": "图像翻转",
}

# 多档位枚举的档位说明（flip 为 0-3 档位枚举，协议 5.3.1 参数表；其余参数为连续数值型无档位）
_SK_IMAGE_VALUE_TEXTS = {
    "flip": {0: "正常", 1: "对角翻转", 2: "水平翻转", 3: "垂直翻转"},
}


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class ImageQueryResult:
    """图像查询编排结果（big_image_query 返回）"""
    ok: bool
    camera: str = ""
    channel: str = ""                                       # "sk"
    capabilities: list = field(default_factory=list)        # 能力+当前值合并列表
    current: Dict[str, Any] = field(default_factory=dict)   # 设备当前值原始平铺字段
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: list = field(default_factory=list)


@dataclass
class ImageSetResult:
    """图像设置编排结果（big_image_set 返回）"""
    ok: bool
    camera: str = ""
    channel: str = ""                                          # "sk"
    updated: Dict[str, Any] = field(default_factory=dict)      # 本次实际生效的字段（回读对比）
    current: Dict[str, Any] = field(default_factory=dict)      # 设置后回读的全量当前值
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: list = field(default_factory=list)


# ──────────────────────────────────────────────
#  调试日志
# ──────────────────────────────────────────────

_IMAGE_DEBUG = os.environ.get("XPAI_IMAGE_DEBUG", "1") != "0"


def set_image_debug(enable: bool = True) -> None:
    """开关图像设置调试日志（Jupyter 里可先调本函数再调 big_image_*）。"""
    global _IMAGE_DEBUG
    _IMAGE_DEBUG = bool(enable)


def _log(*args) -> None:
    if _IMAGE_DEBUG:
        print("[image]", *args, file=sys.stderr)


# ──────────────────────────────────────────────
#  SK 协议图像命令实现
# ──────────────────────────────────────────────

def _sk_query_option(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_IMAGE_OPTION：返回 {"ok", "capabilities": [...], "code", "raw"}。"""
    ok, resp, _status = _sk_http_query_ex(cam.ip, _SK_IMAGE_PORT, _SK_CMD_IMAGE_OPTION, {},
                                          cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查图像能力失败（status={_status}）")
        return {"ok": False, "status": _status}
    caps = resp.get("image")
    _ok = resp.get("code") == _SK_OK_CODE and isinstance(caps, list)
    if _ok:
        _log(f"SK 图像能力 {len(caps)} 项: {[c.get('name') for c in caps if isinstance(c, dict)]}")
    else:
        _log(f"SK 图像能力响应异常 code={resp.get('code')}")
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": _status, "raw": resp}


def _sk_query_current(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_IMAGE：返回 {"ok", "current": {...}, "code", "raw"}。"""
    ok, resp, _status = _sk_http_query_ex(cam.ip, _SK_IMAGE_PORT, _SK_CMD_IMAGE_GET, {},
                                          cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查图像当前值失败（status={_status}）")
        return {"ok": False, "status": _status}
    _head = {"service_type", "msg_id", "cmd_name", "ver", "code", "msg", "channel", "sequence"}
    current = {k: v for k, v in resp.items() if k not in _head}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 图像当前值 code={resp.get('code')}: {current if _ok else '（code 非 C0000）'}")
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": _status, "raw": resp}


def _sk_set(cam, updates: Dict[str, Any]) -> ImageSetResult:
    """SK 私有协议通道设置（读-校验-合并-写-回读）。"""
    # 1. 查能力 → 客户端校验（参数是否支持 + 范围）
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

    # 2. 读基线（SET_IMAGE 是全量下发，未传字段用当前值填充）
    base = _sk_query_current(cam)
    if not base["ok"]:
        if base.get("status") is None:
            return _sk_err(ImageSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_IMAGE_PORT}（SK HTTP 无响应）", camera=cam.name)
        return _sk_err(ImageSetResult, "CURRENT_QUERY_FAILED",
                       f"查询图像当前值失败（code={base['code']}）", camera=cam.name)
    payload = dict(base["current"])
    payload.update(updates)
    _log(f"SK 下发全量 payload={payload}")

    # 3. 全量下发
    ok, resp, _status = _sk_http_query_ex(cam.ip, _SK_IMAGE_PORT, _SK_CMD_IMAGE_SET, payload,
                                          cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT)
    if not ok or not resp:
        return _sk_err(ImageSetResult, "DEVICE_UNREACHABLE" if _status is None else "SET_FAILED",
                       f"设置命令下发失败：{cam.ip}:{_SK_IMAGE_PORT}"
                       + ("" if _status is None else f"（HTTP {_status}）"), camera=cam.name)
    if resp.get("code") != _SK_OK_CODE:
        return _sk_err(ImageSetResult, "SET_FAILED",
                       f"设备拒绝设置（code={resp.get('code')} msg={resp.get('msg')}）", camera=cam.name)

    # 4. 回读确认实际生效值（对外仅上报白名单参数）
    rb = _sk_query_current(cam)
    cur = rb["current"] if rb["ok"] else dict(payload)
    cur = {k: v for k, v in cur.items() if k in _SK_IMAGE_SUPPORTED}
    updated = {k: cur[k] for k in updates if k in cur}
    _log(f"SK 回读确认 updated={updated}")
    return ImageSetResult(ok=True, camera=cam.name, channel="sk", updated=updated, current=cur,
                          message=f"图像参数已生效：{updated}")


# ──────────────────────────────────────────────
#  编排核心（SK 单通道）
# ──────────────────────────────────────────────

def _query_cam(cam) -> ImageQueryResult:
    """SK 私有协议查询核心：能力清单 + 当前值。"""
    _log(f"[SK] 尝试私有协议 {cam.ip}:{_SK_IMAGE_PORT}")
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
    # 对外仅上报白名单参数：能力清单与当前值都过滤
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
    """SK 私有协议设置核心。"""
    _log(f"[SK] 尝试私有协议设置 {cam.ip}:{_SK_IMAGE_PORT}")
    return _sk_set(cam, updates)


# ──────────────────────────────────────────────
#  编排入口
# ──────────────────────────────────────────────

def big_image_query(
    name: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> ImageQueryResult:
    """
    查询 IPC 图像设置：能力清单（哪些参数可调、取值范围）+ 当前值，一次返回。

    协议：SK_SETTING_GET_IMAGE_OPTION + SK_SETTING_GET_IMAGE（协议 5.3.1 / 5.3.3），
    纯 SK 单通道，无 ONVIF 回退。
    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:    摄像头名称（None 时走 resolve_target 降级：唯一一台直接用）
        answers: NEEDS_INPUT 重调时的回答 dict

    Returns:
        ImageQueryResult:
            ok=True:  capabilities 能力列表（含 current/current_text/options），
                      current 当前值（仅 brightness/contrast/saturation/sharpness/flip）；
                      channel 标注实际生效协议通道
            ok=False: error_code + message + hint
    """
    err, cam = _sk_resolve_camera(name, answers, ImageQueryResult)
    if err:
        _log(f"查询终止：resolve_target 失败 error_code={err.error_code}")
        return err
    _log(f"===== 图像查询开始 camera={cam.name} ip={cam.ip} =====")
    result = _query_cam(cam)
    _log(f"===== 图像查询结束 ok={result.ok} channel={result.channel} error_code={result.error_code} =====")
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
    """
    设置 IPC 图像参数（协议 5.3.2 SK_SETTING_SET_IMAGE，读-校验-合并-写-回读）。

    仅支持 brightness/contrast/saturation/sharpness/flip 五个参数（多数设备仅需这五项调节），
    其中 flip 为 0-3 档位枚举。
    未传参数保持当前值（先读基线再全量下发）。
    纯 SK 单通道，无 ONVIF 回退。
    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:           摄像头名称（None 时走 resolve_target 降级）
        brightness:     亮度（能力 specs 范围内，通常 1-255）
        contrast:       对比度
        saturation:     饱和度
        sharpness:      锐度
        flip:           图像翻转（0正常/1对角翻转/2水平翻转/3垂直翻转）
        answers:        NEEDS_INPUT 重调时的回答 dict

    Returns:
        ImageSetResult:
            ok=True:  updated 回读确认实际生效的字段，current 当前值（仅白名单参数）
            ok=False: error_code + message + hint
    """
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
        _log(f"设置终止：resolve_target 失败 error_code={err.error_code}")
        return err
    _log(f"===== 图像设置开始 camera={cam.name} ip={cam.ip} updates={updates} =====")
    result = _set_cam(cam, updates)
    _log(f"===== 图像设置结束 ok={result.ok} channel={result.channel} error_code={result.error_code} =====")
    return result


# ──────────────────────────────────────────────
#  高级封装：manage_image_settings
# ──────────────────────────────────────────────

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
    """
    统一图像管理入口：根据 action 分发到查询或设置。

    仅支持 brightness/contrast/saturation/sharpness/flip 五个参数（多数设备仅需这五项调节），
    其中 flip 为 0-3 档位枚举。纯 SK 单通道，无 ONVIF 回退。

    Args:
        action:         操作类型 (ImageAction: get / set)
        camera_name:    摄像头名称（MCP 层传入，优先使用）
        name:           摄像头名称（内部调用兼容）
        brightness:     亮度（仅 SET）
        contrast:       对比度（仅 SET）
        saturation:     饱和度（仅 SET）
        sharpness:      锐度（仅 SET）
        flip:           图像翻转（仅 SET；0正常/1对角翻转/2水平翻转/3垂直翻转）
        answers:        NEEDS_INPUT 重调时的回答 dict

    Returns:
        ImageQueryResult (action=get) 或 ImageSetResult (action=set)
    """
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
