"""
phase2 - 设备发现模块 - 自动扫描可用的摄像头
支持：局域网 ONVIF 设备发现 (WS-Discovery) + 端口扫描 + USB 扫描
"""
import ipaddress
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2


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
    """发现的局域网摄像头信息"""
    ip: str
    onvif_port: int = 80
    rtsp_port: int = 554
    onvif_available: bool = False
    rtsp_available: bool = False
    http_title: str = ""
    mac_address: str = ""
    device_type: str = ""
    extra_ports: List[int] = field(default_factory=list)


# ──────────────────────────────────────────────
#  WS-Discovery
# ──────────────────────────────────────────────
WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702

WS_PROBE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
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


def _ws_discovery(timeout: float = 3.0) -> List[str]:
    """通过 WS-Discovery 协议发现 ONVIF 设备。"""
    found_ips = []
    msg_id = str(uuid.uuid4())
    probe_msg = WS_PROBE_TEMPLATE.format(msg_id=msg_id).encode("utf-8")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.sendto(probe_msg, (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))
        print(f"  [WS-Discovery] 已发送 Probe，等待响应 ...")
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                if ip not in found_ips:
                    found_ips.append(ip)
                    print(f"  [✓] WS-Discovery 响应: {ip}")
            except socket.timeout:
                break
            except Exception:
                continue
        sock.close()
    except Exception as e:
        print(f"  [!] WS-Discovery 异常: {e}")
    return found_ips


# ──────────────────────────────────────────────
#  端口扫描
# ──────────────────────────────────────────────

def _check_port(ip: str, port: int, timeout: float = 0.3) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _get_http_title(ip: str, port: int, timeout: float = 2.0) -> str:
    try:
        import http.client
        import re
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read(4096).decode("utf-8", errors="ignore")
        conn.close()
        match = re.search(r'<title[^>]*>(.*?)</title>', body, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()[:80]
    except Exception:
        pass
    return ""


def _scan_subnet(subnet: Optional[str] = None, ports: Optional[List[int]] = None,
                  timeout: float = 0.3, max_workers: int = 50) -> Dict[str, List[int]]:
    if subnet is None:
        subnet = _detect_subnet()
        if not subnet:
            return {}
    if ports is None:
        ports = [80, 554, 8080, 8000, 8081, 8899]

    print(f"  [端口扫描] 子网: {subnet}  端口: {ports}")
    network = ipaddress.ip_network(subnet, strict=False)
    results: Dict[str, List[int]] = {}
    lock = threading.Lock()
    semaphore = threading.Semaphore(max_workers)

    def scan_ip_port(ip_str: str, port: int):
        semaphore.acquire()
        try:
            if _check_port(ip_str, port, timeout):
                with lock:
                    if ip_str not in results:
                        results[ip_str] = []
                    results[ip_str].append(port)
        finally:
            semaphore.release()

    threads = []
    for host in network.hosts():
        ip_str = str(host)
        if ip_str.endswith(".1"):
            continue
        for port in ports:
            t = threading.Thread(target=scan_ip_port, args=(ip_str, port))
            threads.append(t)
            t.start()
    for t in threads:
        t.join()
    return results


def _detect_subnet() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print(f"  [网络] 本机 IP: {local_ip}")
        parts = local_ip.split(".")
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    except Exception as e:
        print(f"  [!] 检测子网失败: {e}")
        return None


def _get_local_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


# ──────────────────────────────────────────────
#  公开接口
# ──────────────────────────────────────────────

def discover_network_cameras(subnet: Optional[str] = None, password: str = "",
                              scan_timeout: float = 0.3) -> List[DiscoveredNetworkDevice]:
    """综合发现局域网内的摄像头设备。"""
    print("\n" + "=" * 55)
    print("  局域网摄像头自动发现")
    print("=" * 55)

    local_ip = _get_local_ip()
    if local_ip:
        print(f"\n  本机 IP: {local_ip}")

    print("\n[Step 1/3] WS-Discovery ONVIF 设备发现 ...")
    ws_ips = _ws_discovery(timeout=3.0)

    print(f"\n[Step 2/3] 端口扫描 ...")
    port_results = _scan_subnet(subnet=subnet, ports=[80, 554, 8080, 8000, 8081, 8899, 10554],
                                 timeout=scan_timeout)

    print(f"\n[Step 3/3] 合并发现结果 ...")
    all_ips = set(ws_ips) | set(port_results.keys())
    if local_ip:
        all_ips.discard(local_ip)

    devices = []
    for ip in sorted(all_ips):
        open_ports = port_results.get(ip, [])
        is_ws = ip in ws_ips
        onvif_port = 80
        for p in [80, 8080, 8000, 8899]:
            if p in open_ports:
                onvif_port = p
                break
        rtsp_port = 554
        rtsp_available = 554 in open_ports or 10554 in open_ports
        if 10554 in open_ports and 554 not in open_ports:
            rtsp_port = 10554
        http_title = ""
        if onvif_port in open_ports:
            http_title = _get_http_title(ip, onvif_port)
        device = DiscoveredNetworkDevice(
            ip=ip, onvif_port=onvif_port, rtsp_port=rtsp_port,
            onvif_available=is_ws or (onvif_port in open_ports),
            rtsp_available=rtsp_available, http_title=http_title,
            extra_ports=open_ports,
        )
        devices.append(device)

    print(f"\n{'─' * 55}")
    if not devices:
        print("  未发现局域网内的摄像头设备")
    else:
        print(f"  共发现 {len(devices)} 个网络设备:\n")
        for i, dev in enumerate(devices):
            print(f"  [{i+1}] IP: {dev.ip}")
            print(f"      ONVIF: {'✓' if dev.onvif_available else '✗'}")
            print(f"      RTSP:  {'✓' if dev.rtsp_available else '✗'}")
            print(f"      开放端口: {dev.extra_ports}")
            if dev.http_title:
                print(f"      HTTP标题: {dev.http_title}")
            print()
    print("=" * 55 + "\n")
    return devices


def discover_usb_cameras(max_index: int = 10) -> List[DiscoveredUSBDevice]:
    """扫描系统中可用的 USB 摄像头。"""
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
