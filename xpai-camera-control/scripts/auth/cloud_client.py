"""
Auth: Cloud Client — 智慧云 API 客户端

负责与创维智慧云（Skyworth Smart Cloud）的通信：
  - 向云端发起连接 IPC 的授权请求
  - 处理云端响应（Token / 拒绝 / 超时）
  - 接收云端推送的 Token
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from .token_manager import AuthToken


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class AuthRequestStatus(str, Enum):
    PENDING = "pending"              # 等待用户响应
    APPROVED = "approved"            # 用户同意
    REJECTED = "rejected"            # 用户拒绝
    TIMEOUT = "timeout"              # 超时未响应（视为拒绝）
    UNAUTHORIZED = "unauthorized"    # Claw 无权限
    DEVICE_UNAVAILABLE = "unavailable"  # 设备不可用


class DeviceType(str, Enum):
    PASSWORD_REQUIRED = "password_required"  # 密码登录类
    DIRECT_CONNECT = "direct_connect"        # 直连类


@dataclass
class AuthRequestResult:
    """授权请求返回结果"""
    status: AuthRequestStatus                  # 请求状态
    token: Optional[AuthToken] = None          # 授权通过时的 Token（密码登录类）
    message: str = ""                          # 云端返回的消息
    request_id: str = ""                       # 请求 ID（用于后续查询）


@dataclass
class NotifyResult:
    """通知请求返回结果（直连类设备使用）"""
    success: bool                              # 通知是否发送成功
    message: str = ""                          # 云端返回的消息


# ──────────────────────────────────────────────
#  云端通信函数
# ──────────────────────────────────────────────

def request_authorization(
    cloud_url: str,
    claw_id: str,
    ipc_sn: str,
    ipc_ip: str,
    ipc_model: str = "",
    timeout: int = 30,
) -> AuthRequestResult:
    """
    向智慧云服务器发起连接 IPC 的授权请求（密码登录类设备）。

    流程：
    1. Claw 将发现的设备信息（SN/IP/型号）打包发送到云端
    2. 云端向用户 APP 推送授权弹窗（有时限）
    3. 云端校验 Claw 权限 + 设备可用性
    4. 用户同意后，云端生成短期 Token 并返回

    此函数为同步阻塞调用，等待云端返回最终结果（同意/拒绝/超时）。

    Args:
        cloud_url:  智慧云 API 端点（如 https://smart-cloud.skyworth.com/api/camera/auth）
        claw_id:    Claw Agent 身份标识
        ipc_sn:     设备序列号（SN）
        ipc_ip:     设备 IP 地址
        ipc_model:  设备型号（可选）
        timeout:    请求超时时间（秒，默认 30）

    Returns:
        AuthRequestResult:
            - status: APPROVED（同意）/ REJECTED（拒绝）/ TIMEOUT（超时）/ UNAUTHORIZED / DEVICE_UNAVAILABLE
            - token: 授权通过时的 AuthToken 对象（仅 APPROVED 时有效）
            - message: 云端返回的说明消息
            - request_id: 请求 ID
    """
    raise NotImplementedError("request_authorization 待实现")


def notify_connection(
    cloud_url: str,
    claw_id: str,
    ipc_sn: str,
    ipc_ip: str,
    timeout: int = 30,
) -> NotifyResult:
    """
    向智慧云服务器发送连接通知（直连类设备使用）。

    仅触发云端向用户 APP 推送"该 IPC 被其他应用使用"的提醒，
    不等待用户响应，不影响 Claw 直接连接 IPC。

    Args:
        cloud_url: 智慧云 API 端点
        claw_id:   Claw Agent 身份标识
        ipc_sn:    设备序列号
        ipc_ip:    设备 IP 地址
        timeout:   请求超时时间（秒，默认 30）

    Returns:
        NotifyResult:
            - success: 通知是否发送成功
            - message: 云端返回的消息
    """
    raise NotImplementedError("notify_connection 待实现")


def check_internet_available() -> bool:
    """
    检测当前网络是否可以访问云端。

    用于 WiFi 异常处理：当 WiFi 无法上网时，
    密码登录类 IPC 将拒绝 Claw 的连接请求。

    Returns:
        bool: True 表示可以访问云端
    """
    raise NotImplementedError("check_internet_available 待实现")
