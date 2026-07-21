"""
Toolkit 3: 识别与追踪算法

工具清单：
  - track_vehicles          车辆识别与追踪
  - track_human_shapes      人形识别与追踪
  - monitor_zone_entry      区域进入/离开识别
  - stop_tracking_service   停止当前所有追踪服务
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class TrackingAction(str, Enum):
    START = "start"
    STOP = "stop"


class ZoneAction(str, Enum):
    START = "start"
    STOP = "stop"


@dataclass
class TrackingResult:
    """追踪操作返回结果"""
    success: bool                                # 操作是否成功
    is_tracking: bool = False                    # 当前是否在追踪
    algorithm: str = ""                          # 使用的算法名称
    error_message: str = ""                      # 失败原因


@dataclass
class ZoneMonitorResult:
    """区域监控操作返回结果"""
    success: bool                                # 操作是否成功
    is_monitoring: bool = False                  # 是否在监控中
    zone_triggered: bool = False                 # 是否有人进入/离开
    trigger_type: str = ""                       # 触发类型 ("entry" / "exit" / "")
    error_message: str = ""                      # 失败原因


@dataclass
class StopTrackingResult:
    """停止追踪服务返回结果"""
    success: bool                                # 是否全部停止成功
    stopped_services: List[str]                  # 已停止的服务列表
    error_message: str = ""                      # 失败原因


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def track_vehicles(
    camera_name: str,
    action: TrackingAction = TrackingAction.START,
) -> TrackingResult:
    """
    开启或关闭车辆识别与追踪算法。

    启动后，摄像头将对画面中的车辆进行实时识别和追踪。
    可通过 ONVIF Analytics Service 或创维私有协议实现。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      TrackingAction.START 开启 / TrackingAction.STOP 关闭

    Returns:
        TrackingResult:
            - success: 操作是否成功
            - is_tracking: 当前是否在追踪
            - algorithm: 使用的算法名称（如 "vehicle_detection_v2"）
            - error_message: 失败原因
    """
    raise NotImplementedError("track_vehicles 待实现")


def track_human_shapes(
    camera_name: str,
    action: TrackingAction = TrackingAction.START,
) -> TrackingResult:
    """
    开启或关闭人形识别与追踪算法。

    启动后，摄像头将对画面中的人形目标进行实时识别和自动追踪。
    追踪过程中云台会自动跟随目标移动。

    安全约束: 显式提示 + 代码校验（校验设备是否支持该算法）

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      TrackingAction.START 开启 / TrackingAction.STOP 关闭

    Returns:
        TrackingResult:
            - success: 操作是否成功
            - is_tracking: 当前是否在追踪
            - algorithm: 使用的算法名称（如 "human_tracking_v3"）
            - error_message: 失败原因（如设备不支持该算法）
    """
    raise NotImplementedError("track_human_shapes 待实现")


def monitor_zone_entry(
    camera_name: str,
    action: ZoneAction = ZoneAction.START,
    zone: Optional[Dict[str, List[Tuple[int, int]]]] = None,
) -> ZoneMonitorResult:
    """
    开启或关闭区域进入/离开识别。

    在画面中划定一个或多个区域，当有人进入或离开该区域时触发告警。
    zone 参数为区域顶点坐标列表，格式: {"zone_name": [(x1,y1), (x2,y2), ...]}
    如果 zone 为空，则使用设备默认的区域配置。

    安全约束: 显式提示

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      ZoneAction.START 开启 / ZoneAction.STOP 关闭
        zone:        区域定义字典，key 为区域名称，value 为顶点坐标列表
                     示例: {"大门": [(100,200), (300,200), (300,400), (100,400)]}

    Returns:
        ZoneMonitorResult:
            - success: 操作是否成功
            - is_monitoring: 是否在监控中
            - zone_triggered: 是否有人进入/离开（仅查询时有效）
            - trigger_type: 触发类型 "entry" / "exit" / ""
            - error_message: 失败原因
    """
    raise NotImplementedError("monitor_zone_entry 待实现")


def stop_tracking_service(
    camera_name: str,
) -> StopTrackingResult:
    """
    停止当前所有运行中的追踪算法服务。

    一次性停止车辆追踪、人形追踪、区域监控等所有正在运行的追踪服务。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称（自动填充）

    Returns:
        StopTrackingResult:
            - success: 是否全部停止成功
            - stopped_services: 已停止的服务名称列表（如 ["vehicle_tracking", "human_tracking"]）
            - error_message: 失败原因
    """
    raise NotImplementedError("stop_tracking_service 待实现")
