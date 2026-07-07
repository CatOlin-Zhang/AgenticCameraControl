"""
事件系统模块 - IPC 摄像头事件的订阅/发布接口

协议类型: 局域网 ONVIF 事件订阅

预留支持的事件类型：
- 移动侦测 (Motion Detection)
- 遮挡报警 (Tamper Alarm)
- 越界检测 (Line Crossing)
- 区域入侵 (Region Intrusion)
- IO 报警 (IO Alarm)
- 设备上下线 (Device Online/Offline)
"""
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Any


# ──────────────────────────────────────────────
#  事件类型枚举
# ──────────────────────────────────────────────
class EventType(Enum):
    """IPC 常见事件类型"""
    MOTION_DETECTION = "motion_detection"       # 移动侦测
    TAMPER_ALARM = "tamper_alarm"               # 遮挡/防拆报警
    LINE_CROSSING = "line_crossing"             # 越界检测
    REGION_INTRUSION = "region_intrusion"       # 区域入侵
    IO_ALARM = "io_alarm"                       # IO 报警
    DEVICE_ONLINE = "device_online"             # 设备上线
    DEVICE_OFFLINE = "device_offline"           # 设备离线
    VIDEO_LOSS = "video_loss"                   # 视频丢失
    CUSTOM = "custom"                           # 自定义事件


# ──────────────────────────────────────────────
#  事件数据类
# ──────────────────────────────────────────────
@dataclass
class CameraEvent:
    """摄像头事件数据结构"""
    event_type: EventType                        # 事件类型
    camera_name: str                             # 触发事件的摄像头名称
    timestamp: datetime = field(default_factory=datetime.now)  # 事件时间戳
    severity: str = "info"                       # 严重级别: info / warning / critical
    message: str = ""                            # 事件描述信息
    metadata: Dict[str, Any] = field(default_factory=dict)  # 附加元数据

    def __str__(self) -> str:
        return (
            f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"[{self.severity.upper()}] "
            f"[{self.camera_name}] "
            f"{self.event_type.value}: {self.message}"
        )


# 事件回调函数类型：接收一个 CameraEvent 参数
EventCallback = Callable[[CameraEvent], None]


# ──────────────────────────────────────────────
#  事件总线 - 发布/订阅模式
# ──────────────────────────────────────────────
class EventBus:
    """
    事件总线：负责事件的发布与订阅。
    支持按事件类型订阅，也支持全局监听。
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[EventCallback]] = {}
        self._global_listeners: List[EventCallback] = []
        self._lock = threading.Lock()
        self._event_history: List[CameraEvent] = []
        self._max_history: int = 1000

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)
        print(f"[EventBus] 已订阅事件: {event_type.value}")

    def subscribe_all(self, callback: EventCallback) -> None:
        with self._lock:
            self._global_listeners.append(callback)
        print("[EventBus] 已注册全局事件监听器")

    def unsubscribe(self, event_type: EventType, callback: EventCallback) -> None:
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(callback)
                except ValueError:
                    pass

    def publish(self, event: CameraEvent) -> None:
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]

        callbacks = []
        with self._lock:
            if event.event_type in self._subscribers:
                callbacks.extend(self._subscribers[event.event_type])
            callbacks.extend(self._global_listeners)

        for cb in callbacks:
            try:
                cb(event)
            except Exception as e:
                print(f"[EventBus] 回调执行出错: {e}")

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        camera_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[CameraEvent]:
        with self._lock:
            events = list(self._event_history)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if camera_name:
            events = [e for e in events if e.camera_name == camera_name]
        return events[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._event_history.clear()


# ──────────────────────────────────────────────
#  ONVIF 事件监听器（预留实现）
# ──────────────────────────────────────────────
class OnvifEventListener(ABC):
    """ONVIF 事件监听器抽象基类。"""

    def __init__(self, camera_name: str, event_bus: EventBus):
        self.camera_name = camera_name
        self.event_bus = event_bus
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None

    @abstractmethod
    def _poll_events(self) -> None:
        pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"EventListener-{self.camera_name}",
            daemon=True,
        )
        self._thread.start()
        print(f"[EventListener] {self.camera_name} 事件监听已启动")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        print(f"[EventListener] {self.camera_name} 事件监听已停止")

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._poll_events()
            except Exception as e:
                print(f"[EventListener] {self.camera_name} 轮询异常: {e}")
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.DEVICE_OFFLINE,
                    camera_name=self.camera_name,
                    severity="warning",
                    message=f"事件轮询异常: {e}",
                ))
            time.sleep(1)


class StubOnvifEventListener(OnvifEventListener):
    """占位实现 - 不做任何实际操作，仅用于开发阶段"""

    def _poll_events(self) -> None:
        time.sleep(5)
