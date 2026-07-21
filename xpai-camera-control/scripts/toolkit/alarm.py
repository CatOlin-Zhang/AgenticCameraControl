"""
Toolkit 6: 报警设置

工具清单：
  - configure_alarm_settings  报警声音与触发频率配置
  - configure_alarm_push      报警推送类型与时间段配置
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


# ──────────────────────────────────────────────
#  枚举类型
# ──────────────────────────────────────────────

class PushType(str, Enum):
    APP = "app"                  # APP 内推送
    EMAIL = "email"              # 邮件推送
    BOTH = "both"                # 同时推送


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class AlarmSettingsResult:
    """报警设置返回结果"""
    success: bool
    sound_enabled: bool = False                  # 报警声音是否开启
    trigger_frequency: str = ""                  # 触发频率描述（如 "每30秒最多1次"）
    sensitivity: int = 0                         # 灵敏度等级 (0–100)
    error_message: str = ""


@dataclass
class AlarmPushResult:
    """报警推送设置返回结果"""
    success: bool
    push_type: PushType = PushType.APP           # 推送类型
    time_range: str = ""                         # 生效时间段（如 "08:00-22:00"）
    enabled: bool = False                        # 是否启用
    error_message: str = ""


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def configure_alarm_settings(
    camera_name: str,
    sound_enabled: Optional[bool] = None,
    trigger_frequency: Optional[str] = None,
    sensitivity: Optional[int] = None,
) -> AlarmSettingsResult:
    """
    配置报警声音与触发频率。

    控制摄像头触发报警时是否播放声音、报警的触发频率限制和灵敏度。
    仅传入需要修改的参数，未传入的参数保持不变。

    通过 ONVIF Event Service 或创维私有协议实现。

    安全约束: 显式授权 + 显式提示 + 代码校验

    Args:
        camera_name:       摄像头名称（自动填充）
        sound_enabled:     是否开启报警声音（None 表示不修改）
        trigger_frequency: 触发频率描述字符串，如 "30s" / "1min" / "5min"
                           （None 表示不修改）
        sensitivity:       灵敏度等级 0–100（None 表示不修改）

    Returns:
        AlarmSettingsResult:
            - success: 操作是否成功
            - sound_enabled: 当前声音状态
            - trigger_frequency: 当前触发频率
            - sensitivity: 当前灵敏度
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_alarm_settings 待实现")


def configure_alarm_push(
    camera_name: str,
    push_type: Optional[PushType] = None,
    time_range: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> AlarmPushResult:
    """
    配置报警推送类型与时间段。

    控制报警触发时通过何种方式推送通知（APP推送/邮件/两者兼有），
    以及推送的生效时间段。

    time_range 格式: "HH:MM-HH:MM"，如 "08:00-22:00" 表示早8点到晚10点间推送。
    支持多个时间段用逗号分隔: "08:00-12:00,14:00-22:00"。

    安全约束: 显式授权 + 显式提示 + 代码校验

    Args:
        camera_name: 摄像头名称（自动填充）
        push_type:   推送类型 (PushType.APP / PushType.EMAIL / PushType.BOTH)
                     （None 表示不修改）
        time_range:  生效时间段字符串（None 表示不修改）
        enabled:     是否启用推送（None 表示不修改）

    Returns:
        AlarmPushResult:
            - success: 操作是否成功
            - push_type: 当前推送类型
            - time_range: 当前时间段
            - enabled: 是否启用
            - error_message: 失败原因
    """
    raise NotImplementedError("configure_alarm_push 待实现")
