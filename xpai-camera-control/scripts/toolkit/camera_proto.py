import ctypes
import ipaddress
import json
import math
import operator
import platform
import re
import socket
import sys
import sysconfig
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


DETECT_HUMAN = 1
DETECT_VEHICLE = 2
DETECT_REGION = 3
DETECT_MOTION = 4
DETECT_LINE = 5

JCP_RTSP_PORT = 554
JCP_RTSP_PATH_MAIN = "/stream1"
JCP_RTSP_PATH_SUB = "/stream2"

_ABI_VERSION = b"2.1.0"
_lib = None
_lib_lock = threading.Lock()


class JcpError(RuntimeError):
    pass


class _IPv4Interface(ctypes.Structure):
    _fields_ = [("ip", ctypes.c_char_p), ("broadcast", ctypes.c_char_p)]


def _bind(lib):
    query = [ctypes.c_char_p] * 4 + [ctypes.c_double]
    setting = [ctypes.c_char_p] * 5 + [ctypes.c_double]
    signatures = {
        "sk_version": ([], ctypes.c_char_p),
        "sk_last_error": ([], ctypes.c_char_p),
        "sk_free_str": ([ctypes.c_void_p], None),
        "sk_code_ok": ([ctypes.c_char_p], ctypes.c_int),
        "sk_code_accept": ([ctypes.c_char_p], ctypes.c_int),
        "sk_device_get_info": ([ctypes.c_char_p] * 3 + [ctypes.c_double], ctypes.c_void_p),
        "sk_verify_sk_http": ([ctypes.c_char_p, ctypes.c_double], ctypes.c_void_p),
        "sk_discovery_search": ([ctypes.c_double] + [ctypes.c_char_p] * 3, ctypes.c_void_p),
        "sk_probe_device_sn": ([ctypes.c_char_p, ctypes.c_double,
                                ctypes.c_char_p, ctypes.c_char_p], ctypes.c_void_p),
        "sk_cloud_auth_request": ([ctypes.c_char_p] * 2 + [ctypes.c_double], ctypes.c_void_p),
        "sk_cloud_auth_check": ([ctypes.c_char_p] * 2 + [ctypes.c_double], ctypes.c_void_p),
        "sk_alarm_parser_new": ([], ctypes.c_void_p),
        "sk_alarm_parser_free": ([ctypes.c_void_p], None),
        "sk_alarm_parser_feed": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int], ctypes.c_void_p),
        "sk_alarm_rtsp_ua": ([], ctypes.c_char_p),
        "jcp_discovery_search": ([ctypes.POINTER(_IPv4Interface), ctypes.c_size_t,
                                  ctypes.c_double, ctypes.c_ushort], ctypes.c_void_p),
    }
    for name in ("sk_filllight_get_option", "sk_filllight_get",
                 "sk_image_get_option", "sk_image_get", "sk_ptz_get",
                 "sk_video_get_option", "sk_video_get"):
        signatures[name] = (query, ctypes.c_void_p)
    for name in ("sk_filllight_set", "sk_image_set", "sk_ptz_set", "sk_video_set"):
        signatures[name] = (setting, ctypes.c_void_p)
    for name in ("sk_detect_get_option", "sk_detect_get"):
        signatures[name] = ([ctypes.c_int] + query, ctypes.c_void_p)
    signatures["sk_detect_set"] = ([ctypes.c_int] + setting, ctypes.c_void_p)
    for name, (argtypes, restype) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes = argtypes
        fn.restype = restype


def _library_name():
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError("摄像头协议库需要 64 位 Python 解释器。")
    machine = platform.machine().lower()
    if sys.platform == "win32" and sysconfig.get_platform() == "win-amd64":
        return "camera_proto.dll"
    if sys.platform == "linux" and machine in ("amd64", "x86_64"):
        if platform.libc_ver()[0] != "glibc":
            raise RuntimeError("Linux 协议库仅支持 glibc x64；不支持 musl/Alpine 或无法识别的 libc。")
        return "camera_proto.so"
    if sys.platform == "darwin" and machine in ("x86_64", "arm64"):
        return "camera_proto.dylib"
    raise RuntimeError(
        f"不支持当前协议库平台：{sys.platform}/{machine}；"
        "仅支持 Windows x64、Linux glibc x64、macOS Intel/ARM64 的 64 位解释器。")


def _ensure():
    global _lib
    if _lib is not None:
        return _lib
    with _lib_lock:
        if _lib is not None:
            return _lib
        path = Path(__file__).resolve().with_name(_library_name())
        if not path.is_file():
            raise RuntimeError(
                f"未找到摄像头协议库 {path}；请先用启动 MCP 的 Python 运行 scripts/prepare_runtime.py")
        try:
            lib = ctypes.CDLL(str(path))
            _bind(lib)
        except (OSError, AttributeError) as exc:
            raise RuntimeError(
                f"摄像头协议库加载失败（{path.name}），请检查系统/解释器架构及原生依赖，"
                f"并运行 scripts/prepare_runtime.py 校验依赖：{exc}") from exc
        if lib.sk_version() != _ABI_VERSION:
            raise RuntimeError("摄像头协议库 ABI 版本不匹配，请运行 scripts/prepare_runtime.py 校验固定版本依赖")
        _lib = lib
        return lib


def _b(value) -> Optional[bytes]:
    if value is None:
        return None
    result = value if isinstance(value, bytes) else str(value).encode("utf-8")
    if b"\x00" in result:
        raise ValueError("协议字符串参数不能包含 NUL")
    return result


def _take_str(lib, ptr) -> Optional[str]:
    if not ptr:
        return None
    try:
        return ctypes.string_at(ptr).decode("utf-8", errors="replace")
    finally:
        lib.sk_free_str(ptr)


def _call(name, *args) -> Dict[str, Any]:
    lib = _ensure()
    ptr = getattr(lib, name)(*args)
    if not ptr:
        return {"ok": 0, "http_status": 0, "error": last_error() or "协议库无返回"}
    text = _take_str(lib, ptr)
    try:
        env = json.loads(text) if text else None
        if not isinstance(env, dict):
            raise ValueError("非 JSON 对象")
    except (TypeError, ValueError) as exc:
        match = re.match(r'\s*\{\s*"ok"\s*:\s*\d+\s*,\s*"http_status"\s*:\s*(\d+)',
                         text or "")
        status = int(match.group(1)) if match else 0
        return {"ok": 0, "http_status": status,
                "error": f"设备响应体非合法 JSON（HTTP {status}）: {exc}"}
    body = env.get("body")
    if isinstance(body, dict):
        body.pop("cmd_name", None)
    return env


def _payload_json(payload) -> bytes:
    return json.dumps(payload or {}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def version() -> str:
    value = _ensure().sk_version()
    return value.decode("utf-8") if value else ""


def last_error() -> str:
    value = _ensure().sk_last_error()
    return value.decode("utf-8", errors="replace") if value else ""


def code_ok(code) -> bool:
    return bool(_ensure().sk_code_ok(_b(code)))


def code_accept(code) -> bool:
    return bool(_ensure().sk_code_accept(_b(code)))


def filllight_get_option(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_filllight_get_option", _b(ip), _b(sn), _b(username),
                 _b(password), float(timeout))


def filllight_get(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_filllight_get", _b(ip), _b(sn), _b(username),
                 _b(password), float(timeout))


def filllight_set(ip, sn, username, password, payload=None, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_filllight_set", _b(ip), _b(sn), _b(username),
                 _b(password), _payload_json(payload), float(timeout))


def image_get_option(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_image_get_option", _b(ip), _b(sn), _b(username),
                 _b(password), float(timeout))


def image_get(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_image_get", _b(ip), _b(sn), _b(username),
                 _b(password), float(timeout))


def image_set(ip, sn, username, password, payload=None, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_image_set", _b(ip), _b(sn), _b(username),
                 _b(password), _payload_json(payload), float(timeout))


def video_get_option(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_video_get_option", _b(ip), _b(sn), _b(username),
                 _b(password), float(timeout))


def video_get(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_video_get", _b(ip), _b(sn), _b(username),
                 _b(password), float(timeout))


def video_set(ip, sn, username, password, payload=None, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_video_set", _b(ip), _b(sn), _b(username),
                 _b(password), _payload_json(payload), float(timeout))


def ptz_get(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_ptz_get", _b(ip), _b(sn), _b(username),
                 _b(password), float(timeout))


def ptz_set(ip, sn, username, password, payload=None, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_ptz_set", _b(ip), _b(sn), _b(username),
                 _b(password), _payload_json(payload), float(timeout))


def detect_get_option(type_code, ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_detect_get_option", int(type_code), _b(ip), _b(sn),
                 _b(username), _b(password), float(timeout))


def detect_get(type_code, ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_detect_get", int(type_code), _b(ip), _b(sn),
                 _b(username), _b(password), float(timeout))


def detect_set(type_code, ip, sn, username, password, payload=None,
               timeout=5.0) -> Dict[str, Any]:
    return _call("sk_detect_set", int(type_code), _b(ip), _b(sn),
                 _b(username), _b(password), _payload_json(payload), float(timeout))


def device_get_info(ip, username, password, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_device_get_info", _b(ip), _b(username), _b(password), float(timeout))


def verify_sk_http(ip, timeout=5.0) -> Dict[str, Any]:
    return _call("sk_verify_sk_http", _b(ip), float(timeout))


def _local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "0.0.0.0"


def _local_mac() -> str:
    try:
        value = uuid.getnode()
        return ":".join("%02X" % ((value >> (8 * i)) & 0xFF) for i in reversed(range(6)))
    except Exception:
        return ""


def discovery_search(timeout=3.0, target_sn="") -> List[Dict[str, Any]]:
    lib = _ensure()
    ptr = lib.sk_discovery_search(float(timeout), _b(target_sn),
                                  _b(_local_ip()), _b(_local_mac()))
    text = _take_str(lib, ptr)
    try:
        result = json.loads(text) if text else []
        return result if isinstance(result, list) else []
    except ValueError:
        return []


def probe_device_sn(ip, timeout=3.0) -> str:
    lib = _ensure()
    ptr = lib.sk_probe_device_sn(_b(ip), float(timeout), _b(_local_ip()), _b(_local_mac()))
    return _take_str(lib, ptr) or ""


def _local_interfaces() -> List[tuple]:
    import psutil

    interfaces = []
    seen = set()
    for addresses in psutil.net_if_addrs().values():
        for address in addresses:
            if address.family != socket.AF_INET:
                continue
            try:
                ip = ipaddress.IPv4Address(address.address)
            except ipaddress.AddressValueError:
                continue
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast or str(ip) in seen:
                continue
            seen.add(str(ip))
            broadcast = None
            if address.netmask:
                try:
                    network = ipaddress.IPv4Network(f"{ip}/{address.netmask}", strict=False)
                    broadcast = str(network.broadcast_address)
                except ValueError:
                    pass
            interfaces.append((str(ip), broadcast))
    return interfaces


def list_local_ipv4() -> List[str]:
    return [ip for ip, _ in _local_interfaces()]


def jcp_search(local_ip: str = "", timeout: float = 3.0,
               bind_port: int = 0) -> List[Dict[str, Any]]:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("timeout must be a positive finite number")
    try:
        timeout = float(timeout)
    except OverflowError as exc:
        raise ValueError("timeout must be a positive finite number") from exc
    if timeout <= 0 or not math.isfinite(timeout):
        raise ValueError("timeout must be a positive finite number")
    port = operator.index(bind_port)
    if not 0 <= port <= 65535:
        raise OverflowError("bind_port must be in 0-65535")
    deadline = time.monotonic() + timeout
    interfaces = _local_interfaces() if not local_ip else [(local_ip, None)]
    if not interfaces:
        raise JcpError("No local IPv4 interface available for JCP discovery")
    encoded = [(_b(ip), _b(broadcast)) for ip, broadcast in interfaces]
    addresses = (_IPv4Interface * len(encoded))(*(_IPv4Interface(*item) for item in encoded))
    lib = _ensure()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise JcpError("JCP discovery deadline expired")
    ptr = lib.jcp_discovery_search(addresses, len(addresses), remaining, port)
    if not ptr:
        raise JcpError(last_error() or "JCP discovery failed")
    text = _take_str(lib, ptr)
    try:
        env = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise JcpError("Invalid JCP discovery result") from exc
    if not isinstance(env, dict):
        raise JcpError("Invalid JCP discovery result")
    if not env.get("ok"):
        raise JcpError(env.get("error") or "JCP discovery failed")
    devices = env.get("devices")
    if not isinstance(devices, list):
        raise JcpError("Invalid JCP discovery result")
    return devices


def cloud_auth_request(sn, claw_id, timeout=10.0) -> Dict[str, Any]:
    return _call("sk_cloud_auth_request", _b(sn), _b(claw_id), float(timeout))


def cloud_auth_check(sn, claw_id, timeout=10.0) -> Dict[str, Any]:
    return _call("sk_cloud_auth_check", _b(sn), _b(claw_id), float(timeout))


def rtsp_ua() -> str:
    value = _ensure().sk_alarm_rtsp_ua()
    if not value:
        raise RuntimeError(last_error() or "报警会话参数不可用")
    return value.decode("utf-8")


class AlarmParser:
    def __init__(self):
        self._lib = _ensure()
        self._handle = self._lib.sk_alarm_parser_new()
        if not self._handle:
            raise RuntimeError("报警解析器创建失败（%s）" % last_error())

    def feed(self, data) -> List[Dict[str, Any]]:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("feed 需要 bytes/bytearray")
        if not self._handle:
            raise RuntimeError("报警解析器已释放")
        if len(data) > 0x7FFFFFFF:
            raise ValueError("报警数据过长")
        buffer = bytes(data)
        ptr = self._lib.sk_alarm_parser_feed(self._handle, buffer, len(buffer))
        text = _take_str(self._lib, ptr)
        try:
            result = json.loads(text) if text else []
            return result if isinstance(result, list) else []
        except ValueError:
            return []

    def close(self):
        if self._handle:
            self._lib.sk_alarm_parser_free(self._handle)
            self._handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
