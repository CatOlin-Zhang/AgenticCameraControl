import base64
import hashlib
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

try:
    from . import sk_proto
except ImportError:
    import sk_proto

from .discovery import (
    SkDiscoveredDevice,
    SkChannelInfo,
    discover_sky_devices,
    probe_device_sn,
    SUBTYPE_NAMES,
)

class DiscoveryMethod(str, Enum):
    WS_DISCOVERY = "ws_discovery"
    SKY_DISCOVERY = "sky_discovery"
    USB = "usb"

class DeviceClass(str, Enum):
    PASSWORD_REQUIRED = "password_required"
    DIRECT_CONNECT = "direct_connect"

class AuthStatus(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    REJECTED = "rejected"
    ERROR = "error"

@dataclass
class DiscoveredDevice:
    ip: str
    onvif_port: int = 0
    rtsp_port: int = 554
    device_class: DeviceClass = DeviceClass.PASSWORD_REQUIRED
    sn_code: str = ""
    model: str = ""
    manufacturer: str = ""
    supported_media: List[str] = field(default_factory=list)

    sky_subtype: str = ""
    sky_name: str = ""
    sky_dtype: str = ""
    sky_hw_version: str = ""
    sky_sw_version: str = ""
    sky_did: str = ""
    sky_channels: int = 0
    sky_channel_list: List[SkChannelInfo] = field(default_factory=list)
    sky_web_port: int = 0
    sky_udp_port: int = 0
    sky_net_type: str = ""
    sky_ip_mode: str = ""
    sky_mask: str = ""
    sky_gateway: str = ""
    sky_mac: str = ""
    discovery_method: str = ""
    supported_illumination_modes: List[str] = field(default_factory=list)

@dataclass
class SearchResult:
    success: bool
    devices: List[DiscoveredDevice] = field(default_factory=list)
    error_message: str = ""

@dataclass
class ConnectResult:
    success: bool
    auth_method: str = ""
    status: str = "connected"
    error_message: str = ""
    needs_password: bool = False
    onvif_port: int = 0

@dataclass
class DisconnectResult:
    success: bool
    session_released: bool = False
    error_message: str = ""

@dataclass
class CameraConfig:
    name: str
    connection_type: str = "onvif"
    ip: str = ""
    port: int = 0
    username: str = "admin"
    password: str = ""
    rtsp_port: int = 554
    rtsp_path: str = "/md0_0"
    rtsp_sub_path: str = "/md0_1"
    device_class: str = ""
    sn_code: str = ""
    pkdk: str = ""

    device_index: int = 0
    device_model: str = ""
    product_version: str = ""

    illumination_modes: List[str] = field(default_factory=list)

@dataclass
class RegisterResult:
    success: bool
    camera_name: str = ""
    error_message: str = ""

@dataclass
class AuthOrchestrateResult:
    success: bool
    status: str = ""
    camera_name: str = ""
    sn: str = ""
    claw_id: str = ""
    device_pwd: str = ""
    available_cameras: List[Dict[str, str]] = field(default_factory=list)
    error_message: str = ""

@dataclass
class AuthStatusResult:
    status: AuthStatus
    camera_name: str = ""
    message: str = ""
    auth_status_code: int = -1
    device_pwd: str = ""

@dataclass
class CloudAuthRequestResult:
    success: bool
    claw_id: str = ""
    error_message: str = ""

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"

_SK_TCP_PORT = 9010

def _get_local_ip() -> str:
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
    mac = _get_local_mac().replace(":", "").upper()
    now = datetime.now()
    ts = now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"
    return f"claw-{mac}-{ts}"

def _dump_claw_id_first(data: Dict[str, Any], claw_id: str) -> Dict[str, Any]:
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

        if next(iter(data), None) != "claw_id":
            _dump_claw_id_first(data, str(existing))
        return str(existing)

    claw_id = generate_claw_id()
    _dump_claw_id_first(data, claw_id)
    return claw_id

_ONVIF_NS = {
    "soap": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}

def _onvif_digest_auth_header(username: str, password: str) -> str:
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

_ONVIF_CANDIDATE_PORTS = [2000, 80, 8000, 8899]

_ONVIF_PROBE_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
    '<soap:Header/><soap:Body><tds:GetSystemDateAndTime/></soap:Body></soap:Envelope>'
)

def _probe_onvif_port(ip: str, hint_port: int = 0, timeout: float = 2.0) -> int:
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

            text = (resp.text or "")[:2048].lower()
            if "envelope" in text and "<html" not in text:
                return p
        except Exception:
            continue
    return 0

def _build_rtsp_url(ip: str, port: int, path: str, username: str = "", password: str = "") -> str:
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

def get_registered_cameras() -> List[CameraConfig]:
    return _load_config_cameras()

def register_camera(
    name: str,
    ip: str = "",
    port: int = 0,
    username: str = "admin",
    password: str = "",
    rtsp_port: int = 554,
    rtsp_path: str = "/md0_0",
    device_class: str = "direct_connect",
    connection_type: str = "onvif",
    sn_code: str = "",
    pkdk: str = "",
    rtsp_sub_path: str = "/md0_1",
    device_index: int = 0,
    device_model: str = "",
    product_version: str = "",
    illumination_modes: Optional[List[str]] = None,
) -> RegisterResult:
    import os
    import yaml

    config_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_path = os.path.join(config_dir, "config.yaml")

    if not os.path.exists(config_path):
        alt_path = os.path.join(config_dir, "confg.yaml")
        if os.path.exists(alt_path):
            config_path = alt_path

    data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    cameras = data.get("cameras", [])

    if not password or not sn_code:
        existing = None
        for cam in cameras:
            if cam.get("name") == name:
                existing = cam
                break
        if existing is None and ip:
            for cam in cameras:
                if cam.get("ip") == ip:
                    existing = cam
                    break
        if existing is None and sn_code:
            for cam in cameras:
                if cam.get("sn_code") == sn_code or cam.get("sn") == sn_code:
                    existing = cam
                    break
        if existing:
            if not password and existing.get("password"):
                password = existing["password"]
            if not sn_code:
                sn_code = existing.get("sn_code") or existing.get("sn") or ""

    new_entry = {
        "name": name,
        "connection_type": connection_type,
        "ip": ip,
        "port": port,
        "onvif_port": port,
        "username": username,
        "password": password,
        "rtsp_port": rtsp_port,
        "rtsp_path": rtsp_path,
        "rtsp_path_main": rtsp_path,
        "rtsp_sub_path": rtsp_sub_path,
        "rtsp_path_sub": rtsp_sub_path,
        "device_class": device_class,
        "sn_code": sn_code,
        "sn": sn_code,
        "pkdk": pkdk,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    if connection_type == "usb":
        new_entry["device_index"] = device_index
        new_entry["device_model"] = device_model
        new_entry["product_version"] = product_version
    if illumination_modes:
        new_entry["illumination_modes"] = illumination_modes

    found = False

    for i, cam in enumerate(cameras):
        if cam.get("name") == name:
            cameras[i] = new_entry
            found = True
            break

    if not found and ip:
        for i, cam in enumerate(cameras):
            if cam.get("ip") == ip:
                cameras[i] = new_entry
                found = True
                break

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
    method: Optional[DiscoveryMethod] = None,
    timeout: float = 15.0,
) -> SearchResult:

    if method is not None:
        if method == DiscoveryMethod.SKY_DISCOVERY:
            return _search_sky_devices(timeout)
        elif method == DiscoveryMethod.USB:

            return SearchResult(success=True, devices=[], error_message="USB 扫描已禁用")
        else:
            return _search_ws_discovery_devices(timeout)

    all_devices: List[DiscoveredDevice] = []
    seen_ips: set = set()
    errors: List[str] = []

    for search_fn in (_search_sky_devices, _search_ws_discovery_devices):
        try:
            result = search_fn(timeout)
            if result.success:
                for dev in result.devices:
                    if dev.ip not in seen_ips:
                        seen_ips.add(dev.ip)
                        all_devices.append(dev)
            elif result.error_message:
                errors.append(result.error_message)
        except Exception as e:
            errors.append(str(e))

    if not all_devices and errors:
        return SearchResult(
            success=False,
            devices=[],
            error_message="; ".join(errors),
        )

    return SearchResult(success=True, devices=all_devices)

def _search_sky_devices(timeout: float) -> SearchResult:
    try:
        sky_devices = discover_sky_devices(timeout=timeout)
        devices = []
        for sd in sky_devices:

            rtsp_path = sd.rtsp_paths[0] if sd.rtsp_paths else "/md0_0"
            access = _probe_stream_access(sd.ip, sd.rtsp_port, rtsp_path)
            device_class = (
                DeviceClass.DIRECT_CONNECT if access == "open"
                else DeviceClass.PASSWORD_REQUIRED
            )
            dev = DiscoveredDevice(
                ip=sd.ip,
                onvif_port=0,
                rtsp_port=sd.rtsp_port,
                device_class=device_class,
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
    import select
    import uuid

    probe_wait = max(1.0, min(timeout, 15.0))

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

    devices = []
    for ip, info in sorted(found.items()):
        access = _probe_stream_access(ip, 554, "/md0_0")
        device_class = (
            DeviceClass.DIRECT_CONNECT if access == "open"
            else DeviceClass.PASSWORD_REQUIRED
        )

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

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            addrs.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return addrs

def _parse_ws_probe_match(data: bytes) -> Optional[dict]:
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
    onvif_port = 0
    if xaddrs:
        try:
            parsed = urlparse(xaddrs.split()[0])

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

    if not sn_code:
        return ConnectResult(
            success=False, status="needs_password",
            needs_password=True,
            error_message=(
                f"设备 {camera_name}({ip}) 无 SN，无法发起云端授权。"
                f"请直接输入密码后调用 connect_device。"
            ),
        )

    cr = request_cloud_auth(sn_code)
    if not cr.success:

        return ConnectResult(
            success=False, status="needs_password",
            needs_password=True,
            error_message=(
                f"云端授权服务不可用（{cr.error_message}）。"
                f"请直接输入设备 {camera_name}({ip}) 的密码。"
            ),
        )

    register_camera(
        name=camera_name, ip=ip, port=port,
        username=username, password="",
        rtsp_port=rtsp_port, rtsp_path=rtsp_path,
        device_class="password_required",
        sn_code=sn_code,
        connection_type=cached.connection_type if cached else "onvif",
    )

    poll_interval = 5
    max_polls = 60
    for _ in range(max_polls):
        time.sleep(poll_interval)
        result = poll_auth_status(camera_name)

        if result.status == AuthStatus.AUTHORIZED:

            conn = _try_connect_with_password(
                camera_name, ip, port, rtsp_port, rtsp_path,
                username, result.device_pwd,
                require_rtsp=True,
            )
            if conn.success:

                register_camera(
                    name=camera_name, ip=ip,
                    port=conn.onvif_port or port,
                    username=username, password=result.device_pwd,
                    rtsp_port=rtsp_port, rtsp_path=rtsp_path,
                    device_class="password_required",
                    sn_code=sn_code,
                    connection_type=cached.connection_type if cached else "onvif",
                )

                _probe_and_save_illumination(
                    camera_name, ip,
                    conn.onvif_port or port,
                    username, result.device_pwd, cached,
                )
                return conn
            else:

                return ConnectResult(
                    success=False, status="cloud_pwd_failed",
                    needs_password=True,
                    error_message=(
                        f"云端下发的密码无法通过设备 {camera_name}({ip}) 的验证"
                        f"（{conn.error_message}），设备可能修改过密码或存在凭据隔离。"
                        f"请输入正确密码。"
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

    return ConnectResult(
        success=False, status="needs_password",
        needs_password=True,
        error_message=(
            f"云端授权等待超时（5 分钟），用户未确认。"
            f"请直接输入设备 {camera_name}({ip}) 的密码。"
        ),
    )

def connect_device(
    camera_name: str,
    password: Optional[str] = None,
    ip: Optional[str] = None,
    port: Optional[int] = None,
    rtsp_port: Optional[int] = None,
    rtsp_path: str = "/md0_0",
    username: str = "admin",
    sn_code: str = "",
    device_class: str = "",
) -> ConnectResult:

    cached = _find_cached_camera(camera_name)

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
        dev_port = port or 0
        dev_rtsp_port = rtsp_port or 554
        dev_rtsp_path = rtsp_path
        dev_username = username
        dev_pwd = password or ""
        dev_class = device_class
    else:
        return ConnectResult(
            success=False, status="failed",
            error_message=f"未找到设备 {camera_name} 的连接信息（config.yaml 中无记录且未提供 IP）",
        )

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

            if not effective_sn:
                effective_sn = _probe_sn_via_sky(dev_ip, timeout=3.0)
            if not effective_sn:

                _connected_devices.pop(camera_name, None)
                return ConnectResult(
                    success=False, status="no_sn",
                    error_message=(
                        f"设备 {camera_name}({dev_ip}) 密码验证通过但 SN 探测失败，"
                        f"已拒绝进入连接态（连接态设备必须在 config 中注册 SN，"
                        f"否则 SK 私有功能将全部失效）。"
                        f"请确认设备为 SK 协议设备后重试。"
                    ),
                )

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

            _probe_and_save_illumination(
                camera_name, dev_ip,
                verified_port or (cached.port if cached else 0),
                dev_username, dev_pwd, cached,
            )
            return last_result

        if cached and not password:

            if effective_sn:
                cloud_result = _cloud_auth_and_connect(
                    camera_name, dev_ip, dev_port, effective_sn,
                    dev_rtsp_port, dev_rtsp_path, dev_username,
                    cached=cached,
                )
                if cloud_result.success:
                    return cloud_result

            _remove_camera_config(camera_name)
            return ConnectResult(
                success=False, status="needs_password",
                needs_password=True,
                error_message=(
                    f"缓存凭据已失效（{last_result.error_message}），"
                    f"云端重新授权也未能获取可用密码。"
                    f"请直接输入设备 {camera_name}({dev_ip}) 的当前密码。"
                ),
            )
        return ConnectResult(
            success=False, status="failed",
            needs_password=True,
            error_message=f"密码认证失败: {last_result.error_message}，请确认密码后重试",
        )

    if dev_class == "password_required":
        return _cloud_auth_and_connect(
            camera_name, dev_ip, dev_port, effective_sn,
            dev_rtsp_port, dev_rtsp_path, dev_username,
            cached=cached,
        )

    access = _probe_stream_access(dev_ip, dev_rtsp_port, dev_rtsp_path)

    if access == "open":

        probed_sn = effective_sn or _probe_sn_via_sky(dev_ip, timeout=3.0)

        if not probed_sn:
            return ConnectResult(
                success=False, status="no_sn",
                error_message=(
                    f"设备 {camera_name}({dev_ip}) 免密可达但 SN 探测失败，"
                    f"已拒绝进入连接态（连接态设备必须在 config 中注册 SN，"
                    f"否则 SK 私有功能将全部失效）。"
                    f"请确认设备为 SK 协议设备且网络可达后重试。"
                ),
            )

        verified_port = _probe_onvif_port(dev_ip, hint_port=dev_port)

        sk_http_ok = False
        if probed_sn:
            sk_http_ok = _verify_sk_http(dev_ip, probed_sn)

        conn_info = {
            "ip": dev_ip,
            "port": verified_port or dev_port,
            "rtsp_port": dev_rtsp_port,
            "rtsp_path": dev_rtsp_path,

            "rtsp_sub_path": (cached.rtsp_sub_path if cached and cached.rtsp_sub_path else "") or "/md0_1",
            "username": "",
            "password": "",
            "sn_code": probed_sn,
        }

        if verified_port or dev_port:
            try:
                from onvif import ONVIFCamera
                cam = ONVIFCamera(host=dev_ip, port=verified_port or dev_port,
                                  user=dev_username or "admin", passwd=dev_pwd or "")
                cam.create_devicemgmt_service().GetDeviceInformation()
                conn_info["onvif_camera"] = cam
            except Exception:
                pass
        _connected_devices[camera_name] = conn_info

        if not cached or not cached.sn_code:
            register_camera(
                name=camera_name, ip=dev_ip, port=verified_port,
                username="", password="",
                rtsp_port=dev_rtsp_port, rtsp_path=dev_rtsp_path,
                device_class="direct_connect",
                sn_code=probed_sn,
            )

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

        return _cloud_auth_and_connect(
            camera_name, dev_ip, dev_port, effective_sn,
            dev_rtsp_port, dev_rtsp_path, dev_username,
            cached=cached,
        )

    return ConnectResult(
        success=False,
        status="failed",
        error_message=f"设备 {dev_ip} 不可达（RTSP 端口 {dev_rtsp_port} 无响应）",
    )

_connected_devices: Dict[str, dict] = {}

def _verify_sk_http(ip: str, sn: str, timeout: float = 5.0) -> bool:
    try:
        env = sk_proto.verify_sk_http(ip, timeout=timeout)
        return bool(env.get("available"))
    except Exception:
        return False

def _probe_and_save_illumination(
    camera_name: str,
    ip: str,
    port: int,
    username: str,
    password: str,
    cached: Optional[CameraConfig] = None,
) -> List[str]:

    if cached and cached.illumination_modes:
        return cached.illumination_modes
    try:
        from .illumination import probe_illumination_capability
        info = probe_illumination_capability(
            ip, port, username, password,
            sn_code=cached.sn_code if cached else "",
        )
        if info.supported and info.supported_modes:

            register_camera(
                name=camera_name, ip=ip, port=port,
                username=username, password=password,
                rtsp_port=cached.rtsp_port if cached else 554,
                rtsp_path=cached.rtsp_path if cached else "/md0_0",
                device_class=cached.device_class if cached else "",
                sn_code=cached.sn_code if cached else "",
                connection_type=cached.connection_type if cached else "onvif",
                illumination_modes=info.supported_modes,
            )

            if info.protocol == "sky_private":
                conn = _connected_devices.get(camera_name)
                if conn and not conn.get("tcp_port"):
                    conn["tcp_port"] = _SK_TCP_PORT
            return info.supported_modes
    except Exception:
        pass
    return []

def _remove_camera_config(name: str) -> bool:
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
            return False
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
    require_rtsp: bool = False,
) -> ConnectResult:

    verified_port = _probe_onvif_port(ip, hint_port=onvif_port)
    effective_port = verified_port or onvif_port

    _cached_cfg = _find_cached_camera(camera_name)
    sub_path = (_cached_cfg.rtsp_sub_path if _cached_cfg and _cached_cfg.rtsp_sub_path else "") or "/md0_1"

    env = sk_proto.device_get_info(ip, username, password, timeout=5.0)
    resp = env.get("body") if env.get("ok") else None
    tcp_ok = False
    if resp is not None:
        _tcp_http_status = env.get("http_status", 0)
        _tcp_resp_code = resp.get("code", "")

        tcp_ok = (
            _tcp_http_status == 200
            or (not _tcp_http_status and
                (_tcp_resp_code == "" or sk_proto.code_accept(_tcp_resp_code)))
        )
        if tcp_ok:
            _connected_devices[camera_name] = {
                "ip": ip, "port": effective_port,
                "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
                "rtsp_sub_path": sub_path,
                "username": username, "password": password,
                "tcp_port": _SK_TCP_PORT,
            }

    onvif_ok = False
    if effective_port:
        try:
            from onvif import ONVIFCamera
            cam = ONVIFCamera(host=ip, port=effective_port, user=username, passwd=password)
            dev_svc = cam.create_devicemgmt_service()
            dev_svc.GetDeviceInformation()
            onvif_ok = True

            conn = _connected_devices.get(camera_name, {
                "ip": ip, "port": effective_port,
                "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
                "rtsp_sub_path": sub_path,
                "username": username, "password": password,
            })
            conn["onvif_camera"] = cam
            _connected_devices[camera_name] = conn
        except Exception:
            pass

    rtsp_access = _probe_stream_access(ip, rtsp_port, rtsp_path, username, password)
    rtsp_ok = (rtsp_access == "open")

    if (tcp_ok or onvif_ok) and rtsp_ok:

        return ConnectResult(
            success=True, auth_method="password", status="connected",
            onvif_port=verified_port,
        )

    if (tcp_ok or onvif_ok) and rtsp_access == "auth_required":

        _connected_devices.pop(camera_name, None)
        return ConnectResult(
            success=False, status="failed",
            error_message="TCP/ONVIF 连接成功但 RTSP 认证失败（密码可能对 RTSP 无效）",
        )

    if rtsp_ok:

        _connected_devices[camera_name] = {
            "ip": ip, "port": effective_port,
            "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
            "rtsp_sub_path": sub_path,
            "username": username, "password": password,
        }
        return ConnectResult(
            success=True, auth_method="password", status="connected",
            onvif_port=verified_port,
        )

    if (tcp_ok or onvif_ok) and rtsp_access == "unreachable":
        if require_rtsp:

            _connected_devices.pop(camera_name, None)
            return ConnectResult(
                success=False, status="failed",
                error_message="RTSP 端口不可达，密码未经 RTSP 验证（云端授权密码要求强制 RTSP 验证）",
            )

        return ConnectResult(
            success=True, auth_method="password", status="connected",
            onvif_port=verified_port,
        )

    _connected_devices.pop(camera_name, None)
    return ConnectResult(
        success=False, status="failed",
        error_message="TCP/ONVIF/RTSP 均连接失败",
    )

def _rtsp_read_response_head(sock) -> str:
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
    return response.decode("utf-8", errors="ignore")

def _rtsp_status_code(resp_text: str) -> int:
    import re
    first_line = resp_text.split("\r\n", 1)[0].split("\n", 1)[0].strip()
    m = re.match(r"^RTSP/\d+\.\d+\s+(\d{3})", first_line)
    return int(m.group(1)) if m else 0

def _rtsp_send_describe(sock, rtsp_url: str, cseq: int, auth_header: str = "") -> str:
    request = (
        f"DESCRIBE {rtsp_url} RTSP/1.0\r\n"
        f"CSeq: {cseq}\r\n"
        f"Accept: application/sdp\r\n"
        f"{auth_header}"
        f"\r\n"
    )
    sock.sendall(request.encode("utf-8"))
    return _rtsp_read_response_head(sock)

def _parse_www_authenticate(resp_text: str) -> List[Dict[str, Any]]:
    import re
    challenges: List[Dict[str, Any]] = []
    for line in resp_text.splitlines():
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        if name.strip().lower() != "www-authenticate":
            continue
        m = re.match(r"\s*(Basic|Digest)\s*(.*)", value, re.IGNORECASE)
        if not m:
            continue
        params: Dict[str, str] = {}
        for key, quoted, plain in re.findall(
            r'([a-zA-Z][a-zA-Z0-9_-]*)=(?:"([^"]*)"|([^\s,]+))', m.group(2)
        ):
            params[key.lower()] = quoted if quoted else plain.rstrip(",")
        challenges.append({"scheme": m.group(1).lower(), "params": params})
    return challenges

def _build_rtsp_digest_header(
    params: Dict[str, str],
    username: str,
    password: str,
    method: str,
    uri: str,
) -> str:
    def _md5(s: str) -> str:
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    realm = params.get("realm", "")
    nonce = params.get("nonce", "")
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    qop = (params.get("qop", "") or "").split(",")[0].strip()
    if qop:
        nc = "00000001"
        cnonce = secrets.token_hex(4)
        response = _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        qop_fields = f', qop={qop}, nc={nc}, cnonce="{cnonce}"'
    else:
        response = _md5(f"{ha1}:{nonce}:{ha2}")
        qop_fields = ""
    header = (
        f'Authorization: Digest username="{username}", realm="{realm}", '
        f'nonce="{nonce}", uri="{uri}", response="{response}", algorithm=MD5'
    )
    if params.get("opaque"):
        header += f', opaque="{params["opaque"]}"'
    return header + qop_fields + "\r\n"

def _rtsp_negotiated_describe(
    ip: str,
    rtsp_port: int,
    path: str,
    username: str = "",
    password: str = "",
    timeout: float = 5.0,
) -> Tuple[int, str]:
    rtsp_url = f"rtsp://{ip}:{rtsp_port}{path}"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, rtsp_port))
    except Exception:
        return 0, ""

    try:

        resp = _rtsp_send_describe(sock, rtsp_url, 1)
        code = _rtsp_status_code(resp)
        if code != 401 or not (username and password):
            return code, resp

        try:
            sock.settimeout(0.2)
            while sock.recv(4096):
                pass
        except Exception:
            pass
        sock.settimeout(timeout)

        challenges = _parse_www_authenticate(resp)
        ordered = ([c for c in challenges if c["scheme"] == "digest"]
                   + [c for c in challenges if c["scheme"] == "basic"])
        if not ordered:

            ordered = [{"scheme": "basic", "params": {}}]

        for cseq, challenge in enumerate(ordered, start=2):
            if challenge["scheme"] == "digest":
                auth_header = _build_rtsp_digest_header(
                    challenge["params"], username, password, "DESCRIBE", rtsp_url,
                )
            else:
                token = base64.b64encode(f"{username}:{password}".encode()).decode()
                auth_header = f"Authorization: Basic {token}\r\n"
            resp = _rtsp_send_describe(sock, rtsp_url, cseq, auth_header)
            code = _rtsp_status_code(resp)
            if code != 401:
                return code, resp
        return code, resp
    except Exception:
        return 0, ""
    finally:
        try:
            sock.close()
        except Exception:
            pass

def _probe_stream_access(
    ip: str,
    rtsp_port: int = 554,
    rtsp_path: str = "/md0_0",
    username: str = "",
    password: str = "",
) -> str:

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        result = sock.connect_ex((ip, rtsp_port))
        sock.close()
        if result != 0:
            return "unreachable"
    except Exception:
        return "unreachable"

    code, _resp_text = _rtsp_negotiated_describe(ip, rtsp_port, rtsp_path, username, password)

    if code == 200:
        return "open"
    if code == 401:
        return "auth_required"
    if code:

        for alt_path in ["/Streaming/Channels/101", "/h264/ch1/main/av_stream", "/live",
                         "/stream0", "/md0_0", "/stream1", "/md0_1"]:
            if alt_path == rtsp_path:
                continue
            alt_result = _quick_rtsp_check(ip, rtsp_port, alt_path, username, password)
            if alt_result == "open":
                return "open"
            elif alt_result == "auth_required":
                return "auth_required"
        return "open"

    return "open"

def _quick_rtsp_check(
    ip: str, rtsp_port: int, path: str,
    username: str = "", password: str = "",
) -> str:
    code, _ = _rtsp_negotiated_describe(ip, rtsp_port, path, username, password)
    if code == 200:
        return "open"
    if code == 401:
        return "auth_required"
    return "unreachable"

def _find_cached_camera(camera_name: str) -> Optional[CameraConfig]:
    try:
        cameras = _load_config_cameras()
        for cam in cameras:
            if cam.name == camera_name:
                return cam
    except Exception:
        pass
    return None

def _load_config_cameras() -> List[CameraConfig]:
    if not CONFIG_PATH.exists():

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
                rtsp_path=entry.get("rtsp_path_main", entry.get("rtsp_path", "/md0_0")),
                rtsp_sub_path=entry.get("rtsp_path_sub", entry.get("rtsp_sub_path", "/md0_1")),
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

def request_cloud_auth(sn: str) -> CloudAuthRequestResult:
    claw_id = get_or_create_claw_id()

    try:
        env = sk_proto.cloud_auth_request(sn, claw_id, timeout=10.0)
    except Exception as e:
        return CloudAuthRequestResult(
            success=False,
            claw_id=claw_id,
            error_message=f"云端请求失败: {e}",
        )

    if not env.get("ok"):
        return CloudAuthRequestResult(
            success=False,
            claw_id=claw_id,
            error_message=env.get("error", "云端请求失败"),
        )

    payload = env.get("body") or {}
    if payload.get("code") == 200:
        return CloudAuthRequestResult(success=True, claw_id=claw_id)

    return CloudAuthRequestResult(
        success=False,
        claw_id=claw_id,
        error_message=f"云端拒绝请求（code={payload.get('code')}）: {payload.get('msg', '')}",
    )

def poll_auth_status(
    camera_name: str,
) -> AuthStatusResult:

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

    claw_id = get_or_create_claw_id()

    try:
        env = sk_proto.cloud_auth_check(camera.sn_code, claw_id, timeout=10.0)
    except Exception as e:
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=f"云端请求失败: {e}",
        )

    if not env.get("ok"):
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=env.get("error", "云端请求失败"),
        )

    payload = env.get("body")
    if not isinstance(payload, dict):
        payload = {}

    if payload.get("code") != 200 or not payload.get("success"):
        return AuthStatusResult(
            status=AuthStatus.ERROR,
            camera_name=camera_name,
            message=f"云端拒绝请求（code={payload.get('code')}）: {payload.get('msg', '')}",
        )

    data = payload.get("data") or {}
    auth_code = int(data.get("authStatus", 0))
    device_pwd = str(data.get("devicePwd") or "")

    if auth_code == 1:

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

        return AuthStatusResult(
            status=AuthStatus.PENDING,
            camera_name=camera.name,
            message="等待用户确认",
            auth_status_code=auth_code,
        )

def disconnect_device(
    camera_name: str,
) -> DisconnectResult:
    if camera_name in _connected_devices:
        conn_info = _connected_devices.pop(camera_name)

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

def _find_camera(name: str):
    target = (name or "").strip().lower()
    for cam in get_registered_cameras():
        if (cam.name or "").strip().lower() == target:
            return cam
    return None

def _dev_to_name(dev) -> str:
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

    target, early = _resolve_connect_target(name)
    if early is not None:
        return early
    if not target.sn_code:
        return AuthOrchestrateResult(
            success=False, status="no_sn",
            camera_name=target.name,
            error_message=f"设备 '{target.name}' 未记录 SN，无法发起云端授权",
        )

    cr = request_cloud_auth(target.sn_code)
    if not cr.success:
        return AuthOrchestrateResult(
            success=False, status="cloud_error",
            camera_name=target.name, sn=target.sn_code,
            claw_id=cr.claw_id,
            error_message=cr.error_message,
        )

    poll_interval = 5
    max_polls = 120
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
    answers = answers or {}

    if answers.get("camera"):
        chosen = answers["camera"]
        cam = _find_camera(chosen)
        if cam:
            return {"ok": True, "camera": cam, "via": "user_picked"}

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

    if name:
        cam = _find_camera(name)
        if cam:
            return {"ok": True, "camera": cam, "via": "registered"}
        return {"ok": False, "error_code": "CAMERA_NOT_FOUND",
                "message": f"name={name!r} 不在 config.yaml",
                "hint": "用 get_registered_cameras 看已注册列表，或 search_devices 找新设备"}

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

    return {"ok": False, "error_code": "NEEDS_INPUT",
            "needs_input": [{
                "key": "camera",
                "question": f"局域网发现 {len(sr.devices)} 台设备，注册哪台？",
                "options": [{
                    "label": f"{d.model or d.sn_code or '?'} ({d.ip})",
                    "value": _dev_to_name(d),
                } for d in sr.devices],
            }]}
