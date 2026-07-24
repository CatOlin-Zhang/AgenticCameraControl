---
name: xpai-camera-control
description: Discover, connect, and control Skyworth cameras on the local network. Capabilities include device detection, streaming, snapshot capture, PTZ pan/tilt/zoom control, device management, AI tracking, alarm configuration, video encoding settings, and picture/audio adjustments. Use when the user wants to discover cameras, view a camera feed, capture snapshots, control PTZ, manage camera settings, or mentions ONVIF, RTSP, IP camera, webcam, or Skyworth cameras.
license: MIT
compatibility: Requires Python 3.10+, OpenCV, onvif-zeep, requests, psutil, and access to internet. Cameras must be on the same LAN for discovery.
metadata:
  version: "0.1.0"
---

# Camera Control Skill

## When to Use

Trigger this skill when the user:
- Wants to see a camera feed, capture a snapshot, or record video
- Asks to find or discover cameras on the network
- Requests pan, tilt, zoom, or camera movement
- Mentions ONVIF, RTSP, IP camera, webcam, or specific camera brands
- Wants to configure camera settings (night vision, alarms, video encoding, OSD)

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

After a successful connection, perform streaming operations: `capture_video_screenshot()` for screenshots, `get_audio_video_stream()` for stream addresses, and `toggle_recording()` for recording. Screenshot files are saved in the system temporary directory.

### Phase 4 — PTZ Control

Only ONVIF cameras support: `control_ptz()` for direction control, `save_ptz_preset()` / `go_to_preset()` for presets. USB and pure RTSP cameras do not support PTZ.

Detailed code examples and parameter descriptions are available in [references/WORKFLOW.md](references/WORKFLOW.md).

## Toolkit Modules

8 modules in `scripts/toolkit/`, call with `import scripts.toolkit as tk`:

| Module | Key Functions | Purpose |
|--------|--------------|--------|
| `device_mgmt.py` | `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device` | Config, discovery, connection, management |
| `discovery.py` | `discover_sky_devices`, `send_tcp_command`, `SkyDiscoveryListener` | Skyworth private protocol discovery & TCP channel |
| `stream.py` | `capture_video_screenshot`, `get_audio_video_stream`, `toggle_recording` | Streaming, screenshot, recording |
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

## Limitations

- Cameras and host must be on the same local network 
- RTSP streams require local network connectivity
- Password-required cameras return `needs_password` status if no cached credentials exist


## References

- [references/WORKFLOW.md](references/WORKFLOW.md) — Complete workflow examples, code snippets, and detailed usage for demo mode
- [references/COMMANDS.md](references/COMMANDS.md) — Full function signatures, parameters, return values, and security constraints
- [references/ARCHITECTURE.md](references/ARCHITECTURE.md) — System architecture, connection flow, device discovery protocols, and session rules
- [references/CONFIG.md](references/CONFIG.md) — config.yaml complete schema and examples
