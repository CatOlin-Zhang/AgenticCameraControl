# Stream & Capture

Audio/video streaming, snapshot capture, and recording — exposed as MCP tools by `scripts/mcp_server.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

---

### `get_audio_video_stream(camera_name, sub_stream: bool = False) -> StreamResult`

Fetch the real-time video stream URL.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `StreamResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `sub_stream`: use sub-stream (lower quality) if `True`. |
| **Agent behavior** | Output the `stream_url` to the user so they can open it in a media player (VLC, ffplay, PotPlayer) for live viewing. |

**StreamResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the stream URL was retrieved |
| `stream_url` | string | RTSP URL with auto-injected credentials (e.g. `rtsp://admin:***@192.168.1.100:554/stream1`) |
| `codec` | string | Video codec: `"H.264"` / `"H.265"` / `"MJPEG"` |
| `resolution` | string | Resolution string (e.g. `"2560x1440"`) |
| `fps` | float | Frame rate |
| `bitrate` | int | Bitrate in kbps (0 if unavailable) |
| `error_message` | string | Failure reason (empty on success) |

---

### `capture_video_screenshot(camera_name, save_path: Optional[str] = None) -> ScreenshotResult`

Capture a single frame from the current video stream and save as JPEG.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `ScreenshotResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `save_path`: output directory path (optional; defaults to `snapshots/`). |
| **Agent behavior** | Display the screenshot image to the user using the `file_path` (e.g. `![screenshot](file_path)` in markdown). |

**ScreenshotResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the screenshot was captured |
| `file_path` | string | Full path of the saved JPEG file |
| `width` | int | Image width in pixels |
| `height` | int | Image height in pixels |
| `error_message` | string | Failure reason (empty on success) |

**Note:** Uses `imencode` + `tofile` instead of `cv2.imwrite()` to support file paths containing non-ASCII characters (e.g. Chinese usernames on Windows).

---

### `toggle_recording(camera_name, action, save_path=None, duration=None) -> RecordingResult`

Start, stop, or query the status of local video recording.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `RecordingResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `action`: `"start"`, `"stop"`, or `"status"`. `save_path`: recording directory (optional; defaults to `video/`). `duration`: recording duration in seconds (optional, auto-stops when set; only for `start`). |

**RecordingResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the operation succeeded |
| `is_recording` | bool | Current recording state (`true` after start, `false` after stop/status query) |
| `file_path` | string | Recording file path (populated on stop) |
| `duration_seconds` | float | Recorded duration in seconds (populated on stop) |
| `error_message` | string | Failure reason (empty on success) |

---

### `manage_storage_status(camera_name, action="query", path=None, format=None, policy=None) -> StorageResult`

Query storage usage or configure storage path, format, and policy.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `StorageResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `action`: `"query"` or `"set"`. `path`, `format` (`"mp4"`/`"avi"`/`"jpg"`), `policy` (`"overwrite"`/`"stop_when_full"`/`"circular"`): set mode parameters (optional). |

**StorageResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the operation succeeded |
| `used_space_mb` | float | Used storage space in MB |
| `available_space_mb` | float | Available storage space in MB |
| `storage_path` | string | Current storage directory path |
| `format` | string | File format: `"mp4"` / `"avi"` / `"jpg"` |
| `policy` | string | Storage policy: `"overwrite"` / `"stop_when_full"` / `"circular"` |
| `error_message` | string | Failure reason (empty on success) |
