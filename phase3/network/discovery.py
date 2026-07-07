"""
设备发现模块 - 被动侦测 ONVIF 摄像头心跳包（WS-Discovery Hello）

原理：
  ONVIF 摄像头在接入局域网时会向多播地址 239.255.255.250:3702 发送
  WS-Discovery Hello 消息（即"心跳包"），声明自己的存在。
  本模块通过加入该多播组被动监听这些 Hello 包，从中提取设备 IP，
  无需主动扫描整个子网，效率更高、更隐蔽。

同时也支持：
  - USB(UVC) 摄像头扫描（OpenCV 枚举）
"""
import socket
import struct
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────
@dataclass
class DiscoveredUSBDevice:
    """发现的 USB 摄像头信息"""
    device_index: int
    width: int = 0
    height: int = 0
    fps: float = 0.0
    backend: str = ""


@dataclass
class DiscoveredNetworkDevice:
    """发现的局域网摄像头信息（通过被动监听 WS-Discovery 心跳包发现）"""
    ip: str
    onvif_port: int = 80                        # ONVIF 服务端口
    rtsp_port: int = 554                        # RTSP 端口
    onvif_available: bool = True                # 通过 WS-Discovery 发现，默认支持 ONVIF
    rtsp_available: bool = True                 # 假设 ONVIF 设备均支持 RTSP
    http_title: str = ""
    mac_address: str = ""
    device_type: str = ""                       # WS-Discovery Types 字段
    scopes: str = ""                            # WS-Discovery Scopes 字段
    xaddrs: str = ""                            # WS-Discovery XAddrs 字段
    extra_ports: List[int] = field(default_factory=list)
    discovered_at: float = field(default_factory=time.time)  # 发现时间戳


# ──────────────────────────────────────────────
#  WS-Discovery 常量
# ──────────────────────────────────────────────
WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702


# ──────────────────────────────────────────────
#  XML 解析工具
# ──────────────────────────────────────────────

# WS-Discovery 常用 XML 命名空间
_NS = {
    's':   'http://www.w3.org/2003/05/soap-envelope',
    'wsa': 'http://schemas.xmlsoap.org/ws/2004/08/addressing',
    'wsd': 'http://schemas.xmlsoap.org/ws/2005/04/discovery',
    'dn':  'http://www.onvif.org/ver10/network/wsdl/RemoteDiscoveryBinding',
}


def _parse_hello(xml_data: str) -> dict:
    """
    解析 WS-Discovery Hello / ProbeMatch 消息，提取设备信息。
    返回字段字典（可能为空）。
    """
    info = {}
    try:
        root = ET.fromstring(xml_data)

        # 递归搜索所有元素，按 localName 匹配
        def find_text(local_name: str) -> str:
            for elem in root.iter():
                tag = elem.tag
                # 去除命名空间前缀
                if '}' in tag:
                    tag = tag.split('}', 1)[1]
                if tag == local_name and elem.text:
                    return elem.text.strip()
            return ""

        info['action'] = find_text('Action')
        info['message_id'] = find_text('MessageID')
        info['endpoint_ref'] = find_text('Address')
        info['types'] = find_text('Types')
        info['scopes'] = find_text('Scopes')
        info['xaddrs'] = find_text('XAddrs')

    except ET.ParseError:
        pass
    except Exception:
        pass

    return info


def _is_hello_action(action: str) -> bool:
    """判断 Action 是否为 Hello（心跳上线通知）"""
    return 'Hello' in action if action else False


def _is_probe_match_action(action: str) -> bool:
    """判断 Action 是否为 ProbeMatch（主动探测的响应）"""
    return 'ProbeMatches' in action if action else False


# ──────────────────────────────────────────────
#  多播监听 Socket 构建
# ──────────────────────────────────────────────

def _create_multicast_socket(bind_port: int = WS_DISCOVERY_PORT) -> socket.socket:
    """
    创建并加入 WS-Discovery 多播组的 UDP socket。
    Windows 下使用 SO_REUSEADDR 允许多个进程同时监听。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # 绑定到多播端口（所有接口）
    sock.bind(("", bind_port))

    # 加入多播组：INADDR_ANY 表示在所有接口上接收
    mreq = struct.pack(
        "4sl",
        socket.inet_aton(WS_DISCOVERY_ADDR),
        socket.INADDR_ANY,
    )
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    return sock


# ──────────────────────────────────────────────
#  被动发现（核心）
# ──────────────────────────────────────────────

def _passive_listen(
    timeout: float = 15.0,
    stop_event: Optional[threading.Event] = None,
    on_device_found: Optional[callable] = None,
) -> List[DiscoveredNetworkDevice]:
    """
    被动监听 WS-Discovery 多播组，收集 Hello / ProbeMatch 消息。

    :param timeout: 监听时长（秒）。设大一点以等待更多设备上线。
    :param stop_event: 外部停止信号（可选）
    :param on_device_found: 发现新设备时的回调 (device: DiscoveredNetworkDevice) -> None
    :return: 发现的设备列表
    """
    discovered: Dict[str, DiscoveredNetworkDevice] = {}
    local_ip = _get_local_ip()

    print(f"\n[被动发现] 正在监听 WS-Discovery 心跳包 (最长 {timeout:.0f}s) ...")
    print(f"  多播地址: {WS_DISCOVERY_ADDR}:{WS_DISCOVERY_PORT}")
    print(f"  等待摄像头上线广播 ...")
    if local_ip:
        print(f"  本机 IP: {local_ip}")

    try:
        sock = _create_multicast_socket()
        sock.settimeout(1.0)  # 每次 recv 最多等 1 秒，以便检查 stop_event
    except Exception as e:
        print(f"[被动发现] 创建多播 socket 失败: {e}")
        return []

    deadline = time.time() + timeout

    try:
        while time.time() < deadline:
            if stop_event and stop_event.is_set():
                break

            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                # 没有数据，继续循环
                continue
            except Exception:
                continue

            ip = addr[0]

            # 跳过本机和已发现的设备
            if local_ip and ip == local_ip:
                continue
            if ip in discovered:
                continue

            # 解析 WS-Discovery 消息
            xml_str = data.decode("utf-8", errors="ignore")
            info = _parse_hello(xml_str)
            action = info.get('action', '')

            # 只处理 Hello 和 ProbeMatch
            if not (_is_hello_action(action) or _is_probe_match_action(action)):
                continue

            # 检查是否为 ONVIF 摄像头（Types 包含 NetworkVideoTransmitter）
            types = info.get('types', '')
            is_camera = ('NetworkVideoTransmitter' in types or
                         'nvt' in types.lower() or
                         'onvif' in types.lower() or
                         not types)  # Types 为空也接受（某些设备不发 Types）

            if not is_camera:
                continue

            device = DiscoveredNetworkDevice(
                ip=ip,
                device_type=types,
                scopes=info.get('scopes', ''),
                xaddrs=info.get('xaddrs', ''),
                discovered_at=time.time(),
            )
            discovered[ip] = device

            tag = "Hello" if _is_hello_action(action) else "ProbeMatch"
            print(f"  [✓] 捕获到 {tag}: {ip}")
            if types:
                print(f"      类型: {types[:60]}")
            if info.get('xaddrs'):
                print(f"      服务地址: {info['xaddrs'][:80]}")

            if on_device_found:
                try:
                    on_device_found(device)
                except Exception:
                    pass

    except Exception as e:
        print(f"[被动发现] 监听异常: {e}")
    finally:
        # 退出多播组并关闭 socket
        try:
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(WS_DISCOVERY_ADDR),
                socket.INADDR_ANY,
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            sock.close()
        except Exception:
            pass

    return list(discovered.values())


# ──────────────────────────────────────────────
#  主动探测（可选补充）
# ──────────────────────────────────────────────

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


def _send_probe_and_listen(wait: float = 5.0) -> List[DiscoveredNetworkDevice]:
    """
    主动发送 WS-Discovery Probe 触发在线设备响应，然后收集 ProbeMatch。
    与被动监听互补：被动等 Hello（设备上线时发），主动发 Probe 让已在线设备立即响应。

    :param wait: 发送 Probe 后等待响应的时间（秒）
    :return: 发现的设备列表
    """
    discovered: Dict[str, DiscoveredNetworkDevice] = {}
    local_ip = _get_local_ip()
    msg_id = str(uuid.uuid4())
    probe_msg = _WS_PROBE_TEMPLATE.format(msg_id=msg_id).encode("utf-8")

    print(f"\n[主动探测] 发送 WS-Discovery Probe (等待响应 {wait:.0f}s) ...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(1.0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # 发送 Probe 多播
        sock.sendto(probe_msg, (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))

    except Exception as e:
        print(f"[主动探测] 创建 socket 失败: {e}")
        return []

    deadline = time.time() + wait

    try:
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception:
                continue

            ip = addr[0]
            if local_ip and ip == local_ip:
                continue
            if ip in discovered:
                continue

            xml_str = data.decode("utf-8", errors="ignore")
            info = _parse_hello(xml_str)
            action = info.get('action', '')

            if not _is_probe_match_action(action):
                continue

            types = info.get('types', '')
            device = DiscoveredNetworkDevice(
                ip=ip,
                device_type=types,
                scopes=info.get('scopes', ''),
                xaddrs=info.get('xaddrs', ''),
                discovered_at=time.time(),
            )
            discovered[ip] = device
            print(f"  [✓] ProbeMatch: {ip}")
            if types:
                print(f"      类型: {types[:60]}")

    except Exception as e:
        print(f"[主动探测] 异常: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass

    return list(discovered.values())


# ──────────────────────────────────────────────
#  公开接口：综合发现（被动监听 + 主动探测）
# ──────────────────────────────────────────────

def discover_network_cameras(
    listen_timeout: float = 15.0,
    probe_timeout: float = 5.0,
    passive_only: bool = False,
) -> List[DiscoveredNetworkDevice]:
    """
    发现局域网 ONVIF 摄像头（被动心跳监听 + 可选主动探测）。

    流程：
      1. 被动监听 WS-Discovery Hello（设备上线时广播）
      2. 发送 WS-Discovery Probe，触发已在线设备响应（可选）
      3. 合并去重结果

    :param listen_timeout: 被动监听时长（秒）
    :param probe_timeout: 主动探测等待时长（秒）
    :param passive_only: True 则只被动监听，不发 Probe
    :return: 发现的设备列表
    """
    print("\n" + "=" * 55)
    print("  ONVIF 摄像头被动发现（心跳包监听）")
    print("=" * 55)

    # ── Step 1: 被动监听 Hello ──
    print(f"\n[Step 1/2] 被动监听 WS-Discovery Hello ...")
    passive_devices = _passive_listen(timeout=listen_timeout)
    print(f"  被动发现: {len(passive_devices)} 个设备")

    if passive_only:
        all_devices = passive_devices
    else:
        # ── Step 2: 主动 Probe（补充已在线但不发 Hello 的设备）──
        print(f"\n[Step 2/2] 发送 WS-Discovery Probe ...")
        active_devices = _send_probe_and_listen(wait=probe_timeout)
        print(f"  主动探测: {len(active_devices)} 个设备")

        # 合并去重
        seen_ips = {d.ip for d in passive_devices}
        all_devices = list(passive_devices)
        for d in active_devices:
            if d.ip not in seen_ips:
                all_devices.append(d)
                seen_ips.add(d.ip)

    # ── 打印结果 ──
    print(f"\n{'─' * 55}")
    if not all_devices:
        print("  未发现 ONVIF 摄像头")
        print(f"\n  排查建议:")
        print(f"    1. 确认摄像头已通电并连接到 WiFi")
        print(f"    2. 确认电脑和摄像头在同一局域网")
        print(f"    3. 尝试重启摄像头以触发 Hello 广播")
        print(f"    4. 延长监听时间: listen_timeout=30")
    else:
        print(f"  共发现 {len(all_devices)} 个 ONVIF 设备:\n")
        for i, dev in enumerate(all_devices, 1):
            print(f"  [{i}] IP: {dev.ip}")
            if dev.device_type:
                print(f"      类型: {dev.device_type[:60]}")
            if dev.xaddrs:
                print(f"      服务: {dev.xaddrs[:80]}")
            print(f"      ONVIF端口: {dev.onvif_port}  RTSP端口: {dev.rtsp_port}")
            print()

    print("=" * 55 + "\n")
    return all_devices


# ──────────────────────────────────────────────
#  后台持续监听（供 CLI /probe_all 或持续模式使用）
# ──────────────────────────────────────────────

class PassiveDiscoveryListener:
    """
    后台持续监听 WS-Discovery 心跳包。
    可在 CLI 启动时开始，实时发现新上线的摄像头。

    用法：
        listener = PassiveDiscoveryListener(on_found=my_callback)
        listener.start()
        ...
        listener.stop()
        devices = listener.get_devices()
    """

    def __init__(self, on_found: Optional[callable] = None):
        self._on_found = on_found
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._devices: Dict[str, DiscoveredNetworkDevice] = {}
        self._lock = threading.Lock()

    def _callback_wrapper(self, device: DiscoveredNetworkDevice):
        with self._lock:
            self._devices[device.ip] = device
        if self._on_found:
            self._on_found(device)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="WSDiscoveryListener",
            daemon=True,
        )
        self._thread.start()
        print("[后台发现] WS-Discovery 心跳监听已启动")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        print("[后台发现] WS-Discovery 心跳监听已停止")

    def _run(self) -> None:
        """持续监听，每次 _passive_listen 超时后重新加入多播组"""
        while not self._stop_event.is_set():
            try:
                _passive_listen(
                    timeout=30.0,
                    stop_event=self._stop_event,
                    on_device_found=self._callback_wrapper,
                )
            except Exception as e:
                print(f"[后台发现] 监听异常: {e}")
                time.sleep(2)

    def get_devices(self) -> List[DiscoveredNetworkDevice]:
        with self._lock:
            return list(self._devices.values())

    def get_new_devices(self, known_ips: set) -> List[DiscoveredNetworkDevice]:
        """返回已知 IP 之外的新发现设备"""
        with self._lock:
            return [d for ip, d in self._devices.items() if ip not in known_ips]


# ──────────────────────────────────────────────
#  USB 摄像头发现（保留）
# ──────────────────────────────────────────────

def discover_usb_cameras(max_index: int = 10) -> List[DiscoveredUSBDevice]:
    """
    扫描系统中可用的 USB 摄像头。
    :param max_index: 最大扫描索引范围
    :return: 可用摄像头列表
    """
    found = []
    print("[发现] 正在扫描 USB 摄像头 ...")

    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        backend = "DirectShow"
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)
            backend = "Default"

        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.release()
            cam = DiscoveredUSBDevice(device_index=idx, width=w, height=h, fps=fps, backend=backend)
            found.append(cam)
            print(f"  [✓] 设备 {idx}: {w}x{h} @ {fps:.0f}fps ({backend})")

    if not found:
        print("  [✗] 未发现可用的 USB 摄像头")
    else:
        print(f"[发现] 共发现 {len(found)} 个 USB 摄像头")
    return found


# ──────────────────────────────────────────────
#  辅助函数
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


# ──────────────────────────────────────────────
#  命令行入口：可独立运行此脚本进行被动发现
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ONVIF 摄像头被动发现工具（心跳包监听）")
    parser.add_argument("--timeout", "-t", type=float, default=15.0,
                        help="被动监听时长（秒，默认 15s）")
    parser.add_argument("--no-probe", action="store_true",
                        help="只被动监听，不发送主动 Probe")
    parser.add_argument("--usb", action="store_true",
                        help="同时扫描 USB 摄像头")
    args = parser.parse_args()

    # 网络摄像头被动发现
    net_devices = discover_network_cameras(
        listen_timeout=args.timeout,
        passive_only=args.no_probe,
    )

    # USB 摄像头发现（可选）
    if args.usb:
        print("\n")
        usb_devices = discover_usb_cameras()

    # 输出配置建议
    if net_devices:
        print("\n💡 配置建议 - 将以下信息填入 config.yaml:\n")
        for dev in net_devices:
            print(f"  cameras:")
            print(f"  - name: camera_{dev.ip.replace('.', '_')}")
            print(f"    connection_type: onvif")
            print(f"    ip: {dev.ip}")
            print(f"    port: {dev.onvif_port}")
            print(f"    username: admin")
            print(f"    password: <你的密码>")
            print(f"    rtsp_port: {dev.rtsp_port}")
            print()
