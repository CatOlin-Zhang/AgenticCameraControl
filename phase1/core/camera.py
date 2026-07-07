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
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any

import cv2
import numpy as np

from phase1.core.config import CameraConfig
from phase1.core.events import EventBus, CameraEvent, EventType, StubOnvifEventListener


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
                import socket
                print(f"[ONVIF:{self.config.name}] 正在连接 {self.config.ip}:{self.config.port} ...")
                # 设置 3 秒超时
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(3.0)
                try:
                    self._camera = ONVIFCamera(
                        host=self.config.ip, port=self.config.port,
                        user=self.config.username, passwd=self.config.password,
                    )
                    self._fetch_device_info()
                finally:
                    socket.setdefaulttimeout(old_timeout)
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
        """RTSP 直连，仅使用配置的路径，3秒超时"""
        pwd = self.config.password if self.config.password else ""
        url = f"rtsp://{self.config.username}:{pwd}@{self.config.ip}:{self.config.rtsp_port}{self.config.rtsp_path}"
        try:
            print(f"[ONVIF:{self.config.name}] 尝试 RTSP: {self.config.rtsp_path}")
            # 设置 OpenCV 连接超时为 3 秒
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    h, w = frame.shape[:2]
                    self._status.frame_width = w
                    self._status.frame_height = h
                    self._status.is_connected = True
                    self._status.is_streaming = True
                    self._status.stream_source = url
                    self._status.last_error = ""
                    self._status.last_updated = datetime.now()
                    cap.release()
                    self.event_bus.publish(CameraEvent(
                        event_type=EventType.DEVICE_ONLINE, camera_name=self.config.name,
                        message=f"RTSP 摄像头已连接: {w}x{h} (路径: {self.config.rtsp_path})",
                    ))
                    print(f"[ONVIF:{self.config.name}] RTSP 连接成功 - {w}x{h} (路径: {self.config.rtsp_path})")
                    return True
                cap.release()
            else:
                cap.release()
        except Exception:
            pass

        self._status.is_connected = False
        self._status.last_error = f"RTSP 连接失败 (路径: {self.config.rtsp_path})"
        self._status.last_updated = datetime.now()
        print(f"[ONVIF:{self.config.name}] RTSP 连接失败 (路径: {self.config.rtsp_path})")
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
                    # ONVIF 返回的 URL 通常不带认证信息，需要手动注入
                    url = self._inject_auth(url)
                    self._status.stream_source = url
                    return url
            except Exception as e:
                print(f"[ONVIF:{self.config.name}] ONVIF 获取流地址失败: {e}")
        url = self.config.get_rtsp_url(sub_stream)
        self._status.stream_source = url
        return url

    def _inject_auth(self, url: str) -> str:
        """将 username:password 注入到 RTSP URL 中"""
        if not url.startswith("rtsp://"):
            return url
        # 如果 URL 已经包含 @（已有认证信息），直接返回
        if '@' in url:
            return url
        pwd = self.config.password if self.config.password else ""
        user = self.config.username if self.config.username else "admin"
        # rtsp://host:port/path → rtsp://user:pwd@host:port/path
        url_without_scheme = url[7:]  # 去掉 "rtsp://"
        return f"rtsp://{user}:{pwd}@{url_without_scheme}"

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

    # ── PTZ 云台控制 ──

    def ptz_move(self, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0,
                 speed: float = 0.5) -> bool:
        """
        PTZ 连续移动（相对速度控制）
        :param pan: 水平速度 -1.0~1.0 (负=左, 正=右)
        :param tilt: 垂直速度 -1.0~1.0 (负=下, 正=上)
        :param zoom: 缩放速度 -1.0~1.0 (负=缩小, 正=放大)
        :param speed: 速度系数 0.0~1.0
        """
        if not self._camera:
            print(f"[ONVIF:{self.config.name}] PTZ 不可用 (未通过 ONVIF 连接)")
            return False
        try:
            ptz = self._camera.create_ptz_service()
            media = self._camera.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                print(f"[ONVIF:{self.config.name}] 无 Media Profile")
                return False
            profile_token = profiles[0].token
            request = ptz.create_type('ContinuousMove')
            request.ProfileToken = profile_token
            request.Velocity = {
                'PanTilt': {'x': pan * speed, 'y': tilt * speed},
                'Zoom': {'x': zoom * speed},
            }
            ptz.ContinuousMove(request)
            print(f"[ONVIF:{self.config.name}] PTZ 移动: pan={pan}, tilt={tilt}, zoom={zoom}")
            return True
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] PTZ 移动失败: {e}")
            return False

    def ptz_stop(self) -> bool:
        """停止 PTZ 移动"""
        if not self._camera:
            return False
        try:
            ptz = self._camera.create_ptz_service()
            media = self._camera.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                return False
            profile_token = profiles[0].token
            request = ptz.create_type('Stop')
            request.ProfileToken = profile_token
            ptz.Stop(request)
            print(f"[ONVIF:{self.config.name}] PTZ 已停止")
            return True
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] PTZ 停止失败: {e}")
            return False

    def ptz_goto_preset(self, preset_name: str) -> bool:
        """跳转到 PTZ 预置位"""
        if not self._camera:
            return False
        try:
            ptz = self._camera.create_ptz_service()
            media = self._camera.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                return False
            profile_token = profiles[0].token
            presets = ptz.GetPresets({'ProfileToken': profile_token})
            target = None
            for p in presets:
                if str(getattr(p, 'Name', '')) == preset_name or str(getattr(p, 'token', '')) == preset_name:
                    target = p
                    break
            if not target:
                available = [str(getattr(p, 'Name', getattr(p, 'token', '?'))) for p in presets]
                print(f"[ONVIF:{self.config.name}] 预置位 '{preset_name}' 不存在，可用: {available}")
                return False
            request = ptz.create_type('GotoPreset')
            request.ProfileToken = profile_token
            request.PresetToken = target.token
            ptz.GotoPreset(request)
            print(f"[ONVIF:{self.config.name}] 已跳转到预置位: {preset_name}")
            return True
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] 跳转预置位失败: {e}")
            return False

    def ptz_get_presets(self) -> List[Dict[str, str]]:
        """获取所有 PTZ 预置位"""
        if not self._camera:
            return []
        try:
            ptz = self._camera.create_ptz_service()
            media = self._camera.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                return []
            presets = ptz.GetPresets({'ProfileToken': profiles[0].token})
            result = []
            for p in presets:
                result.append({
                    'token': str(getattr(p, 'token', '')),
                    'name': str(getattr(p, 'Name', '')),
                })
            return result
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] 获取预置位失败: {e}")
            return []

    def get_device_info(self) -> Dict[str, str]:
        """获取 ONVIF 设备详细信息"""
        if not self._camera:
            return {}
        try:
            devicemgmt = self._camera.create_devicemgmt_service()
            info = devicemgmt.GetDeviceInformation()
            return {
                'manufacturer': str(getattr(info, 'Manufacturer', '')),
                'model': str(getattr(info, 'Model', '')),
                'firmware': str(getattr(info, 'FirmwareVersion', '')),
                'serial': str(getattr(info, 'SerialNumber', '')),
                'hardware_id': str(getattr(info, 'HardwareId', '')),
            }
        except Exception as e:
            print(f"[ONVIF:{self.config.name}] 获取设备信息失败: {e}")
            return {}

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
        if not self._connections:
            return None
        # 优先返回动态扫描发现的摄像头
        for name in self._connections:
            if name.startswith("discovered_"):
                return name
        return next(iter(self._connections))

    def get_camera_names(self) -> List[str]:
        return list(self._connections.keys())

    def remove_camera(self, name: str) -> None:
        """移除已注册的摄像头（如已连接则先断开）"""
        if name in self._connections:
            conn = self._connections[name]
            status = conn.get_status()
            if status.is_connected:
                conn.disconnect()
            del self._connections[name]
            print(f"[CameraManager] 已移除摄像头: {name}")

    def update_all_passwords(self, password: str) -> int:
        """批量更新所有 ONVIF 摄像头的密码，返回更新数量"""
        count = 0
        for name, conn in self._connections.items():
            if hasattr(conn, 'config') and conn.config.is_onvif:
                conn.config.password = password
                count += 1
        if count:
            print(f"[CameraManager] 已更新 {count} 个摄像头的密码")
        return count

    # ── PTZ 代理方法 ──

    def ptz_move(self, name: str, pan: float = 0.0, tilt: float = 0.0,
                zoom: float = 0.0, speed: float = 0.5) -> bool:
        conn = self._get_connection(name)
        if hasattr(conn, 'ptz_move'):
            return conn.ptz_move(pan, tilt, zoom, speed)
        print(f"[CameraManager] {name} 不支持 PTZ 控制")
        return False

    def ptz_stop(self, name: str) -> bool:
        conn = self._get_connection(name)
        if hasattr(conn, 'ptz_stop'):
            return conn.ptz_stop()
        return False

    def ptz_goto_preset(self, name: str, preset: str) -> bool:
        conn = self._get_connection(name)
        if hasattr(conn, 'ptz_goto_preset'):
            return conn.ptz_goto_preset(preset)
        print(f"[CameraManager] {name} 不支持 PTZ 预置位")
        return False

    def ptz_get_presets(self, name: str) -> List[Dict[str, str]]:
        conn = self._get_connection(name)
        if hasattr(conn, 'ptz_get_presets'):
            return conn.ptz_get_presets()
        return []

    def get_device_info(self, name: str) -> Dict[str, str]:
        conn = self._get_connection(name)
        if hasattr(conn, 'get_device_info'):
            return conn.get_device_info()
        return {}

    def _get_connection(self, name: str):
        if name not in self._connections:
            raise KeyError(f"未找到摄像头 '{name}'，可用: {list(self._connections.keys())}")
        return self._connections[name]
