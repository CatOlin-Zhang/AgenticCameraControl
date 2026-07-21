"""
Toolkit 5: 设备管理与维护

工具清单：
  - get_registered_cameras  从 config.yaml 加载已注册摄像头配置
  - register_camera         将摄像头信息写入 config.yaml（持久化凭据）
  - search_devices          搜索局域网或云端可用摄像头
  - connect_device          设备连接（自动读取 config.yaml 凭据；无凭据时返回 pending_auth）
  - poll_auth_status        轮询远程授权服务器，检查 Agent 授权状态
  - disconnect_device       断开摄像头连接并释放资源
  - query_device_model      查询设备型号/固件/状态/网络信息
  - update_firmware         固件更新与升级
  - system_maintenance      系统维护（重启/云台矫正）
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ──────────────────────────────────────────────
#  枚举类型
# ──────────────────────────────────────────────

class DiscoveryMethod(str, Enum):
    WS_DISCOVERY = "ws_discovery"    # ONVIF WS-Discovery 局域网发现
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
    status: str = "connected"                  # 连接状态: "connected" | "pending_auth" | "failed"
    error_message: str = ""                    # 失败原因


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
    raise NotImplementedError("get_registered_cameras 待实现")


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
    raise NotImplementedError("register_camera 待实现")


def search_devices(
    method: DiscoveryMethod = DiscoveryMethod.WS_DISCOVERY,
    timeout: float = 15.0,
) -> SearchResult:
    """
    搜索局域网或云端可用摄像头设备。

    WS-Discovery 模式：发送 Probe 多播 + 被动监听 Hello 心跳包，
    从 ProbeMatch 中提取 IP、ONVIF 端口（XAddrs 解析）、SN、型号等信息。
    USB 模式：扫描设备索引 0–9。

    安全约束: 无特殊约束

    Args:
        method:  发现方式 (DiscoveryMethod.WS_DISCOVERY / DiscoveryMethod.USB)
        timeout: 超时时间（秒，默认 15）

    Returns:
        SearchResult:
            - success: 搜索是否成功
            - devices: 发现的设备列表（每个设备含 IP/端口/SN/型号/媒体设置）
            - error_message: 失败原因
    """
    raise NotImplementedError("search_devices 待实现")


def connect_device(
    camera_name: str,
    password: Optional[str] = None,
) -> ConnectResult:
    """
    设备连接。具体连接流程由工具内部实现，Agent 的职责是调用本函数、
    轮询授权状态、提示用户输入密码。

    三种场景：
    1. config.yaml 已缓存凭据 → 工具自动读取 username/password → 直接连接
       返回 ConnectResult(success=True, status="connected", auth_method="password")
    2. direct_connect 设备 → 无需凭据 → 直接连接
       返回 ConnectResult(success=True, status="connected", auth_method="direct")
    3. password_required 且无缓存凭据 → 工具向远程授权服务器发起请求
       返回 ConnectResult(success=False, status="pending_auth")
       → Agent 调用 poll_auth_status() 轮询授权状态
       → 授权后 Agent 提示用户输入密码
       → Agent 再次调用 connect_device(camera_name, password=user_input)
       → 连接成功后 Agent 调用 register_camera() 保存凭据

    安全约束: 显式授权（password_required 需远程授权 + 用户密码输入）

    Args:
        camera_name: 摄像头名称（匹配 config.yaml 注册名或发现后的临时名）
        password:    用户提供的密码（可选；config.yaml 有缓存时自动使用，无需传入）

    Returns:
        ConnectResult:
            - success: 连接是否成功
            - auth_method: 使用的认证方式 ("password" / "direct")
            - status: 连接状态 ("connected" / "pending_auth" / "failed")
            - error_message: 失败原因
    """
    raise NotImplementedError("connect_device 待实现")


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
    raise NotImplementedError("disconnect_device 待实现")


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
