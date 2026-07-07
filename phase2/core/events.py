"""
phase2 - 事件系统模块 - IPC 摄像头事件的订阅/发布接口
（与 phase1 功能一致，独立模块）
"""
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Any


class EventType(Enum):
    """IPC 常见事件类型"""
    MOTION_DETECTION = "motion_detection"
    TAMPER_ALARM = "tamper_alarm"
    LINE_CROSSING = "line_crossing"
    REGION_INTRUSION = "region_intrusion"
    IO_ALARM = "io_alarm"
    DEVICE_ONLINE = "device_online"
    DEVICE_OFFLINE = "device_offline"
    VIDEO_LOSS = "video_loss"
    AUTH_SUCCESS = "auth_success"          # Phase2 新增：SN 认证成功
    AUTH_FAILED = "auth_failed"            # Phase2 新增：SN 认证失败
    CUSTOM = "custom"


@dataclass
class CameraEvent:
    """摄像头事件数据结构"""
    event_type: EventType
    camera_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    severity: str = "info"
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"[{self.severity.upper()}] "
            f"[{self.camera_name}] "
            f"{self.event_type.value}: {self.message}"
        )


EventCallback = Callable[[CameraEvent], None]


class EventBus:
    """事件总线：发布/订阅模式。"""

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

    def subscribe_all(self, callback: EventCallback) -> None:
        with self._lock:
            self._global_listeners.append(callback)

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

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

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
    """占位实现"""

    def _poll_events(self) -> None:
        time.sleep(5)
