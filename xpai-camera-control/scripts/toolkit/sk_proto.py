import base64
import hashlib
import hmac
import http.client
import json
import random
import socket
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

SK_TCP_PORT = 9010
SK_MULTICAST_PORT = 9008
SK_TOOL_RECV_PORT = 9028
SK_MAX_RETRIES = 3
SK_RETRY_INTERVAL = 0.5

SK_TCP_PATH = "/xiaopaitech/device_service"
SK_MULTICAST_ADDR = "239.230.236.230"
SK_BROADCAST_ADDR = "255.255.255.255"

SK_CLOUD_REQ_URL = ("https://device.skyworthdigitaliot.com/"
                    "skyworthAiModel/agent/skill/v1/deviceAuthReq")
SK_CLOUD_CHK_URL = ("https://device.skyworthdigitaliot.com/"
                    "skyworthAiModel/agent/skill/v1/checkAuth")

SK_AUTH_KEY_HEX = "7258ead750d738e654255190814c4d68"
SK_AUTH_KEY = bytes.fromhex(SK_AUTH_KEY_HEX)

SK_RTSP_UA = "skyworth"
SK_HTTP_UA = "Xiaopaitech NVR/1.0"

SK_OK = "C0000"
SK_OK2 = "C000"

SK_CMD_GET_MAGIC = "SK_SETTING_GET_MAGIC"
SK_CMD_FL_OPTION = "SK_SETTING_GET_FILLLIGHT_OPTION"
SK_CMD_FL_GET = "SK_SETTING_GET_FILLLIGHT"
SK_CMD_FL_SET = "SK_SETTING_SET_FILLLIGHT"
SK_CMD_IMG_OPTION = "SK_SETTING_GET_IMAGE_OPTION"
SK_CMD_IMG_GET = "SK_SETTING_GET_IMAGE"
SK_CMD_IMG_SET = "SK_SETTING_SET_IMAGE"
SK_CMD_PTZ_GET = "SK_SETTING_GET_PTZ"
SK_CMD_PTZ_SET = "SK_SETTING_SET_PTZ"
SK_CMD_DISC = "SK_DISCOVERY_SEARCH"
SK_CMD_DISC_R = "SK_DISCOVERY_SEARCH_R"

_DETECT_CMDS = {
    1: ("SK_SETTING_GET_HUMANDETECT_OPTION", "SK_SETTING_GET_HUMANDETECT",
        "SK_SETTING_SET_HUMANDETECT"),
    2: ("SK_SETTING_GET_OBJECTDETECT_OPTION", "SK_SETTING_GET_OBJECTDETECT",
        "SK_SETTING_SET_OBJECTDETECT"),
    3: ("SK_SETTING_GET_VGRECTDETECT_OPTION", "SK_SETTING_GET_VGRECTDETECT",
        "SK_SETTING_SET_VGRECTDETECT"),
    4: ("SK_SETTING_GET_MOTIONDETECT_OPTION", "SK_SETTING_GET_MOTIONDETECT",
        "SK_SETTING_SET_MOTIONDETECT"),
    5: ("SK_SETTING_GET_VGLINEDETECT_OPTION", "SK_SETTING_GET_VGLINEDETECT",
        "SK_SETTING_SET_VGLINEDETECT"),
}

SK_DEV_CMD_BODY = ('{"service_type":"device","cmd_name":"SK_DEVICE_GET_INFO",'
                   '"ver":"1.0"}')
SK_MAGIC_CMD_BODY = ('{"service_type":"setting",'
                     '"msg_id":"0000000000000000000000",'
                     '"cmd_name":"SK_SETTING_GET_MAGIC","ver":"1.0",'
                     '"channel":2,"sequence":0,"refresh":"0"}')

SK_ALARM_BUF_MAX = 4 * 1024 * 1024
SK_ALARM_CHANNEL_ID = 0x65

_ALM_TOPIC_MAP = {
    "MD": "motion",
    "MP": "motion",
    "HD": "human",
    "VGR": "region_intrusion",
    "VGL": "line_crossing",
    "VS": "tamper",
    "VD": "vehicle",
    "HTD": "high_temp",
    "LTD": "low_temp",
}

SK_PROTO_VERSION = "1.0.0"

_tls = threading.local()

def _set_error(msg: str) -> None:
    _tls.err = msg

def version() -> str:
    return SK_PROTO_VERSION

def last_error() -> str:
    return getattr(_tls, "err", "")

def code_ok(code) -> bool:
    return bool(code) and str(code) == SK_OK

def code_accept(code) -> bool:
    return bool(code) and str(code) in (SK_OK, SK_OK2)

def _json_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)

def _env_err(http_status: int, message: str) -> Dict[str, Any]:
    return {"ok": 0, "http_status": http_status, "error": message}

def _env_body(http_status: int, raw: bytes) -> Dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").lstrip(" \t\r\n")
    if not text:
        return _env_err(http_status, "响应 body 为空")
    if text[0] not in "{[":
        return _env_err(http_status, "响应非 JSON: %s" % text[:200])
    try:
        body = json.loads(text)
    except ValueError as e:
        return _env_err(http_status,
                        "设备响应体非合法 JSON（HTTP %d）: %s" % (http_status, e))
    return {"ok": 1, "http_status": http_status, "body": body}

def _payload_json(payload) -> str:
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

def _build_msg_id() -> str:
    now = time.time()
    ts = time.strftime("%Y%m%d%H%M%S", time.localtime(now))
    usec = int((now - int(now)) * 1_000_000)
    return "%s%06d" % (ts, usec)

def _build_msg_id_alt() -> str:
    ts = time.strftime("%y%m%d%H%M%S", time.localtime())
    return "%s%06x" % (ts, random.getrandbits(24))

def _build_setting_body(cmd_name: str, payload: Optional[dict] = None,
                        with_refresh: bool = False) -> str:
    body: Dict[str, Any] = {
        "service_type": "setting",
        "msg_id": _build_msg_id_alt(),
        "cmd_name": cmd_name,
        "ver": "1.0",
        "channel": 2,
        "sequence": 0,
    }
    if with_refresh:
        body["refresh"] = "0"
    if payload:
        body.update(payload)
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

def _token_from_stamp(stamp: str, sn: str) -> str:
    d = hashlib.sha1()
    d.update(stamp.encode("utf-8"))
    d.update(sn.encode("utf-8"))
    d.update(SK_AUTH_KEY)
    return base64.b64encode(d.digest()).decode("ascii")

def _basic_b64(username: str, password: str) -> str:
    raw = "%s:%s" % (username or "", password or "")
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")

def _requests_post(url: str, body: str, headers: Dict[str, str],
                   timeout: float, host: str, port: int
                   ) -> Tuple[Optional[requests.Response], Optional[Dict[str, Any]]]:
    try:
        resp = requests.post(url, data=body.encode("utf-8"),
                             headers=headers, timeout=timeout)
        return resp, None
    except requests.exceptions.Timeout as e:
        _set_error("超时: %s:%d (%s)" % (host, port, e))
    except requests.exceptions.RequestException as e:
        _set_error("连接失败: %s:%d (%s)" % (host, port, e))
    return None, _env_err(0, last_error())

def _get_magic_stamp(host: str, port: int, username: str, password: str,
                     timeout: float) -> Optional[str]:
    headers = {
        "Authorization": "Basic " + _basic_b64(username, password),
        "Content-Type": "application/json; charset=utf-8",
    }
    url = "http://%s:%d%s" % (host, port, SK_TCP_PATH)
    for attempt in range(1, SK_MAX_RETRIES + 1):
        body = _build_setting_body(SK_CMD_GET_MAGIC, with_refresh=True)
        resp, err = _requests_post(url, body, headers, timeout, host, port)
        if resp is None:
            return None
        if resp.status_code == 404 and attempt < SK_MAX_RETRIES:
            time.sleep(SK_RETRY_INTERVAL)
            continue
        if resp.status_code != 200:
            _set_error("GET_MAGIC HTTP %d" % resp.status_code)
            return None
        try:
            obj = json.loads(resp.content.decode("utf-8", errors="replace"))
        except ValueError:
            obj = None
        stamp = obj.get("stamp") if isinstance(obj, dict) else None
        if not isinstance(stamp, str) or not stamp:
            _set_error("GET_MAGIC 未返回 stamp")
            return None
        return stamp
    _set_error("GET_MAGIC 重试 %d 次后仍失败" % SK_MAX_RETRIES)
    return None

def _http_query(host: str, port: int, cmd_name: str, payload: dict,
                sn: str, username: str, password: str,
                timeout: float) -> Dict[str, Any]:
    if (host is None or cmd_name is None or not sn or
            username is None or password is None):
        return _env_err(0, "参数不完整（host/cmd_name/sn/username/password）")
    if port <= 0:
        port = SK_TCP_PORT
    if timeout <= 0:
        timeout = 3.0

    url = "http://%s:%d%s" % (host, port, SK_TCP_PATH)
    for attempt in range(1, SK_MAX_RETRIES + 1):
        stamp = _get_magic_stamp(host, port, username, password, timeout)
        if stamp is None:
            return _env_err(0, "SK 鉴权失败: %s" % last_error())
        token = _token_from_stamp(stamp, sn)
        headers = {
            "Authorization": "Basic " + token,
            "Content-Type": "application/json; charset=utf-8",
        }
        body = _build_setting_body(cmd_name, payload)
        resp, err = _requests_post(url, body, headers, timeout, host, port)
        if resp is None:
            return err
        if resp.status_code == 404 and attempt < SK_MAX_RETRIES:
            time.sleep(SK_RETRY_INTERVAL)
            continue
        if resp.status_code != 200:
            return _env_err(resp.status_code, "SK HTTP %d" % resp.status_code)
        return _env_body(resp.status_code, resp.content)
    return _env_err(0, "SK 命令重试 %d 次后仍失败" % SK_MAX_RETRIES)

def _tcp_command(ip: str, port: int, command_json: str,
                 username: str = "", password: str = "",
                 auth_token: str = "", timeout: float = 10.0) -> Dict[str, Any]:
    if ip is None or command_json is None:
        return _env_err(0, "参数不完整（ip/command_json）")
    if port <= 0:
        port = SK_TCP_PORT
    if timeout <= 0:
        timeout = 10.0

    basic = auth_token if auth_token else _basic_b64(
        username if username is not None else "admin",
        password if password is not None else "")
    headers = {
        "User-Agent": SK_HTTP_UA,
        "Connection": "close",
        "Authorization": "Basic " + basic,
        "Content-Type": "application/json; charset=utf-8",
    }
    try:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.request("POST", SK_TCP_PATH,
                     body=command_json.encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        status = resp.status
        data = resp.read()
        conn.close()
    except (OSError, http.client.HTTPException) as e:
        _set_error("连接失败: %s:%d (%s)" % (ip, port, e))
        return _env_err(0, last_error())
    return _env_body(status, data)

def _setting_cmd(ip: str, cmd_name: str, payload: Optional[dict],
                 sn: str, username: str, password: str,
                 timeout: float) -> Dict[str, Any]:
    if ip is None or not sn or username is None or password is None:
        return _env_err(0, "参数不完整（ip/sn/username/password）")
    return _http_query(ip, SK_TCP_PORT, cmd_name, payload or {},
                       sn, username, password, timeout)

def filllight_get_option(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_FL_OPTION, {}, sn, username, password,
                        float(timeout))

def filllight_get(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_FL_GET, {}, sn, username, password,
                        float(timeout))

def filllight_set(ip, sn, username, password, payload=None,
                  timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_FL_SET, payload, sn, username, password,
                        float(timeout))

def image_get_option(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_IMG_OPTION, {}, sn, username, password,
                        float(timeout))

def image_get(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_IMG_GET, {}, sn, username, password,
                        float(timeout))

def image_set(ip, sn, username, password, payload=None,
              timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_IMG_SET, payload, sn, username, password,
                        float(timeout))

def ptz_get(ip, sn, username, password, timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_PTZ_GET, {}, sn, username, password,
                        float(timeout))

def ptz_set(ip, sn, username, password, payload=None,
            timeout=5.0) -> Dict[str, Any]:
    return _setting_cmd(ip, SK_CMD_PTZ_SET, payload, sn, username, password,
                        float(timeout))

DETECT_HUMAN = 1
DETECT_VEHICLE = 2
DETECT_REGION = 3
DETECT_MOTION = 4
DETECT_LINE = 5

def _detect_cmd(type_code: int, verb: int) -> Optional[str]:
    cmds = _DETECT_CMDS.get(type_code)
    return cmds[verb] if cmds else None

def _detect_bad_type() -> Dict[str, Any]:
    return _env_err(0, "type_code 非法（1=人形 2=车辆 3=区域 4=移动 5=越界）")

def detect_get_option(type_code, ip, sn, username, password,
                      timeout=5.0) -> Dict[str, Any]:
    cmd = _detect_cmd(int(type_code), 0)
    if not cmd:
        return _detect_bad_type()
    payload = {"object": "vehicle"} if int(type_code) == DETECT_VEHICLE else {}
    return _setting_cmd(ip, cmd, payload, sn, username, password, float(timeout))

def detect_get(type_code, ip, sn, username, password,
               timeout=5.0) -> Dict[str, Any]:
    cmd = _detect_cmd(int(type_code), 1)
    if not cmd:
        return _detect_bad_type()
    payload = {"object": "vehicle"} if int(type_code) == DETECT_VEHICLE else {}
    return _setting_cmd(ip, cmd, payload, sn, username, password, float(timeout))

def detect_set(type_code, ip, sn, username, password, payload=None,
               timeout=5.0) -> Dict[str, Any]:
    t = int(type_code)
    cmd = _detect_cmd(t, 2)
    if not cmd:
        return _detect_bad_type()
    if t == DETECT_VEHICLE:
        merged = {"object": "vehicle"}
        if payload:
            merged.update(payload)
        payload = merged
    return _setting_cmd(ip, cmd, payload, sn, username, password, float(timeout))

def device_get_info(ip, username, password, timeout=5.0) -> Dict[str, Any]:
    if ip is None:
        return _env_err(0, "参数为空（ip）")
    if float(timeout) <= 0:
        timeout = 5.0
    return _tcp_command(ip, SK_TCP_PORT, SK_DEV_CMD_BODY,
                        username if username is not None else "admin",
                        password if password is not None else "",
                        timeout=float(timeout))

def verify_sk_http(ip, timeout=5.0) -> Dict[str, Any]:
    if ip is None:
        return _env_err(0, "参数为空（ip）")
    if float(timeout) <= 0:
        timeout = 5.0
    env = _tcp_command(ip, SK_TCP_PORT, SK_MAGIC_CMD_BODY,
                       "admin", "", timeout=float(timeout))
    ok = 1 if env.get("ok") == 1 else 0
    hs = env.get("http_status") or 0
    code = ""
    if ok:
        body = env.get("body")
        if isinstance(body, dict):
            code = body.get("code")
            if not isinstance(code, str):
                code = ""
    available = bool(ok == 1 and
                     (hs == 200 or code == "" or code in (SK_OK, SK_OK2)))
    return {"ok": 1, "http_status": hs, "available": available, "code": code}

def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        s.close()

def _local_mac() -> str:
    try:
        n = uuid.getnode()
        return ":".join("%02X" % ((n >> (8 * i)) & 0xFF)
                        for i in reversed(range(6)))
    except Exception:
        return ""

def _build_search_cmd(target_sn: str = "") -> bytes:
    cmd = {
        "service_type": "discovery",
        "msg_id": _build_msg_id(),
        "cmd_name": SK_CMD_DISC,
        "ver": "1.0",
        "channel": 2,
        "sequence": 0,
        "sn": target_sn or "",
        "type": "SEARCH",
        "model": "",
        "ip": _local_ip(),
        "port": str(SK_TOOL_RECV_PORT),
        "mac": _local_mac(),
    }
    return json.dumps(cmd, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")

def _create_recv_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", SK_TOOL_RECV_PORT))
    return sock

def _search_resp_ok(text: str) -> Optional[dict]:
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("cmd_name") != SK_CMD_DISC_R:
        return None
    code = obj.get("code")
    if not isinstance(code, str):
        code = ""
    if code and code not in (SK_OK, SK_OK2):
        return None
    return obj

def discovery_search(timeout=3.0, target_sn="") -> List[Dict[str, Any]]:
    if timeout <= 0:
        timeout = 3.0
    try:
        sock = _create_recv_socket()
    except OSError as e:
        _set_error("绑定 UDP %d 失败 (%s)" % (SK_TOOL_RECV_PORT, e))
        return []
    try:
        cmd = _build_search_cmd(target_sn)
        try:
            sock.sendto(cmd, (SK_BROADCAST_ADDR, SK_MULTICAST_PORT))
        except OSError:
            _set_error("广播发送失败")
        try:
            sock.sendto(cmd, (SK_MULTICAST_ADDR, SK_MULTICAST_PORT))
        except OSError:
            _set_error("组播发送失败")
    except OSError:
        sock.close()
        return []

    deadline = time.time() + float(timeout)
    seen = set()
    results: List[Dict[str, Any]] = []
    while True:
        remain = deadline - time.time()
        if remain <= 0:
            break
        sock.settimeout(remain)
        try:
            data, src = sock.recvfrom(65535)
        except (socket.timeout, OSError):
            break
        srcip = src[0]
        if srcip in seen:
            continue
        obj = _search_resp_ok(data.decode("utf-8", errors="replace"))
        if obj is None:
            continue
        seen.add(srcip)
        obj["_src"] = srcip
        results.append(obj)
    sock.close()
    return results

def probe_device_sn(ip, timeout=3.0) -> str:
    if not ip:
        _set_error("参数为空（ip）")
        return ""
    if timeout <= 0:
        timeout = 3.0
    try:
        sock = _create_recv_socket()
    except OSError:
        return ""
    try:
        cmd = _build_search_cmd()
        try:
            sock.sendto(cmd, (ip, SK_MULTICAST_PORT))
        except OSError:
            _set_error("单播发送失败")
        try:
            sock.sendto(cmd, (SK_MULTICAST_ADDR, SK_MULTICAST_PORT))
        except OSError:
            _set_error("组播发送失败")
    except OSError:
        sock.close()
        return ""

    deadline = time.time() + float(timeout)
    sn = ""
    while True:
        remain = deadline - time.time()
        if remain <= 0:
            break
        sock.settimeout(remain)
        try:
            data, src = sock.recvfrom(65535)
        except (socket.timeout, OSError):
            break
        obj = _search_resp_ok(data.decode("utf-8", errors="replace"))
        if obj is None:
            continue
        resp_ip = obj.get("ip")
        if not isinstance(resp_ip, str):
            resp_ip = ""
        if (resp_ip and resp_ip == ip) or src[0] == ip:
            sn = obj.get("sn")
            if not isinstance(sn, str):
                sn = ""
            break
    sock.close()
    return sn

def _uuid4() -> str:
    return str(uuid.uuid4())

def _make_sign(request_id: str, timestamp: str, device_key: str,
               agent_skill_id: str) -> Optional[str]:
    if (request_id is None or timestamp is None or device_key is None or
            agent_skill_id is None):
        _set_error("签名参数为空")
        return None
    secret = hashlib.md5(agent_skill_id.encode("utf-8")).hexdigest()
    plain = ("%s%s%s%s" % (request_id, timestamp, device_key,
                           agent_skill_id)).encode("utf-8")
    mac = hmac.new(secret.encode("ascii"), plain, hashlib.sha256).hexdigest()
    return mac[:16]

def _cloud_exchange(url: str, method: str, sn: str, claw_id: str,
                    body: Optional[str], timeout: float) -> Dict[str, Any]:
    if not url or not sn or not claw_id:
        return _env_err(0, "参数不完整（url/sn/claw_id）")
    if timeout <= 0:
        timeout = 10.0
    request_id = _uuid4()
    timestamp = str(int(time.time() * 1000))
    sign = _make_sign(request_id, timestamp, sn, claw_id)
    if sign is None:
        return _env_err(0, "签名计算失败: %s" % last_error())
    headers = {
        "requestId": request_id,
        "timestamp": timestamp,
        "scSign": sign,
    }
    try:
        if method == "GET":
            headers.setdefault("Accept", "*/*")
            resp = requests.get(url, params={"deviceKey": sn,
                                             "agentSkillId": claw_id},
                                headers=headers, timeout=timeout)
        else:
            headers["Content-Type"] = "application/json;charset=utf-8"
            resp = requests.post(url, data=(body or "{}").encode("utf-8"),
                                 headers=headers, timeout=timeout)
    except requests.exceptions.Timeout as e:
        _set_error("云端超时 (%s)" % e)
        return _env_err(0, last_error())
    except requests.exceptions.RequestException as e:
        _set_error("云端连接失败 (%s)" % e)
        return _env_err(0, last_error())
    if resp.status_code != 200:
        return _env_err(resp.status_code, "云端响应 HTTP %d" % resp.status_code)
    return _env_body(resp.status_code, resp.content)

def cloud_auth_request(sn, claw_id, timeout=10.0) -> Dict[str, Any]:
    if not sn or not claw_id:
        return _env_err(0, "参数不完整（sn/claw_id）")
    body = json.dumps({"deviceKey": sn, "agentSkillId": claw_id},
                      ensure_ascii=False, separators=(",", ":"))
    return _cloud_exchange(SK_CLOUD_REQ_URL, "POST", sn, claw_id,
                           body, float(timeout))

def cloud_auth_check(sn, claw_id, timeout=10.0) -> Dict[str, Any]:
    if not sn or not claw_id:
        return _env_err(0, "参数不完整（sn/claw_id）")
    return _cloud_exchange(SK_CLOUD_CHK_URL, "GET", sn, claw_id,
                           None, float(timeout))

def rtsp_ua() -> str:
    return SK_RTSP_UA

def _alarm_topic(alm: str) -> str:
    v = (alm or "").lstrip()
    up = v[:23].upper().rstrip()
    mapped = _ALM_TOPIC_MAP.get(up)
    if mapped:
        return mapped
    if not up:
        return "unknown"
    return v[:len(up)].lower()

def _rtp_payload_offset(d: bytes) -> Optional[int]:
    n = len(d)
    if n < 12:
        return None
    cc = d[0] & 0x0F
    ext = (d[0] >> 4) & 0x01
    off = 12 + cc * 4
    if off > n:
        return None
    if ext and off + 4 <= n:
        ext_len = (d[off + 2] << 8) | d[off + 3]
        off += 4 + ext_len * 4
    if off >= n:
        return None
    return off

class AlarmParser:

    def __init__(self):
        self._buf = bytearray()

    @staticmethod
    def _append_event(j: str, events: List[Dict[str, Any]]) -> None:
        try:
            obj = json.loads(j)
        except ValueError:
            return
        if not isinstance(obj, dict):
            return
        serv = obj.get("serv")
        if not isinstance(serv, str):
            serv = None
        if serv is None:
            serv = obj.get("ser")
        if not isinstance(serv, str) or serv != "alarm":
            return
        alm = obj.get("alm")
        if not isinstance(alm, str):
            alm = ""
        detail: Dict[str, Any] = {}
        for key in ("fn", "fmt", "num", "data", "dir"):
            if key in obj:
                detail[key] = obj[key]
        date_val = obj.get("date")
        if date_val is None:
            date_val = obj.get("dat")

        if date_val not in (None, "", 0, False, [], {}):
            detail["date"] = date_val
        events.append({"topic": _alarm_topic(alm), "detail": detail})

    @staticmethod
    def _process_payload(payload: bytes, events: List[Dict[str, Any]]) -> None:
        text = payload.decode("utf-8", errors="replace")
        j = text.lstrip(" \t\r\n")
        if j.startswith("{"):
            AlarmParser._append_event(j, events)
        else:
            off = _rtp_payload_offset(payload)
            if off is not None:
                j = text[off:].lstrip(" \t\r\n")
                if j.startswith("{"):
                    AlarmParser._append_event(j, events)

    def feed(self, data) -> List[Dict[str, Any]]:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("feed 需要 bytes/bytearray")
        buf = self._buf
        if data:
            data = bytes(data)

            if len(buf) + len(data) + 1 > SK_ALARM_BUF_MAX:
                del buf[:]
                if len(data) + 1 > SK_ALARM_BUF_MAX:
                    return []
            buf += data

        events: List[Dict[str, Any]] = []
        pos = 0
        n = len(buf)
        while n >= pos + 4:
            c0 = buf[pos]

            if (n - pos >= 5 and buf[pos:pos + 5] == b"RTSP/") or (
                    c0 != 0x24 and c0 in (0x20, 0x09, 0x0D, 0x0A)):
                nl = buf.find(b"\n", pos)
                if nl < 0:
                    break
                pos = nl + 1
                continue
            if c0 != 0x24:

                hit = buf.find(b"$", pos + 1)
                if hit < 0:
                    pos = n
                    break
                pos = hit
                continue
            ch = buf[pos + 1]
            flen = (buf[pos + 2] << 8) | buf[pos + 3]
            if flen == 0 or flen > 65536:
                pos += 1
                continue
            if n - pos < 4 + flen:
                break
            if ch == SK_ALARM_CHANNEL_ID:
                self._process_payload(bytes(buf[pos + 4:pos + 4 + flen]),
                                      events)
            pos += 4 + flen

        if pos > 0:
            del buf[:pos]
        return events

    def close(self):
        del self._buf[:]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
