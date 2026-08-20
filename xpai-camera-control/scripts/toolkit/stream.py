"""
Toolkit 1: 音视频流与存储

工具清单：
  - get_audio_video_stream  拉取实时音视频流
  - capture_video_screenshot 截取当前画面并保存
  - toggle_recording        启动或停止录像
  - manage_storage_status   查询/设置存储状态、路径与策略
  - start_webrtc_stream     启动 go2rtc WebRTC 实时预览
  - stop_webrtc_stream      停止 go2rtc WebRTC 转流
"""
import os
import signal
import sys
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
import json
import shutil
import subprocess

# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class RecordingAction(str, Enum):
    START = "start"
    STOP = "stop"
    STATUS = "status"


class StorageAction(str, Enum):
    QUERY = "query"
    SET = "set"


@dataclass
class StreamResult:
    """拉流操作返回结果"""
    success: bool                                # 是否成功获取流
    stream_url: str = ""                         # RTSP / USB 流地址
    codec: str = ""                              # 编码格式 (H.264 / H.265 / MJPEG)
    resolution: str = ""                         # 分辨率 (如 "1920x1080")
    fps: float = 0.0                             # 帧率
    bitrate: int = 0                             # 码率 (kbps)
    error_message: str = ""                      # 失败原因


@dataclass
class ScreenshotResult:
    """截图操作返回结果"""
    success: bool                                # 是否截图成功
    file_path: str = ""                          # 截图保存的完整路径
    width: int = 0                               # 截图宽度
    height: int = 0                              # 截图高度
    error_message: str = ""                      # 失败原因


@dataclass
class RecordingResult:
    """录像操作返回结果"""
    success: bool                                # 操作是否成功
    is_recording: bool = False                   # 当前是否在录像
    file_path: str = ""                          # 录像文件路径（停止时返回）
    duration_seconds: float = 0.0                # 已录制时长（停止时返回）
    auto_stop: bool = False                      # 是否设置了自动停止定时器
    error_message: str = ""                      # 失败原因


@dataclass
class StorageResult:
    """存储管理操作返回结果"""
    success: bool                                # 操作是否成功
    used_space_mb: float = 0.0                   # 已用空间 (MB)
    available_space_mb: float = 0.0              # 可用空间 (MB)
    storage_path: str = ""                       # 当前存储路径
    format: str = ""                             # 文件格式 (mp4 / avi / jpg)
    policy: str = ""                             # 策略名称 (overwrite / stop_when_full / circular)
    error_message: str = ""                      # 失败原因


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def _open_rtsp_capture(rtsp_url: str):
    """打开 RTSP 流（FFmpeg 后端，打开 3s / 读帧 5s 超时）。

    超时经 VideoCapture params 重载传入（OpenCV ≥ 4.5.2）；老版本无此
    重载（或无超时常量）时退回普通打开，避免直接抛异常。
    事件联动快照在后台线程调用本模块，无超时的 cv2 打开会因设备
    高负载挂死线程（TCP 半开 + ffmpeg 内部阻塞）。
    """
    import cv2
    try:
        return cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
        ])
    except (TypeError, AttributeError):
        return cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)


def get_audio_video_stream(
    camera_name: str,
    sub_stream: bool = False,
) -> StreamResult:
    """
    拉取实时音视频流。

    获取当前摄像头的实时音视频流地址并打开预览。
    - ONVIF 设备：通过 ONVIF Media Service GetStreamUri 获取 RTSP URL
    - USB 设备：通过 OpenCV VideoCapture 直接读取帧
    - 自动降级：ONVIF 不可用时尝试 RTSP 直连，依次试多种常见路径

    安全约束: 显式提示 + 代码校验（校验设备已连接、流地址可用）

    Args:
        camera_name: 摄像头名称（自动填充，通常为当前连接的设备）
        sub_stream:  是否使用子码流（低画质，默认 False 使用主码流）

    Returns:
        StreamResult:
            - success: True 表示成功获取流
            - stream_url: RTSP URL 或 USB 设备标识
            - codec: 编码格式（H.264 / H.265）
            - resolution: 分辨率字符串（如 "1920x1080"）
            - fps: 帧率
            - bitrate: 码率 (kbps)
            - error_message: 失败时的错误描述
    """
    # ── Step 1: 获取设备连接信息 ──
    from .device_mgmt import _connected_devices, _find_cached_camera
    conn_info = _connected_devices.get(camera_name)
    if not conn_info:
        # 尝试从 config.yaml 获取配置
        cached = _find_cached_camera(camera_name)
        if cached and cached.ip:
            conn_info = {
                "ip": cached.ip,
                "rtsp_port": cached.rtsp_port,
                "rtsp_path": cached.rtsp_path if not sub_stream else cached.rtsp_sub_path,
                "rtsp_sub_path": cached.rtsp_sub_path,
                "username": cached.username,
                "password": cached.password,
                "connection_type": cached.connection_type,
                "device_index": cached.device_index,
            }
        else:
            return StreamResult(
                success=False,
                error_message=f"设备 {camera_name} 未连接，请先调用 connect_device()",
            )

    conn_type = conn_info.get("connection_type", "onvif")

    # ── Step 2: USB 设备 ──
    if conn_type == "usb":
        try:
            import cv2
            dev_idx = conn_info.get("device_index", 0)
            cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                return StreamResult(
                    success=False,
                    error_message=f"USB 摄像头 {dev_idx} 无法打开",
                )
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
            codec_name = "MJPEG" if fourcc == 1196444237 else "YUYV"
            cap.release()
            return StreamResult(
                success=True,
                stream_url=f"usb://{dev_idx}",
                codec=codec_name,
                resolution=f"{width}x{height}",
                fps=round(fps, 1),
                bitrate=0,
            )
        except ImportError:
            return StreamResult(
                success=False,
                error_message="缺少 opencv-python，无法访问 USB 摄像头",
            )
        except Exception as e:
            return StreamResult(success=False, error_message=str(e))

    # ── Step 3: ONVIF / RTSP 设备 ──
    ip = conn_info.get("ip", "")
    rtsp_port = conn_info.get("rtsp_port", 554)
    username = conn_info.get("username", "")
    password = conn_info.get("password", "")

    # 端点真相源：连接/配置态的主、子码流路径（SK 设备 /md0_0、/md0_1）
    if sub_stream:
        rtsp_path = conn_info.get("rtsp_sub_path") or "/md0_1"
    else:
        rtsp_path = conn_info.get("rtsp_path") or "/md0_0"

    # 构建 RTSP URL（使用 _build_rtsp_url 自动注入凭据）
    from .device_mgmt import _build_rtsp_url
    rtsp_url = _build_rtsp_url(ip, rtsp_port, rtsp_path, username, password)

    # ── Step 4: 验证流可用性并获取元数据 ──
    try:
        import cv2
    except ImportError:
        # 无 OpenCV 时仅验证 RTSP 可达性
        from .device_mgmt import _probe_stream_access
        access = _probe_stream_access(ip, rtsp_port, rtsp_path, username, password)
        if access == "open":
            return StreamResult(
                success=True,
                stream_url=rtsp_url,
                codec="H.264",
                resolution="",
                fps=0.0,
                bitrate=0,
            )
        elif access == "auth_required":
            return StreamResult(
                success=False,
                error_message=f"设备 {camera_name} 需要密码认证，请提供正确的密码",
            )
        else:
            return StreamResult(
                success=False,
                error_message=f"设备 {camera_name}({ip}) RTSP 流不可达",
            )

    # 使用 OpenCV 验证并获取流参数（带打开/读帧超时）
    cap = _open_rtsp_capture(rtsp_url)
    if not cap.isOpened():
        # 端点只用另一条码流互备（主↔子），不盲试通用路径列表——猜测端点
        # 掩盖配置错误，且每次失败都要白等一次连接超时
        cap.release()
        alt_path = (conn_info.get("rtsp_path") or "/md0_0") if sub_stream \
            else (conn_info.get("rtsp_sub_path") or "/md0_1")
        if alt_path != rtsp_path:
            rtsp_url = _build_rtsp_url(ip, rtsp_port, alt_path, username, password)
            cap = _open_rtsp_capture(rtsp_url)
        if not cap.isOpened():
            cap.release()
            return StreamResult(
                success=False,
                error_message=f"无法从 {ip}:{rtsp_port} 获取视频流，请检查 RTSP 路径和认证信息",
            )

    # 获取流参数
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    codec_map = {
        0x31637661: "H.264",   # avc1
        0x31637668: "H.265",   # hev1 (hvc1)
        1196444237: "MJPEG",
    }
    codec = codec_map.get(fourcc_int, f"0x{fourcc_int:08x}")

    cap.release()

    return StreamResult(
        success=True,
        stream_url=rtsp_url,
        codec=codec,
        resolution=f"{width}x{height}" if width and height else "",
        fps=round(fps, 1) if fps > 0 else 0.0,
        bitrate=0,
    )


def capture_video_screenshot(
    camera_name: str,
    save_path: Optional[str] = None,
) -> ScreenshotResult:
    """
    截取当前流画面并保存到指定路径。

    从当前视频流中截取一帧画面，保存为 JPEG 文件。
    如果 save_path 为空，则默认保存到 snapshots/ 目录，文件名含时间戳。

    安全约束: 显式提示 + 代码校验（校验设备已连接、可获取帧数据）

    Args:
        camera_name: 摄像头名称（自动填充）
        save_path:   保存目录或完整 .jpg 文件路径（默认 snapshots/ 并自动
                     生成含时间戳的文件名；事件联动快照传入预生成的完整路径）

    Returns:
        ScreenshotResult:
            - success: True 表示截图成功
            - file_path: 截图文件完整路径
            - width / height: 截图分辨率
            - error_message: 失败时的错误描述
    """
    import os
    import time

    # ── Step 1: 确定保存路径 ──
    # save_path 可为目录（自动生成带时间戳的文件名）或完整 .jpg 文件路径
    # （事件联动快照预生成路径后传入，落盘文件名与事件记录保持一致）
    if save_path is None:
        snapshot_dir = os.path.join(os.path.dirname(__file__), "..", "..", "snapshots")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(snapshot_dir, f"{camera_name}_{timestamp}.jpg")
    elif save_path.lower().endswith((".jpg", ".jpeg")):
        file_path = save_path
        snapshot_dir = os.path.dirname(os.path.abspath(save_path))
    else:
        snapshot_dir = save_path
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(snapshot_dir, f"{camera_name}_{timestamp}.jpg")

    os.makedirs(snapshot_dir, exist_ok=True)

    # ── Step 2: 获取设备连接信息并直接打开视频流 ──
    # 优化: 直接从 _connected_devices 获取连接信息并打开 RTSP 流，
    # 避免先调用 get_audio_video_stream（会打开验证后关闭流）再重新打开。
    from .device_mgmt import _connected_devices, _find_cached_camera
    conn_info = _connected_devices.get(camera_name)
    if not conn_info:
        cached = _find_cached_camera(camera_name)
        if cached and cached.ip:
            conn_info = {
                "ip": cached.ip,
                "rtsp_port": cached.rtsp_port,
                "rtsp_path": cached.rtsp_path,
                "rtsp_sub_path": cached.rtsp_sub_path,
                "username": cached.username,
                "password": cached.password,
                "connection_type": cached.connection_type,
                "device_index": cached.device_index,
            }
        else:
            return ScreenshotResult(
                success=False,
                file_path=file_path,
                error_message=f"设备 {camera_name} 未连接，请先调用 connect_device()",
            )

    conn_type = conn_info.get("connection_type", "onvif")

    try:
        import cv2
    except ImportError:
        return ScreenshotResult(
            success=False,
            file_path=file_path,
            error_message="缺少 opencv-python，请安装: pip install opencv-python",
        )

    # ── Step 3: 打开视频流并捕获帧 ──
    if conn_type == "usb":
        dev_idx = conn_info.get("device_index", 0)
        cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            return ScreenshotResult(
                success=False,
                file_path=file_path,
                error_message=f"USB 摄像头 {dev_idx} 无法打开",
            )
    else:
        ip = conn_info.get("ip", "")
        rtsp_port = conn_info.get("rtsp_port", 554)
        username = conn_info.get("username", "")
        password = conn_info.get("password", "")

        from .device_mgmt import _build_rtsp_url

        # 端点只用连接信息里的主、子码流互备（/md0_0、/md0_1），不盲试通用
        # 路径列表——猜测端点掩盖配置错误，且每次失败都要白等一次连接超时
        paths = []
        for p in (conn_info.get("rtsp_path") or "/md0_0",
                  conn_info.get("rtsp_sub_path") or "/md0_1"):
            if p and p not in paths:
                paths.append(p)

        for rtsp_path in paths:
            rtsp_url = _build_rtsp_url(ip, rtsp_port, rtsp_path, username, password)
            cap = _open_rtsp_capture(rtsp_url)
            if cap.isOpened():
                break
            cap.release()
        else:
            return ScreenshotResult(
                success=False,
                file_path=file_path,
                error_message=f"无法从 {ip}:{rtsp_port} 打开视频流（已尝试 {'、'.join(paths)}），"
                              f"请检查 RTSP 路径和认证信息",
            )

    # 等待并读取多帧以确保获取稳定画面（丢弃前 5 帧）
    for _ in range(5):
        ret, frame = cap.read()
        if not ret:
            cap.release()
            return ScreenshotResult(
                success=False,
                file_path=file_path,
                error_message="无法从流中读取帧数据",
            )

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return ScreenshotResult(
            success=False,
            file_path=file_path,
            error_message="读取帧数据失败",
        )

    # ── Step 4: 保存 JPEG ──
    # 注意: cv2.imwrite 在 Windows 上对含非 ASCII 字符的路径会静默失败，
    # 改用 cv2.imencode + numpy.tofile 写入。
    height, width = frame.shape[:2]
    try:
        import numpy as np
        success_enc, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if success_enc:
            encoded.tofile(file_path)
        else:
            raise RuntimeError("imencode 返回失败")
    except Exception as e:
        return ScreenshotResult(
            success=False,
            file_path=file_path,
            error_message=f"保存截图失败: {e}",
        )

    # 验证文件已写入
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return ScreenshotResult(
            success=False,
            file_path=file_path,
            error_message="截图文件写入失败或为空",
        )

    return ScreenshotResult(
        success=True,
        file_path=file_path,
        width=width,
        height=height,
    )


# ──────────────────────────────────────────────
#  录像模块级状态
# ──────────────────────────────────────────────


# ffmpeg -c:v copy remux 模式下，从 Popen 到实际写入第一帧的延迟（RTSP 握手 + 等待关键帧）
# 实测约 1.0~2.0s，取 1.5s 作补偿
_RECORDING_STARTUP_COMPENSATION = 1.5

_storage_config: Dict[str, dict] = {}     # camera_name -> {"path": str, "format": str, "policy": str}


# ── RTSP transport 降级 ──

_VALID_RTSP_TRANSPORTS = frozenset({"tcp", "udp"})


def _resolve_binary(name: str) -> Optional[str]:
    """先查 PATH，再查 FFMPEG_DIR 环境变量指定的目录。返回可执行文件完整路径或 None。"""
    path = shutil.which(name)
    if path:
        return path
    ffmpeg_dir = os.environ.get("FFMPEG_DIR", "")
    if ffmpeg_dir:
        candidate = os.path.join(ffmpeg_dir, name + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None




def _resolve_transport_plan(rtsp_transport: Optional[Any]) -> List[str]:
    """根据入参解析出重试顺序。

    Args:
        rtsp_transport: None → ["tcp", "udp"] (默认双试);
                        "tcp" / "udp" → 单次;
                        可迭代对象 → 按顺序重试。
    """
    if rtsp_transport is None:
        return ["tcp", "udp"]
    if isinstance(rtsp_transport, str):
        plan = [rtsp_transport]
    else:
        plan = list(rtsp_transport)
    if not plan:
        raise ValueError("rtsp_transport 不能为空")
    bad = [t for t in plan if t not in _VALID_RTSP_TRANSPORTS]
    if bad:
        raise ValueError(f"不支持的 rtsp_transport: {bad}，可选 {sorted(_VALID_RTSP_TRANSPORTS)}")
    return plan


def _probe_dimensions(rtsp_url: str, transport_plan: List[str], timeout: int = 15) -> Tuple[int, int]:
    """ffprobe 拉一次流元数据。失败不报错，返回 (0, 0)。"""
    ffprobe_path = _resolve_binary("ffprobe")
    if not ffprobe_path:
        return 0, 0
    for transport in transport_plan:
        try:
            probe = subprocess.run(
                [
                    ffprobe_path,
                    "-rtsp_transport", transport,
                    "-timeout", "5000000",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_entries", "stream=width,height",
                    "-select_streams", "v:0",
                    rtsp_url,
                ],
                capture_output=True, text=True, timeout=timeout,
            )
            probe_data = json.loads(probe.stdout)
            streams = probe_data.get("streams", [])
            if streams:
                return int(streams[0].get("width", 0)), int(streams[0].get("height", 0))
        except Exception:
            continue
    return 0, 0


# ── 跨平台 ffmpeg 中断信号 ──

_IS_WINDOWS = os.name == "nt"


def _send_ffmpeg_interrupt(proc: subprocess.Popen) -> None:
    """向 ffmpeg 子进程发送中断信号，使其优雅关闭（封包 moov atom）。

    Linux/macOS: SIGINT（ffmpeg 内置 handler 优雅退出）
    Windows:     CTRL_BREAK_EVENT + CREATE_NEW_PROCESS_GROUP 隔离发送
                 （Python Windows 不支持 send_signal(SIGINT)，会抛 ValueError）
    """
    try:
        if _IS_WINDOWS:
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
    except (OSError, ValueError):
        pass  # 进程可能已退出


@dataclass
class _CameraRecState:
    """单台摄像头的录像状态"""
    process: Optional[subprocess.Popen] = None
    start_time: Optional[float] = None
    file_path: str = ""
    transport: str = ""
    timer: Optional[threading.Timer] = None


# camera_name → 录像状态（支持多台摄像头同时录像）
_recording_states: Dict[str, _CameraRecState] = {}


def _get_video_duration(file_path: str) -> Optional[float]:
    """用 ffprobe 读取视频文件的精确时长（秒），失败返回 None。"""
    ffprobe_path = _resolve_binary("ffprobe")
    if not ffprobe_path:
        return None
    try:
        probe = subprocess.run(
            [
                ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_entries", "format=duration",
                file_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(probe.stdout)
        dur = data.get("format", {}).get("duration")
        if dur is not None:
            return round(float(dur), 2)
    except Exception:
        pass
    return None


def toggle_recording(
    camera_name: str,
    action: RecordingAction,
    save_path: Optional[str] = None,
    rtsp_transport: Optional[Any] = None,
    duration: Optional[float] = None,
) -> RecordingResult:
    """
    启动、停止或查询本地录像状态。

    使用 ffmpeg 子进程拉 RTSP 流，以 -c:v copy 纯 remux 方式写入 MP4 文件
    （不解码不重编码，画质 = 原始流）。
    start 时启动子进程，stop 时发送中断信号让 ffmpeg 优雅封包
    （Linux: SIGINT / Windows: CTRL_BREAK_EVENT）。
    支持多台摄像头同时录像，每台设备独立维护 ffmpeg 子进程和定时器。

    RTSP transport 降级：复用截图模块的 _resolve_transport_plan() 做 tcp→udp 降级，
    启动后校验进程存活 + 文件有数据，失败则自动切换 transport 重试。

    Args:
        camera_name:    摄像头名称
        action:         RecordingAction.START 开始 / STOP 停止 / STATUS 查询
        save_path:      录像保存目录（默认 vido/）
        rtsp_transport: "tcp"/"udp" 单次，或可迭代对象表示重试顺序，None=默认 [tcp, udp]
        duration:       录像时长（秒），仅在 START 时有效；设置后后台定时器自动停止

    Returns:
        RecordingResult:
            - success: 操作是否成功
            - is_recording: 当前是否在录像
            - file_path: 录像文件路径（停止时返回）
            - duration_seconds: 已录制时长（停止时返回）
            - auto_stop: 是否设置了自动停止定时器
            - error_message: 失败时的错误描述
    """
    # ── STATUS 查询 ──
    if action == RecordingAction.STATUS:
        state = _recording_states.get(camera_name)
        if state and state.process is not None and state.process.poll() is None:
            elapsed = time.time() - (state.start_time or time.time())
            return RecordingResult(
                success=True, is_recording=True,
                file_path=state.file_path,
                duration_seconds=round(elapsed, 2),
                auto_stop=state.timer is not None,
            )
        return RecordingResult(
            success=True, is_recording=False,
            error_message="当前没有正在进行的录像",
        )

    # ── STOP 流程 ──
    if action == RecordingAction.STOP:
        state = _recording_states.get(camera_name)
        if not state or state.process is None:
            return RecordingResult(
                success=False, is_recording=False,
                error_message="当前没有正在进行的录像",
            )

        # 取消自动停止定时器（如果存在）
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None

        proc = state.process
        start_time = state.start_time or time.time()
        file_path = state.file_path

        # 发送跨平台中断信号让 ffmpeg 优雅关闭（封包 moov atom）
        _send_ffmpeg_interrupt(proc)

        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass

        # 使用 ffprobe 获取视频文件精确时长（替代 wall-clock elapsed，避免关闭时间被计入）
        actual_duration = _get_video_duration(file_path)
        elapsed = time.time() - start_time
        reported_duration = actual_duration if actual_duration is not None else round(elapsed, 2)

        # 清理该摄像头的录像状态
        _recording_states.pop(camera_name, None)

        # 验证输出文件
        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            return RecordingResult(
                success=False, is_recording=False,
                duration_seconds=reported_duration,
                error_message="录像文件为空或不存在，录像可能未成功启动",
            )

        return RecordingResult(
            success=True, is_recording=False,
            file_path=file_path,
            duration_seconds=reported_duration,
        )

    # ── START 流程 ──
    if action == RecordingAction.START:
        # 检查该摄像头是否已在录像
        existing = _recording_states.get(camera_name)
        if existing and existing.process is not None and existing.process.poll() is None:
            return RecordingResult(
                success=False, is_recording=True,
                error_message=f"摄像头 {camera_name} 正在录像（文件: {existing.file_path}），请先停止再开始",
            )
        # 清理残留状态（进程已意外退出的情况，含孤儿定时器）
        if existing:
            if existing.timer is not None:
                existing.timer.cancel()
            _recording_states.pop(camera_name, None)

        # 检查 ffmpeg 是否可用
        ffmpeg_path = _resolve_binary("ffmpeg")
        if not ffmpeg_path:
            return RecordingResult(
                success=False, is_recording=False,
                error_message="ffmpeg 未安装，无法录像",
            )

        # 查找摄像头配置
        from .device_mgmt import _connected_devices, _find_cached_camera, _build_rtsp_url
        conn_info = _connected_devices.get(camera_name)
        cached = _find_cached_camera(camera_name)
        if not conn_info and not cached:
            return RecordingResult(
                success=False, is_recording=False,
                error_message=f"摄像头 '{camera_name}' 未注册",
            )

        # 构造 RTSP URL
        if cached:
            rtsp_url = _build_rtsp_url(
                cached.ip, cached.rtsp_port, cached.rtsp_path,
                cached.username, cached.password,
            )
        else:
            ip = conn_info.get("ip", "")
            rtsp_port = conn_info.get("rtsp_port", 554)
            rtsp_path = conn_info.get("rtsp_path", "/md0_0")
            username = conn_info.get("username", "")
            password = conn_info.get("password", "")
            rtsp_url = _build_rtsp_url(ip, rtsp_port, rtsp_path, username, password)

        # 确定保存目录
        recording_dir = save_path or str(
            Path(__file__).resolve().parent.parent.parent / "vido"
        )
        try:
            os.makedirs(recording_dir, exist_ok=True)
        except OSError as e:
            return RecordingResult(
                success=False, is_recording=False,
                error_message=f"创建录像目录失败: {e}",
            )

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(recording_dir, f"recording_{camera_name}_{timestamp}.mp4")

        # RTSP transport 降级
        try:
            transport_plan = _resolve_transport_plan(rtsp_transport)
        except ValueError as e:
            return RecordingResult(
                success=False, is_recording=False,
                error_message=str(e),
            )

        # 用 ffprobe 探测可用 transport（避免用错误的 transport 启动录像）
        working_transport = ""
        for transport in transport_plan:
            dims = _probe_dimensions(rtsp_url, [transport], timeout=10)
            if dims != (0, 0):
                working_transport = transport
                break

        if not working_transport:
            working_transport = transport_plan[0]

        # 计算 ffmpeg -t 兜底时长（用户 duration + 启动补偿 + 5s 安全余量）
        ffmpeg_timeout = None
        if duration is not None and duration > 0:
            ffmpeg_timeout = duration + _RECORDING_STARTUP_COMPENSATION + 5.0

        last_error = ""
        for transport in ([working_transport] + [t for t in transport_plan if t != working_transport]):
            # 构造 ffmpeg 命令
            ffmpeg_cmd = [
                ffmpeg_path, "-y",
                "-rtsp_transport", transport,
                "-timeout", "5000000",
                "-i", rtsp_url,
                "-c:v", "copy",
                "-an",
                "-movflags", "+faststart",
            ]
            if ffmpeg_timeout is not None:
                ffmpeg_cmd += ["-t", str(ffmpeg_timeout)]
            ffmpeg_cmd.append(file_path)

            popen_kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if _IS_WINDOWS:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(ffmpeg_cmd, **popen_kwargs)
            except FileNotFoundError:
                return RecordingResult(
                    success=False, is_recording=False,
                    error_message="ffmpeg 未安装",
                )

            # Popen 启动后立即记录开始时间
            popen_time = time.time()
            _recording_start_time = popen_time

            # 启动后校验：等 2 秒检查进程存活 + 文件有数据
            time.sleep(2)
            health_check_delay = time.time() - popen_time  # 实际健康检查耗时（≈2s）
            if proc.poll() is not None:
                _, stderr = proc.communicate()
                last_error = (stderr.decode(errors="replace") or "")[-300:]
                if os.path.exists(file_path):
                    os.remove(file_path)
                continue

            if os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                state = _CameraRecState(
                    process=proc, start_time=_recording_start_time,
                    file_path=file_path, transport=transport,
                )
                _recording_states[camera_name] = state
                print(f"[recording] 录像已启动: {file_path} (transport={transport})",
                      file=sys.stderr)

                # 设置自动停止定时器（扣除 health check 已消耗的时间）
                if duration is not None and duration > 0:
                    compensated = max(
                        duration + _RECORDING_STARTUP_COMPENSATION - health_check_delay,
                        1.0,
                    )
                    state.timer = threading.Timer(
                        compensated,
                        lambda: toggle_recording(camera_name, RecordingAction.STOP),
                    )
                    state.timer.daemon = True
                    state.timer.start()
                    print(f"[recording] 已设置自动停止定时器: {compensated:.1f}s 后自动停止"
                          f"（含启动补偿，已扣除 {health_check_delay:.1f}s 健康检查延迟）",
                          file=sys.stderr)

                return RecordingResult(
                    success=True, is_recording=True,
                    file_path=file_path,
                    auto_stop=duration is not None and duration > 0,
                )

            # 文件无数据但进程还活着——可能是等待关键帧，再等一下（总窗口 2+8=10s 覆盖长 GOP）
            time.sleep(8)
            if proc.poll() is None and os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                state = _CameraRecState(
                    process=proc, start_time=_recording_start_time,
                    file_path=file_path, transport=transport,
                )
                _recording_states[camera_name] = state
                print(f"[recording] 录像已启动（等待关键帧）: {file_path} (transport={transport})",
                      file=sys.stderr)

                if duration is not None and duration > 0:
                    compensated = max(
                        duration + _RECORDING_STARTUP_COMPENSATION - health_check_delay,
                        1.0,
                    )
                    state.timer = threading.Timer(
                        compensated,
                        lambda: toggle_recording(camera_name, RecordingAction.STOP),
                    )
                    state.timer.daemon = True
                    state.timer.start()
                    print(f"[recording] 已设置自动停止定时器: {compensated:.1f}s 后自动停止"
                          f"（含启动补偿，已扣除 {health_check_delay:.1f}s 健康检查延迟）",
                          file=sys.stderr)

                return RecordingResult(
                    success=True, is_recording=True,
                    file_path=file_path,
                    auto_stop=duration is not None and duration > 0,
                )

            # transport 失败，终止进程并尝试下一个
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
            if os.path.exists(file_path):
                os.remove(file_path)
            last_error = f"transport={transport} 启动后无数据输出"

        return RecordingResult(
            success=False, is_recording=False,
            error_message=f"录像启动失败（已尝试 transport: {transport_plan}）: {last_error}",
        )

    return RecordingResult(
        success=False, is_recording=False,
        error_message=f"未知的 action: {action}",
    )


def manage_storage_status(
    camera_name: str,
    action: StorageAction = StorageAction.QUERY,
    path: Optional[str] = None,
    format: Optional[str] = None,
    policy: Optional[str] = None,
) -> StorageResult:
    """
    查询存储状态，设置存储路径与格式，存储策略。

    action=QUERY 时仅查询当前存储使用情况和配置；
    action=SET 时更新存储路径、文件格式或存储策略。

    存储策略说明：
      - overwrite:      空间不足时自动覆盖最旧文件
      - stop_when_full: 空间不足时停止录像
      - circular:       循环缓冲区模式

    安全约束: 显式提示 + 代码校验（校验路径可写、策略参数合法）

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      StorageAction.QUERY 查询 / StorageAction.SET 设置
        path:        存储路径（action=SET 时有效）
        format:      文件格式 "mp4" / "avi" / "jpg"（action=SET 时有效）
        policy:      策略名称 "overwrite" / "stop_when_full" / "circular"（action=SET 时有效）

    Returns:
        StorageResult:
            - success: 操作是否成功
            - used_space_mb: 已用空间 (MB)
            - available_space_mb: 可用空间 (MB)
            - storage_path: 当前存储路径
            - format: 文件格式
            - policy: 策略名称
            - error_message: 失败时的错误描述
    """
    import os
    import shutil

    # ── 确保有默认配置 ──
    if camera_name not in _storage_config:
        default_dir = os.path.join(os.path.dirname(__file__), "..", "..", "vido")
        _storage_config[camera_name] = {
            "path": default_dir,
            "format": "mp4",
            "policy": "stop_when_full",
        }

    cfg = _storage_config[camera_name]
    storage_path = cfg["path"]

    if action == StorageAction.SET:
        # 校验参数
        valid_formats = {"mp4", "avi", "jpg"}
        valid_policies = {"overwrite", "stop_when_full", "circular"}

        if path is not None:
            storage_path = path
            try:
                os.makedirs(storage_path, exist_ok=True)
                # 测试可写
                test_file = os.path.join(storage_path, ".write_test")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
            except Exception as e:
                return StorageResult(
                    success=False,
                    storage_path=storage_path,
                    format=cfg["format"],
                    policy=cfg["policy"],
                    error_message=f"存储路径不可写: {e}",
                )
            cfg["path"] = storage_path

        if format is not None:
            if format not in valid_formats:
                return StorageResult(
                    success=False,
                    storage_path=storage_path,
                    format=cfg["format"],
                    policy=cfg["policy"],
                    error_message=f"无效的文件格式: {format}，支持: {valid_formats}",
                )
            cfg["format"] = format

        if policy is not None:
            if policy not in valid_policies:
                return StorageResult(
                    success=False,
                    storage_path=storage_path,
                    format=cfg["format"],
                    policy=cfg["policy"],
                    error_message=f"无效的存储策略: {policy}，支持: {valid_policies}",
                )
            cfg["policy"] = policy

    # ── 查询存储使用情况 ──
    used_mb = 0.0
    available_mb = 0.0

    if os.path.exists(storage_path):
        try:
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(storage_path):
                for fname in filenames:
                    fp = os.path.join(dirpath, fname)
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError:
                        pass
            used_mb = round(total_size / (1024 * 1024), 2)
        except Exception:
            pass

    try:
        usage = shutil.disk_usage(storage_path)
        available_mb = round(usage.free / (1024 * 1024), 2)
    except Exception:
        pass

    return StorageResult(
        success=True,
        used_space_mb=used_mb,
        available_space_mb=available_mb,
        storage_path=storage_path,
        format=cfg["format"],
        policy=cfg["policy"],
    )


# ═══════════════════════════════════════════════
#  WebRTC 实时预览 (go2rtc)
# ═══════════════════════════════════════════════

_GO2RTC_RELEASE_BASE = "https://github.com/AlexxIT/go2rtc/releases/latest/download"

import os as _os
import sys as _sys

# 按平台选择二进制名
_GO2RTC_BIN_NAME = {
    "linux": "go2rtc_linux_amd64",
    "win32": "go2rtc_win64.zip",
    "darwin": "go2rtc_mac_amd64",
}.get(_sys.platform, "go2rtc_linux_amd64")

_GO2RTC_RELEASE = f"{_GO2RTC_RELEASE_BASE}/{_GO2RTC_BIN_NAME}"

# 多源下载列表（按优先级排列，国内镜像在前）
_GO2RTC_DOWNLOAD_URLS = [
    f"https://mirror.ghproxy.com/{_GO2RTC_RELEASE}",
    f"https://ghfast.top/{_GO2RTC_RELEASE}",
    _GO2RTC_RELEASE,
]

_GO2RTC_IS_WIN = _sys.platform == "win32"
_GO2RTC_SKILL_DIR = _os.path.dirname(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
)

_go2rtc_process: Optional[Any] = None


@dataclass
class WebRTCResult:
    """WebRTC 转流返回结构"""
    success: bool = False
    web_url: str = ""
    rtsp_url: str = ""
    error_message: str = ""


def _ensure_go2rtc() -> str:
    """
    检查 go2rtc 是否已安装（跨平台：Linux / Windows / macOS）。

    检查顺序：
      1. PATH 中查找 go2rtc
      2. 技能根目录下查找 go2rtc / go2rtc.exe

    Returns:
        str: go2rtc 二进制绝对路径，未找到返回空字符串。
    """
    import shutil
    path = shutil.which("go2rtc")
    if path:
        return path
    bin_name = "go2rtc.exe" if _GO2RTC_IS_WIN else "go2rtc"
    local_path = _os.path.join(_GO2RTC_SKILL_DIR, bin_name)
    if _os.path.isfile(local_path):
        return local_path
    return ""


def _download_go2rtc() -> str:
    """
    从多个源下载 go2rtc 二进制到技能根目录（跨平台，国内镜像优先）。

    Returns:
        str: 下载成功返回二进制路径，全部失败返回空字符串。
    """
    import shutil
    import urllib.request
    import zipfile

    dest_name = "go2rtc.exe" if _GO2RTC_IS_WIN else "go2rtc"
    dest = _os.path.join(_GO2RTC_SKILL_DIR, dest_name)
    tmp = _os.path.join(_GO2RTC_SKILL_DIR, f"_go2rtc_dl_{_GO2RTC_BIN_NAME}")

    for url in _GO2RTC_DOWNLOAD_URLS:
        print(f"[go2rtc] 尝试下载: {url[:80]}...")
        try:
            urllib.request.urlretrieve(url, tmp)
            if not _os.path.isfile(tmp) or _os.path.getsize(tmp) < 1024:
                print("[go2rtc] 下载文件异常（过小或 HTML 错误页），尝试下一个源")
                if _os.path.exists(tmp):
                    _os.remove(tmp)
                continue
            if _GO2RTC_IS_WIN and tmp.endswith(".zip"):
                with zipfile.ZipFile(tmp, "r") as zf:
                    exe_name = next(
                        (n for n in zf.namelist() if "go2rtc" in n and n.endswith(".exe")),
                        None,
                    )
                    if exe_name:
                        zf.extract(exe_name, _GO2RTC_SKILL_DIR)
                        extracted = _os.path.join(_GO2RTC_SKILL_DIR, exe_name)
                        if extracted != dest:
                            shutil.move(extracted, dest)
                        _os.remove(tmp)
                        print(f"[go2rtc] 下载并解压成功: {dest}")
                        return dest
                    else:
                        print("[go2rtc] zip 中未找到 go2rtc.exe，尝试下一个源")
                        _os.remove(tmp)
                        continue
            else:
                shutil.move(tmp, dest)
                _os.chmod(dest, 0o755)
                print(f"[go2rtc] 下载成功: {dest}")
                return dest
        except Exception as e:
            print(f"[go2rtc] 下载失败: {e}，尝试下一个源")
            if _os.path.exists(tmp):
                _os.remove(tmp)

    print("[go2rtc] 所有下载源均失败")
    return ""


def start_webrtc_stream(
    camera_name: str,
    sub_stream: bool = False,
    go2rtc_path: Optional[str] = None,
    port: int = 1984,
) -> WebRTCResult:
    """
    启动 go2rtc 将摄像头 RTSP 流转为 WebRTC，浏览器打开 web_url 即可实时观看。

    流程：
      1. 检查 go2rtc 是否已安装
      2. 未安装 → 返回错误 + 下载地址让 Agent 引导用户手动安装
      3. 从 config.yaml 构造 RTSP URL
      4. 生成 go2rtc.yaml 配置文件
      5. subprocess.Popen 启动 go2rtc
      6. 返回 WebRTCResult(web_url="http://localhost:<port>")

    Args:
        camera_name:  摄像头名称
        sub_stream:   True 使用子流，False 使用主流
        go2rtc_path:  go2rtc 二进制路径（None 时自动检测）
        port:         Web UI 端口（默认 1984）

    Returns:
        WebRTCResult:
            - success: 是否成功启动
            - web_url: 浏览器访问地址
            - rtsp_url: 使用的 RTSP URL
            - error_message: 失败原因
    """
    import subprocess

    global _go2rtc_process

    # 如果已有进程在运行，先停止
    if _go2rtc_process is not None:
        stop_webrtc_stream()

    # Step 1: 检查 go2rtc
    binary = go2rtc_path or _ensure_go2rtc()
    if not binary:
        return WebRTCResult(
            success=False,
            error_message=(
                f"未检测到 go2rtc（WebRTC 转流工具，约 15MB）。"
                f"请手动下载安装: {_GO2RTC_RELEASE}，"
                f"安装到 {_GO2RTC_SKILL_DIR} 或加入 PATH 后重试。"
            ),
        )

    # Step 2: 从 config.yaml 构造 RTSP URL
    from . import device_mgmt as dm
    cameras = dm.get_registered_cameras()
    target = next((c for c in cameras if c.name == camera_name), None)
    if target is None:
        return WebRTCResult(success=False, error_message=f"未找到摄像头: {camera_name}")

    rtsp_path = target.rtsp_sub_path if sub_stream else target.rtsp_path
    rtsp_url = dm._build_rtsp_url(
        target.ip, target.rtsp_port, rtsp_path, target.username, target.password,
    )

    # Step 3: 生成 go2rtc.yaml
    import yaml

    config_path = _os.path.join(_GO2RTC_SKILL_DIR, "go2rtc.yaml")
    stream_name = camera_name.replace(" ", "_")
    go2rtc_config = {
        "streams": {stream_name: rtsp_url},
        "api": {"listen": f":{port}"},
    }
    with open(config_path, "w") as f:
        yaml.dump(go2rtc_config, f, default_flow_style=False, allow_unicode=True)

    # Step 4: 启动 go2rtc
    try:
        popen_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if _GO2RTC_IS_WIN:
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        _go2rtc_process = subprocess.Popen(
            [binary, "-config", config_path],
            **popen_kwargs,
        )
    except Exception as e:
        return WebRTCResult(
            success=False,
            rtsp_url=rtsp_url,
            error_message=f"go2rtc 启动失败: {e}",
        )

    web_url = f"http://localhost:{port}"
    print(f"[go2rtc] 已启动，浏览器打开 {web_url} 观看摄像头 '{camera_name}'",
          file=_sys.stderr)
    return WebRTCResult(success=True, web_url=web_url, rtsp_url=rtsp_url)


def stop_webrtc_stream() -> bool:
    """
    停止 go2rtc 转流进程。

    Returns:
        bool: True 表示成功停止（或本来就没有运行中的进程）
    """
    global _go2rtc_process

    if _go2rtc_process is None:
        return True

    try:
        _go2rtc_process.terminate()
        _go2rtc_process.wait(timeout=5)
    except Exception:
        try:
            _go2rtc_process.kill()
        except Exception:
            pass
    finally:
        _go2rtc_process = None

    print("[go2rtc] 已停止", file=_sys.stderr)
    return True
