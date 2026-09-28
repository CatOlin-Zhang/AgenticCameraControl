---
name: xpai-camera-control
description: "Discover, connect, and control XPAI LAN cameras via MCP. Capabilities: device detection, streaming, WebRTC preview, snapshots, PTZ control, alarm events, illumination, image settings, detection & tracking, device management."
license: MIT
compatibility: Requires Python 3.10+, OpenCV, onvif-zeep, requests, psutil, PyYAML, and mcp. Cameras must be on the same LAN for discovery.
metadata:
  version: "0.7.0"
---

# Camera Control Skill

## When to Use

Trigger when the user wants to discover, view, capture, record, move (PTZ), monitor (events/alarm), adjust (illumination/image), or track with IP cameras on the local network.

## Installation

If `xpai-camera-control` tools are not present in the available tool set, follow these steps:

**Step 1 — Determine SKILL_ROOT:** the absolute path of the directory containing this SKILL.md, or run:
```bash
python -c "from scripts._paths import get_skill_root; print(get_skill_root())"
```

**Step 2 — Install dependencies:**
```bash
pip install -r <SKILL_ROOT>/requirements.txt
```

**Step 3 — Write MCP config:** append the following JSON to the host's MCP config file (replace `<SKILL_ROOT>` with the actual path from Step 1):
```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "python",
      "args": ["scripts/mcp_server.py"],
      "cwd": "<SKILL_ROOT>"
    }
  }
}
```
Common config locations:
- Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json` (Win) / `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
- Cursor: Settings → MCP → Add Server
- Cline: `.cline/mcp_settings.json`

## MCP-Only Interaction (Hard Rule)

All camera operations **MUST** go through the MCP tools exposed by `scripts/mcp_server.py`:

- If the `xpai-camera-control` tools are **not present** in your available tool set, do NOT fall back to scripting. Follow the [Installation](#installation) steps first, then call the tools.
- **NEVER** import `scripts.toolkit` (or any module inside this package) directly, and **NEVER** write standalone scripts that re-implement or wrap tool functionality.
- Rationale: direct imports bypass the security constraints of this skill (explicit user confirmation, parameter validation) and the in-memory connection state held by the MCP server process — scripted calls in a separate process will silently violate both.

## Single-Instance Limitation

The server is stateful and single-instance (port bind + lease heartbeat + watchdog). **Proactively tell the user:** only one session can control the camera at a time; if another session holds it, tools may fail — that's not a malfunction. On instance-lock conflict (exit code 71), tell the user to close the other session's camera work first.

## Core Workflow

### Phase 0 — Session Init (must be done at the very beginning of the session)

At the beginning of each session, check if there are any registered cameras in config.yaml:

1. Call `get_registered_cameras()` to read the camera configurations (including credentials) saved in config.yaml
2. For each registered camera, call `connect_device(cam.name)` — the tool will automatically use the credentials in config.yaml to connect, **no need for the user to input a password again**
   - Cached credentials are verified via TCP/ONVIF/RTSP three-channel check (password must pass RTSP auth). Retried up to 3 times on failure; if all attempts fail, the tool **automatically attempts cloud re-authorization** to fetch a fresh password; cloud also fails → registration auto-removed from config.yaml → `status="needs_password"`
3. If config.yaml is empty or all registered cameras fail to connect → enter Phase 1

### Phase 1 — Discover Cameras

When Phase 0 cache is unavailable, call `search_devices()` to discover cameras on the local network. The tool **automatically selects the best discovery protocol** — the Agent does not need to choose:

- The tool tries all available methods internally
- Results are returned as a unified `DiscoveredDevice` list — XPAI-specific metadata (SN, channels, MAC, etc.) is included under `sky_*` prefixed fields when available
- Each result includes a `discovery_method` field indicating which protocol found the device

**Camera Naming:** When multiple cameras are found, list them (IP, model, SN) and assign a friendly name to each. Two naming strategies are available:

1. **User-provided names** — Ask the user to name each camera (e.g. "front door", "parking lot").
2. **Auto-naming by multimodal model** — Capture a screenshot from each camera via `capture_video_screenshot()`, then analyze the image content to generate a descriptive name that reflects the scene (e.g. "entrance hallway", "backyard", "loading dock"). Present the generated names to the user for confirmation before saving.

If the user already provides names, use strategy 1. Otherwise, default to strategy 2 (auto-naming). Pass the chosen name as `name` to `connect_device()` / `register_camera()`. `register_camera` matches by name → IP → SN, so calling with a new name + same IP renames in-place.

### Phase 2 — Connect & Authorize

Call `connect_device()` for each camera. The tool handles auth internally (cloud authorization, cached credentials, direct connect). **Agent only reacts to the returned `status`** — see [Decision Table](#decision-table--error--status--action) for mapping.

### Phase 3 — Stream & Capture

After a successful connection, perform streaming operations:
- `capture_video_screenshot()` — captures a single frame from the RTSP stream and saves it as JPEG (uses OpenCV, auto-discards initial buffered frames for a clean capture)
- `get_audio_video_stream()` — retrieves the RTSP stream URL and validates stream availability, returns codec/resolution/fps metadata
- `toggle_recording()` — starts/stops local MP4 recording from the RTSP stream via ffmpeg remux (`-c:v copy`)
- `manage_storage_status()` — queries disk usage and configures storage path/format/policy
- `start_webrtc_stream()` / `stop_webrtc_stream()` — converts RTSP to WebRTC for browser-based live preview, returns HTTP access URL

Screenshot files are saved to `snapshots/` directory by default; recordings go to `video/`.

**Result delivery (when user wants to "see" a camera):**
After capturing a screenshot and fetching the stream URL, the Agent **MUST** deliver both results to the user:
1. **Show the screenshot** — display the image from `file_path` to the user (e.g. via markdown image syntax `![screenshot](file_path)`)
2. **Provide the RTSP URL** — output the `stream_url` from `get_audio_video_stream()` so the user can open it in a media player (VLC, ffplay, PotPlayer, etc.) for live viewing
3. **Or start WebRTC preview** — call `start_webrtc_stream()` for browser-based live viewing when the user prefers a visual player over a raw RTSP URL

### Phase 4 — PTZ Control

PTZ control uses a **dual-protocol strategy**: ONVIF is tried first, automatically falling back to the XPAI private protocol (vendor command via TCP channel) when ONVIF is unavailable.

| Capability                          | Tools | Protocol |
|-------------------------------------|-------|----------|
| Directional movement (4 directions) | `control_ptz` | ONVIF → private fallback |
| Get position & ranges               | `get_ptz_parameters` | ONVIF → private fallback |
| Stop all movement                   | `stop_ptz` | ONVIF → private fallback |
| Physical calibration                | `calibrate_ptz` | Private protocol only |

`control_ptz` auto-stops after `duration_seconds` (default 1s). Direction parameter supports both English (`up`/`down`/`left`/`right`) and Chinese aliases (上/下/左/右).

**Physical Limit Guard:** `control_ptz` validates the command against the PTZ's actual physical travel range at the tool layer — the agent does not need to pre-validate durations. If the head is already at the limit, the command is intercepted before being sent; if the limit is reached mid-movement (e.g. "turn right 5s" but only 3s of travel remains), the tool stops early and replaces the request with the feasible movement. In both cases the result carries `degraded=True` and a human-readable `degrade_reason`. **The Agent MUST explicitly relay `degrade_reason` to the user whenever `degraded=True`** — never report a degraded move as if it completed as requested.

**PTZ Movement Estimation:** The SDK does not report absolute PTZ angles. To estimate how far the view has shifted after a rotation, the Agent should capture a screenshot before and after the movement, compare the two frames visually, and report the estimated shift as a percentage of the frame width/height to the user. This is best-effort — in featureless scenes (blank walls, sky) the estimate may be unreliable; say so when it is.

If PTZ detailed sequences, degrees mode, or calibration (`calibrate_ptz` set_home/go_home) are needed → [WORKFLOW.md — Phase 4](references/WORKFLOW.md#phase-4--ptz-control-detailed-tool-calls).

## Extended Capabilities

Available when the user explicitly requests them (all require camera connected):

| Tool | Actions | Reference |
|------|---------|----------|
| `manage_camera_events` | Alarm events (motion/human/vehicle/tamper/…): `start`/`stop`/`poll`/`wait` | [events.md](references/commands/events.md) |
| `manage_illumination` | Illumination (daynight + fill light): `get`/`set` | [illumination.md](references/commands/illumination.md) |
| `manage_image_settings` | Image params (brightness/contrast/…): `get`/`set` | [image_settings.md](references/commands/image_settings.md) |
| `query_tracking_capabilities` / `set_tracking` | Detection & tracking query/config | [tracking.md](references/commands/tracking.md) |

> `events(start)`, `illumination(set)`, `set_tracking` require **explicit user confirmation** before calling.

## Security Constraints

| Constraint | Rule |
|------------|------|
| **Explicit Prompt** | Inform user and wait for confirmation before: PTZ, streaming, screenshots, event monitor start, illumination/image/tracking changes |
| **Code Validation** | Tool-layer validation for: recording, storage configuration |
| **Background Thread** | Event listeners start **only** after `events(action="start")`; auto-resume only re-arms previously-enabled listeners |

## Gotchas

- **TCP port flaps (DEVICE_UNREACHABLE)** → for illumination/image/tracking tools, retry up to 3× at 2-3s intervals; do not reconnect. Report only after all retries fail.
- **Never hardcode ONVIF port 80** → always use `onvif_port` from `search_devices()` / config.yaml.
- **Never manually construct RTSP URLs** → always use `stream_url` from `get_audio_video_stream()` (credentials auto-injected).
- **Connection state is in-memory only** → on `success=false` with connection error, call `connect_device()` first, then retry.
- **Fixed-duration recording** → always use `toggle_recording(action="start", duration=<seconds>)`. Never implement agent-side sleep → stop.
- **Zombie lock / orphaned MCP server process** → see [WORKFLOW.md — Troubleshooting](references/WORKFLOW.md#troubleshooting-instance-lock) for manual recovery steps.

## Decision Table — error / status → action

This table is the **single runtime source of truth** for error handling. On any tool failure: analyze the error → apply the mapped action. Do NOT write workaround scripts or re-implement tool functionality. Report to the user what failed / why / how to fix, then wait for the user's decision — **except** the bounded auto-retry row below.

| `error_message` pattern / `status` | Agent Action |
|------------------------------------|--------------|
| `not_connected` / `device not found` | Call `connect_device()` first, then retry the failed operation |
| `needs_password` (status) | Cached credentials expired (cloud re-auth also failed), cloud service unreachable, or SN missing — ask user for password → `connect_device(camera_name, password=user_input)` |
| `auth_rejected` (status) | User denied cloud authorization — inform user, cannot connect |
| `cloud_pwd_failed` (status) | Cloud password doesn't match — device may have changed password, ask user for correct password |
| `cached credentials cleared` (in error_message) | Tool already attempted cloud re-authorization; prompt user for password → `connect_device(camera_name, password=user_input)` |
| `degraded=true` (PTZ result) | **MUST** relay `degrade_reason` to user verbatim |
| `limit_reached=true` | Stop sending PTZ commands in that direction — physical limit reached |
| `stream unavailable` / RTSP failure | Check camera is online, verify network connectivity |
| `error_code="timeout"` (stream/screenshot) | Tool hit its hard timeout budget. Retry once with a larger `timeout_seconds` (max 120); if still failing, check device online status |
| `stream busy` (another stream operation already in progress) | Global stream slot occupied (screenshot/stream-probe/recording establishment are serialized). Wait a few seconds and retry |
| `recording in progress` (screenshot rejected on the same camera) | Camera is recording; stop recording (`toggle_recording` action=stop) before screenshotting the same camera |
| `storage full` | Suggest cleanup via `manage_storage_status()` or change storage policy |
| `not support illumination` | Device doesn't support illumination mode control — inform user |
| `MCP tools not available` | Follow [Installation](#installation) steps — do NOT write workaround scripts |
| `DEVICE_UNREACHABLE` (from private protocol / SK HTTP, on illumination / image / tracking tools, ONVIF connection healthy) | **Bounded auto-retry, no user confirmation needed:** retry the same call with unchanged parameters after 2-3 seconds, up to 3 attempts. Transient private-protocol port flapping; do not reconnect or rediscover. Report only after all retries fail |
| `exit code 71` / instance lock conflict / MCP tools all unavailable | Another session holds the camera, or stale lock. Auto-recovery usually handles this; if not → see [WORKFLOW.md — Troubleshooting](references/WORKFLOW.md#troubleshooting-instance-lock) |

## Conditional Loading Index

Load a reference **only when its trigger fires** — do not pre-read.

| Trigger | Read |
|---------|------|
| Common operation sequences (screenshot, PTZ, events, illumination) | [references/WORKFLOW.md — Common Operation Sequences](references/WORKFLOW.md#common-operation-sequences) |
| PTZ detailed sequences, degrees mode, calibration | [references/WORKFLOW.md — Phase 4](references/WORKFLOW.md#phase-4--ptz-control-detailed-tool-calls) |
| Auth flow details beyond the Decision Table | [references/WORKFLOW.md — Phase 2](references/WORKFLOW.md#phase-2--connect--authorize-detailed-tool-calls) |
| Zombie lock / orphaned process recovery | [references/WORKFLOW.md — Troubleshooting](references/WORKFLOW.md#troubleshooting-instance-lock) |
| Building an external consumer on the event store | [references/EVENT_INTEGRATION.md](references/EVENT_INTEGRATION.md) |
| config.yaml full schema or example configs | [references/CONFIG.md](references/CONFIG.md) |
| Per-tool parameter signatures, return fields, safety constraints | [references/commands/](references/commands/) — device_mgmt · discovery · stream · ptz · events · illumination · image_settings · tracking |

## Configuration

Camera configurations are saved in `config.yaml` (skill root). Credentials auto-persist after first successful connection. When config.yaml full schema or example configs are needed → [references/CONFIG.md](references/CONFIG.md).

## Limitations

- Cameras and host must be on the same LAN
- Password-required cameras: ask user for password → `connect_device(camera_name, password=user_input)`
- Screenshot/recording requires `opencv-python` (in requirements.txt)

