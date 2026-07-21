"""
XPAI Camera Control — Auth 鉴权模块

提供云端授权、Token 管理和会话管理功能：
  - token_manager  — Token 生成/校验/生命周期管理
  - cloud_client   — 智慧云 API 客户端
  - session        — 会话管理（心跳续订/自动释放/FIFO队列）
"""

# ── token_manager ──
from .token_manager import (
    parse_token,
    validate_token,
    destroy_token,
    is_token_expired,
    has_permission,
    AuthToken,
    TokenValidationResult,
    TokenPermission,
    TokenStatus,
)

# ── cloud_client ──
from .cloud_client import (
    request_authorization,
    notify_connection,
    check_internet_available,
    AuthRequestResult,
    NotifyResult,
    AuthRequestStatus,
    DeviceType,
)

# ── session ──
from .session import (
    create_session,
    send_heartbeat,
    release_session,
    get_active_sessions,
    get_fifo_queue,
    auto_release_check,
    Session,
    HeartbeatResult,
    ReleaseResult,
    SessionRole,
    SessionStatus,
)

__all__ = [
    # token_manager
    "parse_token",
    "validate_token",
    "destroy_token",
    "is_token_expired",
    "has_permission",
    "AuthToken",
    "TokenValidationResult",
    "TokenPermission",
    "TokenStatus",
    # cloud_client
    "request_authorization",
    "notify_connection",
    "check_internet_available",
    "AuthRequestResult",
    "NotifyResult",
    "AuthRequestStatus",
    "DeviceType",
    # session
    "create_session",
    "send_heartbeat",
    "release_session",
    "get_active_sessions",
    "get_fifo_queue",
    "auto_release_check",
    "Session",
    "HeartbeatResult",
    "ReleaseResult",
    "SessionRole",
    "SessionStatus",
]
