# Stream & Capture

Audio/video streaming, snapshot capture, and recording — exposed as MCP tools by `scripts/mcp_server.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

---

### `get_audio_video_stream(camera_name, sub_stream: bool = False, timeout_seconds: Optional[float] = None) -> StreamResult`

Fetch the real-time video stream URL.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `StreamResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `sub_stream`: use sub-stream (lower quality) if `True`. `timeout_seconds`: max wait in seconds for the stream probe (default 20, max 120); raise it for known slow devices. |
| **Agent behavior** | Output the `stream_url` to the user so they can open it in a media player (VLC, ffplay, PotPlayer) for live viewing. |

**Execution model:** the stream probe runs in a **global serial slot** (mutually exclusive with screenshot / recording establishment) via an ffmpeg/ffprobe subprocess with hard timeouts — on timeout the subprocess is killed and the device RTSP session is released immediately; the call can never hang indefinitely. If the camera is **currently recording**, no second RTSP session is opened: the URL is returned with `success=true`, empty metadata, and an explanatory `error_message`.

**Timeout errors:** a tool-level timeout returns `{"success": false, "error_code": "timeout", ...}`; a busy slot returns an error message containing `stream_busy` semantics ("另一个流操作…正在进行"). On timeout, the Agent may retry once with a larger `timeout_seconds`.

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

### `capture_video_screenshot(camera_name, save_path: Optional[str] = None, timeout_seconds: Optional[float] = None) -> ScreenshotResult`

Capture a single frame from the current video stream and save as JPEG.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `ScreenshotResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `save_path`: output directory path (optional; defaults to `snapshots/`). `timeout_seconds`: max wait in seconds for the frame grab (default 20, max 120); raise it for known slow devices. |
| **Agent behavior** | Display the screenshot image to the user using the `file_path` (e.g. `![screenshot](file_path)` in markdown). |

**Execution model:** RTSP screenshots run in a **global serial slot** via an ffmpeg subprocess (path main↔sub × transport tcp→udp fallback inside); on timeout the subprocess is killed and the device session released — the call cannot hang indefinitely. **Recording conflict:** if the camera is currently recording, the screenshot is **rejected** (one long session already occupies a device RTSP slot; opening a second may exhaust the device's session limit) — stop the recording first. Multiple cameras: screenshots to *different* cameras are serialized by the slot (one burst at a time), which is intentional to avoid concurrent-decode/session contention.

**Timeout errors:** a tool-level timeout returns `{"success": false, "error_code": "timeout", ...}`; a busy slot returns "另一个流操作…正在进行". On timeout, the Agent may retry once with a larger `timeout_seconds`.

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
