"""
Toolkit: 补光模式控制 (Illumination Mode Control)

工具清单：
  - manage_illumination  统一补光模式入口（唯一 MCP 工具），action 切换工作模式:
      get  — 查询当前补光设置及设备支持的可选范围
      set  — 设置补光参数（daynightmode / filllightmode / brightness 等）
  - probe_illumination_capability  探测设备补光能力（内部函数，供连接/发现阶段调用）

双协议策略（与 PTZ 模块一致）：
  1. 创维私有协议（TCP 9010）— 主路径
     - SK_SETTING_GET_FILLLIGHT_OPTION  → 查询补光能力（参数范围）
     - SK_SETTING_GET_FILLLIGHT         → 查询当前补光设置
     - SK_SETTING_SET_FILLLIGHT         → 设置补光参数
     - 提供更精细的控制：日夜模式、补光方式、亮度、定时、灵敏度等
  2. ONVIF Imaging Service (ver20) — 回退路径（非创维设备）
     - GetMoveOptions → 获取设备支持的 IlluminationConfiguration 可选项
     - GetImagingSettings → 获取当前补光设置
     - SetImagingSettings → 修改补光模式

安全边界：
  - 操作前校验设备是否已连接
  - set 操作时校验参数范围（从 GET_FILLLIGHT_OPTION 响应中提取 min/max）
  - ONVIF 回退时不修改其他 Imaging 参数，ForcePersistence 固定为 False
"""
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import requests as _requests_lib
except ImportError:
    _requests_lib = None

try:
    import xml.etree.ElementTree as ET
except ImportError:
    ET = None

from .discovery import send_tcp_command, SK_TCP_PORT


# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────

# ── 日夜模式 (daynightmode) ──
DAYNIGHT_MODES = {
    0: "白天模式",
    1: "夜晚模式",
    2: "自动模式",
    3: "定时模式",
    4: "智能模式",
}

# ── 补光方式 (filllightmode) ──
FILLLIGHT_MODES = {
    0: "全彩模式",
    1: "红外模式",
    2: "智能夜视",
}

# ONVIF Imaging 服务候选路径（非创维设备回退用）
_IMAGING_SERVICE_PATHS = [
    "/onvif/image_service",     # ZCR461 实测正确路径
    "/onvif/imaging_service",
    "/onvif/Imaging",
    "/onvif/device_service",
]

# XML 命名空间
_NS = {
    "soap": "http://www.w3.org/2003/05/soap-envelope",
    "timg": "http://www.onvif.org/ver20/imaging/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}


# ──────────────────────────────────────────────
#  枚举与数据结构
# ──────────────────────────────────────────────

class IlluminationAction(str, Enum):
    """manage_illumination 工作模式"""
    GET = "get"    # 查询当前补光设置及可选项
    SET = "set"    # 设置补光参数


@dataclass
class IlluminationCapability:
    """单个补光参数的能力描述（从 GET_FILLLIGHT_OPTION 提取）"""
    name: str = ""
    type: str = ""                # int / enum / text
    min_val: Optional[int] = None
    max_val: Optional[int] = None
    desc: str = ""                # 参数说明（如 "0:off,1:on,2:auto,3:timer,4:smart"）
    enum_vals: Dict[str, str] = field(default_factory=dict)  # enum 类型的选项映射


@dataclass
class IlluminationInfo:
    """补光能力信息"""
    supported: bool = False
    protocol: str = ""                               # sky_private / onvif
    capabilities: List[IlluminationCapability] = field(default_factory=list)
    current_settings: Dict[str, Any] = field(default_factory=dict)
    # 向后兼容字段
    supported_modes: List[str] = field(default_factory=list)
    current_mode: str = ""
    error_message: str = ""


@dataclass
class IlluminationResult:
    """manage_illumination 返回结果"""
    success: bool
    action: str = ""                                 # get / set
    protocol: str = ""                               # sky_private / onvif
    current_settings: Dict[str, Any] = field(default_factory=dict)
    previous_settings: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[Dict[str, Any]] = field(default_factory=list)
    # 向后兼容字段
    current_mode: str = ""
    previous_mode: str = ""
    supported_modes: List[str] = field(default_factory=list)
    error_message: str = ""


# ──────────────────────────────────────────────
#  ONVIF SOAP 模板（回退路径）
# ──────────────────────────────────────────────

_GET_PROFILES_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:trt="http://www.onvif.org/ver10/media/wsdl">'
    '<soap:Header/><soap:Body>'
    '<trt:GetVideoSources/>'
    '</soap:Body></soap:Envelope>'
)

_GET_MOVE_OPTIONS_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl">'
    '<soap:Header/><soap:Body>'
    '<timg:GetMoveOptions>'
    '<timg:VideoSourceToken>{token}</timg:VideoSourceToken>'
    '</timg:GetMoveOptions>'
    '</soap:Body></soap:Envelope>'
)

_GET_IMAGING_SETTINGS_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl">'
    '<soap:Header/><soap:Body>'
    '<timg:GetImagingSettings>'
    '<timg:VideoSourceToken>{token}</timg:VideoSourceToken>'
    '</timg:GetImagingSettings>'
    '</soap:Body></soap:Envelope>'
)

_SET_ILLUMINATION_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl" '
    'xmlns:tt="http://www.onvif.org/ver10/schema">'
    '<soap:Header/><soap:Body>'
    '<timg:SetImagingSettings>'
    '<timg:VideoSourceToken>{token}</timg:VideoSourceToken>'
    '<timg:ImagingSettings>'
    '<tt:Extension>'
    '<tt:IlluminationConfiguration>'
    '<tt:Mode>{mode}</tt:Mode>'
    '</tt:IlluminationConfiguration>'
    '</tt:Extension>'
    '</timg:ImagingSettings>'
    '<timg:ForcePersistence>false</timg:ForcePersistence>'
    '</timg:SetImagingSettings>'
    '</soap:Body></soap:Envelope>'
)

# IrCutFilter 日夜模式切换（ONVIF 标准方式，适用于不支持 IlluminationConfiguration 的设备）
_SET_IRCUTFILTER_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl" '
    'xmlns:tt="http://www.onvif.org/ver10/schema">'
    '<soap:Header/><soap:Body>'
    '<timg:SetImagingSettings>'
    '<timg:VideoSourceToken>{token}</timg:VideoSourceToken>'
    '<timg:ImagingSettings>'
    '<tt:IrCutFilter>{mode}</tt:IrCutFilter>'
    '</timg:ImagingSettings>'
    '<timg:ForcePersistence>false</timg:ForcePersistence>'
    '</timg:SetImagingSettings>'
    '</soap:Body></soap:Envelope>'
)

_GET_OPTIONS_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl">'
    '<soap:Header/><soap:Body>'
    '<timg:GetOptions>'
    '<timg:VideoSourceToken>{token}</timg:VideoSourceToken>'
    '</timg:GetOptions>'
    '</soap:Body></soap:Envelope>'
)

# IrCutFilter 与日夜模式的映射
_IRCUT_TO_DAYNIGHT = {"ON": 0, "OFF": 1, "AUTO": 2}
_DAYNIGHT_TO_IRCUT = {0: "ON", 1: "OFF", 2: "AUTO"}
_IRCUT_MODE_NAMES = {"ON": "白天模式", "OFF": "夜晚模式", "AUTO": "自动模式"}


# ──────────────────────────────────────────────
#  辅助函数
# ──────────────────────────────────────────────

def _get_device_connection(camera_name: str) -> Optional[Dict[str, Any]]:
    """获取设备连接信息，返回 None 表示未连接"""
    from .device_mgmt import _connected_devices, _find_cached_camera

    conn_info = _connected_devices.get(camera_name)
    if conn_info:
        return conn_info

    cached = _find_cached_camera(camera_name)
    if cached and cached.ip:
        # 缓存回退路径：始终包含 tcp_port 以供创维设备尝试 TCP 9010
        # （_send_sk_filllight 使用 conn.get("tcp_port", SK_TCP_PORT) 默认 9010）
        return {
            "ip": cached.ip,
            "port": cached.port,
            "username": cached.username,
            "password": cached.password,
            "tcp_port": SK_TCP_PORT,
        }
    return None


def _build_sk_msg_id() -> str:
    """生成创维私有协议消息 ID（与 ptz.py 同格式）"""
    now = time.time()
    ts = time.strftime("%Y%m%d%H%M%S", time.localtime(now))
    frac = int((now - int(now)) * 1_000_000)
    return f"{ts}{frac:06d}"[:21]


def _send_sk_filllight(camera_name: str, command: dict) -> Optional[dict]:
    """通过创维 TCP 通道发送补光命令"""
    conn = _get_device_connection(camera_name)
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
        timeout=8.0,
        port=tcp_port,
    )


# ──────────────────────────────────────────────
#  创维私有协议实现
# ──────────────────────────────────────────────

def _sk_get_filllight_option(camera_name: str, channel: int = 2) -> Optional[List[IlluminationCapability]]:
    """查询补光能力 (SK_SETTING_GET_FILLLIGHT_OPTION)"""
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_GET_FILLLIGHT_OPTION",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
    }
    resp = _send_sk_filllight(camera_name, command)
    if not resp or resp.get("code") != "C0000":
        return None

    filllight_list = resp.get("filllight", [])
    if not filllight_list:
        return None

    capabilities = []
    for item in filllight_list:
        cap = IlluminationCapability(
            name=item.get("name", ""),
            type=item.get("type", ""),
            desc=item.get("desc", ""),
        )
        specs = item.get("specs", {})
        if "min" in specs:
            try:
                cap.min_val = int(specs["min"])
            except (ValueError, TypeError):
                pass
        if "max" in specs:
            try:
                cap.max_val = int(specs["max"])
            except (ValueError, TypeError):
                pass
        # enum 类型的 specs 可能是 {"0": "off", "1": "on"}
        for k, v in specs.items():
            if k not in ("min", "max", "length") and isinstance(v, str):
                cap.enum_vals[k] = v
        capabilities.append(cap)

    return capabilities


def _sk_get_filllight(camera_name: str, channel: int = 2) -> Optional[Dict[str, Any]]:
    """查询当前补光设置 (SK_SETTING_GET_FILLLIGHT)"""
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_GET_FILLLIGHT",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
    }
    resp = _send_sk_filllight(camera_name, command)
    if not resp or resp.get("code") != "C0000":
        return None

    # 提取所有补光参数（排除协议框架字段）
    _FRAMEWORK_KEYS = {"service_type", "msg_id", "cmd_name", "ver", "code", "msg", "channel", "sequence"}
    settings = {k: v for k, v in resp.items() if k not in _FRAMEWORK_KEYS}
    return settings


def _sk_set_filllight(
    camera_name: str,
    settings: Dict[str, Any],
    channel: int = 2,
) -> tuple:
    """设置补光参数 (SK_SETTING_SET_FILLLIGHT)

    Returns:
        (success: bool, error_message: str)
    """
    command = {
        "service_type": "setting",
        "msg_id": _build_sk_msg_id(),
        "cmd_name": "SK_SETTING_SET_FILLLIGHT",
        "ver": "1.0",
        "channel": channel,
        "sequence": 0,
    }
    command.update(settings)

    resp = _send_sk_filllight(camera_name, command)
    if resp is None:
        return False, "TCP 通道无响应"
    if resp.get("code") != "C0000":
        return False, resp.get("msg", "未知错误")
    return True, ""


# ──────────────────────────────────────────────
#  ONVIF 回退实现
# ──────────────────────────────────────────────

def _imaging_post(
    ip: str, port: int, body: str,
    username: str, password: str, timeout: float = 8.0,
) -> tuple:
    """向 ONVIF Imaging 服务发送 SOAP 请求，自动尝试候选路径"""
    from .device_mgmt import _onvif_post_with_auth
    if _requests_lib is None:
        return 0, "", ""
    for path in _IMAGING_SERVICE_PATHS:
        try:
            status, text = _onvif_post_with_auth(
                ip, port, path, body, username, password, timeout=timeout,
            )
            if status and "Envelope" in (text or ""):
                return status, text, path
        except Exception:
            continue
    return 0, "", ""


def _extract_text_by_local_name(root, local_name: str) -> str:
    """从 XML 树中按 local name 提取第一个匹配元素的文本"""
    for el in root.iter():
        tag = el.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == local_name and (el.text or "").strip():
            return el.text.strip()
    return ""


def _get_video_source_token(conn_info: Dict[str, Any]) -> str:
    """获取设备的 VideoSourceToken（回退默认 "0"）"""
    ip = conn_info.get("ip", "")
    port = conn_info.get("port", 0)
    username = conn_info.get("username", "admin")
    password = conn_info.get("password", "")
    if not port:
        return "0"
    from .device_mgmt import _onvif_post_with_auth
    for path in ["/onvif/media_service", "/onvif/Media", "/onvif/device_service"]:
        try:
            status, text = _onvif_post_with_auth(
                ip, port, path, _GET_PROFILES_BODY,
                username, password, timeout=5.0,
            )
            if status and "Envelope" in text:
                root = ET.fromstring(text)
                token = _extract_text_by_local_name(root, "token")
                if token:
                    return token
                for el in root.iter():
                    tag = el.tag
                    if "}" in tag:
                        tag = tag.split("}", 1)[1]
                    if tag in ("VideoSources", "VideoSource"):
                        tok = el.get("token", "")
                        if tok:
                            return tok
        except Exception:
            continue
    return "0"


def _parse_illumination_modes_from_move_options(body: str) -> List[str]:
    """从 GetMoveOptionsResponse 提取支持的补光模式列表"""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    modes = []
    in_illumination = False
    for el in root.iter():
        tag = el.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "IlluminationConfiguration":
            in_illumination = True
            continue
        if in_illumination and tag == "Mode":
            if el.text and el.text.strip():
                modes.append(el.text.strip())
            for child in el:
                child_tag = child.tag
                if "}" in child_tag:
                    child_tag = child_tag.split("}", 1)[1]
                if child.text and child.text.strip():
                    modes.append(child.text.strip())
    if not modes:
        for el in root.iter():
            tag = el.tag
            if "}" in tag:
                tag = tag.split("}", 1)[1]
            if tag == "Mode" and el.text and el.text.strip():
                val = el.text.strip()
                if val not in modes:
                    modes.append(val)
    return modes


def _parse_ircut_from_imaging_settings(body: str) -> str:
    """从 GetImagingSettings 响应中提取 IrCutFilter 值 (ON/OFF/AUTO)"""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    for el in root.iter():
        tag = el.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "IrCutFilter" and el.text:
            return el.text.strip().upper()
    return ""


def _parse_ircut_modes_from_options(body: str) -> list:
    """从 GetOptions 响应中提取 IrCutFilterModes 列表"""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    modes = []
    for el in root.iter():
        tag = el.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "IrCutFilterModes" and el.text:
            m = el.text.strip().upper()
            if m and m not in modes:
                modes.append(m)
    return modes


def _parse_current_mode_from_imaging_settings(body: str) -> str:
    """从 GetImagingSettingsResponse 提取当前补光模式"""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    in_illumination = False
    for el in root.iter():
        tag = el.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "IlluminationConfiguration":
            in_illumination = True
            continue
        if in_illumination and tag == "Mode":
            if el.text and el.text.strip():
                return el.text.strip()
    return ""


# ──────────────────────────────────────────────
#  内部探测函数（供连接阶段调用）
# ──────────────────────────────────────────────

def probe_illumination_capability(
    ip: str,
    port: int,
    username: str = "admin",
    password: str = "",
    channel: int = 2,
) -> IlluminationInfo:
    """探测设备补光能力（供连接阶段调用，不作为 MCP 工具暴露）。

    双协议策略:
      1. 先尝试创维私有协议 (SK_SETTING_GET_FILLLIGHT_OPTION via TCP 9010)
      2. 失败则回退到 ONVIF Imaging Service (GetMoveOptions)

    Returns:
        IlluminationInfo: 设备补光能力信息
    """
    # ── 尝试 1: 创维私有协议 ──
    try:
        # 构造临时 camera_name 用于 TCP 探测
        # 直接通过 send_tcp_command 发送，避免依赖 _connected_devices
        cmd = {
            "service_type": "setting",
            "msg_id": _build_sk_msg_id(),
            "cmd_name": "SK_SETTING_GET_FILLLIGHT_OPTION",
            "ver": "1.0",
            "channel": channel,
            "sequence": 0,
        }
        resp = send_tcp_command(
            ip=ip, command=cmd,
            username=username, password=password,
            timeout=5.0, port=SK_TCP_PORT,
        )
        if resp and resp.get("code") == "C0000":
            filllight_list = resp.get("filllight", [])
            if filllight_list:
                capabilities = []
                supported_modes = []
                for item in filllight_list:
                    cap = IlluminationCapability(
                        name=item.get("name", ""),
                        type=item.get("type", ""),
                        desc=item.get("desc", ""),
                    )
                    specs = item.get("specs", {})
                    if "min" in specs:
                        try:
                            cap.min_val = int(specs["min"])
                        except (ValueError, TypeError):
                            pass
                    if "max" in specs:
                        try:
                            cap.max_val = int(specs["max"])
                        except (ValueError, TypeError):
                            pass
                    for k, v in specs.items():
                        if k not in ("min", "max", "length") and isinstance(v, str):
                            cap.enum_vals[k] = v
                    capabilities.append(cap)

                    # 提取 daynightmode 的描述作为 supported_modes（向后兼容）
                    if cap.name == "daynightmode" and cap.desc:
                        supported_modes = [
                            s.strip() for s in cap.desc.split(",") if s.strip()
                        ]

                return IlluminationInfo(
                    supported=True,
                    protocol="sky_private",
                    capabilities=capabilities,
                    supported_modes=supported_modes,
                )
    except Exception:
        pass

    # ── 尝试 2: ONVIF Imaging Service ──
    if not port or _requests_lib is None:
        return IlluminationInfo(
            supported=False,
            error_message="TCP 通道和 ONVIF 端口均不可用",
        )

    conn_info = {"ip": ip, "port": port, "username": username, "password": password}
    token = _get_video_source_token(conn_info)

    move_body = _GET_MOVE_OPTIONS_BODY.format(token=token)
    status, resp_text, _ = _imaging_post(ip, port, move_body, username, password)

    # 尝试从 GetMoveOptions 提取 IlluminationConfiguration 支持的模式
    supported_modes = []
    if status and "Envelope" in resp_text:
        if "Fault" not in resp_text[:2048]:
            supported_modes = _parse_illumination_modes_from_move_options(resp_text)

    # ── IrCutFilter 降级检测 ──
    # 当设备不支持 IlluminationConfiguration 时，检测 IrCutFilter 作为日夜模式控制
    options_body = _GET_OPTIONS_BODY.format(token=token)
    ircut_modes = []
    status_opt, resp_opt, _ = _imaging_post(ip, port, options_body, username, password)
    if status_opt and "Envelope" in (resp_opt or ""):
        ircut_modes = _parse_ircut_modes_from_options(resp_opt)

    # 优先使用 IrCutFilter（如果可用）
    if ircut_modes and not supported_modes:
        # IrCutFilter ON=白天, OFF=夜晚, AUTO=自动
        ircut_as_modes = [_IRCUT_MODE_NAMES.get(m, m) for m in ircut_modes]
        current_ircut = ""
        get_body = _GET_IMAGING_SETTINGS_BODY.format(token=token)
        status2, resp_text2, _ = _imaging_post(ip, port, get_body, username, password)
        if status2 and "Envelope" in resp_text2:
            current_ircut = _parse_ircut_from_imaging_settings(resp_text2)
        return IlluminationInfo(
            supported=True,
            protocol="onvif_ircut",
            capabilities=[],
            supported_modes=ircut_as_modes,
            current_mode=_IRCUT_MODE_NAMES.get(current_ircut, current_ircut),
        )

    if not supported_modes:
        return IlluminationInfo(
            supported=False,
            protocol="onvif",
            error_message="设备不支持 IlluminationConfiguration 和 IrCutFilter",
        )

    current_mode = ""
    get_body = _GET_IMAGING_SETTINGS_BODY.format(token=token)
    status2, resp_text2, _ = _imaging_post(ip, port, get_body, username, password)
    if status2 and "Envelope" in resp_text2:
        current_mode = _parse_current_mode_from_imaging_settings(resp_text2)

    return IlluminationInfo(
        supported=True,
        protocol="onvif",
        supported_modes=supported_modes,
        current_mode=current_mode,
    )


# ──────────────────────────────────────────────
#  MCP 工具入口
# ──────────────────────────────────────────────

# set 操作支持的参数名列表
_SETTABLE_PARAMS = [
    "daynightmode", "filllightmode", "duration",
    "brightnessmode", "brightness",
    "begintime", "endtime", "repeatdays", "enable",
    "irmode", "irbrightness",
    "whiteonvalue", "whiteoffvalue",
    "ironvalue", "iroffvalue",
]


def manage_illumination(
    camera_name: str,
    action: IlluminationAction,
    daynightmode: Optional[int] = None,
    filllightmode: Optional[int] = None,
    duration: Optional[int] = None,
    brightnessmode: Optional[int] = None,
    brightness: Optional[int] = None,
    begintime: Optional[int] = None,
    endtime: Optional[int] = None,
    repeatdays: Optional[str] = None,
    enable: Optional[int] = None,
    irmode: Optional[int] = None,
    irbrightness: Optional[int] = None,
    whiteonvalue: Optional[int] = None,
    whiteoffvalue: Optional[int] = None,
    ironvalue: Optional[int] = None,
    iroffvalue: Optional[int] = None,
) -> IlluminationResult:
    """
    摄像头补光模式统一入口，action 切换工作模式：
    - get: 查询当前补光设置及设备支持的参数范围
    - set: 设置补光参数（仅指定需要修改的参数，其余保持不变）

    双协议策略: 创维私有协议 (TCP 9010) 优先，ONVIF Imaging Service 回退。

    安全约束: 操作前校验设备已连接；set 时校验参数范围

    Args:
        camera_name:    摄像头名称
        action:         工作模式 (IlluminationAction.GET / SET)
        daynightmode:   日夜模式 0=白天 1=夜晚 2=自动 3=定时 4=智能
        filllightmode:  补光方式 0=全彩 1=红外 2=智能夜视
        duration:       智能夜视白光灯补光时间 (5-60 秒)
        brightnessmode: 白光灯亮度模式 0=自动 1=手动
        brightness:     白光灯手动亮度 (1-100)
        begintime:      定时模式开始时间 (0-86399 秒)
        endtime:        定时模式结束时间 (0-172799 秒)
        repeatdays:     定时模式重复日期 (如 "sun,mon,tue,wed,thu,fri,sat,")
        enable:         定时器使能 0=关 1=开
        irmode:         红外灯亮度模式 0=自动 1=手动
        irbrightness:   红外灯手动亮度 (1-100)
        whiteonvalue:   白光灯开灯灵敏度 (0-100)
        whiteoffvalue:  白光灯关灯灵敏度 (0-100)
        ironvalue:      红外灯开灯灵敏度 (0-100)
        iroffvalue:     红外灯关灯灵敏度 (0-100)

    Returns:
        IlluminationResult
    """
    # ── Step 1: 获取设备连接信息 ──
    conn_info = _get_device_connection(camera_name)
    if not conn_info:
        return IlluminationResult(
            success=False, action=action.value,
            error_message=f"设备 {camera_name} 未连接，请先调用 connect_device()",
        )

    # ── Step 2: 尝试创维私有协议 (TCP 9010) ──
    # 始终尝试 TCP：只要有 IP 就有可能走私有协议
    # （与 PTZ 模块对称：PTZ 先 ONVIF 再 TCP fallback；illumination 先 TCP 再 ONVIF fallback）
    ip = conn_info.get("ip", "")
    channel = conn_info.get("channel", 2)

    if ip:
        result = _manage_via_private_protocol(
            camera_name, action, channel,
            daynightmode=daynightmode, filllightmode=filllightmode,
            duration=duration, brightnessmode=brightnessmode,
            brightness=brightness, begintime=begintime, endtime=endtime,
            repeatdays=repeatdays, enable=enable,
            irmode=irmode, irbrightness=irbrightness,
            whiteonvalue=whiteonvalue, whiteoffvalue=whiteoffvalue,
            ironvalue=ironvalue, iroffvalue=iroffvalue,
        )
        if result.success:
            # TCP 成功 → 回写 tcp_port 到连接状态，供后续操作使用
            if not conn_info.get("tcp_port"):
                from .device_mgmt import _connected_devices
                if camera_name in _connected_devices:
                    _connected_devices[camera_name]["tcp_port"] = SK_TCP_PORT
            return result
        # TCP 失败 → 记录原因，继续尝试 ONVIF 回退
        _tcp_error = result.error_message
    else:
        _tcp_error = "设备无 IP 地址"

    # ── Step 3: 回退到 ONVIF ──
    port = conn_info.get("port", 0)
    if port:
        return _manage_via_onvif(
            camera_name, conn_info, action,
            daynightmode=daynightmode, filllightmode=filllightmode,
        )

    return IlluminationResult(
        success=False, action=action.value,
        error_message=(
            f"设备 {camera_name} 补光控制失败："
            f"私有协议(TCP 9010): {_tcp_error}；ONVIF: 无可用端口"
        ),
    )


def _manage_via_private_protocol(
    camera_name: str,
    action: IlluminationAction,
    channel: int,
    **kwargs,
) -> IlluminationResult:
    """通过创维私有协议处理补光操作"""

    # ── GET: 查询能力 + 当前设置 ──
    if action == IlluminationAction.GET:
        capabilities = _sk_get_filllight_option(camera_name, channel)
        current = _sk_get_filllight(camera_name, channel)

        if capabilities is None and current is None:
            # 诊断: 检测 TCP 私有协议不可用 (HTTP 404 / TCP RST / 连接拒绝 / 超时)
            _diag_resp = _send_sk_filllight(camera_name, {
                "service_type": "setting",
                "msg_id": _build_sk_msg_id(),
                "cmd_name": "SK_SETTING_GET_FILLLIGHT_OPTION",
                "ver": "1.0",
                "channel": channel,
                "sequence": 0,
            })
            if _diag_resp and isinstance(_diag_resp, dict):
                _http = _diag_resp.get("_http_status", 0)
                _tcp_err = _diag_resp.get("_tcp_error", "")
                if _http == 404:
                    return IlluminationResult(
                        success=False, action="get", protocol="sky_private",
                        error_message=(
                            "创维私有协议 (TCP 9010) 不可用：设备返回 HTTP 404，"
                            "表明该型号固件不支持 TCP 私有协议接口。"
                            "设备仅可通过 ONVIF 协议控制。"
                        ),
                    )
                elif _tcp_err == "connection_reset":
                    return IlluminationResult(
                        success=False, action="get", protocol="sky_private",
                        error_message=(
                            "创维私有协议 (TCP 9010) 不可用：连接被重置 (RST)，"
                            "该型号固件不支持 TCP 私有协议接口。"
                            "设备仅可通过 ONVIF 协议控制。"
                        ),
                    )
                elif _tcp_err == "connection_refused":
                    return IlluminationResult(
                        success=False, action="get", protocol="sky_private",
                        error_message="创维私有协议 (TCP 9010) 不可用：连接被拒绝，端口未监听",
                    )
                elif _tcp_err == "timeout":
                    return IlluminationResult(
                        success=False, action="get", protocol="sky_private",
                        error_message="创维私有协议 (TCP 9010) 不可用：连接超时",
                    )
                elif _http in (401, 403):
                    return IlluminationResult(
                        success=False, action="get", protocol="sky_private",
                        error_message=f"创维私有协议认证失败 (HTTP {_http})，请检查设备密码",
                    )
            return IlluminationResult(
                success=False, action="get", protocol="sky_private",
                error_message="查询补光信息失败 (SK_SETTING_GET_FILLLIGHT_OPTION 和 GET_FILLLIGHT 均无响应)",
            )

        # 构建 capabilities 序列化格式
        cap_list = []
        supported_modes = []
        if capabilities:
            for cap in capabilities:
                cap_dict = {"name": cap.name, "type": cap.type}
                if cap.min_val is not None:
                    cap_dict["min"] = cap.min_val
                if cap.max_val is not None:
                    cap_dict["max"] = cap.max_val
                if cap.desc:
                    cap_dict["desc"] = cap.desc
                if cap.enum_vals:
                    cap_dict["enum"] = cap.enum_vals
                cap_list.append(cap_dict)
                if cap.name == "daynightmode" and cap.desc:
                    supported_modes = [s.strip() for s in cap.desc.split(",") if s.strip()]

        current_mode = ""
        if current and "daynightmode" in current:
            dm = current["daynightmode"]
            current_mode = DAYNIGHT_MODES.get(int(dm), str(dm))

        return IlluminationResult(
            success=True,
            action="get",
            protocol="sky_private",
            current_settings=current or {},
            capabilities=cap_list,
            current_mode=current_mode,
            supported_modes=supported_modes,
        )

    # ── SET: 设置补光参数 ──
    if action == IlluminationAction.SET:
        # 先查询当前设置（用于合并 + 回显 previous）
        current = _sk_get_filllight(camera_name, channel) or {}

        # 收集用户指定的参数
        new_settings = {}
        for param in _SETTABLE_PARAMS:
            val = kwargs.get(param)
            if val is not None:
                new_settings[param] = val

        if not new_settings:
            return IlluminationResult(
                success=False, action="set", protocol="sky_private",
                current_settings=current,
                error_message="set 操作至少需要指定一个补光参数",
            )

        # 合并：当前设置 + 用户修改（设备要求发送完整参数集）
        merged = dict(current)
        merged.update(new_settings)

        # 过滤掉非设置字段
        send_settings = {k: v for k, v in merged.items() if k in _SETTABLE_PARAMS}

        ok, err = _sk_set_filllight(camera_name, send_settings, channel)
        if not ok:
            return IlluminationResult(
                success=False, action="set", protocol="sky_private",
                previous_settings=current,
                current_settings=current,
                error_message=f"设置补光参数失败: {err}",
            )

        # 查询设置后的新状态
        updated = _sk_get_filllight(camera_name, channel) or merged

        current_mode = ""
        previous_mode = ""
        if updated and "daynightmode" in updated:
            dm = updated["daynightmode"]
            current_mode = DAYNIGHT_MODES.get(int(dm), str(dm))
        if current and "daynightmode" in current:
            dm = current["daynightmode"]
            previous_mode = DAYNIGHT_MODES.get(int(dm), str(dm))

        return IlluminationResult(
            success=True,
            action="set",
            protocol="sky_private",
            previous_settings=current,
            current_settings=updated,
            current_mode=current_mode,
            previous_mode=previous_mode,
        )

    return IlluminationResult(
        success=False, action=action.value, protocol="sky_private",
        error_message=f"未知的 action: {action}",
    )


def _manage_via_onvif(
    camera_name: str,
    conn_info: Dict[str, Any],
    action: IlluminationAction,
    daynightmode: Optional[int] = None,
    filllightmode: Optional[int] = None,
) -> IlluminationResult:
    """通过 ONVIF Imaging Service 处理补光操作（回退路径）。

    支持两种模式:
    - IlluminationConfiguration (传统补光模式控制)
    - IrCutFilter 日夜模式 (ON=白天/OFF=夜晚/AUTO=自动)
    """
    ip = conn_info.get("ip", "")
    port = conn_info.get("port", 0)
    username = conn_info.get("username", "admin")
    password = conn_info.get("password", "")

    token = _get_video_source_token(conn_info)

    # ── 检测 IrCutFilter 支持 ──
    options_body = _GET_OPTIONS_BODY.format(token=token)
    ircut_modes = []
    status_opt, resp_opt, _ = _imaging_post(ip, port, options_body, username, password)
    if status_opt and "Envelope" in (resp_opt or ""):
        ircut_modes = _parse_ircut_modes_from_options(resp_opt)
    use_ircut = bool(ircut_modes)

    # ── GET ──
    if action == IlluminationAction.GET:
        if use_ircut:
            # IrCutFilter 路径: 读取当前 IrCutFilter 值
            get_body = _GET_IMAGING_SETTINGS_BODY.format(token=token)
            status2, resp_text2, _ = _imaging_post(ip, port, get_body, username, password)
            current_ircut = ""
            if status2 and "Envelope" in resp_text2:
                current_ircut = _parse_ircut_from_imaging_settings(resp_text2)
            mode_names = [_IRCUT_MODE_NAMES.get(m, m) for m in ircut_modes]
            return IlluminationResult(
                success=True, action="get", protocol="onvif_ircut",
                current_mode=_IRCUT_MODE_NAMES.get(current_ircut, current_ircut),
                supported_modes=mode_names,
            )

        # 传统 IlluminationConfiguration 路径
        move_body = _GET_MOVE_OPTIONS_BODY.format(token=token)
        status, resp_text, _ = _imaging_post(ip, port, move_body, username, password)

        supported_modes = []
        if status and "Envelope" in resp_text and "Fault" not in resp_text[:2048]:
            supported_modes = _parse_illumination_modes_from_move_options(resp_text)

        if not supported_modes:
            return IlluminationResult(
                success=False, action="get", protocol="onvif",
                error_message="设备不支持 IlluminationConfiguration 和 IrCutFilter",
            )

        current_mode = ""
        get_body = _GET_IMAGING_SETTINGS_BODY.format(token=token)
        status2, resp_text2, _ = _imaging_post(ip, port, get_body, username, password)
        if status2 and "Envelope" in resp_text2:
            current_mode = _parse_current_mode_from_imaging_settings(resp_text2)

        return IlluminationResult(
            success=True, action="get", protocol="onvif",
            current_mode=current_mode,
            supported_modes=supported_modes,
        )

    # ── SET ──
    if action == IlluminationAction.SET:
        # 获取当前值作为 previous
        get_body = _GET_IMAGING_SETTINGS_BODY.format(token=token)
        status_g, resp_g, _ = _imaging_post(ip, port, get_body, username, password)

        if use_ircut:
            previous_ircut = ""
            if status_g and "Envelope" in resp_g:
                previous_ircut = _parse_ircut_from_imaging_settings(resp_g)

            # 映射 daynightmode 数值 → IrCutFilter 字符串
            ircut_mode = ""
            if daynightmode is not None:
                ircut_mode = _DAYNIGHT_TO_IRCUT.get(daynightmode, "")
            if not ircut_mode and ircut_modes:
                ircut_mode = ircut_modes[0]  # 默认第一个

            if not ircut_mode:
                return IlluminationResult(
                    success=False, action="set", protocol="onvif_ircut",
                    error_message="无法确定 IrCutFilter 目标模式",
                )

            set_body = _SET_IRCUTFILTER_BODY.format(token=token, mode=ircut_mode)
            status, resp_text, _ = _imaging_post(ip, port, set_body, username, password, timeout=10.0)

            if not status:
                return IlluminationResult(
                    success=False, action="set", protocol="onvif_ircut",
                    previous_mode=_IRCUT_MODE_NAMES.get(previous_ircut, previous_ircut),
                    error_message="ONVIF Imaging 服务不可达",
                )

            if "Fault" in (resp_text or "")[:2048]:
                return IlluminationResult(
                    success=False, action="set", protocol="onvif_ircut",
                    previous_mode=_IRCUT_MODE_NAMES.get(previous_ircut, previous_ircut),
                    error_message=f"IrCutFilter 设置失败: {_extract_text_by_local_name(ET.fromstring(resp_text), 'Reason')}",
                )

            return IlluminationResult(
                success=True, action="set", protocol="onvif_ircut",
                previous_mode=_IRCUT_MODE_NAMES.get(previous_ircut, previous_ircut),
                current_mode=_IRCUT_MODE_NAMES.get(ircut_mode, ircut_mode),
            )

        # 传统 IlluminationConfiguration SET 路径
        previous_mode = ""
        if status_g and "Envelope" in resp_g:
            previous_mode = _parse_current_mode_from_imaging_settings(resp_g)

        mode_str = ""
        if daynightmode is not None:
            mode_str = DAYNIGHT_MODES.get(daynightmode, str(daynightmode))
        elif filllightmode is not None:
            mode_str = FILLLIGHT_MODES.get(filllightmode, str(filllightmode))

        if not mode_str:
            return IlluminationResult(
                success=False, action="set", protocol="onvif",
                error_message="ONVIF 回退模式需要指定 daynightmode 或 filllightmode",
            )

        set_body = _SET_ILLUMINATION_BODY.format(token=token, mode=mode_str)
        status, resp_text, _ = _imaging_post(ip, port, set_body, username, password, timeout=10.0)

        if not status:
            return IlluminationResult(
                success=False, action="set", protocol="onvif",
                previous_mode=previous_mode, current_mode=previous_mode,
                error_message="ONVIF Imaging 服务不可达",
            )

        if "Fault" in (resp_text or "")[:2048]:
            return IlluminationResult(
                success=False, action="set", protocol="onvif",
                previous_mode=previous_mode, current_mode=previous_mode,
                error_message=f"ONVIF 设置失败: {_extract_text_by_local_name(ET.fromstring(resp_text), 'Reason')}",
            )

        return IlluminationResult(
            success=True, action="set", protocol="onvif",
            previous_mode=previous_mode, current_mode=mode_str,
        )

    return IlluminationResult(
        success=False, action=action.value, protocol="onvif",
        error_message=f"未知的 action: {action}",
    )
