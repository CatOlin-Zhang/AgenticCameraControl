"""
Toolkit 2: 云台与巡航

工具清单：
  - control_ptz          步进式控制云台方向
  - control_lens_zoom    控制镜头自动变焦
  - get_ptz_parameters   获取云台位移与角度参数
  - save_ptz_preset      保存当前角度为预置点
  - calibrate_ptz        执行云台物理校准
  - start_patrol_cruise  按预设路径巡航

前提条件: 仅 ONVIF 连接支持 PTZ，USB 和 RTSP-only 摄像头不支持。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class PTZDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    # 中文别名在代码层映射，不在枚举中定义


class ZoomAction(str, Enum):
    IN = "in"
    OUT = "out"


@dataclass
class PTZMoveResult:
    """云台移动操作返回结果"""
    success: bool                                # 是否成功
    current_pan: float = 0.0                     # 当前水平角度 (度)
    current_tilt: float = 0.0                    # 当前垂直角度 (度)
    current_zoom: float = 0.0                    # 当前变焦倍数
    error_message: str = ""                      # 失败原因


@dataclass
class PTZParameters:
    """云台参数"""
    pan: float = 0.0                             # 水平位置 / 角度
    tilt: float = 0.0                            # 垂直位置 / 角度
    zoom: float = 0.0                            # 变焦位置
    pan_speed: float = 0.0                       # 当前水平速度
    tilt_speed: float = 0.0                      # 当前垂直速度
    is_moving: bool = False                      # 是否正在移动


@dataclass
class PTZPresetResult:
    """预置点操作返回结果"""
    success: bool                                # 是否成功
    preset_name: str = ""                        # 预置点名称
    preset_token: str = ""                       # 预置点 token
    error_message: str = ""                      # 失败原因


@dataclass
class CalibrateResult:
    """云台校准返回结果"""
    success: bool                                # 校准是否完成
    error_message: str = ""                      # 失败原因


@dataclass
class CruiseResult:
    """巡航操作返回结果"""
    success: bool                                # 巡航是否启动
    cruise_name: str = ""                        # 巡航路径名称
    preset_count: int = 0                        # 巡航经过的预置点数量
    error_message: str = ""                      # 失败原因


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def control_ptz(
    camera_name: str,
    direction: PTZDirection,
    speed: float = 0.5,
) -> PTZMoveResult:
    """
    步进式控制云台方向移动。

    向指定方向移动云台，移动 1 秒后自动停止（可通过 speed 控制位移量）。
    方向支持英文 (up/down/left/right) 和中文 (上/下/左/右)。
    speed 取值范围 0.1–1.0，默认 0.5。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        direction:   移动方向 (PTZDirection)
        speed:       速度系数 0.1–1.0（默认 0.5）

    Returns:
        PTZMoveResult:
            - success: 是否成功
            - current_pan / current_tilt / current_zoom: 移动后的绝对位置
            - error_message: 失败原因
    """
    raise NotImplementedError("control_ptz 待实现")


def control_lens_zoom(
    camera_name: str,
    action: ZoomAction,
    speed: float = 0.5,
) -> PTZMoveResult:
    """
    控制镜头自动变焦。

    action=IN 放大，action=OUT 缩小。变焦 1.5 秒后自动停止。
    speed 取值范围 0.1–1.0。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      ZoomAction.IN 放大 / ZoomAction.OUT 缩小
        speed:       变焦速度 0.1–1.0（默认 0.5）

    Returns:
        PTZMoveResult:
            - success: 是否成功
            - current_zoom: 变焦后的位置值
            - error_message: 失败原因
    """
    raise NotImplementedError("control_lens_zoom 待实现")


def get_ptz_parameters(
    camera_name: str,
) -> PTZParameters:
    """
    获取并返回当前云台的位移数据和角度参数。

    通过 ONVIF PTZ Service GetStatus 获取当前云台的 Pan/Tilt/Zoom 位置值、
    当前速度以及是否正在移动。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        PTZParameters:
            - pan / tilt / zoom: 当前位置值
            - pan_speed / tilt_speed: 当前速度
            - is_moving: 是否正在移动
    """
    raise NotImplementedError("get_ptz_parameters 待实现")


def save_ptz_preset(
    camera_name: str,
    preset_name: str,
) -> PTZPresetResult:
    """
    将当前云台位置保存为收藏预置点。

    通过 ONVIF PTZ Service SetPreset 保存当前位置到指定名称的预置点。
    如果同名预置点已存在，则覆盖。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）
        preset_name: 预置点名称（如 "大门"、"客厅"）

    Returns:
        PTZPresetResult:
            - success: 是否成功
            - preset_name: 保存的预置点名称
            - preset_token: 预置点 token（用于后续 GotoPreset）
            - error_message: 失败原因
    """
    raise NotImplementedError("save_ptz_preset 待实现")


def go_to_preset(
    camera_name: str,
    preset_name: str,
    speed: float = 1.0,
) -> PTZMoveResult:
    """
    云台移动到指定预置点。

    通过 ONVIF PTZ Service GotoPreset 将云台移动到之前保存的预置点位置。
    speed 控制移动速度，取值范围 0.1–1.0，默认 1.0（全速）。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        preset_name: 预置点名称（如 "大门"、"客厅"）
        speed:       移动速度 0.1–1.0（默认 1.0）

    Returns:
        PTZMoveResult:
            - success: 是否移动成功
            - current_pan / current_tilt / current_zoom: 移动后的绝对位置
            - error_message: 失败原因（如预置点不存在）
    """
    raise NotImplementedError("go_to_preset 待实现")


def calibrate_ptz(
    camera_name: str,
) -> CalibrateResult:
    """
    执行云台物理校准。

    云台回到初始位置（Home）并重新标定零位。
    校准过程中云台会进行物理运动，耗时约 10–30 秒。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        CalibrateResult:
            - success: 校准是否完成
            - error_message: 失败原因
    """
    raise NotImplementedError("calibrate_ptz 待实现")


def start_patrol_cruise(
    camera_name: str,
    cruise_name: Optional[str] = None,
) -> CruiseResult:
    """
    按预设路径开启云台巡航。

    启动云台按预置点路径自动巡航。如果未指定 cruise_name，
    则使用默认巡航路径（所有已保存的预置点按顺序循环）。
    可通过 ONVIF PTZ Tour 或循环 GotoPreset + 延时实现。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        cruise_name: 巡航路径名称（可选，默认使用预置点顺序）

    Returns:
        CruiseResult:
            - success: 巡航是否启动
            - cruise_name: 巡航路径名称
            - preset_count: 经过的预置点数量
            - error_message: 失败原因
    """
    raise NotImplementedError("start_patrol_cruise 待实现")
