
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

class RecordingAction(str, Enum):
    START = "start"
    STOP = "stop"
    STATUS = "status"


class StorageAction(str, Enum):
    QUERY = "query"
    SET = "set"


@dataclass
class StreamResult:

    success: bool
    stream_url: str = ""
    codec: str = ""
    resolution: str = ""
    fps: float = 0.0
    bitrate: int = 0
    error_message: str = ""


@dataclass
class ScreenshotResult:
    """截图操作返回结果"""
    success: bool
    file_path: str = ""
    width: int = 0
    height: int = 0
    error_message: str = ""


@dataclass
class RecordingResult:

    success: bool
    is_recording: bool = False
    file_path: str = ""
    duration_seconds: float = 0.0
    auto_stop: bool = False
    error_message: str = ""


@dataclass
class StorageResult:

    success: bool
    used_space_mb: float = 0.0
    available_space_mb: float = 0.0
    storage_path: str = ""
    format: str = ""
    policy: str = ""
    error_message: str = ""


def _open_rtsp_capture(rtsp_url: str):

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

    from .device_mgmt import _connected_devices, _find_cached_camera
    conn_info = _connected_devices.get(camera_name)
    if not conn_info:

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

    ip = conn_info.get("ip", "")
    rtsp_port = conn_info.get("rtsp_port", 554)
    username = conn_info.get("username", "")
    password = conn_info.get("password", "")

    if sub_stream:
        rtsp_path = conn_info.get("rtsp_sub_path") or "/md0_1"
    else:
        rtsp_path = conn_info.get("rtsp_path") or "/md0_0"

    from .device_mgmt import _build_rtsp_url
    rtsp_url = _build_rtsp_url(ip, rtsp_port, rtsp_path, username, password)

    try:
        import cv2
    except ImportError:
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

    cap = _open_rtsp_capture(rtsp_url)
    if not cap.isOpened():
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

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    codec_map = {
        0x31637661: "H.264",
        0x31637668: "H.265",
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

    import os
    import time

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

_RECORDING_STARTUP_COMPENSATION = 1.5

_storage_config: Dict[str, dict] = {}     # camera_name -> {"path": str, "format": str, "policy": str}


_VALID_RTSP_TRANSPORTS = frozenset({"tcp", "udp"})


def _resolve_binary(name: str) -> Optional[str]:

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


_IS_WINDOWS = os.name == "nt"


def _send_ffmpeg_interrupt(proc: subprocess.Popen) -> None:

    try:
        if _IS_WINDOWS:
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
    except (OSError, ValueError):
        pass


@dataclass
class _CameraRecState:

    process: Optional[subprocess.Popen] = None
    start_time: Optional[float] = None
    file_path: str = ""
    transport: str = ""
    timer: Optional[threading.Timer] = None
    log_handle: Any = None


_recording_states: Dict[str, _CameraRecState] = {}


_VIDEO_DIR = Path(__file__).resolve().parent.parent.parent / "video"
_REC_STATE_FILE = _VIDEO_DIR / "recording_state.json"


def _load_rec_state_file() -> Dict[str, dict]:
    try:
        with open(_REC_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_rec_state_file(states: Dict[str, dict]) -> None:
    try:
        os.makedirs(_VIDEO_DIR, exist_ok=True)
        with open(_REC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(states, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _persist_rec_start(camera_name: str, pid: int, file_path: str,
                       stop_at: Optional[float]) -> None:
    states = _load_rec_state_file()
    states[camera_name] = {
        "pid": pid,
        "file_path": file_path,
        "start_time": time.time(),
        "stop_at": stop_at,
    }
    _write_rec_state_file(states)


def _persist_rec_remove(camera_name: str) -> None:
    states = _load_rec_state_file()
    if camera_name in states:
        states.pop(camera_name)
        _write_rec_state_file(states)


def _rec_pid_alive(pid: int) -> bool:

    try:
        import psutil
        proc = psutil.Process(pid)
        return proc.is_running() and "ffmpeg" in proc.name().lower()
    except Exception:
        return False


def _get_live_persisted_recording(camera_name: str) -> Optional[dict]:

    states = _load_rec_state_file()
    entry = states.get(camera_name)
    if not entry:
        return None
    pid = entry.get("pid", 0)
    if isinstance(pid, int) and pid > 0 and _rec_pid_alive(pid):
        return entry

    states.pop(camera_name, None)
    _write_rec_state_file(states)
    return None


def _stop_orphan_recording(camera_name: str, entry: dict) -> "RecordingResult":

    pid = entry["pid"]
    file_path = entry.get("file_path", "")
    start_time = entry.get("start_time") or time.time()

    try:
        if _IS_WINDOWS:
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(pid, signal.SIGINT)
    except OSError:
        pass

    deadline = time.time() + 15
    while time.time() < deadline and _rec_pid_alive(pid):
        time.sleep(0.5)
    if _rec_pid_alive(pid):
        try:
            import psutil
            psutil.Process(pid).kill()
        except Exception:
            pass

    _persist_rec_remove(camera_name)

    actual_duration = _get_video_duration(file_path) if file_path else None
    elapsed = time.time() - start_time
    reported_duration = actual_duration if actual_duration is not None else round(elapsed, 2)

    if not file_path or not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
        return RecordingResult(
            success=False, is_recording=False,
            duration_seconds=reported_duration,
            error_message="录像文件为空或不存在，录像可能未成功启动",
        )

    _remove_log_if_empty(file_path)
    return RecordingResult(
        success=True, is_recording=False,
        file_path=file_path,
        duration_seconds=reported_duration,
    )


def _read_log_tail(log_path: str, n: int = 300) -> str:

    try:
        with open(log_path, "rb") as f:
            data = f.read()
        return data[-n:].decode(errors="replace")
    except OSError:
        return ""


def _remove_log_if_empty(video_path: str) -> None:

    log_path = os.path.splitext(video_path)[0] + ".log"
    try:
        if os.path.isfile(log_path) and os.path.getsize(log_path) == 0:
            os.remove(log_path)
    except OSError:
        pass


def _get_video_duration(file_path: str) -> Optional[float]:

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

        persisted = _get_live_persisted_recording(camera_name)
        if persisted:
            elapsed = time.time() - persisted.get("start_time", time.time())
            return RecordingResult(
                success=True, is_recording=True,
                file_path=persisted.get("file_path", ""),
                duration_seconds=round(elapsed, 2),
                auto_stop=persisted.get("stop_at") is not None,
            )
        return RecordingResult(
            success=True, is_recording=False,
            error_message="当前没有正在进行的录像",
        )

    if action == RecordingAction.STOP:
        state = _recording_states.get(camera_name)
        if not state or state.process is None:

            persisted = _get_live_persisted_recording(camera_name)
            if persisted:
                return _stop_orphan_recording(camera_name, persisted)
            return RecordingResult(
                success=False, is_recording=False,
                error_message="当前没有正在进行的录像",
            )

        if state.timer is not None:
            state.timer.cancel()
            state.timer = None

        proc = state.process
        start_time = state.start_time or time.time()
        file_path = state.file_path

        _send_ffmpeg_interrupt(proc)

        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass

        if state.log_handle is not None:
            try:
                state.log_handle.close()
            except OSError:
                pass

        actual_duration = _get_video_duration(file_path)
        elapsed = time.time() - start_time
        reported_duration = actual_duration if actual_duration is not None else round(elapsed, 2)

        _recording_states.pop(camera_name, None)
        _persist_rec_remove(camera_name)

        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            return RecordingResult(
                success=False, is_recording=False,
                duration_seconds=reported_duration,
                error_message="录像文件为空或不存在，录像可能未成功启动",
            )

        _remove_log_if_empty(file_path)

        return RecordingResult(
            success=True, is_recording=False,
            file_path=file_path,
            duration_seconds=reported_duration,
        )

    if action == RecordingAction.START:
        existing = _recording_states.get(camera_name)
        if existing and existing.process is not None and existing.process.poll() is None:
            return RecordingResult(
                success=False, is_recording=True,
                error_message=f"摄像头 {camera_name} 正在录像（文件: {existing.file_path}），请先停止再开始",
            )
        if existing:
            if existing.timer is not None:
                existing.timer.cancel()
            _recording_states.pop(camera_name, None)

        persisted = _get_live_persisted_recording(camera_name)
        if persisted:
            return RecordingResult(
                success=False, is_recording=True,
                file_path=persisted.get("file_path", ""),
                error_message=f"摄像头 {camera_name} 正在录像（文件: {persisted.get('file_path', '')}），"
                              f"若为重试调用则无需重复启动；如需重新录像请先调用 stop",
            )

        ffmpeg_path = _resolve_binary("ffmpeg")
        if not ffmpeg_path:
            return RecordingResult(
                success=False, is_recording=False,
                error_message="ffmpeg 未安装，无法录像",
            )

        from .device_mgmt import _connected_devices, _find_cached_camera, _build_rtsp_url
        conn_info = _connected_devices.get(camera_name)
        cached = _find_cached_camera(camera_name)
        if not conn_info and not cached:
            return RecordingResult(
                success=False, is_recording=False,
                error_message=f"摄像头 '{camera_name}' 未注册",
            )

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

        recording_dir = save_path or str(
            Path(__file__).resolve().parent.parent.parent / "video"
        )
        try:
            os.makedirs(recording_dir, exist_ok=True)
        except OSError as e:
            return RecordingResult(
                success=False, is_recording=False,
                error_message=f"创建录像目录失败: {e}",
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(recording_dir, f"recording_{camera_name}_{timestamp}.mp4")

        try:
            transport_plan = _resolve_transport_plan(rtsp_transport)
        except ValueError as e:
            return RecordingResult(
                success=False, is_recording=False,
                error_message=str(e),
            )

        working_transport = ""
        for transport in transport_plan:
            dims = _probe_dimensions(rtsp_url, [transport], timeout=10)
            if dims != (0, 0):
                working_transport = transport
                break

        if not working_transport:
            working_transport = transport_plan[0]

        ffmpeg_timeout = None
        if duration is not None and duration > 0:
            ffmpeg_timeout = duration + _RECORDING_STARTUP_COMPENSATION + 5.0

        last_error = ""
        for transport in ([working_transport] + [t for t in transport_plan if t != working_transport]):
            ffmpeg_cmd = [
                ffmpeg_path, "-y",
                "-loglevel", "error",
                "-nostats",
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

            log_path = os.path.splitext(file_path)[0] + ".log"
            try:
                log_handle = open(log_path, "wb")
            except OSError:
                log_handle = None
            popen_kwargs = dict(
                stdout=subprocess.DEVNULL,
                stderr=log_handle if log_handle is not None else subprocess.DEVNULL,
            )
            if _IS_WINDOWS:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(ffmpeg_cmd, **popen_kwargs)
            except FileNotFoundError:
                if log_handle is not None:
                    log_handle.close()
                return RecordingResult(
                    success=False, is_recording=False,
                    error_message="ffmpeg 未安装",
                )

            popen_time = time.time()
            _recording_start_time = popen_time

            time.sleep(2)
            health_check_delay = time.time() - popen_time
            if proc.poll() is not None:

                if log_handle is not None:
                    log_handle.close()
                    log_handle = None
                last_error = _read_log_tail(log_path, 300)
                for p in (file_path, log_path):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except OSError:
                        pass
                continue

            if os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                state = _CameraRecState(
                    process=proc, start_time=_recording_start_time,
                    file_path=file_path, transport=transport,
                    log_handle=log_handle,
                )
                _recording_states[camera_name] = state
                print(f"[recording] 录像已启动: {file_path} (transport={transport})",
                      file=sys.stderr)

                stop_at = None
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
                    stop_at = time.time() + compensated
                    print(f"[recording] 已设置自动停止定时器: {compensated:.1f}s 后自动停止"
                          f"（含启动补偿，已扣除 {health_check_delay:.1f}s 健康检查延迟）",
                          file=sys.stderr)

                _persist_rec_start(camera_name, proc.pid, file_path, stop_at)

                return RecordingResult(
                    success=True, is_recording=True,
                    file_path=file_path,
                    auto_stop=duration is not None and duration > 0,
                )

            time.sleep(8)
            if proc.poll() is None and os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                state = _CameraRecState(
                    process=proc, start_time=_recording_start_time,
                    file_path=file_path, transport=transport,
                    log_handle=log_handle,
                )
                _recording_states[camera_name] = state
                print(f"[recording] 录像已启动（等待关键帧）: {file_path} (transport={transport})",
                      file=sys.stderr)

                stop_at = None
                if duration is not None and duration > 0:
                    health_check_delay = time.time() - popen_time
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
                    stop_at = time.time() + compensated
                    print(f"[recording] 已设置自动停止定时器: {compensated:.1f}s 后自动停止"
                          f"（含启动补偿，已扣除 {health_check_delay:.1f}s 健康检查延迟）",
                          file=sys.stderr)

                _persist_rec_start(camera_name, proc.pid, file_path, stop_at)

                return RecordingResult(
                    success=True, is_recording=True,
                    file_path=file_path,
                    auto_stop=duration is not None and duration > 0,
                )

            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

            if log_handle is not None:
                log_handle.close()
                log_handle = None
            for p in (file_path, log_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
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
    import os
    import shutil

    if camera_name not in _storage_config:
        default_dir = os.path.join(os.path.dirname(__file__), "..", "..", "video")
        _storage_config[camera_name] = {
            "path": default_dir,
            "format": "mp4",
            "policy": "stop_when_full",
        }

    cfg = _storage_config[camera_name]
    storage_path = cfg["path"]

    if action == StorageAction.SET:
        valid_formats = {"mp4", "avi", "jpg"}
        valid_policies = {"overwrite", "stop_when_full", "circular"}

        if path is not None:
            storage_path = path
            try:
                os.makedirs(storage_path, exist_ok=True)
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

_GO2RTC_RELEASE_BASE = "https://github.com/AlexxIT/go2rtc/releases/latest/download"

import os as _os
import sys as _sys

_GO2RTC_BIN_NAME = {
    "linux": "go2rtc_linux_amd64",
    "win32": "go2rtc_win64.zip",
    "darwin": "go2rtc_mac_amd64",
}.get(_sys.platform, "go2rtc_linux_amd64")

_GO2RTC_RELEASE = f"{_GO2RTC_RELEASE_BASE}/{_GO2RTC_BIN_NAME}"

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
    success: bool = False
    web_url: str = ""
    rtsp_url: str = ""
    error_message: str = ""


def _ensure_go2rtc() -> str:

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

    import subprocess

    global _go2rtc_process

    if _go2rtc_process is not None:
        stop_webrtc_stream()

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

    from . import device_mgmt as dm
    cameras = dm.get_registered_cameras()
    target = next((c for c in cameras if c.name == camera_name), None)
    if target is None:
        return WebRTCResult(success=False, error_message=f"未找到摄像头: {camera_name}")

    rtsp_path = target.rtsp_sub_path if sub_stream else target.rtsp_path
    rtsp_url = dm._build_rtsp_url(
        target.ip, target.rtsp_port, rtsp_path, target.username, target.password,
    )

    import yaml

    config_path = _os.path.join(_GO2RTC_SKILL_DIR, "go2rtc.yaml")
    stream_name = camera_name.replace(" ", "_")
    go2rtc_config = {
        "streams": {stream_name: rtsp_url},
        "api": {"listen": f":{port}"},
    }
    with open(config_path, "w") as f:
        yaml.dump(go2rtc_config, f, default_flow_style=False, allow_unicode=True)

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
