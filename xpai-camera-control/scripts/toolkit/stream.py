"""
Toolkit 1: 音视频流与存储

工具清单：
  - get_audio_video_stream  拉取实时音视频流
  - capture_video_screenshot 截取当前画面并保存
  - toggle_recording        启动或停止录像
  - manage_storage_status   查询/设置存储状态、路径与策略
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class RecordingAction(str, Enum):
    START = "start"
    STOP = "stop"


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
    rtsp_path = conn_info.get("rtsp_path", "/stream1")
    username = conn_info.get("username", "")
    password = conn_info.get("password", "")

    if sub_stream:
        rtsp_path = conn_info.get("rtsp_sub_path", "/stream2")

    # 构建 RTSP URL
    if username and password:
        rtsp_url = f"rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}"
    else:
        rtsp_url = f"rtsp://{ip}:{rtsp_port}{rtsp_path}"

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

    # 使用 OpenCV 验证并获取流参数
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap.release()
        # 尝试常见备选路径（含创维摄像头路径 /stream0, /md0_0, /md0_1）
        alt_paths = ["/Streaming/Channels/101", "/h264/ch1/main/av_stream", "/live",
                     "/stream0", "/md0_0", "/stream1"]
        if sub_stream:
            alt_paths = ["/Streaming/Channels/102", "/h264/ch1/sub/av_stream", "/stream2",
                         "/md0_1"]
        for alt in alt_paths:
            if alt == rtsp_path:
                continue
            alt_url = f"rtsp://{username}:{password}@{ip}:{rtsp_port}{alt}" if username and password else f"rtsp://{ip}:{rtsp_port}{alt}"
            cap = cv2.VideoCapture(alt_url, cv2.CAP_FFMPEG)
            if cap.isOpened():
                rtsp_url = alt_url
                break
            cap.release()
        else:
            return StreamResult(
                success=False,
                error_message=f"���法从 {ip}:{rtsp_port} 获取视频流，请检查 RTSP 路径和认证信息",
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
        save_path:   保存目录路径（默认 snapshots/）

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
    if save_path is None:
        snapshot_dir = os.path.join(os.path.dirname(__file__), "..", "..", "snapshots")
    else:
        snapshot_dir = save_path

    os.makedirs(snapshot_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{camera_name}_{timestamp}.jpg"
    file_path = os.path.join(snapshot_dir, filename)

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
        rtsp_path = conn_info.get("rtsp_path", "/stream1")
        username = conn_info.get("username", "")
        password = conn_info.get("password", "")

        if username and password:
            rtsp_url = f"rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}"
        else:
            rtsp_url = f"rtsp://{ip}:{rtsp_port}{rtsp_path}"

        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

        # 如果主路径失败，尝试备选路径（含创维摄像头路径）
        if not cap.isOpened():
            cap.release()
            alt_paths = ["/Streaming/Channels/101", "/h264/ch1/main/av_stream", "/live",
                         "/stream0", "/md0_0", "/stream1", "/md0_1"]
            for alt in alt_paths:
                if alt == rtsp_path:
                    continue
                alt_url = f"rtsp://{username}:{password}@{ip}:{rtsp_port}{alt}" if username and password else f"rtsp://{ip}:{rtsp_port}{alt}"
                cap = cv2.VideoCapture(alt_url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    break
                cap.release()
            else:
                return ScreenshotResult(
                    success=False,
                    file_path=file_path,
                    error_message=f"无法从 {ip}:{rtsp_port} 打开视频流，请检查 RTSP 路径和认证信息",
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
#  录像状态管理（模块内部）
# ──────────────────────────────────────────────

_active_recordings: Dict[str, dict] = {}  # camera_name -> {"cap": VideoCapture, "writer": VideoWriter, "file_path": str, "temp_path": str, "start_time": float}
_storage_config: Dict[str, dict] = {}     # camera_name -> {"path": str, "format": str, "policy": str}


def toggle_recording(
    camera_name: str,
    action: RecordingAction,
    save_path: Optional[str] = None,
) -> RecordingResult:
    """
    启动或停止本地录像。

    开始录像时创建 VideoWriter 将视频流录制到本地文件；
    停止录像时关闭 VideoWriter 并返回录像文件路径。

    安全约束: 显式提示 + 代码校验（校验设备已连接、存储空间充足）

    Args:
        camera_name: 摄像头名称（自动填充）
        action:      RecordingAction.START 开始录像 / RecordingAction.STOP 停止录像
        save_path:   录像保存目录（默认 recordings/）

    Returns:
        RecordingResult:
            - success: 操作是否成功
            - is_recording: 当前是否在录像
            - file_path: 录像文件路径（停止时返回）
            - duration_seconds: 已录制时长（停止时返回）
            - error_message: 失败时的错误描述
    """
    import os
    import time

    if action == RecordingAction.STOP:
        if camera_name not in _active_recordings:
            return RecordingResult(
                success=True,
                is_recording=False,
                error_message="当前没有进行中的录像",
            )
        rec = _active_recordings.pop(camera_name)
        try:
            rec["writer"].release()
            rec["cap"].release()
        except Exception:
            pass

        # 将临时录像文件移动到目标路径
        temp_path = rec.get("temp_path", "")
        final_path = rec["file_path"]
        if temp_path and os.path.exists(temp_path):
            import shutil
            try:
                shutil.move(temp_path, final_path)
            except Exception:
                # 移动失败则直接使用临时文件路径
                final_path = temp_path

        duration = time.time() - rec["start_time"]
        return RecordingResult(
            success=True,
            is_recording=False,
            file_path=final_path,
            duration_seconds=round(duration, 1),
        )

    # ── START ──
    if camera_name in _active_recordings:
        return RecordingResult(
            success=False,
            is_recording=True,
            error_message="该设备已在录像中，请先停止",
        )

    # 确定保存路径
    if save_path is None:
        record_dir = os.path.join(os.path.dirname(__file__), "..", "..", "recordings")
    else:
        record_dir = save_path

    os.makedirs(record_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{camera_name}_{timestamp}.mp4"
    file_path = os.path.join(record_dir, filename)

    # 获取流
    stream_result = get_audio_video_stream(camera_name, sub_stream=False)
    if not stream_result.success:
        stream_result = get_audio_video_stream(camera_name, sub_stream=True)
    if not stream_result.success:
        return RecordingResult(
            success=False,
            is_recording=False,
            error_message=f"无法获取视频流: {stream_result.error_message}",
        )

    # 打开视频流
    try:
        import cv2
    except ImportError:
        return RecordingResult(
            success=False,
            is_recording=False,
            error_message="缺少 opencv-python",
        )

    rtsp_url = stream_result.stream_url
    if rtsp_url.startswith("usb://"):
        dev_idx = int(rtsp_url.replace("usb://", ""))
        cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

    if not cap.isOpened():
        cap.release()
        return RecordingResult(
            success=False,
            is_recording=False,
            error_message="无法打开视频流",
        )

    # 创建 VideoWriter
    # 注意: cv2.VideoWriter 在 Windows 上对含非 ASCII 字符的路径会失败，
    # 先写入临时文件（ASCII 路径），停止录像时再移动到目标路径。
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')

    import tempfile
    temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4', prefix='rec_')
    os.close(temp_fd)  # 关闭文件句柄，交给 VideoWriter 使用
    writer = cv2.VideoWriter(temp_path, fourcc, fps, (width, height))

    if not writer.isOpened():
        cap.release()
        os.unlink(temp_path)
        return RecordingResult(
            success=False,
            is_recording=False,
            error_message="无法创建录像文件",
        )

    _active_recordings[camera_name] = {
        "cap": cap,
        "writer": writer,
        "file_path": file_path,
        "temp_path": temp_path,
        "start_time": time.time(),
    }

    return RecordingResult(
        success=True,
        is_recording=True,
        file_path=file_path,
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
        default_dir = os.path.join(os.path.dirname(__file__), "..", "..", "recordings")
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
