"""
创维私有设备发现模块 (Skyworth Private Discovery Protocol)

协议说明:
  - IPC 在组播地址 239.230.236.230:9008 监听客户端 UDP 命令
  - 工具端发送 SK_DISCOVERY_SEARCH 搜索命令（广播/组播）
  - IPC 将 SK_DISCOVERY_SEARCH_R 响应返回给工具端的 9028 端口
  - NVR 接收响应的端口为 9018，工具端为 9028

端口映射:
  9008: IPC 接收 UDP 命令
  9010: IPC 接收 TCP 命令 (HTTP 协议头)
  9012: IPC 接收 OTA 数据
  9018: IPC 发送给 NVR 的 UDP 命令端口
  9028: IPC 发送给工具端的 UDP 命令端口
  8004: IPC 接收对讲数据

TCP 通道:
  POST /xiaopaitech/device_service HTTP/1.1
  Content-Type: application/json; charset=utf-8
  Authorization: Basic <base64(user:pass)>
"""

import json
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────

# 组播地址与端口
SK_MULTICAST_ADDR = "239.230.236.230"
SK_MULTICAST_PORT = 9008          # IPC 监听 UDP 命令的端口

# 工具端接收响应的端口（IPC 将响应发回此端口）
SK_TOOL_RECV_PORT = 9028

# TCP 通道端口
SK_TCP_PORT = 9010
SK_TCP_PATH = "/xiaopaitech/device_service"

# 广播地址（搜索命令通过全网广播发送）
SK_BROADCAST_ADDR = "255.255.255.255"

# 设备类型常量
SK_TYPE_IPC = "IPC"               # 摄像头
SK_TYPE_NVR = "NVR"               # 录像机
SK_TYPE_VMS = "VMS"               # PC端视频管理工具
SK_TYPE_SEARCH = "SEARCH"         # 搜索工具
SK_TYPE_ANDROID = "ANDROID"       # 安卓设备
SK_TYPE_IOS = "IOS"               # iOS设备

# 设备子类型
SK_SUBTYPE_BULLET = "1"           # 枪机
SK_SUBTYPE_DOME = "2"             # 球机
SK_SUBTYPE_HEMISPHERE = "3"       # 半球
SK_SUBTYPE_PAN_TILT = "5"         # 摇头机
SK_SUBTYPE_BULLET_DOME = "6"      # 枪球（双目：一个枪机+一个球机）

SUBTYPE_NAMES = {
    "1": "枪机",
    "2": "球机",
    "3": "半球",
    "5": "摇头机",
    "6": "枪球联动",
}


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class SkChannelInfo:
    """通道信息"""
    chl: str = "0"               # 通道ID
    name: str = ""               # 通道名称
    stream: str = ""             # RTSP 码流模式列表，逗号分隔


@dataclass
class SkDiscoveredDevice:
    """通过创维私有协议发现的设备信息"""
    ip: str = ""                               # 设备 IP 地址
    sn: str = ""                               # 设备 SN（无 SN 的设备为空）
    device_type: str = ""                      # IPC / NVR / VMS 等
    subtype: str = ""                          # 设备子类型：1枪机/2球机/3半球/5摇头机/6枪球
    manufacturer: str = ""                     # 设备制造商 (mfr)
    solution: str = ""                         # 设备方案 (soln)
    name: str = ""                             # 设备名称
    dtype: str = ""                            # 设备类型编号
    model: str = ""                            # 设备型号
    hw_version: str = ""                       # 硬件版本
    sw_version: str = ""                       # 软件版本
    did: str = ""                              # 设备 ID
    channels: int = 1                          # 通道数（单目:1, 双目:2）
    channel_list: List[SkChannelInfo] = field(default_factory=list)  # 通道详情
    rtsp_port: int = 554                       # RTSP 端口
    web_port: int = 80                         # Web 端口
    udp_port: int = 9008                       # UDP 命令端口
    net_type: str = "eth"                      # 网络类型: eth / wifi
    ip_mode: str = "0"                         # 0=dhcp, 1=ip自适应, 2=手动
    mask: str = ""                             # 子网掩码
    gateway: str = ""                          # 网关
    mac: str = ""                              # MAC 地址
    discovered_at: float = field(default_factory=time.time)  # 发现时间戳

    @property
    def subtype_name(self) -> str:
        """返回子类型的中文名称"""
        return SUBTYPE_NAMES.get(self.subtype, f"未知({self.subtype})")

    @property
    def rtsp_paths(self) -> List[str]:
        """从 channel_list 提取所有 RTSP 码流路径"""
        paths = []
        for ch in self.channel_list:
            if ch.stream:
                for s in ch.stream.split(","):
                    s = s.strip()
                    if s:
                        paths.append(s)
        return paths


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def _get_local_ip() -> Optional[str]:
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _get_local_mac() -> str:
    """获取本机 MAC 地址（尽力而为）"""
    try:
        import uuid as _uuid
        mac_int = _uuid.getnode()
        mac = ":".join(f"{(mac_int >> (8 * i)) & 0xFF:02X}" for i in reversed(range(6)))
        return mac
    except Exception:
        return ""


def _build_msg_id() -> str:
    """生成消息 ID（时间戳格式，兼容示例）"""
    now = time.time()
    ts = time.strftime("%Y%m%d%H%M%S", time.localtime(now))
    frac = int((now - int(now)) * 1_000_000)
    return f"{ts}{frac:06d}"[:21]


# ──────────────────────────────────────────────
#  构建搜索命令
# ──────────────────────────────────────────────

def build_search_command(
    local_ip: str = "",
    local_port: int = SK_TOOL_RECV_PORT,
    local_mac: str = "",
    target_sn: str = "",
) -> bytes:
    """
    构建 SK_DISCOVERY_SEARCH 搜索命令 JSON。

    Args:
        local_ip:   本机 IP（留空则自动检测）
        local_port: 本机接收响应的端口（默认 9028）
        local_mac:  本机 MAC（留空则自动检测）
        target_sn:  指定搜索某个 SN（留空则搜索所有设备）

    Returns:
        编码后的 JSON bytes
    """
    if not local_ip:
        local_ip = _get_local_ip() or "0.0.0.0"
    if not local_mac:
        local_mac = _get_local_mac()

    cmd = {
        "service_type": "discovery",
        "msg_id": _build_msg_id(),
        "cmd_name": "SK_DISCOVERY_SEARCH",
        "ver": "1.0",
        "channel": 2,
        "sequence": 0,
        "sn": target_sn,
        "type": SK_TYPE_SEARCH,
        "model": "",
        "ip": local_ip,
        "port": str(local_port),
        "mac": local_mac,
    }
    return json.dumps(cmd, ensure_ascii=False).encode("utf-8")


# ──────────────────────────────────────────────
#  解析响应
# ──────────────────────────────────────────────

def _parse_search_response(data: bytes) -> Optional[SkDiscoveredDevice]:
    """
    解析 SK_DISCOVERY_SEARCH_R 响应 JSON。

    Returns:
        SkDiscoveredDevice 或 None（解析失败时）
    """
    try:
        text = data.decode("utf-8", errors="ignore")
        obj = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if obj.get("cmd_name") != "SK_DISCOVERY_SEARCH_R":
        return None
    if obj.get("code") not in ("C0000", "C000", ""):
        # 非成功响应
        return None

    # 解析通道列表
    channel_list = []
    for ch in obj.get("mode", []):
        channel_list.append(SkChannelInfo(
            chl=str(ch.get("chl", "")),
            name=str(ch.get("name", "")),
            stream=str(ch.get("stream", "")),
        ))

    return SkDiscoveredDevice(
        ip=obj.get("ip", ""),
        sn=obj.get("sn", ""),
        device_type=obj.get("type", ""),
        subtype=obj.get("subtype", ""),
        manufacturer=obj.get("mfr", ""),
        solution=obj.get("soln", ""),
        name=obj.get("name", ""),
        dtype=obj.get("dtype", ""),
        model=obj.get("model", ""),
        hw_version=obj.get("hwver", ""),
        sw_version=obj.get("swver", ""),
        did=obj.get("did", ""),
        channels=int(obj.get("chls", "1")),
        channel_list=channel_list,
        rtsp_port=int(obj.get("rtsp", "554")),
        web_port=int(obj.get("web", "80")),
        udp_port=int(obj.get("udp", "9008")),
        net_type=obj.get("net", "eth"),
        ip_mode=obj.get("ipmode", "0"),
        mask=obj.get("mask", ""),
        gateway=obj.get("gw", ""),
        mac=obj.get("mac", ""),
        discovered_at=time.time(),
    )


# ──────────────────────────────────────────────
#  核心发现逻辑
# ──────────────────────────────────────────────

def _create_recv_socket(bind_port: int = SK_TOOL_RECV_PORT) -> socket.socket:
    """创建接收响应的 UDP socket，绑定到工具端端口"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Windows 下允许端口重用
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass  # Windows 不支持 SO_REUSEPORT，忽略
    sock.bind(("", bind_port))
    return sock


def _send_search(
    sock: socket.socket,
    search_cmd: bytes,
    use_broadcast: bool = True,
    use_multicast: bool = True,
):
    """发送搜索命令到广播和/或组播地址"""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    if use_broadcast:
        try:
            sock.sendto(search_cmd, (SK_BROADCAST_ADDR, SK_MULTICAST_PORT))
        except OSError as e:
            print(f"  [!] 广播发送失败: {e}")

    if use_multicast:
        try:
            sock.sendto(search_cmd, (SK_MULTICAST_ADDR, SK_MULTICAST_PORT))
        except OSError as e:
            print(f"  [!] 组播发送失败: {e}")


def discover_sky_devices(
    timeout: float = 5.0,
    target_sn: str = "",
    bind_port: int = SK_TOOL_RECV_PORT,
    use_broadcast: bool = True,
    use_multicast: bool = True,
) -> List[SkDiscoveredDevice]:
    """
    通过创维私有协议发现局域网内的设备。

    流程：
      1. 构建 SK_DISCOVERY_SEARCH 命令
      2. 通过广播 + 组播发送
      3. 在 bind_port (默认9028) 上监听 SK_DISCOVERY_SEARCH_R 响应
      4. 解析并返回设备列表

    Args:
        timeout:       等待响应的超时时间（秒，默认 5s）
        target_sn:     指定搜索某个 SN（留空搜索全部）
        bind_port:     本机接收响应的端口（默认 9028）
        use_broadcast: 是否使用广播发送（默认 True）
        use_multicast: 是否使用组播发送（默认 True）

    Returns:
        发现的设备列表
    """
    local_ip = _get_local_ip()
    print(f"\n{'=' * 55}")
    print(f"  创维私有协议设备发现")
    print(f"{'=' * 55}")
    if local_ip:
        print(f"  本机 IP: {local_ip}")
    print(f"  组播地址: {SK_MULTICAST_ADDR}:{SK_MULTICAST_PORT}")
    print(f"  接收端口: {bind_port}")
    print(f"  超时时间: {timeout}s")

    search_cmd = build_search_command(
        local_ip=local_ip or "",
        local_port=bind_port,
        target_sn=target_sn,
    )
    print(f"  搜索命令: {search_cmd.decode('utf-8')[:120]}...")

    discovered: Dict[str, SkDiscoveredDevice] = {}

    try:
        recv_sock = _create_recv_socket(bind_port)
        recv_sock.settimeout(1.0)  # 每次 recv 超时 1s，便于循环检查总超时

        # 发送搜索命令
        _send_search(recv_sock, search_cmd, use_broadcast, use_multicast)
        print(f"  搜索命令已发送，等待响应 ...")

    except OSError as e:
        print(f"  [!] 创建 socket 失败: {e}")
        return []

    deadline = time.time() + timeout

    try:
        while time.time() < deadline:
            try:
                data, addr = recv_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                continue

            src_ip = addr[0]
            # 跳过自己
            if local_ip and src_ip == local_ip:
                continue
            # 去重
            if src_ip in discovered:
                continue

            device = _parse_search_response(data)
            if device is None:
                continue

            # 使用响应中的 IP（比 UDP 源地址更准确）
            device_ip = device.ip if device.ip else src_ip
            device.ip = device_ip

            if device_ip in discovered:
                continue

            discovered[device_ip] = device
            print(f"  [✓] 发现设备: {device_ip}")
            print(f"      类型: {device.device_type} ({device.subtype_name})")
            print(f"      型号: {device.model}")
            if device.sn:
                print(f"      SN:   {device.sn}")
            print(f"      名称: {device.name}")
            print(f"      通道数: {device.channels}")
            for ch in device.channel_list:
                print(f"        通道{ch.chl} ({ch.name}): {ch.stream}")
            print(f"      RTSP:{device.rtsp_port}  Web:{device.web_port}  UDP:{device.udp_port}")
            print(f"      网络: {device.net_type}  MAC: {device.mac}")
            print()

    except Exception as e:
        print(f"  [!] 发现过程异常: {e}")
    finally:
        try:
            recv_sock.close()
        except Exception:
            pass

    # 打印汇总
    print(f"{'─' * 55}")
    if not discovered:
        print("  未发现创维设备")
        print(f"\n  排查建议:")
        print(f"    1. 确认设备已通电并连接到网络")
        print(f"    2. 确认电脑和设备在同一局域网")
        print(f"    3. 检查防火墙是否阻止了 UDP 端口 {bind_port}")
        print(f"    4. 尝试增加超时时间: timeout=10")
    else:
        print(f"  共发现 {len(discovered)} 个创维设备")

    print(f"{'=' * 55}\n")
    return list(discovered.values())


# ──────────────────────────────────────────────
#  TCP 通道通信（用于连接后的命令交互）
# ──────────────────────────────────────────────

def send_tcp_command(
    ip: str,
    command: dict,
    username: str = "admin",
    password: str = "",
    timeout: float = 10.0,
    port: int = SK_TCP_PORT,
) -> Optional[dict]:
    """
    通过 TCP 通道（端口 9010）向设备发送 JSON 命令并接收响应。

    协议格式:
        POST /xiaopaitech/device_service HTTP/1.1
        Host: <ip>
        User-Agent: Xiaopaitech NVR/1.0
        Content-Type: application/json; charset=utf-8
        Content-Length: <len>
        Connection: close
        Authorization: Basic <base64>

        <json body>

    Args:
        ip:       设备 IP
        command:  要发送的 JSON 命令字典
        username: 登录用户名（默认 admin）
        password: 登录密码
        timeout:  响应超时（秒）
        port:     TCP 端口（默认 9010）

    Returns:
        解析后的响应字典，失败返回 None
    """
    import base64

    body = json.dumps(command, ensure_ascii=False).encode("utf-8")
    auth_str = base64.b64encode(f"{username}:{password}".encode()).decode()

    header = (
        f"POST {SK_TCP_PATH} HTTP/1.1\r\n"
        f"Host: {ip}\r\n"
        f"User-Agent: Xiaopaitech NVR/1.0\r\n"
        f"Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"Authorization: Basic {auth_str}\r\n"
        f"\r\n"
    )

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.sendall(header.encode("utf-8") + body)

        # 接收响应
        response_data = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
            except socket.timeout:
                break
        sock.close()

        # 解析 HTTP 响应
        response_text = response_data.decode("utf-8", errors="ignore")
        # 找到空行（header 和 body 的分隔）
        sep_idx = response_text.find("\r\n\r\n")
        if sep_idx < 0:
            sep_idx = response_text.find("\n\n")
        if sep_idx < 0:
            return None

        body_text = response_text[sep_idx:].strip()
        return json.loads(body_text)

    except Exception as e:
        print(f"  [!] TCP 通信异常 ({ip}:{port}): {e}")
        return None


# ──────────────────────────────────────────────
#  后台持续发现监听器
# ──────────────────────────────────────────────

class SkyDiscoveryListener:
    """
    后台持续发现监听器。
    定期发送搜索命令并收集响应，用于实时发现新上线的设备。

    用法：
        listener = SkyDiscoveryListener()
        listener.start()
        ...
        devices = listener.get_devices()
        listener.stop()
    """

    def __init__(
        self,
        interval: float = 30.0,
        timeout: float = 5.0,
        bind_port: int = SK_TOOL_RECV_PORT,
        on_found: Optional[callable] = None,
    ):
        """
        Args:
            interval:  搜索间隔（秒）
            timeout:   每次搜索的超时时间
            bind_port: 接收端口
            on_found:  发现新设备时的回调 (device: SkDiscoveredDevice) -> None
        """
        self._interval = interval
        self._timeout = timeout
        self._bind_port = bind_port
        self._on_found = on_found
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._devices: Dict[str, SkDiscoveredDevice] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="SkyDiscoveryListener",
            daemon=True,
        )
        self._thread.start()
        print("[后台发现] 创维设备搜索监听已启动")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        print("[后台发现] 创维设备搜索监听已停止")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                # 静默搜索（不打印日志）
                devices = _silent_discover(
                    timeout=self._timeout,
                    bind_port=self._bind_port,
                )
                with self._lock:
                    for dev in devices:
                        if dev.ip not in self._devices:
                            self._devices[dev.ip] = dev
                            if self._on_found:
                                try:
                                    self._on_found(dev)
                                except Exception:
                                    pass
            except Exception as e:
                print(f"[后台发现] 搜索异常: {e}")

            # 等待下次搜索
            self._stop_event.wait(self._interval)

    def get_devices(self) -> List[SkDiscoveredDevice]:
        with self._lock:
            return list(self._devices.values())

    def get_new_devices(self, known_ips: set) -> List[SkDiscoveredDevice]:
        with self._lock:
            return [d for ip, d in self._devices.items() if ip not in known_ips]


def _silent_discover(
    timeout: float = 5.0,
    bind_port: int = SK_TOOL_RECV_PORT,
) -> List[SkDiscoveredDevice]:
    """静默版发现（不打印日志，供后台监听器使用）"""
    local_ip = _get_local_ip()
    search_cmd = build_search_command(
        local_ip=local_ip or "",
        local_port=bind_port,
    )
    discovered: Dict[str, SkDiscoveredDevice] = {}

    try:
        recv_sock = _create_recv_socket(bind_port)
        recv_sock.settimeout(1.0)
        _send_search(recv_sock, search_cmd)
    except OSError:
        return []

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                data, addr = recv_sock.recvfrom(65535)
            except (socket.timeout, OSError):
                continue

            src_ip = addr[0]
            if local_ip and src_ip == local_ip:
                continue
            if src_ip in discovered:
                continue

            device = _parse_search_response(data)
            if device is None:
                continue
            device_ip = device.ip if device.ip else src_ip
            device.ip = device_ip
            if device_ip not in discovered:
                discovered[device_ip] = device
    except Exception:
        pass
    finally:
        try:
            recv_sock.close()
        except Exception:
            pass

    return list(discovered.values())


# ──────────────────────────────────────────────
#  命令行入口
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="创维私有协议设备发现工具")
    parser.add_argument("--timeout", "-t", type=float, default=5.0,
                        help="搜索超时时间（秒，默认 5s）")
    parser.add_argument("--sn", type=str, default="",
                        help="指定搜索某个 SN")
    parser.add_argument("--port", type=int, default=SK_TOOL_RECV_PORT,
                        help=f"本机接收端口（默认 {SK_TOOL_RECV_PORT}）")
    parser.add_argument("--no-broadcast", action="store_true",
                        help="禁用广播发送（仅组播）")
    parser.add_argument("--no-multicast", action="store_true",
                        help="禁用组播发送（仅广播）")
    args = parser.parse_args()

    devices = discover_sky_devices(
        timeout=args.timeout,
        target_sn=args.sn,
        bind_port=args.port,
        use_broadcast=not args.no_broadcast,
        use_multicast=not args.no_multicast,
    )
