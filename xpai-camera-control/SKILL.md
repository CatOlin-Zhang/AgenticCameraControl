---
name: xpai-camera-control
description: Discover, connect, and control Skyworth cameras on the local network. Capabilities include device detection, streaming, snapshot capture, PTZ pan/tilt/zoom control, device management, AI tracking, alarm configuration, video encoding settings, and picture/audio adjustments. Supports both WorkBuddy Skill mode and MCP Server mode. Use when the user wants to discover cameras, view a camera feed, capture snapshots, control PTZ, manage camera settings, or mentions ONVIF, RTSP, IP camera, webcam, or Skyworth cameras.
license: MIT
compatibility: Requires Python 3.10+, OpenCV, onvif-zeep, requests, psutil, PyYAML, and mcp. Cameras must be on the same LAN for discovery.
metadata:
  version: "0.2.0"
---

# Camera Control Skill

## When to Use

Trigger this skill when the user:
- Wants to see a camera feed, capture a snapshot, or record video
- Asks to find or discover cameras on the network
- Requests pan, tilt, zoom, or camera movement
- Mentions ONVIF, RTSP, IP camera, webcam, or specific camera brands
- Wants to configure camera settings (night vision, alarms, video encoding, OSD)
- Wants to set up this skill as an MCP server for use with MCP-compatible clients

## Running Modes

### Mode 1: WorkBuddy Skill (default)
Load this SKILL.md in WorkBuddy and the toolkit functions are called directly via `import scripts.toolkit as tk`. No additional setup needed.

### Mode 2: MCP Server
Run `scripts/mcp_server.py` as a standalone MCP server that exposes all camera control functions as MCP tools via stdio transport. Compatible with any MCP client (Claude Desktop, WorkBuddy, etc.).

```bash
# Install dependencies
pip install -r requirements.txt

# Run MCP server
python scripts/mcp_server.py
```

**MCP Configuration** — Add to your MCP client's config:
```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "python",
      "args": ["scripts/mcp_server.py"],
      "cwd": "/path/to/xpai-camera-control"
    }
  }
}
```

The MCP server exposes **31 tools** covering all 8 toolkit modules. See [references/COMMANDS.md](references/COMMANDS.md) for the complete list of tool signatures and parameters.

## Core Workflow

### Phase 0 — Session Init (must be done at the very beginning of the session)

At the beginning of each session, check if there are any registered cameras in config.yaml:

1. Call `get_registered_cameras()` to read the camera configurations (including credentials) saved in config.yaml
2. For each registered camera, call `connect_device(cam.name)` — the tool will automatically use the credentials in config.yaml to connect, **no need for the user to input a password again**
3. If config.yaml is empty or all registered cameras fail to connect → enter Phase 1

### Phase 1 — Discover Cameras

When Phase 0 cache is unavailable, call `search_devices()` to discover cameras on the local network.

### Phase 2 — Connect & Authorize

For each discovered camera, call `connect_device()` to connect. **The specific connection process is handled internally by the tool** (stream probe → detect auth requirement → connect or prompt). The Agent's responsibilities are as follows:

| Scenario | Agent Operation |
|----------|----------------|
| **direct_connect** (stream probe succeeds) | Tool connects directly via RTSP → `ConnectResult(auth_method="direct")` — no user interaction |
| **needs_password** (stream probe returns 401) | Tool returns `ConnectResult(status="needs_password", needs_password=True)` → Agent prompts user for password → Agent calls `connect_device(name, password=user_input)` with the IP/port info from the first call |
| **Cached credentials** (config.yaml has password) | Tool auto-loads credentials → connects via ONVIF/RTSP/TCP → `ConnectResult(success=True)` — no user interaction |
| **Connection successful** | Agent calls `register_camera()` to persist credentials to config.yaml → future sessions auto-connect via Phase 0 |

### Phase 3 — Stream & Capture

After a successful connection, perform streaming operations:
- `capture_video_screenshot()` — captures a single frame from the RTSP stream and saves it as JPEG (uses OpenCV, auto-discards initial buffered frames for a clean capture)
- `get_audio_video_stream()` — retrieves the RTSP stream URL and validates stream availability, returns codec/resolution/fps metadata
- `toggle_recording()` — starts/stops local MP4 recording from the RTSP stream via OpenCV VideoWriter
- `manage_storage_status()` — queries disk usage and configures storage path/format/policy

Screenshot files are saved to `snapshots/` directory by default; recordings go to `recordings/`.

### Phase 4 — PTZ Control

Only ONVIF cameras support: `control_ptz()` for direction control, `save_ptz_preset()` / `go_to_preset()` for presets. USB and pure RTSP cameras do not support PTZ.

Detailed code examples and parameter descriptions are available in [references/WORKFLOW.md](references/WORKFLOW.md).

## Toolkit Modules

8 modules in `scripts/toolkit/`, call with `import scripts.toolkit as tk`:

| Module | Key Functions | Purpose |
|--------|--------------|--------|
| `device_mgmt.py` | `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device` | Config, discovery, connection, management |
| `discovery.py` | `discover_sky_devices`, `send_tcp_command`, `SkyDiscoveryListener` | Skyworth private protocol discovery & TCP channel |
| `stream.py` | `capture_video_screenshot`, `get_audio_video_stream`, `toggle_recording`, `manage_storage_status` | Streaming, screenshot (OpenCV), recording (OpenCV), storage |
| `ptz.py` | `control_ptz`, `control_lens_zoom`, `save_ptz_preset`, `go_to_preset` | PTZ control |
| `tracking.py` | `track_human_shapes`, `track_vehicles`, `monitor_zone_entry` | AI tracking |
| `image_audio.py` | `adjust_picture_settings`, `configure_night_vision`, `configure_microphone` | Image and audio settings |
| `alarm.py` | `configure_alarm_settings`, `configure_alarm_push` | Alarm settings |
| `encoding_osd.py` | `configure_video_encoding`, `configure_osd_settings` | Encoding and OSD |

Complete function signatures and security constraints are listed in [references/COMMANDS.md](references/COMMANDS.md).

## Security Constraints

| Constraint | Rule | Applies To |
|------------|------|-----------|
| **Explicit Prompt** | Inform the user of the operation content before execution and wait for confirmation | PTZ, streaming, screenshots, picture settings, tracking |
| **Code Validation** | Validate parameters, device status, and connection availability | Recording, microphone/speaker, firmware update, alarm configuration |
| **Explicit Authorization** | Requires user password input | Firmware update, restart, factory reset, alarm push |


## Configuration

Camera configurations are saved in the skill's root directory under `config.yaml`. After a successful connection, the credentials are automatically written to config.yaml and are reused in subsequent conversations. Complete schema can be found in [references/CONFIG.md](references/CONFIG.md).

## MCP Server Tools

When running in MCP server mode, all toolkit functions are exposed as MCP tools. The complete list of 29 tools:

**Device Management (7):** `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device`, `query_device_model`, `poll_auth_status`

**Stream & Capture (4):** `get_audio_video_stream`, `capture_video_screenshot`, `toggle_recording`, `manage_storage_status`

**PTZ Control (6):** `control_ptz`, `control_lens_zoom`, `get_ptz_parameters`, `save_ptz_preset`, `go_to_preset`, `start_patrol_cruise`

**AI Tracking (3):** `track_vehicles`, `track_human_shapes`, `monitor_zone_entry`

**Image & Audio (6):** `adjust_picture_settings`, `flip_video_display`, `configure_night_vision`, `set_floodlight_mode`, `configure_microphone`, `configure_speaker`

**Alarm (2):** `configure_alarm_settings`, `configure_alarm_push`

**Encoding & OSD (2):** `configure_video_encoding`, `configure_osd_settings`

**Discovery (2):** `discover_sky_devices`, `send_tcp_command`

## Limitations

- Cameras and host must be on the same local network
- RTSP streams require local network connectivity
- Password-required cameras return `needs_password` status if no cached credentials exist
- Screenshot/recording requires `opencv-python` (included in requirements.txt)
- MCP server mode uses stdio transport only

## Known Issues & Notes

### Chinese character paths (Windows)

OpenCV's `cv2.imwrite()` and `cv2.VideoWriter()` silently fail when the file path contains non-ASCII characters (e.g. Chinese usernames in the Windows user directory). The toolkit works around this by:
- **Screenshots:** Using `cv2.imencode()` + `numpy.tofile()` instead of `cv2.imwrite()`
- **Recordings:** Writing to a temporary file via `tempfile.mkstemp()` (ASCII path), then moving to the final destination on stop

If `save_path` is provided, ensure it is writable. The default `snapshots/` and `recordings/` directories are created automatically.

### Same-process connection requirement

The toolkit stores connection state in an in-memory dict (`_connected_devices`). This means `connect_device()` and subsequent operations (`capture_video_screenshot()`, `get_audio_video_stream()`, etc.) must run in the **same Python process**. If using the toolkit via shell commands, combine connect + capture in a single script invocation:

```python
import scripts.toolkit as tk
tk.connect_device("172.28.234.22")
result = tk.capture_video_screenshot("172.28.234.22")
print(result.file_path)
```

### Skyworth camera RTSP paths

Skyworth IP cameras (discovered via `sky_discovery`) use non-standard RTSP paths. The toolkit automatically tries these paths in order:

| Path | Stream | Typical Resolution |
|------|--------|-------------------|
| `/stream0` | Main stream | 2560x1440 |
| `/stream1` | Main stream (alt) | 2560x1440 |
| `/md0_0` | Main stream (alt) | 2560x1440 |
| `/md0_1` | Sub stream | 1280x720 |

Standard ONVIF paths (`/Streaming/Channels/101`, `/h264/ch1/main/av_stream`, `/live`) are also tried as fallbacks.


## References

- [references/WORKFLOW.md](references/WORKFLOW.md) — Complete workflow examples and code snippets
- [references/COMMANDS.md](references/COMMANDS.md) — Full function signatures, parameters, return values, and security constraints
- [references/ARCHITECTURE.md](references/ARCHITECTURE.md) — System architecture, connection flow, device discovery protocols, and session rules
- [references/CONFIG.md](references/CONFIG.md) — config.yaml complete schema and examples
- [requirements.txt](requirements.txt) — Python dependencies for both Skill and MCP Server modes
