#!/usr/bin/env python3
"""
ONVIF 局域网设备发现与协议版本测试脚本 (自动多端口探测版)
"""
import socket
import struct
import uuid
import time
from rich.console import Console
from rich.table import Table

console = Console()

# 常见 ONVIF 端口列表，可根据实际情况增减
COMMON_ONVIF_PORTS = [80, 8080, 8899, 8000]


def discover_onvif_devices(timeout=3):
    """
    使用 WS-Discovery 协议发现局域网内的 ONVIF 设备 IP
    """
    MULTICAST_GROUP = "239.255.255.250"
    MULTICAST_PORT = 3702

    probe_message = f'''<?xml version="1.0" encoding="UTF-8"?>
    <e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
    xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
    xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
      <e:Header>
        <w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>
        <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005/04/discovery</w:To>
        <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
      </e:Header>
      <e:Body>
        <d:Probe xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
          <d:Types>dn:NetworkVideoTransmitter</d:Types>
        </d:Probe>
      </e:Body>
    </e:Envelope>'''

    devices = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        sock.bind(('', MULTICAST_PORT))

        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        sock.sendto(probe_message.encode(), (MULTICAST_GROUP, MULTICAST_PORT))
        console.print(f"[bold green]正在扫描局域网 ONVIF 设备 (超时: {timeout}秒)...[/bold green]")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(65507)
                response = data.decode('utf-8', errors='ignore')
                ip = addr[0]
                if "NetworkVideoTransmitter" in response and ip not in [d['ip'] for d in devices]:
                    devices.append({'ip': ip})
            except socket.timeout:
                break
    except Exception as e:
        console.print(f"[bold red]设备发现过程出错: {e}[/bold red]")
    finally:
        sock.close()

    return devices


def test_onvif_version(ip, username='admin', password='admin'):
    """
    自动尝试多个端口连接 ONVIF 设备并获取协议版本及基本信息
    """
    from onvif import ONVIFCamera

    for port in COMMON_ONVIF_PORTS:
        try:
            # 尝试连接当前端口
            cam = ONVIFCamera(ip, port, username, password)
            device_info = cam.devicemgmt.GetDeviceInformation()
            capabilities = cam.devicemgmt.GetCapabilities({'Category': 'All'})

            supported_profiles = []
            if hasattr(capabilities, 'Media') and capabilities.Media:
                if hasattr(capabilities.Media, 'XAddr'):
                    supported_profiles.append("Profile S/T (Media Service Active)")

            return {
                'status': 'Success',
                'port': port,
                'manufacturer': device_info.Manufacturer,
                'model': device_info.Model,
                'firmware': device_info.FirmwareVersion,
                'serial': device_info.SerialNumber,
                'profiles': supported_profiles
            }
        except Exception:
            # 当前端口连接失败，继续尝试下一个端口
            continue

    # 所有端口均尝试失败
    return {'status': 'Failed', 'port': '-', 'error': 'All common ports failed'}


if __name__ == "__main__":
    found_devices = discover_onvif_devices(timeout=4)

    if not found_devices:
        console.print("[yellow]未在局域网内发现 ONVIF 设备。请确保摄像头已开启 ONVIF 服务并与本机在同一网段。[/yellow]")
    else:
        table = Table(title="ONVIF 设备协议版本测试结果 (多端口探测)")
        table.add_column("IP 地址", style="cyan")
        table.add_column("端口", style="yellow")
        table.add_column("制造商", style="magenta")
        table.add_column("型号")
        table.add_column("固件版本")
        table.add_column("支持 Profile")
        table.add_column("状态", style="bold")

        for dev in found_devices:
            # ⚠️ 实际使用时请替换为真实的 ONVIF 用户名和密码
            result = test_onvif_version(dev['ip'], 'admin', 'your_password')

            if result['status'] == 'Success':
                table.add_row(
                    dev['ip'],
                    str(result['port']),
                    result['manufacturer'],
                    result['model'],
                    result['firmware'],
                    ", ".join(result['profiles']) or "Media Service Detected",
                    "[green]成功[/green]"
                )
            else:
                table.add_row(dev['ip'], "-", "-", "-", "-", "-", f"[red]失败: {result['error']}[/red]")

        console.print(table)