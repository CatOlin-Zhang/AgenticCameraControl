"""
Toolkit: 图像参数设置（协议 5.3 SK_SETTING_*_IMAGE 三命令）

工具清单：
  - big_image_query         查询图像能力清单 + 当前值（双通道：SK 优先 / ONVIF 回退）
  - big_image_set           设置图像参数（读-校验-合并-写-回读）
  - manage_image_settings   统一图像管理入口（查询/设置）

传输通道 1：SK TCP HTTP（POST http://<ip>:9010/xiaopaitech/device_service，动态 Token 鉴权）
传输通道 2（回退）：ONVIF Imaging Service（部分固件未实现 SK 图像命令，如 ZCR461）

三条 SK 命令：
  - SK_SETTING_GET_IMAGE_OPTION  查询图像能力（image 数组，name/type/specs）
  - SK_SETTING_GET_IMAGE         查询当前图像参数（平铺字段）
  - SK_SETTING_SET_IMAGE         设置图像参数（全量字段下发）

支持参数：brightness/contrast/saturation/sharpness/flip/whitebalance/wdr/face_mode/plate_mode
SET_IMAGE 是全量下发，设置前必须先 GET_IMAGE 读基线再合并，否则未传字段会被重置
"""
import base64
import hashlib
import os
import re
import secrets
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    requests = None

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

# 图像参数中文标签（协议字段 → 中文，协议 5.3.1 参数表）
_SK_IMAGE_LABELS = {
    "brightness": "亮度",
    "contrast": "对比度",
    "saturation": "饱和度",
    "sharpness": "锐度",
    "flip": "图像翻转",
    "whitebalance": "白平衡",
    "default": "默认参数开关",
    "wdr": "宽动态",
    "face_mode": "看清人脸",
    "plate_mode": "看清车牌",
}

# 多档位枚举的档位说明
_SK_IMAGE_VALUE_TEXTS = {
    "flip": {0: "正常", 1: "对角翻转", 2: "水平翻转", 3: "垂直翻转"},
    "whitebalance": {0: "自动", 1: "白光灯", 2: "白炽灯", 3: "自然光", 4: "暖光灯"},
    "default": {0: "使用设置参数", 1: "使用默认参数"},
    "wdr": {0: "关闭", 1: "打开"},
    "face_mode": {0: "关闭", 1: "打开"},
    "plate_mode": {0: "关闭", 1: "打开"},
}

# MCP 入参为 bool、协议值为 0/1 的字段
_SK_BOOL_FIELDS = ("wdr", "face_mode", "plate_mode")


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class ImageQueryResult:
    """图像查询编排结果（big_image_query 返回）"""
    ok: bool
    camera: str = ""
    channel: str = ""                                       # "sk" | "onvif"
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
    channel: str = ""                                          # "sk" | "onvif"
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

    # 4. 回读确认实际生效值
    rb = _sk_query_current(cam)
    cur = rb["current"] if rb["ok"] else dict(payload)
    updated = {k: cur[k] for k in updates if k in cur}
    _log(f"SK 回读确认 updated={updated}")
    return ImageSetResult(ok=True, camera=cam.name, channel="sk", updated=updated, current=cur,
                          message=f"图像参数已生效：{updated}")


# ──────────────────────────────────────────────
#  ONVIF Imaging Service 回退通道
#  （SK 命令未实现的固件如 ZCR461，回退到标准 ONVIF）
# ──────────────────────────────────────────────

_ONVIF_IMG_ACTION = "http://www.onvif.org/ver20/imaging/wsdl/"
_ONVIF_MEDIA_ACTION = "http://www.onvif.org/ver10/media/wsdl/"
_ONVIF_IMAGING_PATH = "/onvif/image_service"
_ONVIF_MEDIA_PATH = "/onvif/media_service"
_ONVIF_IMAGE_FIELDS = ("brightness", "contrast", "saturation", "sharpness")
_ONVIF_TT = "{http://www.onvif.org/ver10/schema}"
_vsrc_token_cache: Dict[str, str] = {}


def _onvif_wsse_header(username: str, password: str) -> str:
    """WS-UsernameToken PasswordDigest 头，无凭据时返回空串。"""
    if not username:
        return ""
    nonce_raw = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce_raw + created.encode() + password.encode()).digest()
    ).decode()
    return ('<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-wssecurity-secext-1.0.xsd" mustUnderstand="true">'
            '<wsse:UsernameToken>'
            f'<wsse:Username>{username}</wsse:Username>'
            f'<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password>'
            f'<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce_raw).decode()}</wsse:Nonce>'
            f'<wsu:Created xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</wsu:Created>'
            '</wsse:UsernameToken></wsse:Security>')


def _onvif_imaging_post(cam, action: str, inner_body: str):
    """POST SOAP1.2 到 imaging/media 服务。Returns: (ok, status, body_text)。"""
    if requests is None:
        return False, None, ""
    path = _ONVIF_MEDIA_PATH if "/media/" in action else _ONVIF_IMAGING_PATH
    header = _onvif_wsse_header(cam.username, cam.password)
    envelope = ('<?xml version="1.0" encoding="utf-8"?>'
                '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
                f'<soap:Header>{header}</soap:Header>'
                f'<soap:Body>{inner_body}</soap:Body></soap:Envelope>')
    try:
        resp = requests.post(
            f"http://{cam.ip}:{cam.port}{path}", data=envelope.encode("utf-8"),
            headers={"Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"'},
            timeout=_SK_IMAGE_TIMEOUT + 2,
        )
        _ok = resp.status_code == 200 and "Fault" not in resp.text
        _log(f"ONVIF {action.split('/')[-1]} → HTTP {resp.status_code} {'ok' if _ok else 'Fault/失败'}")
        if not _ok and resp.text:
            m = re.search(r'<[^>]*Text[^>]*>([^<]*)<', resp.text)
            if m:
                _log(f"ONVIF Fault 原因: {m.group(1).strip()}")
        return _ok, resp.status_code, resp.text
    except requests.RequestException as e:
        _log(f"ONVIF {action.split('/')[-1]} 连接失败: {type(e).__name__}: {e}")
        return False, None, ""


def _onvif_get_vsrc_token(cam) -> str:
    """获取 VideoSourceToken：先试常见 token，失败再 GetVideoSources 解析（进程内缓存）。"""
    key = f"{cam.ip}:{cam.port}"
    if key in _vsrc_token_cache:
        return _vsrc_token_cache[key]
    token = ""
    for cand in ("VideoSourceToken_0", "VideoSource_0", "video_source_0", "0"):
        ok, _s, _b = _onvif_imaging_post(
            cam, _ONVIF_IMG_ACTION + "GetImagingSettings",
            f'<GetImagingSettings xmlns="http://www.onvif.org/ver20/imaging/wsdl">'
            f'<VideoSourceToken>{cand}</VideoSourceToken></GetImagingSettings>')
        if ok:
            token = cand
            break
    if not token:
        ok, _s, body = _onvif_imaging_post(
            cam, _ONVIF_MEDIA_ACTION + "GetVideoSources",
            '<GetVideoSources xmlns="http://www.onvif.org/ver10/media/wsdl"/>')
        if ok:
            m = re.search(r'<[^>]*VideoSources\s+token="([^"]+)"', body)
            if m:
                token = m.group(1)
    if token:
        _vsrc_token_cache[key] = token
        _log(f"ONVIF VideoSourceToken 确定: {token}")
    else:
        _log("ONVIF 无法获取 VideoSourceToken（Imaging 服务不可用）")
    return token


def _parse_imaging_settings(body: str) -> Dict[str, float]:
    """解析 GetImagingSettings 响应 → {brightness, contrast, saturation, sharpness}。"""
    out: Dict[str, float] = {}
    m = re.search(r'<[^>]*ImagingSettings[^>]*>(.*?)</[^>]*ImagingSettings>', body, re.S)
    if not m:
        return out
    inner = m.group(1)
    for sk, xmltag in (("brightness", "Brightness"), ("contrast", "Contrast"),
                       ("saturation", "ColorSaturation"), ("sharpness", "Sharpness")):
        mm = re.search(rf'<[^>]*{xmltag}>(.*?)</[^>]*{xmltag}>', inner, re.S)
        if mm:
            try:
                out[sk] = float(mm.group(1).strip())
            except ValueError:
                pass
    return out


def _parse_imaging_options(body: str) -> Dict[str, Dict[str, float]]:
    """解析 GetOptions 响应 → 各字段的 {min, max} 范围。"""
    ranges: Dict[str, Dict[str, float]] = {}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ranges
    ns = "http://www.onvif.org/ver20/imaging/wsdl"
    for resp_el in root.iter(f"{{{ns}}}GetOptionsResponse"):
        for opts in resp_el.iter(f"{{{ns}}}ImagingOptions"):
            for sk, tag in (("brightness", "Brightness"), ("contrast", "Contrast"),
                            ("saturation", "ColorSaturation"), ("sharpness", "Sharpness")):
                el = opts.find(f"{_ONVIF_TT}{tag}")
                if el is None:
                    continue
                mn = el.find(f"{_ONVIF_TT}Min")
                mx = el.find(f"{_ONVIF_TT}Max")
                if mn is not None and mx is not None:
                    try:
                        ranges[sk] = {"min": float(mn.text), "max": float(mx.text)}
                    except (TypeError, ValueError):
                        pass
    return ranges


def _onvif_query_all(cam) -> Dict[str, Any]:
    """ONVIF 通道查询：{ok, capabilities, current}。capabilities 与 SK 格式对齐。"""
    token = _onvif_get_vsrc_token(cam)
    if not token:
        _log("ONVIF 查询中止：无可用 VideoSourceToken")
        return {"ok": False}
    ok1, _s1, b1 = _onvif_imaging_post(
        cam, _ONVIF_IMG_ACTION + "GetImagingSettings",
        f'<GetImagingSettings xmlns="http://www.onvif.org/ver20/imaging/wsdl">'
        f'<VideoSourceToken>{token}</VideoSourceToken></GetImagingSettings>')
    if not ok1:
        _log("ONVIF GetImagingSettings 失败，查询中止")
        return {"ok": False}
    current = _parse_imaging_settings(b1)
    _log(f"ONVIF 当前值: {current}")
    _ok2, _s2, b2 = _onvif_imaging_post(
        cam, _ONVIF_IMG_ACTION + "GetOptions",
        f'<GetOptions xmlns="http://www.onvif.org/ver20/imaging/wsdl">'
        f'<VideoSourceToken>{token}</VideoSourceToken></GetOptions>')
    ranges = _parse_imaging_options(b2)
    _log(f"ONVIF 参数范围: {ranges}")
    caps = []
    for sk in _ONVIF_IMAGE_FIELDS:
        if sk not in current:
            continue
        r = ranges.get(sk)
        item = {"name": sk, "type": "int",
                "specs": {"min": str(int(r["min"])), "max": str(int(r["max"]))} if r else {}}
        caps.append(item)
    return {"ok": True, "capabilities": caps, "current": current, "token": token}


def _onvif_set(cam, updates: Dict[str, Any]) -> ImageSetResult:
    """ONVIF 通道设置（读-校验-写-回读），仅支持亮度/对比度/饱和度/锐度。"""
    _log(f"ONVIF 通道设置 updates={updates}")
    unsupported = [k for k in updates if k not in _ONVIF_IMAGE_FIELDS]
    if unsupported:
        _log(f"ONVIF 拒绝不支持参数: {unsupported}")
        return _sk_err(ImageSetResult, "PARAM_NOT_SUPPORTED",
                       f"该摄像头不支持参数：{', '.join(unsupported)}（SK 协议未实现，ONVIF 通道仅支持 "
                       f"{'/'.join(_ONVIF_IMAGE_FIELDS)}）", camera=cam.name)
    token = _onvif_get_vsrc_token(cam)
    if not token:
        return _sk_err(ImageSetResult, "DEVICE_UNREACHABLE",
                       f"ONVIF Imaging 服务无响应（{cam.ip}:{cam.port}）", camera=cam.name)
    ok1, _s1, b1 = _onvif_imaging_post(
        cam, _ONVIF_IMG_ACTION + "GetImagingSettings",
        f'<GetImagingSettings xmlns="http://www.onvif.org/ver20/imaging/wsdl">'
        f'<VideoSourceToken>{token}</VideoSourceToken></GetImagingSettings>')
    if not ok1:
        return _sk_err(ImageSetResult, "CURRENT_QUERY_FAILED", "ONVIF GetImagingSettings 失败", camera=cam.name)
    current = _parse_imaging_settings(b1)
    _ok2, _s2, b2 = _onvif_imaging_post(
        cam, _ONVIF_IMG_ACTION + "GetOptions",
        f'<GetOptions xmlns="http://www.onvif.org/ver20/imaging/wsdl">'
        f'<VideoSourceToken>{token}</VideoSourceToken></GetOptions>')
    ranges = _parse_imaging_options(b2)
    for k, v in updates.items():
        r = ranges.get(k)
        if r and not (r["min"] <= v <= r["max"]):
            return _sk_err(ImageSetResult, "PARAM_OUT_OF_RANGE",
                           f"{k}={v} 超出允许范围 {int(r['min'])}-{int(r['max'])}", camera=cam.name)
    payload = dict(current)
    payload.update({k: float(v) for k, v in updates.items()})
    _log(f"ONVIF 下发全量 payload={payload}")
    tags = "".join(
        f"<{t}>{payload[sk]:.1f}</{t}>" for sk, t in
        (("brightness", "Brightness"), ("contrast", "Contrast"),
         ("saturation", "ColorSaturation"), ("sharpness", "Sharpness")) if sk in payload)
    ok3, _s3, _b3 = _onvif_imaging_post(
        cam, _ONVIF_IMG_ACTION + "SetImagingSettings",
        f'<SetImagingSettings xmlns="http://www.onvif.org/ver20/imaging/wsdl">'
        f'<VideoSourceToken>{token}</VideoSourceToken>'
        f'<ImagingSettings xmlns:tt="http://www.onvif.org/ver10/schema">{tags}</ImagingSettings>'
        f'</SetImagingSettings>')
    if not ok3:
        return _sk_err(ImageSetResult, "SET_FAILED", "ONVIF SetImagingSettings 被设备拒绝", camera=cam.name)
    ok4, _s4, b4 = _onvif_imaging_post(
        cam, _ONVIF_IMG_ACTION + "GetImagingSettings",
        f'<GetImagingSettings xmlns="http://www.onvif.org/ver20/imaging/wsdl">'
        f'<VideoSourceToken>{token}</VideoSourceToken></GetImagingSettings>')
    cur: Dict[str, Any] = _parse_imaging_settings(b4) if ok4 else dict(payload)
    for k in _ONVIF_IMAGE_FIELDS:
        if k not in cur and k in payload:
            cur[k] = payload[k]
    updated = {k: cur[k] for k in updates if k in cur}
    _log(f"ONVIF 回读确认 updated={updated}")
    return ImageSetResult(ok=True, camera=cam.name, channel="onvif", updated=updated, current=cur,
                          message=f"图像参数已生效（ONVIF 通道）：{updated}")


# ──────────────────────────────────────────────
#  双通道编排核心
# ──────────────────────────────────────────────

def _query_cam(cam) -> ImageQueryResult:
    """双通道查询核心：SK 私有协议优先，失败回退 ONVIF Imaging。"""
    _log(f"[通道1-SK] 尝试私有协议 {cam.ip}:{_SK_IMAGE_PORT}")
    sk_reachable = True
    opt = _sk_query_option(cam)
    if opt["ok"]:
        cur = _sk_query_current(cam)
        if cur["ok"]:
            return ImageQueryResult(
                ok=True, camera=cam.name, channel="sk",
                capabilities=_merge_capabilities(opt["capabilities"], cur["current"],
                                                 _SK_IMAGE_LABELS, _SK_IMAGE_VALUE_TEXTS),
                current=cur["current"],
            )
        return _sk_err(ImageQueryResult, "CURRENT_QUERY_FAILED",
                       f"查询图像当前值失败（code={cur['code']}）", camera=cam.name)
    sk_reachable = opt.get("status") is not None
    _log(f"[通道1-SK] 不可用（{'9010 端口无响应' if not sk_reachable else '图像命令未实现(HTTP 404)'}），切换 ONVIF 回退")

    _log(f"[通道2-ONVIF] 尝试 Imaging 服务 {cam.ip}:{cam.port}")
    onv = _onvif_query_all(cam)
    if onv["ok"]:
        return ImageQueryResult(
            ok=True, camera=cam.name, channel="onvif",
            capabilities=_merge_capabilities(onv["capabilities"], onv["current"],
                                             _SK_IMAGE_LABELS, _SK_IMAGE_VALUE_TEXTS),
            current=onv["current"],
        )

    if not sk_reachable:
        return _sk_err(ImageQueryResult, "DEVICE_UNREACHABLE",
                       f"无法连接 {cam.ip}（SK 9010 与 ONVIF {cam.port} 均无响应）",
                       "确认摄像头在线、网络可达，且已注册正确凭据", camera=cam.name)
    return _sk_err(ImageQueryResult, "OPTION_QUERY_FAILED",
                   "设备未实现图像设置命令（SK 返回 404，ONVIF Imaging 不可用）",
                   "确认设备固件版本是否支持图像设置", camera=cam.name)


def _set_cam(cam, updates: Dict[str, Any]) -> ImageSetResult:
    """双通道设置核心：SK 优先，失败回退 ONVIF Imaging。"""
    _log(f"[通道1-SK] 尝试私有协议设置 {cam.ip}:{_SK_IMAGE_PORT}")
    result = _sk_set(cam, updates)
    if result.ok or result.error_code not in (
            "DEVICE_UNREACHABLE", "OPTION_QUERY_FAILED", "CURRENT_QUERY_FAILED"):
        return result
    sk_reachable = result.error_code != "DEVICE_UNREACHABLE"
    _log(f"[通道1-SK] 不可用（{result.error_code}），切换 ONVIF 回退")

    _log(f"[通道2-ONVIF] 尝试 Imaging 服务 {cam.ip}:{cam.port}")
    result = _onvif_set(cam, updates)
    if result.ok or result.error_code != "DEVICE_UNREACHABLE":
        return result

    if not sk_reachable:
        return _sk_err(ImageSetResult, "DEVICE_UNREACHABLE",
                       f"无法连接 {cam.ip}（SK 9010 与 ONVIF {cam.port} 均无响应）",
                       "确认摄像头在线、网络可达，且已注册正确凭据", camera=cam.name)
    return _sk_err(ImageSetResult, "OPTION_QUERY_FAILED",
                   "设备未实现图像设置命令（SK 返回 404，ONVIF Imaging 不可用）",
                   "确认设备固件版本是否支持图像设置", camera=cam.name)


# ──────────────────────────────────────────────
#  编排入口
# ──────────────────────────────────────────────

def big_image_query(
    name: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> ImageQueryResult:
    """
    查询 IPC 图像设置：能力清单（哪些参数可调、取值范围）+ 当前值，一次返回。

    协议：SK_SETTING_GET_IMAGE_OPTION + SK_SETTING_GET_IMAGE（协议 5.3.1 / 5.3.3）。
    双通道：SK 私有协议优先，固件不支持时自动回退 ONVIF Imaging。
    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:    摄像头名称（None 时走 resolve_target 降级：唯一一台直接用）
        answers: NEEDS_INPUT 重调时的回答 dict

    Returns:
        ImageQueryResult:
            ok=True:  capabilities 能力列表（含 current/current_text/options），
                      current 设备原始平铺当前值；channel 标注实际生效协议通道
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
    whitebalance: Optional[int] = None,
    wdr: Optional[bool] = None,
    face_mode: Optional[bool] = None,
    plate_mode: Optional[bool] = None,
    restore_default: Optional[bool] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> ImageSetResult:
    """
    设置 IPC 图像参数（协议 5.3.2 SK_SETTING_SET_IMAGE，读-校验-合并-写-回读）。

    仅传需要修改的参数，未传参数保持当前值（先读基线再全量下发）。
    双通道：SK 私有协议优先，固件不支持时自动回退 ONVIF Imaging。
    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:           摄像头名称（None 时走 resolve_target 降级）
        brightness:     亮度（能力 specs 范围内，通常 1-255）
        contrast:       对比度
        saturation:     饱和度
        sharpness:      锐度
        flip:           图像翻转 0正常 1对角 2水平 3垂直
        whitebalance:   白平衡 0自动 1白光灯 2白炽灯 3自然光 4暖光灯
        wdr:            宽动态开关
        face_mode:      看清人脸开关
        plate_mode:     看清车牌开关
        restore_default: True=恢复默认图像参数（协议 default=1）
        answers:        NEEDS_INPUT 重调时的回答 dict

    Returns:
        ImageSetResult:
            ok=True:  updated 回读确认实际生效的字段，current 回读全量当前值
            ok=False: error_code + message + hint
    """
    updates: Dict[str, Any] = {}
    for k, v in (("brightness", brightness), ("contrast", contrast),
                 ("saturation", saturation), ("sharpness", sharpness),
                 ("flip", flip), ("whitebalance", whitebalance)):
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, int):
                return _sk_err(ImageSetResult, "INVALID_PARAM_TYPE", f"{k} 需要整数，收到 {v!r}")
            updates[k] = v
    for k, v in (("wdr", wdr), ("face_mode", face_mode), ("plate_mode", plate_mode)):
        if v is not None:
            updates[k] = 1 if v else 0
    if restore_default:
        updates["default"] = 1
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
    whitebalance: Optional[int] = None,
    wdr: Optional[bool] = None,
    face_mode: Optional[bool] = None,
    plate_mode: Optional[bool] = None,
    restore_default: Optional[bool] = None,
    answers: Optional[Dict[str, Any]] = None,
):
    """
    统一图像管理入口：根据 action 分发到查询或设置。

    Args:
        action:         操作类型 (ImageAction: get / set)
        camera_name:    摄像头名称（MCP 层传入，优先使用）
        name:           摄像头名称（内部调用兼容）
        brightness:     亮度（仅 SET）
        contrast:       对比度（仅 SET）
        saturation:     饱和度（仅 SET）
        sharpness:      锐度（仅 SET）
        flip:           图像翻转（仅 SET）
        whitebalance:   白平衡（仅 SET）
        wdr:            宽动态（仅 SET）
        face_mode:      看清人脸（仅 SET）
        plate_mode:     看清车牌（仅 SET）
        restore_default: 恢复默认参数（仅 SET）
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
            whitebalance=whitebalance,
            wdr=wdr,
            face_mode=face_mode,
            plate_mode=plate_mode,
            restore_default=restore_default,
            answers=answers,
        )
    else:
        return ImageSetResult(ok=False, error_code="INVALID_ACTION",
                              message=f"不支持的操作：{action}")
