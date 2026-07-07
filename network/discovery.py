"""
设备发现模块 - 自动扫描可用的摄像头
支持：
  1. 局域网 ONVIF 设备发现 (WS-Discovery)
  2. 局域网端口扫描 (RTSP / HTTP)
  3. USB(UVC) 摄像头扫描
"""
import ipaddress
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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
    """发现的局域网摄像头信息"""
    ip: str
    onvif_port: int = 80                        # ONVIF 服务端口
    rtsp_port: int = 554                       # RTSP 端口
    onvif_available: bool = False              # 是否响应 ONVIF
    rtsp_available: bool = False               # 是否响应 RTSP
    http_title: str = ""                       # HTTP 页面标题（辅助识别品牌）
    mac_address: str = ""                      # MAC 地址
    device_type: str = ""                      # 设备类型描述
    extra_ports: List[int] = field(default_factory=list)  # 其他开放端口


# ──────────────────────────────────────────────
#  WS-Discovery (ONVIF 标准发现协议)
# ──────────────────────────────────────────────

# WS-Discovery 多播地址和端口
WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702

# WS-Discovery Probe 报文模板
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
    """
    通过 WS-Discovery 协议发现 ONVIF 设备。
    发送多播 Probe 消息，收集设备的响应。

    :param timeout: 等待响应的时间（秒）
    :return: 发现的设备 IP 列表
    """
    found_ips = []
    msg_id = str(uuid.uuid4())
    probe_msg = WS_PROBE_TEMPLATE.format(msg_id=msg_id).encode("utf-8")

    try:
        # 创建 UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # 发送多播 Probe
        sock.sendto(probe_msg, (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))
        print(f"  [WS-Discovery] 已发送 Probe，等待响应 (超时 {timeout}s) ...")

        # 收集响应
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                if ip not in found_ips:
                    found_ips.append(ip)
                    # 尝试从响应中提取设备信息
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

# 摄像头常见端口及其含义
CAMERA_PORTS = {
    80:    "HTTP/ONVIF",
    443:   "HTTPS",
    554:   "RTSP",
    10554: "RTSP-Alt",
    8000:  "HTTP-Alt (海康/大华)",
    8080:  "HTTP-Proxy",
    8081:  "HTTP-Alt",
    8090:  "HTTP-Alt",
    8899:  "ONVIF-Alt",
    9000:  "HTTP-Alt",
    3702:  "WS-Discovery",
    5000:  "UPnP",
}


def _check_port(ip: str, port: int, timeout: float = 0.3) -> bool:
    """检查单个端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _get_http_title(ip: str, port: int, timeout: float = 2.0) -> str:
    """尝试获取 HTTP 页面标题（辅助识别摄像头品牌）"""
    try:
        import http.client
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read(4096).decode("utf-8", errors="ignore")
        conn.close()

        # 简单提取 <title>
        import re
        match = re.search(r'<title[^>]*>(.*?)</title>', body, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()[:80]
    except Exception:
        pass
    return ""


def _scan_subnet(
    subnet: Optional[str] = None,
    ports: Optional[List[int]] = None,
    timeout: float = 0.3,
    max_workers: int = 50,
) -> Dict[str, List[int]]:
    """
    扫描局域网子网，找出开放指定端口的设备。

    :param subnet: 子网 CIDR (如 "192.168.1.0/24")，None 则自动检测
    :param ports: 要扫描的端口列表
    :param timeout: 每个端口的连接超时
    :param max_workers: 最大并发线程数
    :return: {ip: [open_ports]}
    """
    if subnet is None:
        subnet = _detect_subnet()
        if not subnet:
            print("  [!] 无法自动检测子网，请手动指定")
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
        # 跳过网关（通常是 .1）和本机
        if ip_str.endswith(".1"):
            continue
        for port in ports:
            t = threading.Thread(target=scan_ip_port, args=(ip_str, port))
            threads.append(t)
            t.start()

    # 等待所有线程完成
    for t in threads:
        t.join()

    return results


def _detect_subnet() -> Optional[str]:
    """
    自动检测本机所在的子网。
    通过获取本机 IP 地址推算子网。
    """
    try:
        # 创建一个 UDP socket 来获取本机出口 IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        print(f"  [网络] 本机 IP: {local_ip}")

        # 假设 /24 子网（绝大多数家庭/办公网络）
        parts = local_ip.split(".")
        subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        return subnet

    except Exception as e:
        print(f"  [!] 检测子网失败: {e}")
        return None


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
#  公开接口：综合发现
# ──────────────────────────────────────────────

def discover_network_cameras(
    subnet: Optional[str] = None,
    password: str = "",
    scan_timeout: float = 0.3,
) -> List[DiscoveredNetworkDevice]:
    """
    综合发现局域网内的摄像头设备。
    流程：
      1. WS-Discovery 多播发现 ONVIF 设备
      2. 端口扫描补充（HTTP/RTSP 端口）
      3. 合并结果

    :param subnet: 子网 CIDR，None 自动检测
    :param password: 用于验证连接的密码
    :param scan_timeout: 端口扫描超时
    :return: 发现的设备列表
    """
    print("\n" + "=" * 55)
    print("  局域网摄像头自动发现")
    print("=" * 55)

    local_ip = _get_local_ip()
    if local_ip:
        print(f"\n  本机 IP: {local_ip}")

    # ── Step 1: WS-Discovery ──
    print("\n[Step 1/3] WS-Discovery ONVIF 设备发现 ...")
    ws_ips = _ws_discovery(timeout=3.0)

    # ── Step 2: 端口扫描 ──
    print(f"\n[Step 2/3] 端口扫描 ...")
    port_results = _scan_subnet(
        subnet=subnet,
        ports=[80, 554, 8080, 8000, 8081, 8899, 10554],
        timeout=scan_timeout,
    )

    # ── Step 3: 合并结果 ──
    print(f"\n[Step 3/3] 合并发现结果 ...")

    # 收集所有 IP
    all_ips = set(ws_ips) | set(port_results.keys())
    # 排除本机
    if local_ip:
        all_ips.discard(local_ip)

    devices = []
    for ip in sorted(all_ips):
        open_ports = port_results.get(ip, [])
        is_ws = ip in ws_ips

        # 判断 ONVIF 端口
        onvif_port = 80
        for p in [80, 8080, 8000, 8899]:
            if p in open_ports:
                onvif_port = p
                break

        # 判断 RTSP 端口
        rtsp_port = 554
        rtsp_available = 554 in open_ports or 10554 in open_ports
        if 10554 in open_ports and 554 not in open_ports:
            rtsp_port = 10554

        # 尝试获取 HTTP 标题
        http_title = ""
        if onvif_port in open_ports:
            http_title = _get_http_title(ip, onvif_port)

        device = DiscoveredNetworkDevice(
            ip=ip,
            onvif_port=onvif_port,
            rtsp_port=rtsp_port,
            onvif_available=is_ws or (onvif_port in open_ports),
            rtsp_available=rtsp_available,
            http_title=http_title,
            extra_ports=open_ports,
        )
        devices.append(device)

    # ── 打印结果 ──
    print(f"\n{'─' * 55}")
    if not devices:
        print("  未发现局域网内的摄像头设备")
        print(f"\n  排查建议:")
        print(f"    1. 确认摄像头已通电并连接到 WiFi")
        print(f"    2. 确认电脑和摄像头在同一局域网")
        print(f"    3. 检查路由器 DHCP 列表确认摄像头 IP")
        print(f"    4. 尝试手动指定子网: python -m discovery --subnet 192.168.x.0/24")
    else:
        print(f"  共发现 {len(devices)} 个网络设备:\n")
        for i, dev in enumerate(devices):
            print(f"  [{i+1}] IP: {dev.ip}")
            print(f"      ONVIF: {'✓ 可用 (端口 ' + str(dev.onvif_port) + ')' if dev.onvif_available else '✗ 未检测到'}")
            print(f"      RTSP:  {'✓ 可用 (端口 ' + str(dev.rtsp_port) + ')' if dev.rtsp_available else '✗ 未检测到'}")
            print(f"      开放端口: {dev.extra_ports}")
            if dev.http_title:
                print(f"      HTTP标题: {dev.http_title}")
            print()

    print("=" * 55 + "\n")
    return devices


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
#  命令行入口：可独立运行此脚本进行扫描
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="摄像头自动发现工具")
    parser.add_argument("--subnet", "-s", type=str, default=None,
                        help="指定子网 CIDR (如 192.168.1.0/24)")
    parser.add_argument("--password", "-p", type=str, default="",
                        help="摄像头连接密码")
    parser.add_argument("--usb", action="store_true",
                        help="同时扫描 USB 摄像头")
    parser.add_argument("--timeout", "-t", type=float, default=0.3,
                        help="端口扫描超时 (默认 0.3s)")
    args = parser.parse_args()

    # 网络摄像头发现
    net_devices = discover_network_cameras(
        subnet=args.subnet,
        password=args.password,
        scan_timeout=args.timeout,
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
            print(f"    device_model: LC2418")
            print(f"    product_version: ZCR461")
            print()
