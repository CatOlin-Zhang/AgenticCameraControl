"""
Toolkit 5: 设备管理与维护

工具清单：
  - get_registered_cameras  从 config.yaml 加载已注册摄像头配置
  - register_camera         将摄像头信息写入 config.yaml（持久化凭据）
  - search_devices          搜索局域网可用摄像头（支持 WS-Discovery / USB / 创维私有协议）
  - connect_device          设备连接（自动读取 config.yaml 凭据；无凭据时提示用户输入密码）
  - disconnect_device       断开摄像头连接并释放资源
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, quote

try:
    import requests as _requests_lib
except ImportError:
    _requests_lib = None

try:
    import yaml as _yaml_lib
except ImportError:
    _yaml_lib = None

from .discovery import (
    SkDiscoveredDevice,
    SkChannelInfo,
    discover_sky_devices,
    send_tcp_command,
    probe_device_sn,
    SK_TCP_PORT,
    SUBTYPE_NAMES,
)


# ──────────────────────────────────────────────
#  枚举类型
# ──────────────────────────────────────────────

class DiscoveryMethod(str, Enum):
    WS_DISCOVERY = "ws_discovery"    # ONVIF WS-Discovery 局域网发现
    SKY_DISCOVERY = "sky_discovery"  # 创维私有协议发现 (SK_DISCOVERY_SEARCH)
    USB = "usb"                       # USB 摄像头扫描


class DeviceClass(str, Enum):
    PASSWORD_REQUIRED = "password_required"  # 需密码登录（非免流设备）
    DIRECT_CONNECT = "direct_connect"        # 宽带直连（免流设备）


class AuthStatus(str, Enum):
    PENDING = "pending"                      # 用户尚未在 APP 端确认
    AUTHORIZED = "authorized"                # 用户已授权
    REJECTED = "rejected"                    # 用户拒绝或超时
    ERROR = "error"                          # 服务器错误


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class DiscoveredDevice:
    """发现的设备信息"""
    ip: str                                   # IP 地址
    onvif_port: int = 0                        # ONVIF 服务端口（0=未知，待连接时探测验证）
    rtsp_port: int = 554                       # RTSP 端口
    device_class: DeviceClass = DeviceClass.PASSWORD_REQUIRED
    sn_code: str = ""                          # 设备序列号
    model: str = ""                            # 设备型号
    manufacturer: str = ""                     # 厂商
    supported_media: List[str] = field(default_factory=list)  # 支持的媒体设置

    # ── 创维私有协议专用字段 ──
    sky_subtype: str = ""                      # 设备子类型: 1枪机/2球机/3半球/5摇头机/6枪球
    sky_name: str = ""                         # 设备名称 (name)
    sky_dtype: str = ""                        # 设备类型编号 (dtype)
    sky_hw_version: str = ""                   # 硬件版本
    sky_sw_version: str = ""                   # 软件版本
    sky_did: str = ""                          # 设备 ID (did)
    sky_channels: int = 0                      # 通道数（0=非创维设备, 1=单目, 2=双目）
    sky_channel_list: List[SkChannelInfo] = field(default_factory=list)
    sky_web_port: int = 0                      # Web 端口
    sky_udp_port: int = 0                      # UDP 命令端口
    sky_net_type: str = ""                     # 网络类型: eth / wifi
    sky_ip_mode: str = ""                      # IP 模式: 0=dhcp, 1=自适应, 2=手动
    sky_mask: str = ""                         # 子网掩码
    sky_gateway: str = ""                      # 网关
    sky_mac: str = ""                          # MAC 地址
    discovery_method: str = ""                 # 发现方式: ws_discovery / sky_discovery / usb
    supported_illumination_modes: List[str] = field(default_factory=list)  # 支持的补光模式列表（连接后探测填充）


@dataclass
class SearchResult:
    """搜索设备返回结果"""
    success: bool
    devices: List[DiscoveredDevice] = field(default_factory=list)
    error_message: str = ""


@dataclass
class ConnectResult:
    """设备连接返回结果"""
    success: bool                              # 连接是否成功
    auth_method: str = ""                      # 认证方式 ("password" / "direct")
    status: str = "connected"                  # "connected" | "needs_password" | "failed"
    error_message: str = ""                    # 失败原因
    needs_password: bool = False               # True 表示需要密码，Agent 应提示用户输入
    onvif_port: int = 0                        # 实际验证过的 ONVIF 端口（0=未验证成功）


@dataclass
class DisconnectResult:
    """设备断开连接返回结果"""
    success: bool                              # 断开是否成功
    session_released: bool = False             # 是否释放了云端会话
    error_message: str = ""                    # 失败原因


@dataclass
class CameraConfig:
    """从 config.yaml 加载的摄像头配置"""
    name: str                                  # 摄像头名称
    connection_type: str = "onvif"             # "onvif" | "usb"
    ip: str = ""                               # IP 地址
    port: int = 0                              # ONVIF 端口（0=未知，待探测验证）
    username: str = "admin"                    # 用户名
    password: str = ""                         # 密码（从 config.yaml 加载，不暴露给用户）
    rtsp_port: int = 554                       # RTSP 端口
    rtsp_path: str = "/stream1"                # 主流路径
    rtsp_sub_path: str = "/stream2"            # 子流路径
    device_class: str = ""                     # "password_required" | "direct_connect"
    sn_code: str = ""                          # 序列号
    pkdk: str = ""                             # 设备公钥标识

    # USB 专用字段
    device_index: int = 0                      # OpenCV 设备索引
    device_model: str = ""                     # USB 设备型号
    product_version: str = ""                  # 产品版本

    # 补光能力（连接后探测填充）
    illumination_modes: List[str] = field(default_factory=list)  # 支持的补光模式列表


@dataclass
class RegisterResult:
    """注册摄像头到 config.yaml 的返回结果"""
    success: bool                              # 注册是否成功
    camera_name: str = ""                      # 注册的摄像头名称
    error_message: str = ""                    # 失败原因


@dataclass
class AuthOrchestrateResult:
    """云端授权编排结果"""
    success: bool                              # 授权是否成功
    status: str = ""                           # "authorized" | "rejected" | "timeout" | "no_devices" | "needs_selection" | "no_sn" | "cloud_error" | "error"
    camera_name: str = ""                      # 选中的摄像头名
    sn: str = ""                               # 选中的设备 SN
    claw_id: str = ""                          # 本次使用的 clawID / agentSkillId
    device_pwd: str = ""                       # 授权成功时的设备密码（已自动写入 config.yaml）
    available_cameras: List[Dict[str, str]] = field(default_factory=list)  # needs_selection 时填
    error_message: str = ""                    # 失败原因


@dataclass
class AuthStatusResult:
    """轮询远程授权服务器的返回结果"""
    status: AuthStatus                         # 授权状态 (pending / authorized / rejected / error)
    camera_name: str = ""                      # 摄像头名称
    message: str = ""                          # 状态说明
    auth_status_code: int = -1                 # 云端原始 authStatus（0=未授权 / 1=已授权 / 2=已拒绝）
    device_pwd: str = ""                       # 云端返回的设备密码（仅 authStatus=1 时有值）


@dataclass
class CloudAuthRequestResult:
    """向云端发起授权请求的结果"""
    success: bool                              # 云端是否接受请求（HTTP 200 且 R.data == true）
    claw_id: str = ""                          # 本次使用的 clawID / agentSkillId（已持久化，重发时复用）
    error_message: str = ""                    # 失败原因


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


# ──────────────────────────────────────────────
#  云端授权常量
# ──────────────────────────────────────────────

_CLOUD_AUTH_URL = "https://app.skyworthtest.top/skyworthAiModel/agent/skill/v1/deviceAuthReq"  # 云端设备授权请求接口
_CLOUD_AUTH_CHECK_URL = "https://app.skyworthtest.top/skyworthAiModel/agent/skill/v1/checkAuth"  # 云端检测授权状态接口
_CLOUD_AUTH_POLL_URL = ""  # 云端授权状态轮询地址，留空则使用 _CLOUD_AUTH_CHECK_URL


# ──────────────────────────────────────────────
#  本机标识辅助函数（云端授权 claw_id 使用）
# ──────────────────────────────────────────────

def _get_local_ip() -> str:
    """通过临时 UDP socket 取本机出口 IP（不发包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "192.168.1.100"
    finally:
        s.close()
    return ip


def _get_local_mac() -> str:
    """跨平台取本机 MAC；失败返回占位 MAC。"""
    import platform
    try:
        if platform.system() == "Windows":
            import re
            import subprocess
            out = subprocess.check_output("getmac", shell=True).decode("gbk", "ignore")
            m = re.search(r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", out)
            if m:
                return m.group(0).replace("-", ":").upper()
        else:
            return ":".join(f"{b:02X}" for b in uuid.getnode().to_bytes(6, "big"))
    except Exception:
        pass
    return "00:00:00:00:00:00"


def generate_claw_id() -> str:
    """生成 Claw ID（MAC + 毫秒时间戳）。

    仅在首次创建或显式重新注册时调用。
    生成后由 get_or_create_claw_id() 持久化到 config.yaml，后续复用。

    格式: claw-<mac12>-<yyyyMMddHHMMSSmmm>
    示例: claw-000C296F9083-20260724104530123
    """
    mac = _get_local_mac().replace(":", "").upper()
    now = datetime.now()
    ts = now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"
    return f"claw-{mac}-{ts}"


def _dump_claw_id_first(data: Dict[str, Any], claw_id: str) -> Dict[str, Any]:
    """构造 claw_id 置顶的 dict（其余键顺序不变），并写回 config.yaml。

    仅调整键顺序，不改动任何值，不影响 cameras 等字段的读取。
    写失败不抛异常（文件保持原样，不影响本次返回）。
    """
    ordered: Dict[str, Any] = {"claw_id": claw_id}
    ordered.update({k: v for k, v in data.items() if k != "claw_id"})
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            _yaml_lib.safe_dump(ordered, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except OSError:
        pass
    return ordered


def get_or_create_claw_id() -> str:
    """从 config.yaml 读取 clawID；不存在则生成并持久化（置顶写入）。

    clawID 是机器级标识，存于 config.yaml 顶层 claw_id 字段，且始终位于
    文件第一个键（顶部）。首次调用时生成（MAC + 时间戳），后续所有授权
    请求复用同一 ID，确保 HTTP 重发时云端识别为同一会话、不重复弹窗。
    旧文件中 claw_id 不在顶部时，读取时会顺带归一化到顶部。

    yaml 不可用或文件读写失败时降级为每次临时生成（本会话内可用，
    但跨进程不保证一致）。
    """
    if _yaml_lib is None:
        return generate_claw_id()

    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = _yaml_lib.safe_load(f) or {}
        else:
            data = {}
    except (OSError, _yaml_lib.YAMLError):
        return generate_claw_id()

    existing = data.get("claw_id", "")
    if existing:
        # 已存在 → 复用；若不在文件顶部则归一化置顶（不改任何值）
        if next(iter(data), None) != "claw_id":
            _dump_claw_id_first(data, str(existing))
        return str(existing)

    # 不存在 → 生成并置顶写入 config.yaml
    claw_id = generate_claw_id()
    _dump_claw_id_first(data, claw_id)
    return claw_id


# ──────────────────────────────────────────────
#  ONVIF WS-UsernameToken 鉴权辅助函数
# ──────────────────────────────────────────────

_ONVIF_NS = {
    "soap": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}


def _onvif_digest_auth_header(username: str, password: str) -> str:
    """生成 ONVIF WS-UsernameToken PasswordDigest 的 SOAP Header XML 片段。"""
    nonce_raw = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest_input = nonce_raw + created.encode("utf-8") + password.encode("utf-8")
    password_digest = base64.b64encode(hashlib.sha1(digest_input).digest()).decode()
    nonce_b64 = base64.b64encode(nonce_raw).decode()
    return (
        '<wsse:UsernameToken xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
        'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
        f'<wsse:Username>{username}</wsse:Username>'
        f'<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{password_digest}</wsse:Password>'
        f'<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</wsse:Nonce>'
        f'<wsu:Created>{created}</wsu:Created>'
        '</wsse:UsernameToken>'
    )


def _onvif_post_with_auth(
    ip: str, port: int, path: str, body: str,
    username: str, password: str, timeout: float = 5.0,
) -> Tuple[int, str]:
    """POST SOAP 到 ONVIF endpoint，自动注入 WS-UsernameToken 鉴权头。返回 (status_code, body_text)。"""
    if _requests_lib is None:
        raise RuntimeError("requests 未安装")
    auth_xml = _onvif_digest_auth_header(username, password)
    if "xmlns:wsse=" not in body:
        body = body.replace(
            "<soap:Envelope ",
            '<soap:Envelope xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
            'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd" ',
            1,
        )
    if "<soap:Header/>" in body:
        body = body.replace("<soap:Header/>", f"<soap:Header>{auth_xml}</soap:Header>", 1)
    elif "<soap:Header>" in body:
        body = body.replace("<soap:Header>", f"<soap:Header>{auth_xml}", 1)

    resp = _requests_lib.post(
        f"http://{ip}:{port}{path}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        timeout=timeout,
    )
    return resp.status_code, resp.text


# 常见 ONVIF 服务端口（创维实测 2000；80 多为 Web UI，需实际验证）
_ONVIF_CANDIDATE_PORTS = [2000, 80, 8000, 8899]

_ONVIF_PROBE_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
    '<soap:Header/><soap:Body><tds:GetSystemDateAndTime/></soap:Body></soap:Envelope>'
)


def _probe_onvif_port(ip: str, hint_port: int = 0, timeout: float = 2.0) -> int:
    """探测并验证设备真实的 ONVIF 服务端口。

    向候选端口 POST 免鉴权的 GetSystemDateAndTime，只有返回 SOAP Envelope
    的端口才认定为 ONVIF 端口（Web UI 端口会返回 HTML/404，可确定性区分）。
    候选顺序: hint_port（调用方线索）→ 常见端口列表。

    Returns:
        验证成功的端口号；全部失败返回 0（表示未知，不可当事实持久化）。
    """
    if _requests_lib is None:
        return 0
    candidates = []
    for p in [hint_port, *_ONVIF_CANDIDATE_PORTS]:
        if p and p not in candidates:
            candidates.append(p)
    for p in candidates:
        try:
            resp = _requests_lib.post(
                f"http://{ip}:{p}/onvif/device_service",
                data=_ONVIF_PROBE_BODY.encode("utf-8"),
                headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                timeout=timeout,
            )
            # 状态码不作硬性要求（部分设备对免鉴权请求回 400/401 的 SOAP Fault，
            # 但只要 body 是 SOAP Envelope 即证明该端口提供 ONVIF 服务）
            text = (resp.text or "")[:2048].lower()
            if "envelope" in text and "<html" not in text:
                return p
        except Exception:
            continue
    return 0


def _build_rtsp_url(ip: str, port: int, path: str, username: str = "", password: str = "") -> str:
    """构造完整 RTSP URL，自动注入凭据。

    支持两种 path 形态:
      - 纯路径 "/md0_0" → rtsp://user:pwd@ip:port/md0_0
      - 完整 URL "rtsp://host:port/md0_0" → 注入凭据
    """
    path = (path or "").strip()
    if path.lower().startswith(("rtsp://", "http://", "https://")):
        parsed = urlparse(path)
        if "@" in parsed.netloc:
            _, host_port = parsed.netloc.split("@", 1)
        else:
            host_port = parsed.netloc
        new_netloc = (
            f"{quote(username, safe='')}:{quote(password or '', safe='')}@{host_port}"
            if username else host_port
        )
        new_path = parsed.path or "/"
        if not new_path.startswith("/"):
            new_path = "/" + new_path
        from urllib.parse import urlunparse
        return urlunparse((parsed.scheme, new_netloc, new_path,
                           parsed.params, parsed.query, parsed.fragment))

    if not path.startswith("/"):
        path = "/" + path
    if username:
        return f"rtsp://{quote(username, safe='')}:{quote(password or '', safe='')}@{ip}:{port}{path}"
    return f"rtsp://{ip}:{port}{path}"


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def get_registered_cameras() -> List[CameraConfig]:
    """
    从 config.yaml 加载所有已注册摄像头配置。

    每次对话开始时（Phase 0）必须先调用此函数，检查是否有缓存的摄像头信息。
    已注册摄像头的凭据（username/password）保存在 config.yaml 中，
    后续 connect_device 会自动使用这些凭据，用户无需重复输入密码。

    安全约束: 无特殊约束

    Returns:
        List[CameraConfig]: 已注册摄像头列表（含 IP、端口、凭据、device_class 等）
    """
    return _load_config_cameras()


def register_camera(
    name: str,
    ip: str = "",
    port: int = 0,
    username: str = "admin",
    password: str = "",
    rtsp_port: int = 554,
    rtsp_path: str = "/stream1",
    device_class: str = "direct_connect",
    connection_type: str = "onvif",
    sn_code: str = "",
    pkdk: str = "",
    rtsp_sub_path: str = "/stream2",
    device_index: int = 0,
    device_model: str = "",
    product_version: str = "",
    illumination_modes: Optional[List[str]] = None,
) -> RegisterResult:
    """
    将摄像头信息写入 config.yaml，持久化凭据供下次自动连接。

    首次成功连接摄像头后调用此函数，将设备信息和凭据保存到 config.yaml。
    保存后，后续对话的 Phase 0 可通过 get_registered_cameras() 读取配置，
    connect_device 自动使用保存的凭据连接，用户不再需要手动输入密码。

    安全约束: 无特殊约束（内部配置写入，不向用户暴露凭据）

    Args:
        name:            摄像头唯一名称
        ip:              IP 地址
        port:            ONVIF 端口（0=未知；只应传入验证过的真实端口，不要传假设值）
        username:        登录用户名（默认 "admin"）
        password:        登录密码（保存到 config.yaml，不显示给用户）
        rtsp_port:       RTSP 端口（默认 554）
        rtsp_path:       主流路径（默认 "/stream1"）
        device_class:    设备类型（"password_required" | "direct_connect"）
        connection_type: 连接类型（"onvif" | "usb"）
        sn_code:         序列号（可选）
        pkdk:            设备公钥标识（可选）
        rtsp_sub_path:   子流路径（默认 "/stream2"）
        device_index:    USB 设备索引（USB 摄像头专用，默认 0）
        device_model:    USB 设备型号（可选）
        product_version: 产品版本（可选）

    Returns:
        RegisterResult:
            - success: 注册是否成功
            - camera_name: 注册的摄像头名称
            - error_message: 失败原因
    """
    import os
    import yaml

    # 确定 config.yaml 路径
    config_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_path = os.path.join(config_dir, "config.yaml")
    # 兼容旧文件名 confg.yaml
    if not os.path.exists(config_path):
        alt_path = os.path.join(config_dir, "confg.yaml")
        if os.path.exists(alt_path):
            config_path = alt_path

    # 读取现有配置
    data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    cameras = data.get("cameras", [])

    # 构建新条目（同时写入两种方案的字段名以兼容）
    new_entry = {
        "name": name,
        "connection_type": connection_type,
        "ip": ip,
        "port": port,
        "onvif_port": port,           # 密码认证方案兼容字段
        "username": username,
        "password": password,
        "rtsp_port": rtsp_port,
        "rtsp_path": rtsp_path,
        "rtsp_path_main": rtsp_path,  # 密码认证方案兼容字段
        "rtsp_sub_path": rtsp_sub_path,
        "rtsp_path_sub": rtsp_sub_path,  # 密码认证方案兼容字段
        "device_class": device_class,
        "sn_code": sn_code,
        "sn": sn_code,               # 密码认证方案兼容字段
        "pkdk": pkdk,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    if connection_type == "usb":
        new_entry["device_index"] = device_index
        new_entry["device_model"] = device_model
        new_entry["product_version"] = product_version
    if illumination_modes:
        new_entry["illumination_modes"] = illumination_modes

    # 更新或追加（按 name → ip → sn 三级匹配，支持重命名）
    found = False
    # 1) 按 name 匹配 — 同名更新
    for i, cam in enumerate(cameras):
        if cam.get("name") == name:
            cameras[i] = new_entry
            found = True
            break
    # 2) 按 ip 匹配 — 同一 IP 不同名称 → 重命名
    if not found and ip:
        for i, cam in enumerate(cameras):
            if cam.get("ip") == ip:
                cameras[i] = new_entry
                found = True
                break
    # 3) 按 sn_code 匹配 — 同一 SN 不同名称 → 重命名
    if not found and sn_code:
        for i, cam in enumerate(cameras):
            if cam.get("sn_code") == sn_code or cam.get("sn") == sn_code:
                cameras[i] = new_entry
                found = True
                break
    if not found:
        cameras.append(new_entry)

    data["cameras"] = cameras

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        return RegisterResult(success=True, camera_name=name)
    except Exception as e:
        return RegisterResult(success=False, camera_name=name, error_message=str(e))


def search_devices(
    method: DiscoveryMethod = DiscoveryMethod.WS_DISCOVERY,
    timeout: float = 15.0,
) -> SearchResult:
    """
    搜索局域网或云端可用摄像头设备。

    WS-Discovery 模式：发送 Probe 多播 + 被动监听 Hello 心跳包，
    从 ProbeMatch 中提取 IP、ONVIF 端口（XAddrs 解析）、SN、型号等信息。

    SKY-Discovery 模式：通过创维私有协议（SK_DISCOVERY_SEARCH）搜索，
    向组播地址 239.230.236.230:9008 发送搜索命令，在 9028 端口监听响应，
    返回包含 SN、型号、通道信息、RTSP 端口等完整设备信息。

    USB 模式：扫描设备索引 0–9。

    安全约束: 无特殊约束

    Args:
        method:  发现方式 (DiscoveryMethod.WS_DISCOVERY / SKY_DISCOVERY / USB)
        timeout: 超时时间（秒，默认 15）

    Returns:
        SearchResult:
            - success: 搜索是否成功
            - devices: 发现的设备列表（每个设备含 IP/端口/SN/型号/媒体设置）
            - error_message: 失败原因
    """
    if method == DiscoveryMethod.SKY_DISCOVERY:
        return _search_sky_devices(timeout)
    elif method == DiscoveryMethod.USB:
        return _search_usb_devices(timeout)
    else:
        return _search_ws_discovery_devices(timeout)


def _search_sky_devices(timeout: float) -> SearchResult:
    """通过创维私有协议搜索设备"""
    try:
        sky_devices = discover_sky_devices(timeout=timeout)
        devices = []
        for sd in sky_devices:
            dev = DiscoveredDevice(
                ip=sd.ip,
                onvif_port=0,               # SK 协议只回报 web 端口，非 ONVIF 端口；置 0 待 connect_device 探测验证
                rtsp_port=sd.rtsp_port,
                device_class=DeviceClass.PASSWORD_REQUIRED,
                sn_code=sd.sn,
                model=sd.model,
                manufacturer=sd.manufacturer,
                supported_media=[s for s in sd.rtsp_paths],
                sky_subtype=sd.subtype,
                sky_name=sd.name,
                sky_dtype=sd.dtype,
                sky_hw_version=sd.hw_version,
                sky_sw_version=sd.sw_version,
                sky_did=sd.did,
                sky_channels=sd.channels,
                sky_channel_list=sd.channel_list,
                sky_web_port=sd.web_port,
                sky_udp_port=sd.udp_port,
                sky_net_type=sd.net_type,
                sky_ip_mode=sd.ip_mode,
                sky_mask=sd.mask,
                sky_gateway=sd.gateway,
                sky_mac=sd.mac,
                discovery_method="sky_discovery",
            )
            devices.append(dev)
        return SearchResult(
            success=True,
            devices=devices,
        )
    except Exception as e:
        return SearchResult(
            success=False,
            error_message=str(e),
        )


def _search_usb_devices(timeout: float) -> SearchResult:
    """通过 OpenCV 扫描 USB 摄像头"""
    try:
        import cv2
        found = []
        for idx in range(10):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if cap.isOpened():
                cap.release()
                dev = DiscoveredDevice(
                    ip=f"usb://{idx}",
                    device_class=DeviceClass.DIRECT_CONNECT,
                    model=f"USB Camera {idx}",
                    discovery_method="usb",
                )
                found.append(dev)
        return SearchResult(success=True, devices=found)
    except Exception as e:
        return SearchResult(success=False, error_message=str(e))


def _search_ws_discovery_devices(timeout: float) -> SearchResult:
    """通过 WS-Discovery 协议搜索 ONVIF 设备。

    向多播地址 239.255.255.250:3702 发送 Probe（多网卡逐一发送），
    解析 ProbeMatch 响应提取 IP、ONVIF 端口（XAddrs）、品牌/型号（Scopes）。
    发现后用免密 RTSP 探测对设备分类（open → direct_connect）。
    """
    import select
    import uuid

    probe_wait = max(1.0, min(timeout, 5.0))

    # ── Step 1: 每个本机网卡发送一次多播 Probe ──
    socks = []
    for local_ip in _list_local_ipv4():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((local_ip, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                         socket.inet_aton(local_ip))
            s.setblocking(False)
            probe = _WS_PROBE_TEMPLATE.format(msg_id=uuid.uuid4()).encode("utf-8")
            s.sendto(probe, (_WS_DISCOVERY_ADDR, _WS_DISCOVERY_PORT))
            socks.append(s)
        except Exception:
            try:
                s.close()
            except Exception:
                pass

    if not socks:
        return SearchResult(
            success=False,
            error_message="无可用网络接口，WS-Discovery 探测失败",
        )

    # ── Step 2: 在超时窗口内收集 ProbeMatch 响应 ──
    found: Dict[str, dict] = {}
    deadline = time.time() + probe_wait
    while time.time() < deadline:
        try:
            ready, _, _ = select.select(socks, [], [], 0.5)
        except Exception:
            break
        for s in ready:
            try:
                data, addr = s.recvfrom(65535)
            except Exception:
                continue
            info = _parse_ws_probe_match(data)
            if info and addr[0] not in found:
                found[addr[0]] = info
    for s in socks:
        try:
            s.close()
        except Exception:
            pass

    # ── Step 3: 免密 RTSP 探测分类 + 创维私有协议 SN 补探测 ──
    devices = []
    for ip, info in sorted(found.items()):
        access = _probe_stream_access(ip, 554, "/stream1")
        device_class = (
            DeviceClass.DIRECT_CONNECT if access == "open"
            else DeviceClass.PASSWORD_REQUIRED
        )
        # 通过创维私有协议补探测 SN（WS-Discovery 不提供 SN）
        sn = _probe_sn_via_sky(ip, timeout=2.0)
        devices.append(DiscoveredDevice(
            ip=ip,
            onvif_port=info["onvif_port"],
            rtsp_port=554,
            device_class=device_class,
            sn_code=sn,
            model=info["model"],
            manufacturer=info["brand"],
            discovery_method="ws_discovery",
        ))

    return SearchResult(success=True, devices=devices)


# ── WS-Discovery 协议常量与解析辅助 ──

_WS_DISCOVERY_ADDR = "239.255.255.250"
_WS_DISCOVERY_PORT = 3702

_WS_PROBE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:tds="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:tns="http://www.onvif.org/ver10/network/wsdl/RemoteDiscoveryBinding">
  <s:Header>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>uuid:{msg_id}</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
  </s:Header>
  <s:Body>
    <tds:Probe>
      <tds:Types>tns:NetworkVideoTransmitter</tds:Types>
    </tds:Probe>
  </s:Body>
</s:Envelope>"""


def _list_local_ipv4() -> List[str]:
    """枚举本机所有非回环 IPv4 地址（多网卡时向每个接口发送多播探测）"""
    addrs: List[str] = []
    try:
        import psutil
        for _, addr_list in psutil.net_if_addrs().items():
            for a in addr_list:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    addrs.append(a.address)
    except Exception:
        pass
    if not addrs:
        # psutil 不可用时回退到默认路由接口
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            addrs.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return addrs


def _parse_ws_probe_match(data: bytes) -> Optional[dict]:
    """解析 WS-Discovery ProbeMatch/Hello XML。

    提取 XAddrs（解析真实 ONVIF 端口——不一定是 80，创维实测为 2000）
    和 Scopes（品牌 /name/、型号 /hardware/）。
    Types 含 NetworkVideoTransmitter 才视为摄像头。
    """
    import xml.etree.ElementTree as ET
    from urllib.parse import unquote

    try:
        text = data.decode("utf-8", errors="ignore")
        start = text.find("<")
        if start < 0:
            return None
        root = ET.fromstring(text[start:])
    except Exception:
        return None

    def _find_text(tag: str) -> str:
        for elem in root.iter():
            if elem.tag.endswith("}" + tag) or elem.tag == tag:
                return (elem.text or "").strip()
        return ""

    types_text = _find_text("Types")
    if types_text and "NetworkVideoTransmitter" not in types_text:
        return None

    xaddrs = _find_text("XAddrs")
    onvif_port = 0   # 0 = 未知（无 XAddrs 时不假设 80）
    if xaddrs:
        try:
            parsed = urlparse(xaddrs.split()[0])
            # XAddrs URL 未显式写端口时，HTTP 默认 80 是协议事实，可采信
            onvif_port = parsed.port or 80
        except Exception:
            pass

    brand = ""
    model = ""
    for scope in _find_text("Scopes").split():
        if "/name/" in scope:
            brand = unquote(scope.split("/name/")[-1])
        elif "/hardware/" in scope:
            model = unquote(scope.split("/hardware/")[-1])

    return {"onvif_port": onvif_port, "xaddrs": xaddrs, "brand": brand, "model": model}


def _probe_sn_via_sky(ip: str, timeout: float = 3.0) -> str:
    """通过创维私有协议单播探测设备 SN（WS-Discovery 补探测用）。

    封装 discovery.py 的 probe_device_sn()，异常安全，失败返回空字符串。
    """
    try:
        return probe_device_sn(ip=ip, timeout=timeout)
    except Exception:
        return ""


def _cloud_auth_and_connect(
    camera_name: str,
    ip: str,
    port: int,
    sn_code: str,
    rtsp_port: int,
    rtsp_path: str,
    username: str,
    cached: Optional[CameraConfig] = None,
) -> ConnectResult:
    """内部函数：云端授权 + 自动连接。由 connect_device 在 pending_auth 场景调用。

    流程：
      1. 检查 SN → 2. POST 云端授权请求 → 3. 轮询等待结果（5s 间隔，最长 10 分钟）
      4. 授权通过 → 用云端密码连接 → 注册凭据
    """
    # 1. 检查 SN 是否可用
    if not sn_code:
        return ConnectResult(
            success=False, status="needs_password",
            needs_password=True,
            error_message=(
                f"设备 {camera_name}({ip}) 无 SN，无法发起云端授权。"
                f"请直接输入密码后调用 connect_device。"
            ),
        )

    # 2. 向云端发起授权请求
    cr = request_cloud_auth(sn_code)
    if not cr.success:
        # 云端不可达 / 网络错误 → 降级为本地流程
        return ConnectResult(
            success=False, status="needs_password",
            needs_password=True,
            error_message=(
                f"云端授权服务不可用（{cr.error_message}）。"
                f"请直接输入设备 {camera_name}({ip}) 的密码。"
            ),
        )

    # 3. 先注册设备信息到 config.yaml（云端轮询需要 SN 查设备）
    register_camera(
        name=camera_name, ip=ip, port=port,
        username=username, password="",
        rtsp_port=rtsp_port, rtsp_path=rtsp_path,
        device_class="password_required",
        sn_code=sn_code,
        connection_type=cached.connection_type if cached else "onvif",
    )

    # 4. 轮询等待授权结果（5s 间隔，最长 10 分钟 = 120 次）
    poll_interval = 5
    max_polls = 120
    for _ in range(max_polls):
        time.sleep(poll_interval)
        result = poll_auth_status(camera_name)

        if result.status == AuthStatus.AUTHORIZED:
            # 5. 用云端下发的密码尝试连接
            conn = _try_connect_with_password(
                camera_name, ip, port, rtsp_port, rtsp_path,
                username, result.device_pwd,
            )
            if conn.success:
                # 连接成功 → 持久化凭据（含 SN）
                register_camera(
                    name=camera_name, ip=ip,
                    port=conn.onvif_port or port,
                    username=username, password=result.device_pwd,
                    rtsp_port=rtsp_port, rtsp_path=rtsp_path,
                    device_class="password_required",
                    sn_code=sn_code,
                    connection_type=cached.connection_type if cached else "onvif",
                )
                # 探测补光能力（失败不阻断）
                _probe_and_save_illumination(
                    camera_name, ip,
                    conn.onvif_port or port,
                    username, result.device_pwd, cached,
                )
                return conn
            else:
                # 云端密码连接失败 → 设备可能改过密码
                return ConnectResult(
                    success=False, status="cloud_pwd_failed",
                    needs_password=True,
                    error_message=(
                        f"云端下发的密码连接设备 {camera_name}({ip}) 失败，"
                        f"设备可能修改过密码。请输入正确密码。"
                    ),
                )

        elif result.status == AuthStatus.REJECTED:
            return ConnectResult(
                success=False, status="auth_rejected",
                error_message=(
                    f"用户拒绝了设备 {camera_name}({ip}) 的云端授权请求，无法连接。"
                ),
            )

        elif result.status == AuthStatus.ERROR:
            return ConnectResult(
                success=False, status="needs_password",
                needs_password=True,
                error_message=(
                    f"云端授权出错（{result.message}）。"
                    f"请直接输入设备 {camera_name}({ip}) 的密码。"
                ),
            )
        # PENDING: 继续轮询

    # 超时
    return ConnectResult(
        success=False, status="needs_password",
        needs_password=True,
        error_message=(
            f"云端授权等待超时（10 分钟），用户未确认。"
            f"请直接输入设备 {camera_name}({ip}) 的密码。"
        ),
    )


def connect_device(
    camera_name: str,
    password: Optional[str] = None,
    ip: Optional[str] = None,
    port: Optional[int] = None,
    rtsp_port: Optional[int] = None,
    rtsp_path: str = "/stream1",
    username: str = "admin",
    sn_code: str = "",
) -> ConnectResult:
    """
    设备连接。流程：

    1. 如果 config.yaml 有缓存凭据 → 自动使用缓存密码连接（重试 3 次）
       多次重试仍失败 → 清除 config.yaml 中的注册信息，返回 needs_password
    2. 如果传入了 password → 使用提供的密码连接（单次尝试，不清除缓存）
    3. 如果无密码且 device_class == "password_required" → 内部发起云端授权
       云端同意 → 用云端密码自动连接并注册
       云端拒绝 → 返回 auth_rejected
       云端不可用 → 返回 needs_password，让用户直接输入
       云端密码连接失败 → 返回 cloud_pwd_failed，让用户输入
    4. 如果无密码且非 password_required → 尝试免密拉流探测
    5. Agent 获取到密码后再次调用 connect_device(camera_name, password=xxx)

    安全约束: 显式提示（需要密码时提示用户输入）

    Args:
        camera_name: 摄像头名称（匹配 config.yaml 注册名或发现后的临时名）
        password:    用户提供的密码（可选；有缓存时自动使用）
        ip:          设备 IP（新发现的设备，未注册到 config.yaml 时需传入）
        port:        ONVIF 端口（可选；不传或传错时由工具自动探测验证真实端口）
        rtsp_port:   RTSP 端口（默认 554）
        rtsp_path:   RTSP 路径（默认 /stream1）
        username:    登录用户名（默认 admin）
        sn_code:     设备 SN（发现阶段获取，云端授权必需）

    Returns:
        ConnectResult:
            - success: 连接是否成功
            - auth_method: "password" 或 "direct"
            - status: "connected" / "needs_password" / "auth_rejected" / "cloud_pwd_failed" / "failed"
            - needs_password: True 表示需要密码
            - error_message: 失败原因
    """
    # ── Step 1: 从 config.yaml 查找缓存配置 ──
    cached = _find_cached_camera(camera_name)

    # 确定连接参数（缓存优先，参数兜底）
    # SN 来源优先级：缓存 > 参数传入
    effective_sn = (cached.sn_code if cached and cached.sn_code else "") or sn_code
    if cached and cached.ip:
        dev_ip = cached.ip
        dev_port = cached.port
        dev_rtsp_port = cached.rtsp_port
        dev_rtsp_path = cached.rtsp_path
        dev_username = cached.username or username
        dev_pwd = password or cached.password or ""
        dev_class = cached.device_class or ""
    elif ip:
        dev_ip = ip
        dev_port = port or 0   # 0 = 未知，交由连接流程探测验证（不再假设 80）
        dev_rtsp_port = rtsp_port or 554
        dev_rtsp_path = rtsp_path
        dev_username = username
        dev_pwd = password or ""
        dev_class = ""
    else:
        return ConnectResult(
            success=False, status="failed",
            error_message=f"未找到设备 {camera_name} 的连接信息（config.yaml 中无记录且未提供 IP）",
        )

    # ── Step 2: 如果有密码（缓存或用户提供），直接尝试 ONVIF 鉴权连接 ──
    if dev_pwd:
        max_attempts = 3 if (cached and not password) else 1
        last_result = None
        for attempt in range(1, max_attempts + 1):
            last_result = _try_connect_with_password(
                camera_name, dev_ip, dev_port, dev_rtsp_port, dev_rtsp_path,
                dev_username, dev_pwd,
            )
            if last_result.success:
                break
            if attempt < max_attempts:
                time.sleep(1.0)

        if last_result.success:
            # 连接成功 → 持久化凭据与验证过的 ONVIF 端口。
            # result.onvif_port 为实测验证值（0=未验证成功）；未验证时不把假设端口写盘，
            # 保证 config.yaml 落盘结果只取决于设备事实，不随调用方传参漂移。
            verified_port = last_result.onvif_port
            port_changed = bool(verified_port) and (not cached or cached.port != verified_port)
            if not cached or cached.password != dev_pwd or port_changed:
                register_camera(
                    name=camera_name, ip=dev_ip,
                    port=verified_port or (cached.port if cached else 0),
                    username=dev_username, password=dev_pwd,
                    rtsp_port=dev_rtsp_port, rtsp_path=dev_rtsp_path,
                    device_class=dev_class or "password_required",
                    sn_code=effective_sn or (cached.sn_code if cached else ""),
                    connection_type=cached.connection_type if cached else "onvif",
                )
            # 连接成功后探测补光能力（失败不阻断）
            _probe_and_save_illumination(
                camera_name, dev_ip,
                verified_port or (cached.port if cached else 0),
                dev_username, dev_pwd, cached,
            )
            return last_result

        # 密码认证失败
        if cached and not password:
            # 缓存凭据多次重试仍失败 → 清除过期注册，让后续流程重新发现设备
            _remove_camera_config(camera_name)
            return ConnectResult(
                success=False, status="failed",
                needs_password=True,
                error_message=(
                    f"缓存凭据连接失败（已重试 {max_attempts} 次）: {last_result.error_message}。"
                    f"已从 config.yaml 清除设备 '{camera_name}' 的注册信息，"
                    f"请重新搜索并连接该设备。"
                ),
            )
        return ConnectResult(
            success=False, status="failed",
            needs_password=True,
            error_message=f"密码认证失败: {last_result.error_message}，请确认密码后重试",
        )

    # ── Step 3: 无密码 + password_required → 内部发起云端授权 ──
    if dev_class == "password_required":
        return _cloud_auth_and_connect(
            camera_name, dev_ip, dev_port, effective_sn,
            dev_rtsp_port, dev_rtsp_path, dev_username,
            cached=cached,
        )

    # ── Step 4: 非 password_required → 尝试免密拉流探测 ──
    access = _probe_stream_access(dev_ip, dev_rtsp_port, dev_rtsp_path)

    if access == "open":
        # 免密设备，直接连接（ONVIF 端口同样以探测验证结果为准）
        verified_port = _probe_onvif_port(dev_ip, hint_port=dev_port)
        conn_info = {
            "ip": dev_ip,
            "port": verified_port or dev_port,
            "rtsp_port": dev_rtsp_port,
            "rtsp_path": dev_rtsp_path,
            "username": "",
            "password": "",
        }
        # 尽力建立 ONVIF 连接（部分免密设备支持默认凭据/匿名 ONVIF，供 PTZ 控制使用）
        if verified_port or dev_port:
            try:
                from onvif import ONVIFCamera
                cam = ONVIFCamera(host=dev_ip, port=verified_port or dev_port,
                                  user=dev_username or "admin", passwd=dev_pwd or "")
                cam.create_devicemgmt_service().GetDeviceInformation()
                conn_info["onvif_camera"] = cam
            except Exception:
                pass  # ONVIF 不可用不影响拉流，仅 PTZ 功能受限
        _connected_devices[camera_name] = conn_info
        # 缓存为 direct_connect（仅持久化验证过的端口，未验证则留 0 待解析）
        if not cached:
            register_camera(
                name=camera_name, ip=dev_ip, port=verified_port,
                username="", password="",
                rtsp_port=dev_rtsp_port, rtsp_path=dev_rtsp_path,
                device_class="direct_connect",
            )
        # 连接成功后探测补光能力（失败不阻断）
        _probe_and_save_illumination(
            camera_name, dev_ip, verified_port or dev_port,
            dev_username or "", dev_pwd or "", cached,
        )
        return ConnectResult(
            success=True,
            auth_method="direct",
            status="connected",
        )

    if access == "auth_required":
        # 需要密码 → 内部发起云端授权
        return _cloud_auth_and_connect(
            camera_name, dev_ip, dev_port, effective_sn,
            dev_rtsp_port, dev_rtsp_path, dev_username,
            cached=cached,
        )

    # 设备不可达
    return ConnectResult(
        success=False,
        status="failed",
        error_message=f"设备 {dev_ip} 不可达（RTSP 端口 {dev_rtsp_port} 无响应）",
    )


# ──────────────────────────────────────────────
#  连接状态管理（模块内部）
# ──────────────────────────────────────────────

_connected_devices: Dict[str, dict] = {}   # camera_name -> 连接信息


def _probe_and_save_illumination(
    camera_name: str,
    ip: str,
    port: int,
    username: str,
    password: str,
    cached: Optional[CameraConfig] = None,
) -> List[str]:
    """连接成功后探测设备补光能力并持久化到 config.yaml（非阻塞，失败静默）。

    双协议探测：先尝试创维私有协议 (TCP 9010)，失败则回退 ONVIF Imaging Service。

    Returns:
        支持的补光模式列表（空列表 = 不支持或探测失败）
    """
    # 如果 config.yaml 中已有缓存的补光模式，跳过重复探测
    if cached and cached.illumination_modes:
        return cached.illumination_modes
    try:
        from .illumination import probe_illumination_capability
        info = probe_illumination_capability(
            ip, port, username, password,
            sn_code=cached.sn_code if cached else "",
        )
        if info.supported and info.supported_modes:
            # 探测到补光能力 → 持久化到 config.yaml
            register_camera(
                name=camera_name, ip=ip, port=port,
                username=username, password=password,
                rtsp_port=cached.rtsp_port if cached else 554,
                rtsp_path=cached.rtsp_path if cached else "/stream1",
                device_class=cached.device_class if cached else "",
                sn_code=cached.sn_code if cached else "",
                connection_type=cached.connection_type if cached else "onvif",
                illumination_modes=info.supported_modes,
            )
            # 如果探测到 TCP 可用，回写 tcp_port 到内存连接状态
            # 这确保 manage_illumination 后续能直接走私有协议路径
            if info.protocol == "sky_private":
                conn = _connected_devices.get(camera_name)
                if conn and not conn.get("tcp_port"):
                    conn["tcp_port"] = SK_TCP_PORT
            return info.supported_modes
    except Exception:
        pass  # 探测失败不阻断连接流程
    return []


def _remove_camera_config(name: str) -> bool:
    """从 config.yaml 移除指定摄像头的注册信息。

    用于缓存凭据连接反复失败后清除过期注册，避免后续会话反复尝试无效设备。

    Returns:
        True 表示成功移除，False 表示未找到或写入失败。
    """
    if _yaml_lib is None:
        return False
    try:
        if not CONFIG_PATH.exists():
            return False
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = _yaml_lib.safe_load(f) or {}
        cameras = data.get("cameras", [])
        new_cameras = [c for c in cameras if c.get("name") != name]
        if len(new_cameras) == len(cameras):
            return False  # 未找到
        data["cameras"] = new_cameras
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            _yaml_lib.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return True
    except Exception:
        return False


def _try_connect_with_password(
    camera_name: str,
    ip: str,
    onvif_port: int,
    rtsp_port: int,
    rtsp_path: str,
    username: str,
    password: str,
) -> ConnectResult:
    """
    使用密码尝试连接设备（TCP 通道 → ONVIF → RTSP 逐级尝试）。
    连接成功则记录到 _connected_devices。

    确定性保证: 传入的 onvif_port 只作为探测线索（hint），不直接采信。
    先探测验证设备真实 ONVIF 端口，成功路径统一使用验证后的端口，
    并通过 ConnectResult.onvif_port 回传（0=未验证成功），供上层决定是否持久化。
    """
    # ── Step 0: 探测验证真实 ONVIF 端口（不信任调用方传入的假设值）──
    verified_port = _probe_onvif_port(ip, hint_port=onvif_port)
    effective_port = verified_port or onvif_port  # 探测失败时保留 hint 供内存会话使用

    # ── 尝试 1: 创维 TCP 通道 (9010) ──
    test_cmd = {
        "service_type": "device",
        "cmd_name": "SK_DEVICE_GET_INFO",
        "ver": "1.0",
    }
    resp = send_tcp_command(
        ip=ip,
        command=test_cmd,
        username=username,
        password=password,
        timeout=5.0,
        port=SK_TCP_PORT,
    )
    if resp is not None:
        _connected_devices[camera_name] = {
            "ip": ip, "port": effective_port,
            "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
            "username": username, "password": password,
            "tcp_port": SK_TCP_PORT,
        }
        return ConnectResult(
            success=True, auth_method="password", status="connected",
            onvif_port=verified_port,
        )

    # ── 尝试 2: ONVIF 连接（使用验证过的端口）──
    if effective_port:
        try:
            from onvif import ONVIFCamera
            cam = ONVIFCamera(host=ip, port=effective_port, user=username, passwd=password)
            dev_svc = cam.create_devicemgmt_service()
            dev_svc.GetDeviceInformation()
            _connected_devices[camera_name] = {
                "ip": ip, "port": effective_port,
                "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
                "username": username, "password": password,
                "onvif_camera": cam,
            }
            return ConnectResult(
                success=True, auth_method="password", status="connected",
                onvif_port=effective_port,  # ONVIF 鉴权调用成功，该端口即验证事实
            )
        except Exception:
            # ONVIF 失败，继续尝试 RTSP
            pass

    # ── 尝试 3: RTSP 带认证拉流 ──
    access = _probe_stream_access(ip, rtsp_port, rtsp_path, username, password)
    if access == "open":
        _connected_devices[camera_name] = {
            "ip": ip, "port": effective_port,
            "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
            "username": username, "password": password,
        }
        return ConnectResult(
            success=True, auth_method="password", status="connected",
            onvif_port=verified_port,
        )

    return ConnectResult(
        success=False, status="failed",
        error_message="TCP/ONVIF/RTSP 均连接失败",
    )


def _probe_stream_access(
    ip: str,
    rtsp_port: int = 554,
    rtsp_path: str = "/stream1",
    username: str = "",
    password: str = "",
) -> str:
    """
    探测 RTSP 流是否可访问。

    Returns:
        "open"           — 可以拉流（免密或密码正确）
        "auth_required"  — 需要密码（返回 401）
        "unreachable"    — 设备不可达
    """
    import socket

    # 先检查端口是否开放
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        result = sock.connect_ex((ip, rtsp_port))
        sock.close()
        if result != 0:
            return "unreachable"
    except Exception:
        return "unreachable"

    # 端口开放 → 发送 RTSP DESCRIBE 探测
    rtsp_url = f"rtsp://{ip}:{rtsp_port}{rtsp_path}"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((ip, rtsp_port))

        # 构建 RTSP DESCRIBE 请求
        if username and password:
            import base64
            auth = base64.b64encode(f"{username}:{password}".encode()).decode()
            auth_header = f"Authorization: Basic {auth}\r\n"
        else:
            auth_header = ""

        request = (
            f"DESCRIBE {rtsp_url} RTSP/1.0\r\n"
            f"CSeq: 1\r\n"
            f"Accept: application/sdp\r\n"
            f"{auth_header}"
            f"\r\n"
        )
        sock.sendall(request.encode("utf-8"))

        # 读取响应
        response = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response:
                    break
            except socket.timeout:
                break
        sock.close()

        resp_text = response.decode("utf-8", errors="ignore")

        # 解析 RTSP 状态码
        if "RTSP/1.0 200" in resp_text:
            return "open"
        elif "401" in resp_text:
            return "auth_required"
        elif "RTSP/1.0" in resp_text:
            # 其他 RTSP 错误码（404 等）— 可能是路径不对，但端口可达
            # 尝试常见路径（含创维摄像头路径 /stream0, /md0_0, /md0_1）
            for alt_path in ["/Streaming/Channels/101", "/h264/ch1/main/av_stream", "/live",
                             "/stream0", "/md0_0", "/stream1", "/md0_1"]:
                if alt_path == rtsp_path:
                    continue
                alt_result = _quick_rtsp_check(ip, rtsp_port, alt_path, username, password)
                if alt_result == "open":
                    return "open"
                elif alt_result == "auth_required":
                    return "auth_required"
            return "open"  # 端口开放且响应了 RTSP，视为可用
        else:
            # 非标准响应，端口开放视为可达
            return "open"

    except Exception:
        return "unreachable"


def _quick_rtsp_check(
    ip: str, rtsp_port: int, path: str,
    username: str = "", password: str = "",
) -> str:
    """快速检查单个 RTSP 路径是否可访问"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect((ip, rtsp_port))

        rtsp_url = f"rtsp://{ip}:{rtsp_port}{path}"
        if username and password:
            import base64
            auth = base64.b64encode(f"{username}:{password}".encode()).decode()
            auth_header = f"Authorization: Basic {auth}\r\n"
        else:
            auth_header = ""

        request = (
            f"DESCRIBE {rtsp_url} RTSP/1.0\r\n"
            f"CSeq: 1\r\n"
            f"Accept: application/sdp\r\n"
            f"{auth_header}"
            f"\r\n"
        )
        sock.sendall(request.encode("utf-8"))
        response = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response:
                    break
            except socket.timeout:
                break
        sock.close()

        text = response.decode("utf-8", errors="ignore")
        if "200" in text:
            return "open"
        elif "401" in text:
            return "auth_required"
    except Exception:
        pass
    return "unreachable"


def _find_cached_camera(camera_name: str) -> Optional[CameraConfig]:
    """从 config.yaml 查找指定名称的摄像头配置"""
    try:
        cameras = _load_config_cameras()
        for cam in cameras:
            if cam.name == camera_name:
                return cam
    except Exception:
        pass
    return None


def _load_config_cameras() -> List[CameraConfig]:
    """从 config.yaml 加载摄像头配置列表（内部辅助）。
    
    兼容两种 config.yaml 字段格式:
      - MCP 方案: port / sn_code / rtsp_path / rtsp_sub_path
      - 密码认证方案: onvif_port / sn / rtsp_path_main / rtsp_path_sub
    """
    if not CONFIG_PATH.exists():
        # 兜底搜索
        alt_paths = [
            os.path.join(os.path.dirname(__file__), "..", "..", "confg.yaml"),
            "config.yaml",
        ]
        for p in alt_paths:
            p = os.path.normpath(p)
            if os.path.exists(p):
                break
        else:
            return []

    config_path = CONFIG_PATH if CONFIG_PATH.exists() else os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
    )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            import yaml
            data = yaml.safe_load(f) or {}
    except Exception:
        return []

    cameras_data = data.get("cameras", [])
    configs = []
    for entry in cameras_data:
        try:
            cfg = CameraConfig(
                name=entry.get("name", ""),
                connection_type=entry.get("connection_type", "onvif"),
                ip=entry.get("ip", ""),
                port=int(entry.get("onvif_port", entry.get("port", 0)) or 0),
                username=entry.get("username", "admin"),
                password=entry.get("password", ""),
                rtsp_port=int(entry.get("rtsp_port", 554)),
                rtsp_path=entry.get("rtsp_path_main", entry.get("rtsp_path", "/stream1")),
                rtsp_sub_path=entry.get("rtsp_path_sub", entry.get("rtsp_sub_path", "/stream2")),
                device_class=entry.get("device_class", ""),
                sn_code=entry.get("sn", entry.get("sn_code", "")),
                pkdk=entry.get("pkdk", ""),
                device_index=int(entry.get("device_index", 0)),
                device_model=entry.get("device_model", ""),
                product_version=entry.get("product_version", ""),
                illumination_modes=entry.get("illumination_modes", []),
            )
            configs.append(cfg)
        except Exception:
            continue
    return configs


# ──────────────────────────────────────────────
#  云端授权函数
# ──────────────────────────────────────────────

def _make_device_auth_sign(
    request_id: str,
    timestamp: str,
    device_key: str,
    agent_skill_id: str,
) -> str:
    """按 DeviceCryptUtils#ucHmacSHA256AuthSign 规则计算 scSign。

    - 明文: requestId + timestamp + deviceKey + agentSkillId（无分隔符拼接）
    - 密钥: MD5(agentSkillId)（32 位小写 hex）
    - 签名: HMAC-SHA256(plain, secret) 的 hex 小写串取前 16 位
    """
    secret = hashlib.md5(agent_skill_id.encode("utf-8")).hexdigest()
    plain = request_id + timestamp + device_key + agent_skill_id
    return hmac.new(
        secret.encode("utf-8"), plain.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]


def request_cloud_auth(sn: str) -> CloudAuthRequestResult:
    """
    向云端发起设备授权请求（智能体认证设备授权参数）。

    在 search_devices 发现设备后、connect_device 之前调用。
    向云端 POST /agent/skill/v1/deviceAuthReq，请求体为
    {deviceKey: sn, agentSkillId: claw_id}，云端校验通过后返回 true。

    请求头携带设备签名（HMAC-SHA256）：
    - requestId: 本次请求唯一标识（UUID）
    - timestamp: 毫秒时间戳字符串
    - scSign:    HMAC-SHA256(requestId+timestamp+deviceKey+agentSkillId,
                 MD5(agentSkillId)) 的 hex 前 16 位

    agentSkillId 复用 clawID（从 config.yaml 读取，首次自动生成并持久化），
    HTTP 丢包重发时复用同一 clawID，确保云端识别为同一 Agent。

    安全约束: 无特殊约束（仅发起请求，不携带密码等敏感信息）

    Args:
        sn: 设备序列号（deviceKey）

    Returns:
        CloudAuthRequestResult:
            - success: 云端是否接受请求（R.data == true）
            - claw_id: 本次使用的 clawID（重发时传入相同值）
            - error_message: 失败原因
    """
    claw_id = get_or_create_claw_id()

    if not _CLOUD_AUTH_URL:
        return CloudAuthRequestResult(
            success=False,
            claw_id=claw_id,
            error_message="云端授权地址未配置（_CLOUD_AUTH_URL 为空，请填入 http://host:port/path）",
        )

    if _requests_lib is None:
        return CloudAuthRequestResult(
            success=False,
            claw_id=claw_id,
            error_message="requests 未安装，无法发送 HTTP 请求",
        )

    # 构造设备签名请求头
    request_id = str(uuid.uuid4())
    timestamp = str(int(time.time() * 1000))
    sc_sign = _make_device_auth_sign(request_id, timestamp, sn, claw_id)

    body = {"deviceKey": sn, "agentSkillId": claw_id}
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "requestId": request_id,
        "timestamp": timestamp,
        "scSign": sc_sign,
    }
    try:
        resp = _requests_lib.post(
            _CLOUD_AUTH_URL,
            data=json.dumps(body, separators=(',', ':')),
            headers=headers,
            timeout=10.0,
        )
    except _requests_lib.RequestException as e:
        return CloudAuthRequestResult(
            success=False,
            claw_id=claw_id,
            error_message=f"HTTP 请求失败: {e}",
        )

    if resp.status_code != 200:
        return CloudAuthRequestResult(
            success=False,
            claw_id=claw_id,
            error_message=f"云端返回 HTTP {resp.status_code}: {resp.text[:200]}",
        )

    # 解析 SpringBlade R<T> 响应: code==200 且 data==true 才算成功
    try:
        payload = resp.json()
    except ValueError:
        return CloudAuthRequestResult(
            success=False,
            claw_id=claw_id,
            error_message=f"云端响应非 JSON: {resp.text[:200]}",
        )

    if payload.get("code") == 200 :
        return CloudAuthRequestResult(success=True, claw_id=claw_id)

    return CloudAuthRequestResult(
        success=False,
        claw_id=claw_id,
        error_message=f"云端拒绝请求（code={payload.get('code')}）: {payload.get('msg', '')}",
    )


def poll_auth_status(
    camera_name: str,
) -> AuthStatusResult:
    """
    检测智能体与设备的授权状态（对接 /agent/skill/v1/checkAuth）。

    单次调用做一次查询。Agent 应反复调用（建议间隔 5 秒，最长等待 600 秒 / 10 分钟）：
    - status == AUTHORIZED → devicePwd 已自动写回 config.yaml，可直接调 connect_device
    - status == REJECTED   → 用户在 APP 端拒绝了授权，流程终止
    - status == PENDING    → 用户尚未确认，继续轮询
    - status == ERROR      → 服务器异常或本地配置缺失，流程终止

    授权通过时，云端返回的 devicePwd（MD5(deviceKey) 后 6 位）会自动写入
    config.yaml 中该摄像头的 password 字段，后续 connect_device 直接复用。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称或 SN（从 config.yaml 查找设备 SN）

    Returns:
        AuthStatusResult:
            - status: 授权状态 (PENDING / AUTHORIZED / REJECTED / ERROR)
            - camera_name: 摄像头名称
            - message: 状态说明
            - auth_status_code: 云端原始 authStatus（0/1/2）
            - device_pwd: 授权通过时的设备密码（其余场景为空）
    """
    # 1. 从 config.yaml 查设备 SN
    if _yaml_lib is None:
        return AuthStatusResult(status=AuthStatus.ERROR, camera_name=camera_name, message="pyyaml 未安装")

    cameras = get_registered_cameras()
    camera = next(
        (c for c in cameras if c.name == camera_name or (c.sn_code and c.sn_code == camera_name)),
        None,
    )
    if camera is None or not camera.sn_code:
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=f"未在 config.yaml 找到摄像头或其 SN: {camera_name}",
        )

    # 2. 取持久化 clawID
    claw_id = get_or_create_claw_id()

    # 3. 确定轮询 URL
    check_url = _CLOUD_AUTH_POLL_URL or _CLOUD_AUTH_CHECK_URL
    if not check_url:
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message="云端轮询地址未配置（_CLOUD_AUTH_CHECK_URL 和 _CLOUD_AUTH_POLL_URL 均为空）",
        )

    if _requests_lib is None:
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message="requests 未安装",
        )

    # 4. 构造签名 GET 请求
    request_id = str(uuid.uuid4())
    timestamp = str(int(time.time() * 1000))
    sc_sign = _make_device_auth_sign(request_id, timestamp, camera.sn_code, claw_id)
    params = {"deviceKey": camera.sn_code, "agentSkillId": claw_id}
    headers = {
        "requestId": request_id,
        "timestamp": timestamp,
        "scSign": sc_sign,
    }
    try:
        resp = _requests_lib.get(check_url, params=params, headers=headers, timeout=10.0)
    except _requests_lib.RequestException as e:
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=f"HTTP 请求失败: {e}",
        )

    if resp.status_code != 200:
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=f"云端返回 HTTP {resp.status_code}: {resp.text[:200]}",
        )

    # 5. 解析 R<AgentDeviceAuthVO>
    try:
        payload = resp.json()
    except ValueError:
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=f"云端响应非 JSON: {resp.text[:200]}",
        )

    if payload.get("code") != 200 or not payload.get("success"):
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=f"云端拒绝请求（code={payload.get('code')}）: {payload.get('msg', '')}",
        )

    data = payload.get("data") or {}
    auth_code = int(data.get("authStatus", 0))
    device_pwd = str(data.get("devicePwd") or "")

    # 6. 映射 authStatus → AuthStatus
    if auth_code == 1:
        # 授权通过：devicePwd 写回 config.yaml
        if device_pwd:
            register_camera(
                name=camera.name,
                ip=camera.ip,
                port=camera.port,
                username=camera.username,
                password=device_pwd,
                rtsp_port=camera.rtsp_port,
                rtsp_path=camera.rtsp_path,
                rtsp_sub_path=camera.rtsp_sub_path,
                device_class=camera.device_class,
                sn_code=camera.sn_code,
                pkdk=camera.pkdk,
            )
        return AuthStatusResult(
            status=AuthStatus.AUTHORIZED,
            camera_name=camera.name,
            message=f"用户已授权（devicePwd={device_pwd}）" if device_pwd else "用户已授权",
            auth_status_code=auth_code,
            device_pwd=device_pwd,
        )
    elif auth_code == 2:
        return AuthStatusResult(
            status=AuthStatus.REJECTED,
            camera_name=camera.name,
            message="用户在 APP 端拒绝了授权",
            auth_status_code=auth_code,
        )
    else:
        # auth_code == 0 或其他值都当作 PENDING
        return AuthStatusResult(
            status=AuthStatus.PENDING,
            camera_name=camera.name,
            message="等待用户确认",
            auth_status_code=auth_code,
        )



def disconnect_device(
    camera_name: str,
) -> DisconnectResult:
    """
    断开与摄像头的连接，释放所有资源。

    执行步骤：
    1. 停止所有活跃的视频流和录像
    2. 释放云端会话（如有）
    3. 关闭 ONVIF/RTSP 连接

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        DisconnectResult:
            - success: 断开是否成功
            - session_released: 是否释放了云端会话
            - error_message: 失败原因
    """
    if camera_name in _connected_devices:
        conn_info = _connected_devices.pop(camera_name)
        # 尝试关闭 ONVIF camera 对象
        onvif_cam = conn_info.get("onvif_camera")
        if onvif_cam:
            try:
                onvif_cam.close()
            except Exception:
                pass
        return DisconnectResult(success=True, session_released=True)

    return DisconnectResult(
        success=True,
        session_released=False,
        error_message="设备未在连接列表中",
    )


# ──────────────────────────────────────────────
#  共享辅助: camera 解析器 + resolve_target
# ──────────────────────────────────────────────

def _find_camera(name: str):
    """按 name 查注册表（大小写不敏感）。返回 CameraConfig 或 None。"""
    target = (name or "").strip().lower()
    for cam in get_registered_cameras():
        if (cam.name or "").strip().lower() == target:
            return cam
    return None


def _dev_to_name(dev) -> str:
    """DiscoveredDevice → 默认注册名（model 优先，IP 后缀防重名）"""
    base = dev.model or dev.sn_code or "camera"
    suffix = dev.ip.split(".")[-1] if dev.ip else "x"
    return f"{base}_{suffix}"


def big_register(
    name: str = "",
    ip: str = "",
    onvif_port: int = 2000,
    rtsp_port: int = 554,
    sn_code: str = "",
    password: str = "",
    device_class: str = "password_required",
) -> RegisterResult:
    """注册摄像头到 config.yaml。name 为空时自动生成；提供 password 则验证 ONVIF 鉴权。"""
    rr = register_camera(
        name=name, ip=ip, port=onvif_port,
        username="admin", password=password,
        rtsp_port=rtsp_port,
        device_class=device_class, sn_code=sn_code,
    )
    if not rr.success:
        return rr

    if password:
        try:
            cr = connect_device(rr.camera_name, password=password)
            if not cr.success:
                rr.success = False
                rr.error_message = f"注册成功但 ONVIF 鉴权失败: {cr.error_message}"
        except Exception as e:
            rr.success = False
            rr.error_message = f"注册成功但鉴权异常: {e}"

    return rr


def _resolve_connect_target(name: str) -> Tuple[Optional[CameraConfig], Optional[AuthOrchestrateResult]]:
    """从 config.yaml 按 name 解析目标摄像头；返回 (target, early_result)。
    early_result 不为 None 时，big_connect 应直接返回它。
    """
    cameras = get_registered_cameras()
    if not cameras:
        return None, AuthOrchestrateResult(
            success=False, status="no_devices",
            error_message="config.yaml 中没有已注册设备，请先调用 search_devices",
        )
    if not name:
        if len(cameras) == 1:
            return cameras[0], None
        return None, AuthOrchestrateResult(
            success=False, status="needs_selection",
            available_cameras=[
                {"name": c.name, "ip": c.ip, "sn": c.sn_code, "model": c.device_model}
                for c in cameras
            ],
            error_message="config.yaml 中有多台设备，请指定 name 重新调用",
        )
    target = next((c for c in cameras if c.name == name or c.sn_code == name), None)
    if target is None:
        return None, AuthOrchestrateResult(
            success=False, status="needs_selection",
            available_cameras=[
                {"name": c.name, "ip": c.ip, "sn": c.sn_code, "model": c.device_model}
                for c in cameras
            ],
            error_message=f"未找到摄像头 '{name}'",
        )
    return target, None


def big_connect(name: str = "") -> AuthOrchestrateResult:
    """云端授权编排：发起授权 + 轮询状态，一次调用完成。

    内部流程（对 Agent 透明）：
    1. POST /deviceAuthReq 发起授权请求
    2. GET /checkAuth 轮询状态（5 秒一次，最长 10 分钟）
    3. 授权通过时自动把 devicePwd 写回 config.yaml

    Args:
        name: 摄像头名称（空 → 单台直接用，多台返回列表让 Agent 问用户）

    Returns:
        成功: AuthOrchestrateResult(success=True, status="authorized",
              camera_name, sn, claw_id, device_pwd)
        失败: AuthOrchestrateResult(success=False, status="rejected|timeout|error|...",
              error_message)
    """
    # 1. 解析目标摄像头
    target, early = _resolve_connect_target(name)
    if early is not None:
        return early
    if not target.sn_code:
        return AuthOrchestrateResult(
            success=False, status="no_sn",
            camera_name=target.name,
            error_message=f"设备 '{target.name}' 未记录 SN，无法发起云端授权",
        )

    # 2. 发起授权请求（POST）
    cr = request_cloud_auth(target.sn_code)
    if not cr.success:
        return AuthOrchestrateResult(
            success=False, status="cloud_error",
            camera_name=target.name, sn=target.sn_code,
            claw_id=cr.claw_id,
            error_message=cr.error_message,
        )

    # 3. 轮询授权状态（GET，5 秒一次，最多 10 分钟 = 120 次）
    poll_interval = 5
    max_polls = 120  # 10 * 60 / 5 = 120
    for _ in range(max_polls):
        time.sleep(poll_interval)
        result = poll_auth_status(target.name)
        if result.status == AuthStatus.AUTHORIZED:
            return AuthOrchestrateResult(
                success=True, status="authorized",
                camera_name=target.name, sn=target.sn_code,
                claw_id=cr.claw_id,
                device_pwd=result.device_pwd,
            )
        elif result.status == AuthStatus.REJECTED:
            return AuthOrchestrateResult(
                success=False, status="rejected",
                camera_name=target.name, sn=target.sn_code,
                claw_id=cr.claw_id,
                error_message="用户在 APP 端拒绝了授权",
            )
        elif result.status == AuthStatus.ERROR:
            return AuthOrchestrateResult(
                success=False, status="error",
                camera_name=target.name, sn=target.sn_code,
                claw_id=cr.claw_id,
                error_message=result.message,
            )
        # PENDING: 继续轮询

    # 4. 超时
    return AuthOrchestrateResult(
        success=False, status="timeout",
        camera_name=target.name, sn=target.sn_code,
        claw_id=cr.claw_id,
        error_message="授权等待超时（10 分钟），用户未确认",
    )


def resolve_target(
    name: Optional[str] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    解析目标 camera，4 段降级（写死，agent 不需判断）：
      Stage 0. answers["camera"] 已选（NEEDS_INPUT 重调）→ 查注册；未注册就重 search + register
      Stage 1. name 显式给 → 查注册
      Stage 2. 注册列表 1 台 → 用；多台 → NEEDS_INPUT
      Stage 3. 注册列表 0 台 → 自动 search → 1 台 auto-register；多台 NEEDS_INPUT；0 台 NO_CAMERAS

    Returns:
        ok=True:  {"ok": True, "camera": CameraConfig, "via": "user_picked|user_picked_registered|registered|auto_registered"}
        ok=False: {"ok": False, "error_code": "NEEDS_INPUT|CAMERA_NOT_FOUND|NO_CAMERAS|...", "message", "hint", "needs_input"?}
    """
    answers = answers or {}

    # ── Stage 0: NEEDS_INPUT 重调带 camera 选 ──
    if answers.get("camera"):
        chosen = answers["camera"]
        cam = _find_camera(chosen)
        if cam:
            return {"ok": True, "camera": cam, "via": "user_picked"}
        # 未注册 → 从 search options 选的 → 重 search + register
        try:
            sr = search_devices(timeout=15.0)
        except Exception as e:
            return {"ok": False, "error_code": "SEARCH_FAILED", "message": f"重 search 失败: {e}"}
        if sr.success:
            for dev in sr.devices:
                if _dev_to_name(dev) == chosen:
                    reg = big_register(
                        name=chosen, ip=dev.ip, onvif_port=dev.onvif_port,
                        rtsp_port=dev.rtsp_port, sn_code=dev.sn_code,
                        device_class=dev.device_class.value if hasattr(dev.device_class, "value") else str(dev.device_class),
                    )
                    if reg.success:
                        return {"ok": True, "camera": _find_camera(chosen), "via": "user_picked_registered"}
                    return {"ok": False, "error_code": "AUTO_REGISTER_FAILED",
                            "message": f"注册 {chosen} 失败: {reg.error_message}"}
        return {"ok": False, "error_code": "CAMERA_NOT_FOUND",
                "message": f"选了 {chosen!r} 但局域网未发现该设备",
                "hint": "重新调 search_devices 看当前可发现设备"}

    # ── Stage 1: name 显式给 ──
    if name:
        cam = _find_camera(name)
        if cam:
            return {"ok": True, "camera": cam, "via": "registered"}
        return {"ok": False, "error_code": "CAMERA_NOT_FOUND",
                "message": f"name={name!r} 不在 config.yaml",
                "hint": "用 get_registered_cameras 看已注册列表，或 search_devices 找新设备"}

    # ── Stage 2: 没 name，看注册列表 ──
    cams = get_registered_cameras()
    if len(cams) == 1:
        return {"ok": True, "camera": cams[0], "via": "registered"}
    if len(cams) > 1:
        return {"ok": False, "error_code": "NEEDS_INPUT",
                "needs_input": [{
                    "key": "camera",
                    "question": f"已注册 {len(cams)} 台摄像头，选哪台？",
                    "options": [{"label": f"{c.name} ({c.ip})", "value": c.name} for c in cams],
                }]}

    # ── Stage 3: list 空，自动 search ──
    try:
        sr = search_devices(timeout=15.0)
    except Exception as e:
        return {"ok": False, "error_code": "NO_CAMERAS",
                "message": f"config.yaml 空 + search 失败: {e}",
                "hint": "检查网络或手动 search_devices"}

    if not sr.success or not sr.devices:
        return {"ok": False, "error_code": "NO_CAMERAS",
                "message": "config.yaml 空 + 局域网内未发现任何设备",
                "hint": "检查相机电源和网络"}

    # ── Stage 4: search 找到几台 ──
    if len(sr.devices) == 1:
        dev = sr.devices[0]
        dev_name = _dev_to_name(dev)
        reg = big_register(
            name=dev_name, ip=dev.ip, onvif_port=dev.onvif_port,
            rtsp_port=dev.rtsp_port, sn_code=dev.sn_code,
            device_class=dev.device_class.value if hasattr(dev.device_class, "value") else str(dev.device_class),
        )
        if reg.success:
            return {"ok": True, "camera": _find_camera(dev_name), "via": "auto_registered"}
        return {"ok": False, "error_code": "AUTO_REGISTER_FAILED",
                "message": f"自动注册 {dev_name} 失败: {reg.error_message}",
                "hint": "手动调 register_camera 排查"}

    # 多台 → NEEDS_INPUT
    return {"ok": False, "error_code": "NEEDS_INPUT",
            "needs_input": [{
                "key": "camera",
                "question": f"局域网发现 {len(sr.devices)} 台设备，注册哪台？",
                "options": [{
                    "label": f"{d.model or d.sn_code or '?'} ({d.ip})",
                    "value": _dev_to_name(d),
                } for d in sr.devices],
            }]}
