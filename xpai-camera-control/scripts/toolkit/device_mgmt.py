"""
Toolkit 5: 设备管理与维护

工具清单：
  - get_registered_cameras  从 config.yaml 加载已注册摄像头配置
  - register_camera         将摄像头信息写入 config.yaml（持久化凭据）
  - search_devices          搜索局域网可用摄像头（支持 WS-Discovery / USB / 创维私有协议）
  - connect_device          设备连接（先尝试免密拉流，失败则提示用户输入密码）
  - disconnect_device       断开摄像头连接并释放资源
  - query_device_model      查询设备型号/固件/状态/网络信息
  - update_firmware         固件更新与升级
  - system_maintenance      系统维护（重启/云台矫正）
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .discovery import (
    SkDiscoveredDevice,
    SkChannelInfo,
    discover_sky_devices,
    send_tcp_command,
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


class MaintenanceAction(str, Enum):
    REBOOT = "reboot"                        # 重启设备
    CALIBRATE_PTZ = "calibrate_ptz"          # 云台矫正
    FACTORY_RESET = "factory_reset"          # 恢复出厂设置


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class DiscoveredDevice:
    """发现的设备信息"""
    ip: str                                   # IP 地址
    onvif_port: int = 80                       # ONVIF 服务端口
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


@dataclass
class DisconnectResult:
    """设备断开连接返回结果"""
    success: bool                              # 断开是否成功
    session_released: bool = False             # 是否释放了云端会话
    error_message: str = ""                    # 失败原因


@dataclass
class DeviceInfo:
    """设备详细信息"""
    manufacturer: str = ""                     # 厂商
    model: str = ""                            # 型号
    firmware_version: str = ""                 # 固件版本
    serial_number: str = ""                    # 序列号 (SN)
    hardware_id: str = ""                      # 硬件 ID
    ip_address: str = ""                       # IP 地址
    mac_address: str = ""                      # MAC 地址
    is_online: bool = False                    # 是否在线
    network_type: str = ""                     # 网络类型 (WiFi / Ethernet)


@dataclass
class DeviceInfoResult:
    """查询设备信息返回结果"""
    success: bool
    info: Optional[DeviceInfo] = None
    error_message: str = ""


@dataclass
class FirmwareResult:
    """固件更新返回结果"""
    success: bool
    old_version: str = ""                      # 旧版本号
    new_version: str = ""                      # 新版本号
    error_message: str = ""


@dataclass
class MaintenanceResult:
    """系统维护返回结果"""
    success: bool
    action_performed: str = ""                 # 执行的维护操作名称
    error_message: str = ""


@dataclass
class CameraConfig:
    """从 config.yaml 加载的摄像头配置"""
    name: str                                  # 摄像头名称
    connection_type: str = "onvif"             # "onvif" | "usb"
    ip: str = ""                               # IP 地址
    port: int = 80                             # ONVIF 端口
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


@dataclass
class RegisterResult:
    """注册摄像头到 config.yaml 的返回结果"""
    success: bool                              # 注册是否成功
    camera_name: str = ""                      # 注册的摄像头名称
    error_message: str = ""                    # 失败原因


@dataclass
class AuthStatusResult:
    """轮询远程授权服务器的返回结果"""
    status: AuthStatus                         # 授权状态 (pending / authorized / rejected / error)
    camera_name: str = ""                      # 摄像头名称
    message: str = ""                          # 状态说明（如 "用户已授权" 或 "超时未确认"）


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
    port: int = 80,
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
        port:            ONVIF 端口（默认 80）
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

    # 构建新条目
    new_entry = {
        "name": name,
        "connection_type": connection_type,
        "ip": ip,
        "port": port,
        "username": username,
        "password": password,
        "rtsp_port": rtsp_port,
        "rtsp_path": rtsp_path,
        "rtsp_sub_path": rtsp_sub_path,
        "device_class": device_class,
        "sn_code": sn_code,
        "pkdk": pkdk,
    }
    if connection_type == "usb":
        new_entry["device_index"] = device_index
        new_entry["device_model"] = device_model
        new_entry["product_version"] = product_version

    # 更新或追加
    found = False
    for i, cam in enumerate(cameras):
        if cam.get("name") == name:
            cameras[i] = new_entry
            found = True
            break
    if not found:
        cameras.append(new_entry)

    data["cameras"] = cameras

    # 确保 auth 节存在
    if "auth" not in data:
        data["auth"] = {
            "cloud_url": "",
            "token_timeout": 300,
            "auth_timeout": 30,
            "auto_request_auth": True,
        }

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
                onvif_port=sd.web_port,     # 创维设备的 ONVIF 服务一般在 web 端口
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
    """通过 WS-Discovery 协议搜索 ONVIF 设备（占位，待集成）"""
    # 后续可集成 phase1/phase3 的 WS-Discovery 实现
    return SearchResult(
        success=False,
        error_message="WS-Discovery 暂未实现，请使用 sky_discovery 或 usb",
    )


def connect_device(
    camera_name: str,
    password: Optional[str] = None,
    ip: Optional[str] = None,
    port: Optional[int] = None,
    rtsp_port: Optional[int] = None,
    rtsp_path: str = "/stream1",
    username: str = "admin",
) -> ConnectResult:
    """
    设备连接。流程：

    1. 如果 config.yaml 有缓存凭据 → 自动使用缓存密码连接
    2. 如果传入了 password → 使用提供的密码连接
    3. 如果无密码 → 先尝试无密码拉流探测：
       a. 成功 → 免密设备，直接连接
       b. 返回 401/认证失败 → 返回 status="needs_password"，Agent 提示用户输入密码
    4. Agent 获取到密码后再次调用 connect_device(camera_name, password=xxx)

    安全约束: 显式提示（需要密码时提示用户输入）

    Args:
        camera_name: 摄像头名称（匹配 config.yaml 注册名或发现后的临时名）
        password:    用户提供的密码（可选；有缓存时自动使用）
        ip:          设备 IP（新发现的设备，未注册到 config.yaml 时需传入）
        port:        ONVIF 端口（默认 80）
        rtsp_port:   RTSP 端口（默认 554）
        rtsp_path:   RTSP 路径（默认 /stream1）
        username:    登录用户名（默认 admin）

    Returns:
        ConnectResult:
            - success: 连接是否成功
            - auth_method: "password" 或 "direct"
            - status: "connected" / "needs_password" / "failed"
            - needs_password: True 表示需要密码
            - error_message: 失败原因
    """
    # ── Step 1: 从 config.yaml 查找缓存配置 ──
    cached = _find_cached_camera(camera_name)

    # 确定连接参数（缓存优先，参数兜底）
    if cached and cached.ip:
        dev_ip = cached.ip
        dev_port = cached.port
        dev_rtsp_port = cached.rtsp_port
        dev_rtsp_path = cached.rtsp_path
        dev_username = cached.username or username
        dev_pwd = password or cached.password or ""
    elif ip:
        dev_ip = ip
        dev_port = port or 80
        dev_rtsp_port = rtsp_port or 554
        dev_rtsp_path = rtsp_path
        dev_username = username
        dev_pwd = password or ""
    else:
        return ConnectResult(
            success=False, status="failed",
            error_message=f"未找到设备 {camera_name} 的连接信息（config.yaml 中无记录且未提供 IP）",
        )

    # ── Step 2: 如果有密码（缓存或用户提供），直接尝试连接 ──
    if dev_pwd:
        result = _try_connect_with_password(
            camera_name, dev_ip, dev_port, dev_rtsp_port, dev_rtsp_path,
            dev_username, dev_pwd,
        )
        if result.success:
            return result
        # 密码认证失败
        return ConnectResult(
            success=False, status="failed",
            needs_password=True,
            error_message=f"密码认证失败: {result.error_message}，请确认密码后重试",
        )

    # ── Step 3: 无密码 → 先尝试免密拉流探测 ──
    access = _probe_stream_access(dev_ip, dev_rtsp_port, dev_rtsp_path)

    if access == "open":
        # 免密设备，直接连接
        _connected_devices[camera_name] = {
            "ip": dev_ip,
            "port": dev_port,
            "rtsp_port": dev_rtsp_port,
            "rtsp_path": dev_rtsp_path,
            "username": "",
            "password": "",
        }
        return ConnectResult(
            success=True,
            auth_method="direct",
            status="connected",
        )

    if access == "auth_required":
        # 需要密码 → 返回 needs_password，Agent 应提示用户输入
        return ConnectResult(
            success=False,
            status="needs_password",
            needs_password=True,
            error_message=f"设备 {camera_name}({dev_ip}) 需要密码才能访问，请输入密码",
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
    """
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
            "ip": ip, "port": onvif_port,
            "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
            "username": username, "password": password,
            "tcp_port": SK_TCP_PORT,
        }
        return ConnectResult(
            success=True, auth_method="password", status="connected",
        )

    # ── 尝试 2: ONVIF 连接 ──
    try:
        from onvif import ONVIFCamera
        cam = ONVIFCamera(host=ip, port=onvif_port, user=username, passwd=password)
        dev_svc = cam.create_devicemgmt_service()
        dev_svc.GetDeviceInformation()
        _connected_devices[camera_name] = {
            "ip": ip, "port": onvif_port,
            "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
            "username": username, "password": password,
            "onvif_camera": cam,
        }
        return ConnectResult(
            success=True, auth_method="password", status="connected",
        )
    except Exception as onvif_err:
        # ONVIF 失败，继续尝试 RTSP
        pass

    # ── 尝试 3: RTSP 带认证拉流 ──
    access = _probe_stream_access(ip, rtsp_port, rtsp_path, username, password)
    if access == "open":
        _connected_devices[camera_name] = {
            "ip": ip, "port": onvif_port,
            "rtsp_port": rtsp_port, "rtsp_path": rtsp_path,
            "username": username, "password": password,
        }
        return ConnectResult(
            success=True, auth_method="password", status="connected",
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
    """从 config.yaml 加载摄像头配置列表（内部辅助）"""
    import os
    import yaml

    # 查找 config.yaml：优先当前目录，其次 skill 根目录
    config_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml"),
        os.path.join(os.path.dirname(__file__), "..", "..", "confg.yaml"),
        "config.yaml",
    ]

    for path in config_paths:
        path = os.path.normpath(path)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                cameras_data = data.get("cameras", [])
                configs = []
                for entry in cameras_data:
                    cfg = CameraConfig(
                        name=entry.get("name", ""),
                        connection_type=entry.get("connection_type", "onvif"),
                        ip=entry.get("ip", ""),
                        port=int(entry.get("port", 80)),
                        username=entry.get("username", "admin"),
                        password=entry.get("password", ""),
                        rtsp_port=int(entry.get("rtsp_port", 554)),
                        rtsp_path=entry.get("rtsp_path", "/stream1"),
                        rtsp_sub_path=entry.get("rtsp_sub_path", "/stream2"),
                        device_class=entry.get("device_class", ""),
                        sn_code=entry.get("sn_code", ""),
                        pkdk=entry.get("pkdk", ""),
                        device_index=int(entry.get("device_index", 0)),
                        device_model=entry.get("device_model", ""),
                        product_version=entry.get("product_version", ""),
                    )
                    configs.append(cfg)
                return configs
            except Exception:
                continue
    return []


def poll_auth_status(
    camera_name: str,
) -> AuthStatusResult:
    """
    轮询远程授权服务器，检查 Agent 是否已被授权连接该摄像头。

    在 connect_device() 返回 status="pending_auth" 后，Agent 应反复调用此函数
    （建议间隔 5 秒，最长等待 120 秒），直到：
    - status == "authorized" → Agent 提示用户输入密码，再调用 connect_device(camera_name, password)
    - status == "rejected"   → 用户在 APP 端拒绝了授权，流程终止
    - status == "error"      → 服务器异常，流程终止

    安全约束: 无特殊约束

    Args:
        camera_name: 正在等待授权的摄像头名称

    Returns:
        AuthStatusResult:
            - status: 授权状态 (AuthStatus.PENDING / AUTHORIZED / REJECTED / ERROR)
            - camera_name: 摄像头名称
            - message: 状态说明
    """
    raise NotImplementedError("poll_auth_status 待实现")


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


def query_device_model(
    camera_name: str,
) -> DeviceInfoResult:
    """
    查询设备型号、固件版本、在线状态、网络信息。

    通过 ONVIF GetDeviceInformation 获取设备详细信息，
    包括厂商、型号、固件版本、序列号、硬件 ID、网络状态等。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        DeviceInfoResult:
            - success: 是否查询成功
            - info: DeviceInfo 对象（含 manufacturer/model/firmware/serial/hardware_id/ip/mac/online）
            - error_message: 失败原因
    """
    raise NotImplementedError("query_device_model 待实现")


def update_firmware(
    camera_name: str,
    firmware_path: Optional[str] = None,
) -> FirmwareResult:
    """
    固件更新与升级。

    通过 ONVIF Device Service 或创维私有协议推送固件到设备。
    更新前校验：固件版本、设备状态、电量/网络稳定性。
    更新过程中设备可能重启，期间不可操作。

    安全约束: 显式授权 + 显式提示 + 代码校验

    Args:
        camera_name:   摄像头名称（自动填充）
        firmware_path: 固件文件路径（可选，None 则从云端获取最新固件）

    Returns:
        FirmwareResult:
            - success: 更新是否成功
            - old_version: 更新前的版本号
            - new_version: 更新后的版本号
            - error_message: 失败原因
    """
    raise NotImplementedError("update_firmware 待实现")


def system_maintenance(
    camera_name: str,
    action: MaintenanceAction = MaintenanceAction.REBOOT,
) -> MaintenanceResult:
    """
    系统维护（重启设备、云台矫正、恢复出厂设置）。

    - reboot:         重启设备（ONVIF SystemReboot），设备将在约 30s 后重新上线
    - calibrate_ptz:  云台矫正（回到 Home 位并重新标定零位）
    - factory_reset:  恢复出厂设置（危险操作，将清除所有配置）

    安全约束: 显式授权 + 显式提示 + 代码校验

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      维护操作 (MaintenanceAction)

    Returns:
        MaintenanceResult:
            - success: 操作是否成功
            - action_performed: 执行的维护操作名称
            - error_message: 失败原因
    """
    raise NotImplementedError("system_maintenance 待实现")
