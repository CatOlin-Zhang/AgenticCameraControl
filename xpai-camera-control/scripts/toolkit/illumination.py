"""
Toolkit: 补光设置（协议 5.2 SK_SETTING_*_FILLLIGHT 三命令）

工具清单：
  - big_filllight_query         查询补光能力清单 + 当前值
  - big_filllight_set           设置补光参数（读-校验-合并-写-回读）
  - manage_illumination         统一补光管理入口（查询/设置）
  - probe_illumination_capability  探测摄像头补光能力

SK 动态 Token 鉴权：先调 GET_MAGIC 拿 stamp，再 token = Base64(SHA1(stamp + sn + KEY))
对外仅暴露 daynightmode/filllightmode 两个参数（多数设备只支持这两项调节），
其余固件字段不上报、不可设置，仅在 SET_FILLLIGHT 全量下发时作为基线透传
SET_FILLLIGHT 是全量下发，设置前必须先 GET_FILLLIGHT 读基线再合并
"""
import base64
import hashlib
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:  # SK/ONVIF HTTP 需要；缺失时不可用
    requests = None

try:
    from .device_mgmt import resolve_target, CameraConfig
except ImportError:  # 独立脚本运行时无包上下文
    from device_mgmt import resolve_target, CameraConfig

# ──────────────────────────────────────────────
#  枚举与常量
# ──────────────────────────────────────────────


class IlluminationAction(str, Enum):
    """补光管理操作类型"""
    QUERY = "get"           # 查询补光能力与当前值
    SET = "set"              # 设置补光参数


class DaynightMode(str, Enum):
    """开灯设置（日夜模式）"""
    DAY = "day"              # 0 白天模式
    NIGHT = "night"          # 1 夜晚模式
    AUTO = "auto"            # 2 自动模式
    TIMER = "timer"          # 3 定时模式
    SMART = "smart"          # 4 智能模式


class FilllightModeEnum(str, Enum):
    """补光方式"""
    FULL_COLOR = "full_color"  # 0 全彩模式
    INFRARED = "infrared"      # 1 红外模式
    SMART = "smart"            # 2 智能夜视


# 日夜模式：整数 ↔ 中文/英文别名
DAYNIGHT_MODES = {
    0: "白天模式", 1: "夜晚模式", 2: "自动模式", 3: "定时模式", 4: "智能模式",
}

# 补光方式：整数 ↔ 中文/英文别名
FILLLIGHT_MODES = {
    0: "全彩模式", 1: "红外模式", 2: "智能夜视",
}


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class IlluminationInfo:
    """补光能力信息（单条能力项 + 当前值）"""
    name: str                                 # 协议字段名
    label: str                                # 中文标签
    type: str = "int"                         # 参数类型
    min: Optional[int] = None                 # 最小值
    max: Optional[int] = None                 # 最大值
    current: Optional[Any] = None             # 当前值
    current_text: str = ""                    # 当前值中文说明
    options: Dict[str, str] = field(default_factory=dict)  # 枚举选项 {值: 说明}


@dataclass
class FilllightQueryResult:
    """补光查询结果。"""
    ok: bool
    camera: str = ""
    channel: str = ""       # "sk" | "onvif"：实际生效协议通道
    capabilities: list = field(default_factory=list)
    current: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: list = field(default_factory=list)


@dataclass
class FilllightSetResult:
    """补光设置结果（SK 通道始终回读确认，verified=True）。"""
    ok: bool
    camera: str = ""
    channel: str = ""
    updated: Dict[str, Any] = field(default_factory=dict)
    current: Dict[str, Any] = field(default_factory=dict)
    verified: bool = True
    error_code: str = ""
    message: str = ""
    hint: str = ""
    needs_input: list = field(default_factory=list)


# ──────────────────────────────────────────────
#  调试日志
# ──────────────────────────────────────────────

_FILL_DEBUG = os.environ.get("XPAI_FILL_DEBUG", "1") != "0"


def set_filllight_debug(enable: bool = True) -> None:
    """开关补光设置调试日志。"""
    global _FILL_DEBUG
    _FILL_DEBUG = bool(enable)


def _log(*args) -> None:
    if _FILL_DEBUG:
        print("[filllight]", *args, file=sys.stderr)


# ──────────────────────────────────────────────
#  SK 协议常量
# ──────────────────────────────────────────────

_SK_IMAGE_PORT = 9010                            # SK TCP HTTP 服务端口
_SK_IMAGE_TIMEOUT = 3.0                          # 设置类命令超时（秒）
_SK_OK_CODE = "C0000"                            # 协议成功状态码

_SK_CMD_FILLLIGHT_OPTION = "SK_SETTING_GET_FILLLIGHT_OPTION"
_SK_CMD_FILLLIGHT_GET = "SK_SETTING_GET_FILLLIGHT"
_SK_CMD_FILLLIGHT_SET = "SK_SETTING_SET_FILLLIGHT"

# 对外暴露的补光参数白名单（多数设备仅支持这两项调节，其余固件字段不上报）
_SK_FILLLIGHT_SUPPORTED = ("daynightmode", "filllightmode")

# 补光参数中文标签（协议字段 → 中文，协议 5.2.1 参数表）
_SK_FILLLIGHT_LABELS = {
    "daynightmode": "开灯设置（日夜模式）",
    "filllightmode": "补光方式",
}

# 枚举档位文本（协议 5.2.1）
_SK_FILLLIGHT_VALUE_TEXTS = {
    "daynightmode": {0: "白天模式", 1: "夜晚模式", 2: "自动模式", 3: "定时模式", 4: "智能模式"},
    "filllightmode": {0: "全彩模式", 1: "红外模式", 2: "智能夜视"},
}

# 枚举参数的字符串别名（字符串/整数均可传入，小写后匹配）
_SK_DAYNIGHT_ALIASES = {"day": 0, "白天": 0, "night": 1, "夜晚": 1, "auto": 2, "自动": 2,
                        "timer": 3, "定时": 3, "smart": 4, "智能": 4}
_SK_FILLMODE_ALIASES = {"color": 0, "full_color": 0, "全彩": 0,
                        "ir": 1, "infrared": 1, "红外": 1,
                        "smart": 2, "智能夜视": 2}

# ── SK 协议动态 Token 计算 ──
# Authorization: Basic <SHA1(stamp + sn + KEY) 的 base64>
# stamp 通过 SK_SETTING_GET_MAGIC 获取；KEY 是 16 字节固定常量
_SK_AUTH_KEY = bytes([0x72, 0x58, 0xea, 0xd7, 0x50, 0xd7, 0x38, 0xe6,
                      0x54, 0x25, 0x51, 0x90, 0x81, 0x4c, 0x4d, 0x68])
_SK_MAX_RETRIES = 3  # SK 命令最大重试次数（含首次，共 3 次机会）
_SK_RETRY_INTERVAL = 0.5  # 重试间隔（秒）


# ──────────────────────────────────────────────
#  SK 协议底层函数
# ──────────────────────────────────────────────

def _sk_err(result_cls, error_code: str, message: str, hint: str = "", needs_input=None, camera: str = ""):
    """构造统一失败结果。"""
    return result_cls(ok=False, error_code=error_code, message=message, hint=hint,
                      needs_input=needs_input or [], camera=camera)


def _sk_resolve_camera(name, answers, result_cls):
    """resolve_target 公共前置：返回 (err_result, cam) 二元组，成功时 err_result=None。"""
    rt = resolve_target(name=name, answers=answers)
    if not rt["ok"]:
        return _sk_err(result_cls, rt.get("error_code", "RESOLVE_FAILED"),
                       rt.get("message", "解析目标摄像头失败"), rt.get("hint", ""),
                       rt.get("needs_input")), None
    return None, rt["camera"]


def _sk_compute_auth_token(sn: str, username: str, password: str,
                           host: str, port: int, timeout: float) -> Optional[str]:
    """计算 SK 协议的动态 Authorization token。

    步骤：
      1. 先用 Basic Auth(username:password) 发 SK_SETTING_GET_MAGIC 拿 stamp
      2. token = Base64(SHA1(stamp + sn + KEY))

    重试策略：GET_MAGIC 返回 404 时最多重试 _SK_MAX_RETRIES 次（含首次），
    连接失败/超时/其他 HTTP 错误不重试。
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
            return None  # 连接失败不重试
        if resp.status_code == 404 and attempt < _SK_MAX_RETRIES:
            _log(f"SK auth: GET_MAGIC 404（固件间歇性），{_SK_RETRY_INTERVAL}s 后重试...")
            time.sleep(_SK_RETRY_INTERVAL)
            continue
        if resp.status_code != 200:
            _log(f"SK auth: GET_MAGIC HTTP {resp.status_code}")
            return None  # 其他 HTTP 错误不重试
        try:
            data = resp.json()
        except ValueError:
            _log("SK auth: GET_MAGIC 响应非 JSON")
            return None
        stamp = data.get("stamp")
        if not stamp:
            _log(f"SK auth: GET_MAGIC 未返回 stamp (code={data.get('code')})")
            return None
        _log(f"SK auth: stamp={stamp}")
        # 2. 计算 token = Base64(SHA1(stamp + sn + KEY))
        h = hashlib.sha1()
        h.update(stamp.encode("utf-8"))
        h.update(sn.encode("utf-8"))
        h.update(_SK_AUTH_KEY)
        token = base64.b64encode(h.digest()).decode("utf-8")
        _log(f"SK auth: token={token}")
        return token

    return None  # 兜底


def _sk_http_query_ex(host: str, port: int, cmd_name: str, payload: dict,
                      sn: str, username: str, password: str, timeout: float):
    """SK 协议 HTTP POST 查询，区分"HTTP 错误(404=命令不支持)"与"连接失败"。

    Authorization 通过动态计算 token 下发：
      1. 先用 Basic Auth 调 GET_MAGIC 拿 stamp
      2. token = Base64(SHA1(stamp + sn + KEY))

    重试策略：固件间歇性 404 时最多重试 _SK_MAX_RETRIES 次（含首次），
    连接失败/超时/其他 HTTP 错误不重试。

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
        _log(f"SK POST {url} cmd={cmd_name} payload_extra={list(payload) or '无'}（第 {attempt}/{_SK_MAX_RETRIES} 次）")
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            _log(f"SK 连接失败/超时: {type(e).__name__}: {e}")
            return False, None, None  # 连接失败/超时不重试
        if resp.status_code == 404 and attempt < _SK_MAX_RETRIES:
            _log(f"SK HTTP 404（固件间歇性），{_SK_RETRY_INTERVAL}s 后重试...")
            time.sleep(_SK_RETRY_INTERVAL)
            continue
        if resp.status_code != 200:
            _log(f"SK HTTP {resp.status_code}（非 200，404=设备未实现该命令）")
            return False, None, resp.status_code  # HTTP 错误不重试
        try:
            data = resp.json()
            _log(f"SK 200 响应 code={data.get('code')} cmd={data.get('cmd_name')}")
            return True, data, resp.status_code
        except ValueError:
            _log("SK 200 但响应体非 JSON")
            return False, None, resp.status_code

    # 理论上不会到这里（循环内必 return），兜底
    return False, None, None


# ──────────────────────────────────────────────
#  SK 补光命令实现
# ──────────────────────────────────────────────

def _coerce_int(v):
    """能力 specs 的 min/max 是字符串，安全转 int；失败返回 None。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _merge_capabilities(caps: list, current: Dict[str, Any],
                        labels: Optional[Dict[str, str]] = None,
                        value_texts: Optional[Dict[str, dict]] = None) -> list:
    """能力清单 + 当前值合并，并补中文标签与档位文本。"""
    labels = labels if labels is not None else _SK_FILLLIGHT_LABELS
    value_texts = value_texts if value_texts is not None else _SK_FILLLIGHT_VALUE_TEXTS
    merged = []
    for item in caps:
        if not isinstance(item, dict):
            continue
        fname = str(item.get("name", ""))
        specs = item.get("specs") or {}
        entry: Dict[str, Any] = {
            "name": fname,
            "label": labels.get(fname, fname),
            "type": item.get("type", "int"),
            "min": _coerce_int(specs.get("min")),
            "max": _coerce_int(specs.get("max")),
        }
        if fname in current:
            entry["current"] = current[fname]
            text_map = value_texts.get(fname)
            cv = _coerce_int(current[fname])
            if text_map and cv is not None and cv in text_map:
                entry["current_text"] = text_map[cv]
            if text_map:
                lo, hi = entry["min"], entry["max"]
                if lo is not None and hi is not None:
                    entry["options"] = {str(v): text_map[v] for v in range(lo, hi + 1) if v in text_map}
        merged.append(entry)
    return merged


def _enum_coerce(v, aliases: Dict[str, int], field_name: str, result_cls, camera: str = ""):
    """枚举参数归一：接受 int / 数字字符串 / 别名。成功 (True, int, None)，失败 (False, None, err)。"""
    if isinstance(v, bool):
        return False, None, _sk_err(result_cls, "INVALID_PARAM_TYPE",
                                    f"{field_name} 需要整数或字符串别名，收到 {v!r}", camera=camera)
    if isinstance(v, int):
        return True, v, None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in aliases:
            return True, aliases[s], None
        if s.isdigit():
            return True, int(s), None
    return False, None, _sk_err(result_cls, "INVALID_PARAM_VALUE",
                                f"{field_name} 取值 {v!r} 无法识别",
                                f"支持整数或别名：{', '.join(sorted(aliases))}", camera=camera)


def _sk_filllight_option(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_FILLLIGHT_OPTION：返回 {"ok", "capabilities", "code", "status", "raw"}。"""
    ok, resp, _status = _sk_http_query_ex(cam.ip, _SK_IMAGE_PORT, _SK_CMD_FILLLIGHT_OPTION, {},
                                          cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查补光能力失败（status={_status}）")
        return {"ok": False, "status": _status}
    caps = resp.get("filllight")
    _ok = resp.get("code") == _SK_OK_CODE and isinstance(caps, list)
    if _ok:
        _log(f"SK 补光能力 {len(caps)} 项: {[c.get('name') for c in caps if isinstance(c, dict)]}")
    else:
        _log(f"SK 补光能力响应异常 code={resp.get('code')}")
    return {"ok": _ok, "capabilities": caps if isinstance(caps, list) else [],
            "code": resp.get("code", ""), "status": _status, "raw": resp}


def _sk_filllight_cur(cam) -> Dict[str, Any]:
    """SK_SETTING_GET_FILLLIGHT：返回 {"ok", "current", "code", "status", "raw"}。"""
    ok, resp, _status = _sk_http_query_ex(cam.ip, _SK_IMAGE_PORT, _SK_CMD_FILLLIGHT_GET, {},
                                          cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT)
    if not ok or not resp:
        _log(f"SK 查补光当前值失败（status={_status}）")
        return {"ok": False, "status": _status}
    _head = {"service_type", "msg_id", "cmd_name", "ver", "code", "msg", "channel", "sequence"}
    current = {k: v for k, v in resp.items() if k not in _head}
    _ok = resp.get("code") == _SK_OK_CODE
    _log(f"SK 补光当前值 code={resp.get('code')}: {current if _ok else '（code 非 C0000）'}")
    return {"ok": _ok, "current": current,
            "code": resp.get("code", ""), "status": _status, "raw": resp}


def _sk_filllight_set(cam, updates: Dict[str, Any]) -> FilllightSetResult:
    """SK 私有协议通道补光设置（读-校验-合并-写-回读，协议 5.2.2）。"""
    # 1. 查能力 → 客户端校验
    opt = _sk_filllight_option(cam)
    if not opt["ok"]:
        if opt.get("status") is None:
            return _sk_err(FilllightSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_IMAGE_PORT}（SK HTTP 无响应）", camera=cam.name)
        return _sk_err(FilllightSetResult, "OPTION_QUERY_FAILED",
                       f"查询补光能力失败（code={opt.get('code') or '404'}）", camera=cam.name)
    cap_map: Dict[str, dict] = {}
    for item in opt["capabilities"]:
        if isinstance(item, dict) and item.get("name"):
            cap_map[str(item["name"])] = item
    for k, v in updates.items():
        item = cap_map.get(k)
        if item is None:
            return _sk_err(FilllightSetResult, "PARAM_NOT_SUPPORTED",
                           f"该摄像头不支持补光参数 {k}",
                           f"支持的参数：{', '.join(sorted(cap_map)) or '无'}", camera=cam.name)
        specs = item.get("specs") or {}
        lo, hi = _coerce_int(specs.get("min")), _coerce_int(specs.get("max"))
        if lo is not None and hi is not None and not (lo <= v <= hi):
            return _sk_err(FilllightSetResult, "PARAM_OUT_OF_RANGE",
                           f"{k}={v} 超出允许范围 {lo}-{hi}", camera=cam.name)
    # 2. 读基线（SET_FILLLIGHT 是全量下发）
    base = _sk_filllight_cur(cam)
    if not base["ok"]:
        if base.get("status") is None:
            return _sk_err(FilllightSetResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_IMAGE_PORT}（SK HTTP 无响应）", camera=cam.name)
        return _sk_err(FilllightSetResult, "CURRENT_QUERY_FAILED",
                       f"查询补光当前值失败（code={base['code']}）", camera=cam.name)
    payload = dict(base["current"])
    payload.update(updates)
    _log(f"SK 补光下发全量 payload={payload}")
    # 3. 全量下发
    ok, resp, _status = _sk_http_query_ex(cam.ip, _SK_IMAGE_PORT, _SK_CMD_FILLLIGHT_SET, payload,
                                          cam.sn_code, cam.username, cam.password, _SK_IMAGE_TIMEOUT)
    if not ok or not resp:
        return _sk_err(FilllightSetResult, "DEVICE_UNREACHABLE" if _status is None else "SET_FAILED",
                       f"补光设置命令下发失败：{cam.ip}:{_SK_IMAGE_PORT}"
                       + ("" if _status is None else f"（HTTP {_status}）"), camera=cam.name)
    if resp.get("code") != _SK_OK_CODE:
        return _sk_err(FilllightSetResult, "SET_FAILED",
                       f"设备拒绝设置（code={resp.get('code')} msg={resp.get('msg')}）", camera=cam.name)
    # 4. 回读确认（对外仅上报白名单参数）
    rb = _sk_filllight_cur(cam)
    cur = rb["current"] if rb["ok"] else dict(payload)
    cur = {k: v for k, v in cur.items() if k in _SK_FILLLIGHT_SUPPORTED}
    updated = {k: cur[k] for k in updates if k in cur}
    _log(f"SK 补光回读确认 updated={updated}")
    return FilllightSetResult(ok=True, camera=cam.name, channel="sk", updated=updated, current=cur,
                              message=f"补光参数已生效：{updated}")


# ──────────────────────────────────────────────
#  编排入口
# ──────────────────────────────────────────────

def _query_filllight_cam(cam) -> FilllightQueryResult:
    """SK 私有协议补光查询：能力 + 当前值。"""
    _log(f"[SK] 尝试补光私有协议 {cam.ip}:{_SK_IMAGE_PORT}")
    opt = _sk_filllight_option(cam)
    if not opt["ok"]:
        if opt.get("status") is None:
            return _sk_err(FilllightQueryResult, "DEVICE_UNREACHABLE",
                           f"无法连接 {cam.ip}:{_SK_IMAGE_PORT}（SK HTTP 无响应）",
                           "确认摄像头在线、网络可达，且已注册正确凭据", camera=cam.name)
        return _sk_err(FilllightQueryResult, "OPTION_QUERY_FAILED",
                       f"查询补光能力失败（code={opt.get('code') or '404'}）",
                       "确认设备固件版本是否支持补光设置", camera=cam.name)
    cur = _sk_filllight_cur(cam)
    if not cur["ok"]:
        return _sk_err(FilllightQueryResult, "CURRENT_QUERY_FAILED",
                       f"查询补光当前值失败（code={cur['code']}）", camera=cam.name)
    # 对外仅上报白名单参数：能力清单与当前值都过滤
    caps = [c for c in opt["capabilities"]
            if isinstance(c, dict) and str(c.get("name", "")) in _SK_FILLLIGHT_SUPPORTED]
    current = {k: v for k, v in cur["current"].items() if k in _SK_FILLLIGHT_SUPPORTED}
    return FilllightQueryResult(
        ok=True, camera=cam.name, channel="sk",
        capabilities=_merge_capabilities(caps, current,
                                         _SK_FILLLIGHT_LABELS, _SK_FILLLIGHT_VALUE_TEXTS),
        current=current,
    )


def _set_filllight_cam(cam, updates: Dict[str, Any]) -> FilllightSetResult:
    """SK 私有协议补光设置。"""
    _log(f"[SK] 尝试补光私有协议设置 {cam.ip}:{_SK_IMAGE_PORT}")
    return _sk_filllight_set(cam, updates)


def big_filllight_query(
    name: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> FilllightQueryResult:
    """
    查询 IPC 夜视补光设置：能力清单 + 当前值（协议 5.2.1 / 5.2.3）。

    SK 私有协议（动态 Token 鉴权），返回补光能力与当前值（仅 daynightmode/filllightmode）。
    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:    摄像头名称（None 时走 resolve_target 降级：唯一一台直接用）
        answers: NEEDS_INPUT 重调时的回答 dict

    Returns:
        FilllightQueryResult:
            ok=True:  capabilities 能力列表；current 当前值；channel="sk"
            ok=False: error_code + message + hint
    """
    err, cam = _sk_resolve_camera(name, answers, FilllightQueryResult)
    if err:
        _log(f"补光查询终止：resolve_target 失败 error_code={err.error_code}")
        return err
    _log(f"===== 补光查询开始 camera={cam.name} ip={cam.ip} =====")
    result = _query_filllight_cam(cam)
    _log(f"===== 补光查询结束 ok={result.ok} channel={result.channel} error_code={result.error_code} =====")
    return result


def big_filllight_set(
    name: Optional[str] = None,
    daynightmode=None,
    filllightmode=None,
    answers: Optional[Dict[str, Any]] = None,
) -> FilllightSetResult:
    """
    设置 IPC 夜视补光参数（协议 5.2.2 SK_SETTING_SET_FILLLIGHT，读-校验-合并-写-回读）。

    仅支持 daynightmode/filllightmode 两个参数（多数设备只支持这两项调节）；
    枚举参数接受整数或字符串别名（如 daynightmode='auto' 或 2）。
    可独立调试：直接调用本函数即可，无需 MCP。

    Args:
        name:           摄像头名称（None 时走 resolve_target 降级）
        daynightmode:   开灯设置 0白天/1夜晚/2自动/3定时/4智能（别名 day/night/auto/timer/smart）
        filllightmode:  补光方式 0全彩/1红外/2智能夜视（别名 color/ir/smart）
        answers:        NEEDS_INPUT 重调时的回答 dict

    Returns:
        FilllightSetResult:
            ok=True:  updated 生效字段；current 当前值（仅白名单参数）；channel="sk"
            ok=False: error_code + message + hint
    """
    updates: Dict[str, Any] = {}
    for k, v, aliases in (("daynightmode", daynightmode, _SK_DAYNIGHT_ALIASES),
                          ("filllightmode", filllightmode, _SK_FILLMODE_ALIASES)):
        if v is None:
            continue
        okv, val, err = _enum_coerce(v, aliases, k, FilllightSetResult)
        if not okv:
            return err
        updates[k] = val
    if not updates:
        return _sk_err(FilllightSetResult, "NO_PARAMS", "未传入任何要修改的补光参数",
                       "至少传一个参数，如 daynightmode='auto'；可先调 big_filllight_query 查看可设置项")

    err, cam = _sk_resolve_camera(name, answers, FilllightSetResult)
    if err:
        _log(f"补光设置终止：resolve_target 失败 error_code={err.error_code}")
        return err
    _log(f"===== 补光设置开始 camera={cam.name} ip={cam.ip} updates={updates} =====")
    result = _set_filllight_cam(cam, updates)
    _log(f"===== 补光设置结束 ok={result.ok} channel={result.channel} error_code={result.error_code} =====")
    return result


# ──────────────────────────────────────────────
#  高级封装：manage_illumination / probe_illumination_capability
# ──────────────────────────────────────────────

def manage_illumination(
    action: IlluminationAction = IlluminationAction.QUERY,
    camera_name: Optional[str] = None,
    name: Optional[str] = None,
    daynightmode=None,
    filllightmode=None,
    answers: Optional[Dict[str, Any]] = None,
):
    """
    统一补光管理入口：根据 action 分发到查询或设置。

    仅支持 daynightmode/filllightmode 两个参数（多数设备只支持这两项调节）。

    Args:
        action:         操作类型 (IlluminationAction: get / set)
        camera_name:    摄像头名称（MCP 层传入，优先使用）
        name:           摄像头名称（内部调用兼容）
        daynightmode:   开灯设置（仅 SET）
        filllightmode:  补光方式（仅 SET）
        answers:        NEEDS_INPUT 重调时的回答 dict

    Returns:
        FilllightQueryResult (action=get) 或 FilllightSetResult (action=set)
    """
    # camera_name 与 name 统一归并：MCP 传 camera_name，内部可调 name
    resolved_name = camera_name or name

    if action == IlluminationAction.QUERY:
        return big_filllight_query(name=resolved_name, answers=answers)
    elif action == IlluminationAction.SET:
        return big_filllight_set(
            name=resolved_name,
            daynightmode=daynightmode,
            filllightmode=filllightmode,
            answers=answers,
        )
    else:
        return FilllightSetResult(ok=False, error_code="INVALID_ACTION",
                                  message=f"不支持的操作：{action}")


def probe_illumination_capability(
    name: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> FilllightQueryResult:
    """
    探测摄像头补光能力：返回设备支持的补光参数列表与当前值。

    等价于 big_filllight_query 的别名，用于连接后自动探测补光能力。

    Args:
        name:    摄像头名称
        answers: NEEDS_INPUT 重调时的回答 dict

    Returns:
        FilllightQueryResult
    """
    return big_filllight_query(name=name, answers=answers)
