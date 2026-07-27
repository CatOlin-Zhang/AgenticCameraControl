---
name: xpai-camera-control
description: Discover, connect, and control Skyworth cameras on the local network. Capabilities include device detection, streaming, snapshot capture, PTZ pan/tilt/zoom control, device management, AI tracking, alarm configuration, video encoding settings, and picture/audio adjustments. Runs as an MCP Server. Use when the user wants to discover cameras, view a camera feed, capture snapshots, control PTZ, manage camera settings, or mentions ONVIF, RTSP, IP camera, webcam, or Skyworth cameras.
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
- Requests pan, tilt, zoom, camera movement, or PTZ calibration
- Mentions ONVIF, RTSP, IP camera, webcam, or specific camera brands
- Wants to configure camera settings (night vision, alarms, video encoding, OSD)
- Wants to set up this skill as an MCP server for use with MCP-compatible clients

## Running Mode: MCP Server

Run `scripts/mcp_server.py` as a standalone MCP server that exposes all camera control functions as MCP tools via stdio transport. Compatible with any MCP client (Claude Desktop, etc.).

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

The MCP server exposes **33 tools** covering all 8 toolkit modules. See [references/commands/](references/commands/) for per-module tool signatures and parameters.

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

PTZ control uses a **dual-protocol strategy**: ONVIF is tried first, automatically falling back to the Skyworth private protocol (`SK_SETTING_SET_PTZ` via TCP port 9010) when ONVIF is unavailable.

| Capability | Tools | Protocol |
|------------|-------|----------|
| Directional movement (8 directions) | `control_ptz` | ONVIF → private fallback |
| Zoom in/out | `control_lens_zoom` | ONVIF → private fallback |
| Get position & ranges | `get_ptz_parameters` | ONVIF → private fallback |
| Stop all movement | `stop_ptz` | ONVIF → private fallback |
| Save/go to preset | `save_ptz_preset`, `go_to_preset` | ONVIF only |
| Physical calibration | `calibrate_ptz` | Private protocol only |
| Move to absolute (x,y,z) | `move_to_position` | Private protocol only |
| Patrol cruise | `start_patrol_cruise` | ONVIF only |

`control_ptz` and `control_lens_zoom` auto-stop after `duration_seconds` (default 1s) and 1.5s respectively. Direction parameter supports both English (`up`/`down`/`left`/`right`/`upleft`/`upright`/`downleft`/`downright`) and Chinese aliases (上/下/左/右/左上/右上/左下/右下).

Detailed code examples and parameter descriptions are available in [references/WORKFLOW.md](references/WORKFLOW.md).

## Toolkit Modules

8 modules in `scripts/toolkit/`:

| Module | Key Functions | Reference |
|--------|--------------|----------|
| `device_mgmt.py` | `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device` | [commands/device_mgmt.md](references/commands/device_mgmt.md) |
| `discovery.py` | `discover_sky_devices`, `SkyDiscoveryListener` | [commands/discovery.md](references/commands/discovery.md) |
| `stream.py` | `capture_video_screenshot`, `get_audio_video_stream`, `toggle_recording`, `manage_storage_status` | [commands/stream.md](references/commands/stream.md) |
| `ptz.py` | `control_ptz`, `control_lens_zoom`, `get_ptz_parameters`, `save_ptz_preset`, `go_to_preset`, `calibrate_ptz`, `move_to_position`, `stop_ptz`, `start_patrol_cruise` | [commands/ptz.md](references/commands/ptz.md) |
| `tracking.py` | `track_human_shapes`, `track_vehicles`, `monitor_zone_entry` | [commands/tracking.md](references/commands/tracking.md) |
| `image_audio.py` | `adjust_picture_settings`, `flip_video_display`, `configure_night_vision`, `set_floodlight_mode`, `configure_microphone`, `configure_speaker` | [commands/image_audio.md](references/commands/image_audio.md) |
| `alarm.py` | `configure_alarm_settings`, `configure_alarm_push` | [commands/alarm.md](references/commands/alarm.md) |
| `encoding_osd.py` | `configure_video_encoding`, `configure_osd_settings` | [commands/encoding_osd.md](references/commands/encoding_osd.md) |

## Security Constraints

| Constraint | Rule | Applies To |
|------------|------|-----------|
| **Explicit Prompt** | Inform the user of the operation content before execution and wait for confirmation | PTZ, streaming, screenshots, picture settings, tracking |
| **Code Validation** | Validate parameters, device status, and connection availability | Recording, microphone/speaker, firmware update, alarm configuration |
| **Explicit Authorization** | Requires user password input | Firmware update, restart, factory reset, alarm push |


## Configuration

Camera configurations are saved in the skill's root directory under `config.yaml`. After a successful connection, the credentials are automatically written to config.yaml and are reused in subsequent conversations. Complete schema can be found in [references/CONFIG.md](references/CONFIG.md).

## Limitations

- Cameras and host must be on the same local network
- RTSP streams require local network connectivity
- Password-required cameras return `needs_password` status if no cached credentials exist
- Screenshot/recording requires `opencv-python` (included in requirements.txt)
- MCP server mode uses stdio transport only

## References

- [references/commands/](references/commands/) — Per-module tool reference (parameter signatures, safety constraints, implementation details)
- [references/WORKFLOW.md](references/WORKFLOW.md) — Complete workflow examples and code snippets
- [references/ARCHITECTURE.md](references/ARCHITECTURE.md) — System architecture, connection flow, device discovery protocols, session rules, and known issues
- [references/CONFIG.md](references/CONFIG.md) — config.yaml complete schema and examples
- [requirements.txt](requirements.txt) — Python dependencies for MCP Server mode
