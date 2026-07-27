# Stream & Capture

Audio/video streaming, snapshot capture, and recording — `scripts/toolkit/stream.py`

---

### `get_audio_video_stream(camera_name, sub_stream: bool = False) -> StreamResult`

Fetch the real-time video stream URL.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `StreamResult` (success, stream URL, codec, resolution, frame rate) |
| **Parameters** | `camera_name`: camera identifier. `sub_stream`: use sub-stream (lower quality) if `True`. |
| **Implementation** | ONVIF: `GetStreamUri` → RTSP URL with auto-injected credentials via `_build_rtsp_url()`; USB: OpenCV `VideoCapture`. Credentials from connection state are automatically embedded in the RTSP URL. |
| **Agent behavior** | Output the `stream_url` to the user so they can open it in a media player (VLC, ffplay, PotPlayer) for live viewing. |

### `capture_video_screenshot(camera_name, save_path: str = "snapshots/") -> ScreenshotResult`

Capture a single frame from the current video stream and save as JPEG.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `ScreenshotResult` (success, file path) |
| **Parameters** | `camera_name`: camera identifier. `save_path`: output directory path. |
| **Implementation** | OpenCV `VideoCapture.read()` → `cv2.imencode()` + `numpy.tofile()`. RTSP URL auto-constructed with credentials via `_build_rtsp_url()`. Falls back to alternate RTSP paths if primary fails. |
| **Agent behavior** | Display the screenshot image to the user using the `file_path` (e.g. `![screenshot](file_path)` in markdown). |

**Note:** Uses `imencode` + `tofile` instead of `cv2.imwrite()` to support file paths containing non-ASCII characters (e.g. Chinese usernames on Windows).

### `toggle_recording(camera_name, action, save_path=None) -> RecordingResult`

Start or stop local video recording.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `RecordingResult` (recording state, file path) |
| **Parameters** | `camera_name`: camera identifier. `action`: `"start"` or `"stop"`. `save_path`: output file path (optional). |
| **Implementation** | OpenCV `VideoWriter` (MP4/H.264 encoding) |

### `manage_storage_status(action, path=None, format=None, policy=None) -> StorageResult`

Query storage usage or configure storage path, format, and policy.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `StorageResult` (used/available space, storage path, policy name) |
| **Parameters** | `action`: `"query"` or `"set"`. `path`, `format`, `policy`: set mode parameters (optional). |
