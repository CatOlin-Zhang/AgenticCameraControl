"""
摄像头管理模块 - ONVIF 协议摄像头管理
功能：
  - 连接/断开 ONVIF 摄像头
  - 获取 RTSP 视频流地址
  - 获取设备信息 / 状态
  - 多摄像头管理（预留）
  - PTZ 控制（预留）
"""
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

from onvif import ONVIFCamera

from config import CameraConfig
from events import EventBus, CameraEvent, EventType, StubOnvifEventListener


# ──────────────────────────────────────────────
#  摄像头状态
# ──────────────────────────────────────────────
@dataclass
class CameraStatus:
    """摄像头实时状态信息"""
    name: str
    ip: str
    is_connected: bool = False
    is_streaming: bool = False
    manufacturer: str = ""
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    rtsp_url: str = ""
    last_error: str = ""
    last_updated: Optional[datetime] = None


# ──────────────────────────────────────────────
#  单个摄像头连接管理器
# ──────────────────────────────────────────────
class CameraConnection:
    """
    单个 ONVIF 摄像头的连接管理。
    封装 ONVIFCamera 对象，提供设备信息获取、流地址获取等方法。
    """

    def __init__(self, config: CameraConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self._camera: Optional[ONVIFCamera] = None
        self._status = CameraStatus(name=config.name, ip=config.ip)
        self._lock = threading.Lock()

        # 事件监听器（预留，使用 Stub 实现）
        self._event_listener = StubOnvifEventListener(config.name, event_bus)

    # ── 连接管理 ────────────────────────────────

    def connect(self) -> bool:
        """
        连接 ONVIF 摄像头。
        连接成功后自动拉取设备基本信息。
        :return: 是否连接成功
        """
        with self._lock:
            try:
                print(f"[Camera:{self.config.name}] 正在连接 {self.config.ip}:{self.config.port} ...")

                self._camera = ONVIFCamera(
                    host=self.config.ip,
                    port=self.config.port,
                    user=self.config.username,
                    passwd=self.config.password,
                )

                # 验证连接 & 拉取设备信息
                self._fetch_device_info()
                self._status.is_connected = True
                self._status.last_error = ""
                self._status.last_updated = datetime.now()

                # 启动事件监听
                self._event_listener.start()

                # 发布上线事件
                self.event_bus.publish(CameraEvent(
                    event_type=EventType.DEVICE_ONLINE,
                    camera_name=self.config.name,
                    message=f"摄像头已连接: {self.config.model}",
                ))

                print(f"[Camera:{self.config.name}] 连接成功 - {self.config.manufacturer} {self.config.model}")
                return True

            except Exception as e:
                error_msg = f"连接失败: {e}"
                self._status.is_connected = False
                self._status.last_error = error_msg
                self._status.last_updated = datetime.now()
                print(f"[Camera:{self.config.name}] {error_msg}")
                return False

    def disconnect(self) -> None:
        """断开摄像头连接"""
        with self._lock:
            self._event_listener.stop()
            self._camera = None
            self._status.is_connected = False
            self._status.is_streaming = False
            self._status.last_updated = datetime.now()

            self.event_bus.publish(CameraEvent(
                event_type=EventType.DEVICE_OFFLINE,
                camera_name=self.config.name,
                message="摄像头已断开",
            ))
            print(f"[Camera:{self.config.name}] 已断开连接")

    # ── 视频流 ──────────────────────────────────

    def get_stream_url(self, sub_stream: bool = False) -> str:
        """
        获取 RTSP 视频流地址。
        优先通过 ONVIF Media 服务获取，失败时退化为配置文件中的拼接地址。
        :param sub_stream: True 获取子码流, False 获取主码流
        :return: RTSP URL
        """
        if not self._is_ready():
            raise ConnectionError(f"摄像头 {self.config.name} 未连接")

        try:
            # 尝试通过 ONVIF Media2 服务获取流地址
            url = self._fetch_stream_via_onvif(sub_stream)
            if url:
                self._status.rtsp_url = url
                return url
        except Exception as e:
            print(f"[Camera:{self.config.name}] ONVIF 获取流地址失败，使用配置地址: {e}")

        # 退化为配置拼接
        url = self.config.get_rtsp_url(sub_stream)
        self._status.rtsp_url = url
        return url

    def _fetch_stream_via_onvif(self, sub_stream: bool = False) -> Optional[str]:
        """通过 ONVIF Media 服务获取 RTSP 流地址"""
        if not self._camera:
            return None

        try:
            media = self._camera.create_media_service()
            profiles = media.GetProfiles()

            if not profiles:
                return None

            # 通常第一个 profile 是主码流，第二个是子码流
            profile_idx = 1 if (sub_stream and len(profiles) > 1) else 0
            profile_token = profiles[profile_idx].token

            stream_uri = media.GetStreamUri({
                'StreamSetup': {
                    'Stream': 'RTP-Unicast',
                    'Transport': {'Protocol': 'RTSP'},
                },
                'ProfileToken': profile_token,
            })
            return stream_uri.Uri

        except Exception as e:
            print(f"[Camera:{self.config.name}] ONVIF Media 服务调用异常: {e}")
            return None

    # ── 截图（预留）──────────────────────────────

    def get_snapshot_url(self) -> Optional[str]:
        """获取快照（截图）地址"""
        if not self._is_ready():
            raise ConnectionError(f"摄像头 {self.config.name} 未连接")

        try:
            media = self._camera.create_media_service()
            profiles = media.GetProfiles()
            if profiles:
                snapshot_uri = media.GetSnapshotUri({'ProfileToken': profiles[0].token})
                return snapshot_uri.Uri
        except Exception as e:
            print(f"[Camera:{self.config.name}] 获取快照地址失败: {e}")
        return None

    # ── 设备信息 ────────────────────────────────

    def get_status(self) -> CameraStatus:
        """获取摄像头当前状态"""
        self._status.last_updated = datetime.now()
        return self._status

    def _fetch_device_info(self) -> None:
        """拉取设备基本信息（连接时调用）"""
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
            print(f"[Camera:{self.config.name}] 获取设备信息失败: {e}")

    # ── PTZ 控制（预留）─────────────────────────

    def ptz_move(self, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0) -> None:
        """
        PTZ 云台控制（预留接口）
        :param pan: 水平速度 (-1.0 ~ 1.0)
        :param tilt: 垂直速度 (-1.0 ~ 1.0)
        :param zoom: 缩放速度 (-1.0 ~ 1.0)
        """
        raise NotImplementedError("PTZ 控制功能尚未实现，请后续补充")

    def ptz_goto_preset(self, preset_name: str) -> None:
        """
        跳转到预置位（预留接口）
        :param preset_name: 预置位名称
        """
        raise NotImplementedError("预置位跳转功能尚未实现，请后续补充")

    # ── 内部辅助 ────────────────────────────────

    def _is_ready(self) -> bool:
        """检查摄像头是否已连接"""
        return self._camera is not None and self._status.is_connected


# ──────────────────────────────────────────────
#  多摄像头管理器
# ──────────────────────────────────────────────
class CameraManager:
    """
    摄像头管理器 - 管理所有摄像头连接。
    当前支持单台，未来可扩展为多台。
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._connections: Dict[str, CameraConnection] = {}

    def add_camera(self, config: CameraConfig) -> CameraConnection:
        """
        注册一个摄像头（不立即连接）
        :param config: 摄像头配置
        :return: CameraConnection 对象
        """
        conn = CameraConnection(config, self.event_bus)
        self._connections[config.name] = conn
        print(f"[CameraManager] 已注册摄像头: {config.name} ({config.ip})")
        return conn

    def connect(self, name: str) -> bool:
        """连接指定摄像头"""
        conn = self._get_connection(name)
        return conn.connect()

    def connect_all(self) -> Dict[str, bool]:
        """连接所有已注册的摄像头"""
        results = {}
        for name, conn in self._connections.items():
            results[name] = conn.connect()
        return results

    def disconnect(self, name: str) -> None:
        """断开指定摄像头"""
        conn = self._get_connection(name)
        conn.disconnect()

    def disconnect_all(self) -> None:
        """断开所有摄像头"""
        for conn in self._connections.values():
            conn.disconnect()

    def get_stream_url(self, name: str, sub_stream: bool = False) -> str:
        """获取指定摄像头的视频流地址"""
        conn = self._get_connection(name)
        return conn.get_stream_url(sub_stream)

    def get_snapshot_url(self, name: str) -> Optional[str]:
        """获取指定摄像头的快照地址"""
        conn = self._get_connection(name)
        return conn.get_snapshot_url()

    def get_status(self, name: str) -> CameraStatus:
        """获取指定摄像头状态"""
        conn = self._get_connection(name)
        return conn.get_status()

    def list_cameras(self) -> List[CameraStatus]:
        """列出所有摄像头状态"""
        return [conn.get_status() for conn in self._connections.values()]

    def get_default_camera_name(self) -> Optional[str]:
        """获取默认（第一个）摄像头名称"""
        if self._connections:
            return next(iter(self._connections))
        return None

    def _get_connection(self, name: str) -> CameraConnection:
        """获取连接对象，不存在则抛异常"""
        if name not in self._connections:
            available = list(self._connections.keys())
            raise KeyError(f"未找到摄像头 '{name}'，可用: {available}")
        return self._connections[name]
