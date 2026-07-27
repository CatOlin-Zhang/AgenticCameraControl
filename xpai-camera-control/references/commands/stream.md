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
| **Implementation** | ONVIF: `GetStreamUri` → RTSP URL; USB: OpenCV `VideoCapture` |

### `capture_video_screenshot(camera_name, save_path: str = "snapshots/") -> ScreenshotResult`

Capture a single frame from the current video stream and save as JPEG.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `ScreenshotResult` (success, file path) |
| **Parameters** | `camera_name`: camera identifier. `save_path`: output directory path. |
| **Implementation** | OpenCV `VideoCapture.read()` → `cv2.imencode()` + `numpy.tofile()` |

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
