"""
phase2 - 摄像头管理模块 - 支持 USB/ONVIF 双模式 + SN 码认证

Phase2 新增：
  - 集成 SNDecoder，连接时自动解码密码
  - 支持运行时通过 SN 码更新摄像头密码
  - CameraManager 持有 SNDecoder 实例
"""
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import cv2
import numpy as np

from phase2.core.config import CameraConfig, ConnectionType
from phase2.core.events import EventBus, CameraEvent, EventType, StubOnvifEventListener
from phase2.core.auth import SNDecoder


# ──────────────────────────────────────────────
#  摄像头状态
# ──────────────────────────────────────────────
@dataclass
class CameraStatus:
    """摄像头实时状态信息"""
    name: str
    connection_type: str = "onvif"
    ip: str = ""
    device_index: int = -1
    is_connected: bool = False
    is_streaming: bool = False
    is_authenticated: bool = False         # Phase2: SN 认证状态
    manufacturer: str = ""
    model: str = ""
    product_version: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    stream_source: str = ""
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
                self._status.is_authenticated = True  # USB 无需认证
                self._status.stream_source = f"USB device [{idx}]"
                self._status.last_error = ""
                self._status.last_updated = datetime.now()
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.DEVICE_ONLINE, camera_name=self.config.name,
                    message=f"USB 摄像头已连接: {self._status.frame_width}x{self._status.frame_height}",
                ))
                return True
            except Exception as e:
                self._status.is_connected = False
                self._status.last_error = f"USB 摄像头连接失败: {e}"
                self._status.last_updated = datetime.now()
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
                event_type=EventType.DEVICE_OFFLINE, camera_name=self.config.name,
                message="USB 摄像头已断开",
            ))

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
#  ONVIF/RTSP 局域网摄像头连接 (集成 SN 认证)
# ──────────────────────────────────────────────
class ONVIFCameraConnection:
    """ONVIF/RTSP 局域网摄像头连接管理。Phase2: 集成 SN 码认证。"""

    def __init__(self, config: CameraConfig, event_bus: EventBus, sn_decoder: Optional[SNDecoder] = None):
        self.config = config
        self.event_bus = event_bus
        self._sn_decoder = sn_decoder
        self._camera = None
        self._status = CameraStatus(
            name=config.name, connection_type="onvif", ip=config.ip,
            model=config.device_model, product_version=config.product_version,
        )
        self._lock = threading.Lock()
        self._event_listener = StubOnvifEventListener(config.name, event_bus)

    def connect(self) -> bool:
        with self._lock:
            try:
                # Phase2: 如果密码为空但有 SN 码，尝试 SN 解码
                if not self.config.password and self.config.sn_code and self._sn_decoder:
                    self._apply_sn_password()

                from onvif import ONVIFCamera
                print(f"[ONVIF:{self.config.name}] 正在连接 {self.config.ip}:{self.config.port} ...")
                self._camera = ONVIFCamera(
                    host=self.config.ip, port=self.config.port,
                    user=self.config.username, passwd=self.config.password,
                )
                self._fetch_device_info()
                self._status.is_connected = True
                self._status.is_authenticated = True
                self._status.last_error = ""
                self._status.last_updated = datetime.now()
                self._event_listener.start()
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.DEVICE_ONLINE, camera_name=self.config.name,
                    message=f"ONVIF 摄像头已连接: {self._status.manufacturer} {self._status.model}",
                ))
                return True
            except ImportError:
                print(f"[ONVIF:{self.config.name}] onvif-zeep 未安装，使用 RTSP-only 模式")
                return self._connect_rtsp_only()
            except Exception as e:
                print(f"[ONVIF:{self.config.name}] ONVIF 连接失败: {e}")
                print(f"[ONVIF:{self.config.name}] 尝试 RTSP-only 模式 ...")
                return self._connect_rtsp_only()

    def _apply_sn_password(self) -> bool:
        """通过 SN 解码器获取密码并更新配置"""
        try:
            password = self._sn_decoder.get_password(self.config.sn_code)
            if password:
                self.config.password = password
                self._status.is_authenticated = True
                print(f"[Auth:{self.config.name}] SN 码已解码，密码已更新")
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.AUTH_SUCCESS, camera_name=self.config.name,
                    message=f"SN 码 {self.config.sn_code} 解码成功",
                ))
                return True
            else:
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.AUTH_FAILED, camera_name=self.config.name,
                    message=f"SN 码 {self.config.sn_code} 解码失败",
                ))
                return False
        except Exception as e:
            print(f"[Auth:{self.config.name}] SN 解码异常: {e}")
            self.event_bus.publish(CameraEvent(
                event_type=EventType.AUTH_FAILED, camera_name=self.config.name,
                message=f"SN 解码异常: {e}",
            ))
            return False

    def _connect_rtsp_only(self) -> bool:
        try:
            # Phase2: 确保密码已通过 SN 解码
            if not self.config.password and self.config.sn_code and self._sn_decoder:
                self._apply_sn_password()

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
                    self._status.is_authenticated = bool(self.config.password)
                    self._status.last_error = ""
                    self._status.last_updated = datetime.now()
                    cap.release()
                    self.event_bus.publish(CameraEvent(
                        event_type=EventType.DEVICE_ONLINE, camera_name=self.config.name,
                        message=f"RTSP 摄像头已连接: {w}x{h}",
                    ))
                    return True
                cap.release()
            self._status.is_connected = False
            self._status.last_error = "RTSP 流无法打开"
            self._status.last_updated = datetime.now()
            return False
        except Exception as e:
            self._status.last_error = f"RTSP 验证异常: {e}"
            return False

    def disconnect(self) -> None:
        with self._lock:
            self._event_listener.stop()
            self._camera = None
            self._status.is_connected = False
            self._status.is_streaming = False
            self._status.last_updated = datetime.now()
            self.event_bus.publish(CameraEvent(
                event_type=EventType.DEVICE_OFFLINE, camera_name=self.config.name,
                message="ONVIF 摄像头已断开",
            ))

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

    def update_password(self, password: str) -> None:
        """Phase2: 运行时更新密码（由 SN 解码后调用）"""
        self.config.password = password
        self._status.is_authenticated = True

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


def create_camera_connection(config: CameraConfig, event_bus: EventBus,
                              sn_decoder: Optional[SNDecoder] = None):
    if config.is_usb:
        return USBCameraConnection(config, event_bus)
    elif config.is_onvif:
        return ONVIFCameraConnection(config, event_bus, sn_decoder)
    else:
        raise ValueError(f"不支持的连接类型: {config.connection_type}")


# ──────────────────────────────────────────────
#  多摄像头管理器 (集成 SN 解码器)
# ──────────────────────────────────────────────
class CameraManager:
    """摄像头管理器 - Phase2: 集成 SN 码认证。"""

    def __init__(self, event_bus: EventBus, sn_decoder: Optional[SNDecoder] = None):
        self.event_bus = event_bus
        self.sn_decoder = sn_decoder
        self._connections: Dict[str, Any] = {}
        self._configs: Dict[str, CameraConfig] = {}

    def add_camera(self, config: CameraConfig):
        conn = create_camera_connection(config, self.event_bus, self.sn_decoder)
        self._connections[config.name] = conn
        self._configs[config.name] = config
        mode = "USB" if config.is_usb else "ONVIF/RTSP"
        sn_tag = f" SN:{config.sn_code}" if config.sn_code else ""
        print(f"[CameraManager] 已注册摄像头: {config.name} [{mode}]{sn_tag}")
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

    def get_config(self, name: str) -> Optional[CameraConfig]:
        """获取摄像头配置"""
        return self._configs.get(name)

    def update_camera_password(self, name: str, password: str) -> None:
        """Phase2: 通过 SN 解码后更新摄像头密码"""
        config = self._configs.get(name)
        if config:
            config.password = password
        conn = self._connections.get(name)
        if conn and hasattr(conn, 'update_password'):
            conn.update_password(password)

    def apply_sn_to_all(self, sn_code: str) -> int:
        """
        Phase2: 将 SN 码应用到所有未认证的 ONVIF 摄像头。
        返回成功应用的数量。
        """
        if not self.sn_decoder:
            return 0
        count = 0
        password = self.sn_decoder.get_password(sn_code)
        if not password:
            return 0
        for name, config in self._configs.items():
            if config.is_onvif and not config.password:
                config.password = password
                config.sn_code = sn_code
                conn = self._connections.get(name)
                if conn and hasattr(conn, 'update_password'):
                    conn.update_password(password)
                count += 1
                print(f"[CameraManager] {name} 已通过 SN 码获取密码")
        return count

    def _get_connection(self, name: str):
        if name not in self._connections:
            raise KeyError(f"未找到摄像头 '{name}'，可用: {list(self._connections.keys())}")
        return self._connections[name]
