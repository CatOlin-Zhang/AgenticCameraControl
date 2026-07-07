"""
摄像头管理模块 - 支持 USB(UVC) 和 ONVIF/RTSP(局域网) 双模式

协议类型:
  - USB: 本地 UVC 设备，通过 OpenCV VideoCapture 直接读取
  - ONVIF/RTSP: 局域网网络摄像头，通过 RTSP 协议获取视频流

功能：
  - 统一接口：无论哪种连接方式，提供一致的 API
  - RTSP-only 降级：ONVIF 不可用时自动退化为 RTSP 直连
  - 多摄像头管理（可扩展）
  - PTZ 控制 / 事件监听（预留）
"""
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import cv2
import numpy as np

from core.config import CameraConfig, ConnectionType
from core.events import EventBus, CameraEvent, EventType, StubOnvifEventListener


# ──────────────────────────────────────────────
#  摄像头状态
# ──────────────────────────────────────────────
@dataclass
class CameraStatus:
    """摄像头实时状态信息"""
    name: str
    connection_type: str = "usb"       # usb / onvif
    ip: str = ""
    device_index: int = -1
    is_connected: bool = False
    is_streaming: bool = False
    manufacturer: str = ""
    model: str = ""
    product_version: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    stream_source: str = ""            # USB 设备索引 或 RTSP URL
    frame_width: int = 0
    frame_height: int = 0
    fps: float = 0.0
    last_error: str = ""
    last_updated: Optional[datetime] = None


# ──────────────────────────────────────────────
#  USB 摄像头连接
# ──────────────────────────────────────────────
class USBCameraConnection:
    """USB(UVC) 摄像头连接管理。"""

    def __init__(self, config: CameraConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self._cap: Optional[cv2.VideoCapture] = None
        self._status = CameraStatus(
            name=config.name, connection_type="usb",
            device_index=config.device_index,
            model=config.device_model, product_version=config.product_version,
        )
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None

    def connect(self) -> bool:
        with self._lock:
            try:
                idx = self.config.device_index
                print(f"[USB:{self.config.name}] 正在打开 USB 摄像头 (设备索引: {idx}) ...")
                self._cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if not self._cap.isOpened():
                    self._cap = cv2.VideoCapture(idx)
                if not self._cap.isOpened():
                    raise RuntimeError(f"无法打开 USB 设备 (索引: {idx})")
                self._status.frame_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self._status.frame_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self._status.fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
                self._status.is_connected = True
                self._status.is_streaming = True
                self._status.stream_source = f"USB device [{idx}]"
                self._status.last_error = ""
                self._status.last_updated = datetime.now()
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.DEVICE_ONLINE, camera_name=self.config.name,
                    message=f"USB 摄像头已连接: {self.config.device_model} ({self._status.frame_width}x{self._status.frame_height}@{self._status.fps:.0f}fps)",
                ))
                print(f"[USB:{self.config.name}] 连接成功 - {self._status.frame_width}x{self._status.frame_height} @ {self._status.fps:.0f}fps")
                return True
            except Exception as e:
                self._status.is_connected = False
                self._status.last_error = f"USB 摄像头连接失败: {e}"
                self._status.last_updated = datetime.now()
                print(f"[USB:{self.config.name}] {self._status.last_error}")
                return False

    def disconnect(self) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None
            self._status.is_connected = False
            self._status.is_streaming = False
            self._status.last_updated = datetime.now()
            self.event_bus.publish(CameraEvent(
                event_type=EventType.DEVICE_OFFLINE, camera_name=self.config.name, message="USB 摄像头已断开",
            ))
            print(f"[USB:{self.config.name}] 已断开连接")

    def read_frame(self) -> Optional[np.ndarray]:
        if not self._is_ready():
            return None
        ret, frame = self._cap.read()
        if ret:
            self._frame = frame
            return frame
        return None

    def get_stream_url(self, sub_stream: bool = False) -> str:
        if not self._is_ready():
            raise ConnectionError(f"摄像头 {self.config.name} 未连接")
        return f"USB:{self.config.device_index} ({self._status.frame_width}x{self._status.frame_height})"

    def get_snapshot(self) -> Optional[np.ndarray]:
        return self.read_frame()

    def get_status(self) -> CameraStatus:
        if self._cap and self._cap.isOpened():
            self._status.frame_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._status.frame_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._status.last_updated = datetime.now()
        return self._status

    def _is_ready(self) -> bool:
        return self._cap is not None and self._cap.isOpened() and self._status.is_connected


# ──────────────────────────────────────────────
#  ONVIF/RTSP 局域网摄像头连接
# ──────────────────────────────────────────────
class ONVIFCameraConnection:
    """ONVIF/RTSP 局域网摄像头连接管理。"""

    def __init__(self, config: CameraConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self._camera = None  # ONVIFCamera（延迟导入）
        self._status = CameraStatus(
            name=config.name, connection_type="onvif", ip=config.ip,
            model=config.device_model, product_version=config.product_version,
        )
        self._lock = threading.Lock()
        self._event_listener = StubOnvifEventListener(config.name, event_bus)

    def connect(self) -> bool:
        with self._lock:
            try:
                from onvif import ONVIFCamera
                print(f"[ONVIF:{self.config.name}] 正在连接 {self.config.ip}:{self.config.port} ...")
                self._camera = ONVIFCamera(
                    host=self.config.ip, port=self.config.port,
                    user=self.config.username, passwd=self.config.password,
                )
                self._fetch_device_info()
                self._status.is_connected = True
                self._status.last_error = ""
                self._status.last_updated = datetime.now()
                self._event_listener.start()
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.DEVICE_ONLINE, camera_name=self.config.name,
                    message=f"ONVIF 摄像头已连接: {self._status.manufacturer} {self._status.model}",
                ))
                print(f"[ONVIF:{self.config.name}] 连接成功 - {self._status.manufacturer} {self._status.model}")
                return True
            except ImportError:
                print(f"[ONVIF:{self.config.name}] onvif-zeep 未安装，使用 RTSP-only 模式")
                return self._connect_rtsp_only()
            except Exception as e:
                print(f"[ONVIF:{self.config.name}] ONVIF 连接失败: {e}")
                print(f"[ONVIF:{self.config.name}] 尝试 RTSP-only 模式 ...")
                return self._connect_rtsp_only()

    def _connect_rtsp_only(self) -> bool:
        try:
            rtsp_url = self.config.get_rtsp_url()
            self._status.stream_source = rtsp_url
            print(f"[ONVIF:{self.config.name}] 验证 RTSP 流: {rtsp_url[:50]}...")
            cap = cv2.VideoCapture(rtsp_url)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    h, w = frame.shape[:2]
                    self._status.frame_width = w
                    self._status.frame_height = h
                    self._status.is_connected = True
                    self._status.is_streaming = True
                    self._status.last_error = ""
                    self._status.last_updated = datetime.now()
                    cap.release()
                    self.event_bus.publish(CameraEvent(
                        event_type=EventType.DEVICE_ONLINE, camera_name=self.config.name,
                        message=f"RTSP 摄像头已连接: {w}x{h}",
                    ))
                    print(f"[ONVIF:{self.config.name}] RTSP 连接成功 - {w}x{h}")
                    return True
                cap.release()
            self._status.is_connected = False
            self._status.last_error = "RTSP 流无法打开"
            self._status.last_updated = datetime.now()
            print(f"[ONVIF:{self.config.name}] RTSP 流验证失败")
            return False
        except Exception as e:
            self._status.last_error = f"RTSP 验证异常: {e}"
            print(f"[ONVIF:{self.config.name}] {self._status.last_error}")
            return False

    def disconnect(self) -> None:
        with self._lock:
            self._event_listener.stop()
            self._camera = None
            self._status.is_connected = False
            self._status.is_streaming = False
            self._status.last_updated = datetime.now()
            self.event_bus.publish(CameraEvent(
                event_type=EventType.DEVICE_OFFLINE, camera_name=self.config.name, message="ONVIF 摄像头已断开",
            ))
            print(f"[ONVIF:{self.config.name}] 已断开连接")

    def get_stream_url(self, sub_stream: bool = False) -> str:
        if self._camera:
            try:
                url = self._fetch_stream_via_onvif(sub_stream)
                if url:
                    self._status.stream_source = url
                    return url
            except Exception as e:
                print(f"[ONVIF:{self.config.name}] ONVIF 获取流地址失败: {e}")
        url = self.config.get_rtsp_url(sub_stream)
        self._status.stream_source = url
        return url

    def get_snapshot(self) -> Optional[np.ndarray]:
        try:
            url = self.get_stream_url()
            cap = cv2.VideoCapture(url)
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                if ret:
                    return frame
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] 抓帧失败: {e}")
        return None

    def get_status(self) -> CameraStatus:
        self._status.last_updated = datetime.now()
        return self._status

    def _fetch_device_info(self) -> None:
        if not self._camera:
            return
        try:
            devicemgmt = self._camera.create_devicemgmt_service()
            device_info = devicemgmt.GetDeviceInformation()
            self._status.manufacturer = str(getattr(device_info, 'Manufacturer', ''))
            self._status.model = str(getattr(device_info, 'Model', ''))
            self._status.firmware_version = str(getattr(device_info, 'FirmwareVersion', ''))
            self._status.serial_number = str(getattr(device_info, 'SerialNumber', ''))
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] 获取设备信息失败: {e}")

    def _fetch_stream_via_onvif(self, sub_stream: bool = False) -> Optional[str]:
        if not self._camera:
            return None
        try:
            media = self._camera.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                return None
            profile_idx = 1 if (sub_stream and len(profiles) > 1) else 0
            stream_uri = media.GetStreamUri({
                'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
                'ProfileToken': profiles[profile_idx].token,
            })
            return stream_uri.Uri
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] ONVIF Media 异常: {e}")
            return None

    def _is_ready(self) -> bool:
        return self._camera is not None and self._status.is_connected


# ──────────────────────────────────────────────
#  连接工厂
# ──────────────────────────────────────────────
CameraConn = USBCameraConnection | ONVIFCameraConnection


def create_camera_connection(config: CameraConfig, event_bus: EventBus):
    if config.is_usb:
        return USBCameraConnection(config, event_bus)
    elif config.is_onvif:
        return ONVIFCameraConnection(config, event_bus)
    else:
        raise ValueError(f"不支持的连接类型: {config.connection_type}")


# ──────────────────────────────────────────────
#  多摄像头管理器
# ──────────────────────────────────────────────
class CameraManager:
    """摄像头管理器 - 统一管理所有摄像头连接。支持 USB 和 ONVIF/RTSP 混合。"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._connections: Dict[str, Any] = {}

    def add_camera(self, config: CameraConfig):
        conn = create_camera_connection(config, self.event_bus)
        self._connections[config.name] = conn
        mode = "USB" if config.is_usb else "ONVIF/RTSP"
        print(f"[CameraManager] 已注册摄像头: {config.name} [{mode}]")
        return conn

    def connect(self, name: str) -> bool:
        return self._get_connection(name).connect()

    def connect_all(self) -> Dict[str, bool]:
        return {name: conn.connect() for name, conn in self._connections.items()}

    def disconnect(self, name: str) -> None:
        self._get_connection(name).disconnect()

    def disconnect_all(self) -> None:
        for conn in self._connections.values():
            conn.disconnect()

    def get_stream_url(self, name: str, sub_stream: bool = False) -> str:
        return self._get_connection(name).get_stream_url(sub_stream)

    def get_snapshot(self, name: str) -> Optional[np.ndarray]:
        return self._get_connection(name).get_snapshot()

    def read_frame(self, name: str) -> Optional[np.ndarray]:
        conn = self._get_connection(name)
        if hasattr(conn, 'read_frame'):
            return conn.read_frame()
        return conn.get_snapshot()

    def get_status(self, name: str) -> CameraStatus:
        return self._get_connection(name).get_status()

    def list_cameras(self) -> List[CameraStatus]:
        return [conn.get_status() for conn in self._connections.values()]

    def get_default_camera_name(self) -> Optional[str]:
        if self._connections:
            return next(iter(self._connections))
        return None

    def get_camera_names(self) -> List[str]:
        return list(self._connections.keys())

    def _get_connection(self, name: str):
        if name not in self._connections:
            raise KeyError(f"未找到摄像头 '{name}'，可用: {list(self._connections.keys())}")
        return self._connections[name]
