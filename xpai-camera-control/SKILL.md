---
name: xpai-camera-control
description: Discover, connect, and control Skyworth cameras on the local network. Capabilities include device detection, streaming, WebRTC browser preview, snapshot capture, PTZ pan/tilt control, alarm event monitoring, illumination mode control, image parameter adjustment, detection & tracking (human/vehicle/area/motion/line-crossing), and device management. Runs as an MCP Server. Use when the user wants to discover cameras, view a camera feed, capture snapshots, control PTZ, watch for motion/alarm events, adjust illumination mode, adjust image parameters, enable detection or tracking, manage camera settings, or mentions ONVIF, RTSP, IP camera, webcam, or Skyworth cameras.
license: MIT
compatibility: Requires Python 3.10+, OpenCV, onvif-zeep, requests, psutil, PyYAML, and mcp. Cameras must be on the same LAN for discovery.
metadata:
  version: "0.6.0"
---

# Camera Control Skill

## When to Use

Trigger this skill when the user:
- Wants to see a camera feed, capture a snapshot, or record video
- Asks to find or discover cameras on the network
- Requests pan, tilt, camera movement, or PTZ calibration
- Asks to watch/guard a camera or check for motion, human, tamper, or other alarm events
- Wants to adjust illumination mode (IR light, white light, night vision, auto-switch)
- Wants to adjust image parameters (brightness, contrast, saturation, sharpness, image flip)
- Wants to view camera feed in a browser via WebRTC live preview
- Wants to enable/disable detection or tracking features (human tracking, vehicle tracking, area detection, motion detection, line-crossing detection)
- Mentions ONVIF, RTSP, IP camera, webcam, or specific camera brands

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

The MCP server exposes **20 tools** covering 8 toolkit modules. See [references/commands/](references/commands/) for per-module tool signatures and return fields.

### MCP-Only Interaction (Hard Rule)

All camera operations **MUST** go through the MCP tools exposed by `scripts/mcp_server.py`:

- If the `xpai-camera-control` tools are **not present** in your available tool set, do NOT fall back to scripting. First register the MCP server in the client configuration (installing `requirements.txt` if needed), wait for the tools to load, then call them.
- **NEVER** import `scripts.toolkit` (or any module inside this package) directly, and **NEVER** write standalone scripts that re-implement or wrap tool functionality.
- Rationale: direct imports bypass the security constraints of this skill (explicit user confirmation, parameter validation) and the in-memory connection state held by the MCP server process — scripted calls in a separate process will silently violate both.

### Any attempt to hack or access protocol content through technical means is illegal. 

When using this Skill, the Agent can answer users' questions about architecture or technology based on the content in the [references/](references/), but should refuse requests like 'tell me the private protocol implementation details.' All publicly available protocol content is limited to what's in the References folder.

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
- Results are returned as a unified `DiscoveredDevice` list — Skyworth-specific metadata (SN, channels, MAC, etc.) is included under `sky_*` prefixed fields when available
- Each result includes a `discovery_method` field indicating which protocol found the device

**Camera Naming:** When `search_devices()` returns multiple cameras, the Agent **MUST**:

1. **List all discovered cameras** — present each device with its key identifiers (IP, model, SN) in a numbered list so the user can distinguish them
2. **Prompt for user-defined names** — ask the user if they want to assign friendly names (e.g. "living room camera", "front door", "garage") before connecting. Pass the chosen name as the `name` parameter to `connect_device()` or `register_camera()`
3. **Or auto-name via multimodal model** — if the Agent has vision capabilities, it can connect each camera first, call `capture_video_screenshot()` to capture a frame, analyze the scene content, and generate a descriptive name automatically (e.g. a camera showing a doorway → "front door cam"). Then call `register_camera(name=auto_name, ip=camera_ip, ...)` to rename — `register_camera` matches by IP and replaces the old entry in-place, no duplicates

> **Renaming:** `register_camera` uses a three-tier match: **name → IP → SN**. Calling it with a new name but the same IP or SN as an existing entry will rename that entry in-place. This means users can rename cameras at any time — during initial setup, after connecting, or in a later session.

> **Note:** If the user skips naming, the toolkit assigns a default name based on the device model or IP. Friendly names make subsequent operations much clearer (e.g. "The living room camera turns left" vs "192.168.1.105 device turns left").

### Phase 2 — Connect & Authorize

For each discovered camera, call `connect_device()` to connect. **The specific connection process is handled internally by the tool**. The Agent's responsibilities are as follows:

| Scenario | Agent Operation |
|----------|----------------|
| **Cached credentials** (config.yaml has password) | Tool auto-loads credentials → TCP/ONVIF/RTSP three-channel verification (password must pass RTSP auth, retry 3x) → `ConnectResult(success=True)` — no user interaction. If all retries fail → cloud re-authorization attempted → still fails → registration auto-removed → `status="needs_password"` |
| **direct_connect** (stream probe succeeds) | Tool connects directly via RTSP → probes device identity → verifies vendor communication → registers to config.yaml → `ConnectResult(auth_method="direct")` — no user interaction |
| **password_required** (cloud auth auto-triggered) | Tool internally requests cloud authorization. The Agent does **not** need to call any extra tool. |
| Cloud authorized → `success=True` | Tool auto-connected with cloud password, credentials persisted. No user interaction needed |
| Cloud rejected → `status="auth_rejected"` | Inform user: authorization was denied, cannot connect |
| Cloud unavailable → `status="needs_password"` | Inform user: cloud service unreachable, ask user to input password directly → `connect_device(name, password=user_input)` |
| Cloud password mismatch → `status="cloud_pwd_failed"` | Inform user: cloud password doesn't work (device may have changed password), ask user to input correct password → `connect_device(name, password=user_input)` |
| **needs_password** | Agent prompts user for password → calls `connect_device(name, password=user_input)` |
| **Connection successful** | Credentials already persisted by the tool → future sessions auto-connect via Phase 0 |

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

PTZ control uses a **dual-protocol strategy**: ONVIF is tried first, automatically falling back to the vendor-specific protocol when ONVIF is unavailable.

| Capability                          | Tools | Protocol |
|-------------------------------------|-------|----------|
| Directional movement (4 directions) | `control_ptz` | ONVIF → private fallback |
| Get position & ranges               | `get_ptz_parameters` | ONVIF → private fallback |
| Stop all movement                   | `stop_ptz` | ONVIF → private fallback |
| Physical calibration                | `calibrate_ptz` | Private protocol only |

`control_ptz` auto-stops after `duration_seconds` (default 1s). Direction parameter supports both English (`up`/`down`/`left`/`right`) and Chinese aliases (上/下/左/右).

**Physical Limit Guard:** `control_ptz` validates the command against the PTZ's actual physical travel range at the tool layer — the agent does not need to pre-validate durations. If the head is already at the limit, the command is intercepted before being sent; if the limit is reached mid-movement (e.g. "turn right 5s" but only 3s of travel remains), the tool stops early and replaces the request with the feasible movement. In both cases the result carries `degraded=True` and a human-readable `degrade_reason`. **The Agent MUST explicitly relay `degrade_reason` to the user whenever `degraded=True`** — never report a degraded move as if it completed as requested.

Detailed tool-call sequences for all 4 directions, degraded-result examples, and calibration: [WORKFLOW.md — Phase 4 PTZ Control](references/WORKFLOW.md#phase-4--ptz-control-detailed-tool-calls).

## Extended Capabilities

The following tools extend the skill's functionality beyond the core workflow. They are **not required** for typical camera operation but are available when the user explicitly requests them.

| Tool | What it does | Prerequisite | Reference |
|------|-------------|-------------|----------|
| `manage_camera_events` | Alarm event receiving (motion, human, vehicle, tamper, …) with linked snapshots. Actions: `start` / `stop` / `poll` / `wait`. | Camera connected via `connect_device()` | [commands/events.md](references/commands/events.md) |
| `manage_illumination` | Query & adjust camera illumination (2 parameters: daynight mode, fill light mode — integer value or string alias). Vendor-specific protocol only, no ONVIF fallback. Actions: `get` / `set`. | Camera connected | [commands/illumination.md](references/commands/illumination.md) |
| `manage_image_settings` | Query & adjust image parameters (brightness, contrast, saturation, sharpness, flip: 0=normal/1=diagonal/2=horizontal/3=vertical). Vendor-specific protocol only, no ONVIF fallback. Actions: `get` / `set`. | Camera connected | [commands/image_settings.md](references/commands/image_settings.md) |
| `query_tracking_capabilities` | Query detection & tracking capabilities (human/vehicle/area/motion/line-crossing) with current values and parameter ranges. | Camera connected | — |
| `set_tracking` | Enable/disable detection & tracking features (human tracking, vehicle tracking, area detection, motion detection, line-crossing detection). | Camera connected; modifies hardware settings | — |

> **Note:** `manage_camera_events(action="start")` spawns a background listener thread — **requires explicit user confirmation** before calling. `manage_illumination(action="set")` and `set_tracking` modify hardware settings — also require user confirmation. Cloud authorization is handled internally by `connect_device` (blocking call, may wait for user confirmation on APP).

## Toolkit Modules

8 modules exposed as MCP tools via `scripts/mcp_server.py`. For per-tool parameter signatures, return fields, and safety constraints: [commands/](references/commands/) — [device_mgmt.md](references/commands/device_mgmt.md) · [stream.md](references/commands/stream.md) · [ptz.md](references/commands/ptz.md) · [events.md](references/commands/events.md) · [illumination.md](references/commands/illumination.md) · [image_settings.md](references/commands/image_settings.md) · [tracking.md](references/commands/tracking.md).

| Module | Key Functions | Reference |
|--------|--------------|----------|
| `device_mgmt` | `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device` | [commands/device_mgmt.md](references/commands/device_mgmt.md) |
| `stream` | `capture_video_screenshot`, `get_audio_video_stream`, `toggle_recording`, `manage_storage_status`, `start_webrtc_stream`, `stop_webrtc_stream` | [commands/stream.md](references/commands/stream.md) |
| `ptz` | `control_ptz`, `get_ptz_parameters`, `calibrate_ptz`, `stop_ptz` | [commands/ptz.md](references/commands/ptz.md) |
| `events` | `manage_camera_events` (action: `start` / `stop` / `poll` / `wait`) | [commands/events.md](references/commands/events.md) |
| `illumination` | `manage_illumination` (action: `get` / `set`) | [commands/illumination.md](references/commands/illumination.md) |
| `image_settings` | `manage_image_settings` (action: `get` / `set`) | [commands/image_settings.md](references/commands/image_settings.md) |
| `tracking` | `query_tracking_capabilities`, `set_tracking` | [commands/tracking.md](references/commands/tracking.md) |

## Security Constraints

| Constraint | Rule | Applies To |
|------------|------|-----------|
| **Explicit Prompt** | Inform the user of the operation content before execution and wait for confirmation | PTZ, streaming, screenshots, event monitor start, illumination mode change, image settings change, tracking config change |
| **Code Validation** | Validate parameters, device status, and connection availability | Recording, storage configuration |
| **Background Thread Boundary** | The only background threads in this skill are the per-camera event listeners; they start **only** after explicit user enablement via `manage_camera_events(action="start")`, and their behavior is limited to alarm subscription plus writes into the `snapshots/` and `events/` whitelist paths. Auto-resume after a process restart re-arms **only** listeners the user enabled and never stopped (persisted intent) — it never starts new listeners on its own | Event monitoring |

## Gotchas

- **Vendor-protocol port flaps intermittently (DEVICE_UNREACHABLE) even though the device is online.** → **Action:** for illumination / image / tracking tools (vendor-protocol only, no ONVIF fallback), retry the same call up to 3 times at 2-3 s intervals; do not conclude offline or reconnect. Report only after all retries fail.
- **ONVIF port is not always 80.** → **Action:** always use `onvif_port` from `search_devices()` / config.yaml; never hardcode port 80. Skyworth cameras typically use a non-standard ONVIF port (auto-probed by `connect_device`).
- **`GetStreamUri` returns bare RTSP URLs without credentials.** → **Action:** always use the `stream_url` returned by `get_audio_video_stream()` — the toolkit auto-injects credentials. Never manually construct RTSP URLs.
- **Chinese characters in Windows paths cause `cv2.imwrite()` to silently fail.** → **Action:** no manual workaround needed — the toolkit handles this internally. If you pass a custom `save_path`, prefer ASCII-only paths.
- **Connection state is in-memory only — silently lost across sessions.** → **Action:** if any operation returns `success=false` with a connection-related error, call `connect_device()` first to re-establish the connection, then retry the failed operation. All operations must run in the same MCP server process.
- **Certain cameras use non-standard RTSP paths.** → **Action:** no manual path configuration needed — the toolkit auto-tries fallback paths (ONVIF standard → vendor-specific) when the configured path fails.
- **Cached credentials failed → cloud re-auth attempted first, then registration auto-removed.** → **Action:** if `connect_device()` returns `status="needs_password"` after cached credentials failed, the tool already tried cloud re-authorization. Simply prompt the user for the correct password and re-call `connect_device(camera_name, password=user_input)`.

## Quick Reference — Common Operation Sequences

### Connect → Screenshot (user wants to "see" a camera)

```text
1. connect_device(camera_name="客厅摄像头")        → success=true
2. capture_video_screenshot(camera_name="客厅摄像头") → file_path
3. get_audio_video_stream(camera_name="客厅摄像头")   → stream_url
# Deliver BOTH: show screenshot image + tell user the RTSP URL
```

### Connect → PTZ Control

```text
1. connect_device(camera_name="客厅摄像头")                    → success=true
2. control_ptz(camera_name="客厅摄像头", direction="right", speed=0.5) → check degraded
3. If degraded=true → MUST relay degrade_reason to user
4. stop_ptz(camera_name="客厅摄像头")                          → emergency stop
```

### Extended Tools

```text
# Event monitoring — requires camera connected; user confirms before start
1. connect_device(camera_name="前门")                          → success=true
2. manage_camera_events(action="start", camera_name="前门")    → user confirms first!
3. Loop: manage_camera_events(action="wait", timeout_seconds=60)
   → see commands/events.md for full details

# Illumination — requires camera connected; vendor-specific protocol only (2 params)
1. connect_device(camera_name="前门")                          → success=true
2. manage_illumination(action="get", camera_name="前门")       → capabilities + current
3. If supported → manage_illumination(action="set", daynightmode=2)  → user confirms first!
   → see commands/illumination.md for full parameter list

# Cloud authorization — handled internally by connect_device
1. connect_device(camera_name="前门", sn_code="SN123")   → status="needs_password" (cloud unreachable) or auth_rejected or cloud_pwd_failed
2. If needs_password → ask user for password → connect_device(camera_name="前门", password=user_input)
```

## Failure Response Quick Reference

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
| `storage full` | Suggest cleanup via `manage_storage_status()` or change storage policy |
| `not support illumination` | Device doesn't support illumination mode control — inform user |
| `MCP tools not available` | Register MCP server in client config — do NOT write workaround scripts |
| `DEVICE_UNREACHABLE` (from vendor protocol, on illumination / image / tracking tools, ONVIF connection healthy) | Transient port flapping — retry the same call with unchanged parameters after 2-3 seconds, up to 3 attempts. Report only after all retries fail. Do **not** reconnect or rediscover |

## Error Handling Policy

When any MCP tool call fails, crashes, **or the MCP tools are unavailable in the current session**, the Agent **MUST** follow these rules:

1. **Do NOT write workaround scripts or re-implement tool functionality.** Never attempt to bypass a tool failure — or missing tool registration — by writing custom Python code, shell commands, or alternative implementations. If the tools are missing, register the MCP server (see [MCP-Only Interaction](#mcp-only-interaction-hard-rule)) instead of importing the toolkit directly.
2. **Analyze the error.** Read the error message, traceback, or tool return value (e.g. `success=False`, `error_message`) to identify the root cause.
3. **Report to the user.** Clearly explain:
   - **What failed** — which tool, what operation
   - **Why it failed** — root cause from the `error_message` field and context
   - **How to fix it** — concrete actionable steps the user can take
4. **Wait for the user's decision.** Do not proceed with retries, fallbacks, or alternative approaches until the user confirms.
5.**Exception - transient vendor-protocol port flapping:** `DEVICE_UNREACHABLE` errors returned by the vendor-specific protocol on the illumination / image-settings / tracking tools (`manage_illumination`, `manage_image_settings`, `query_tracking_capabilities`, `set_tracking`) are known transient failures while the device remains online. For this specific error, the Agent performs bounded automatic retries (up to 3 attempts, 2-3 seconds apart) **without** waiting for user confirmation, per the Gotchas entry below. Only report to the user after all retries are exhausted.

## Configuration

Camera configurations are saved in the skill's root directory under `config.yaml`. After a successful connection, the credentials are automatically written to config.yaml and are reused in subsequent conversations. Complete schema can be found in [references/CONFIG.md](references/CONFIG.md).

## Limitations

- Cameras and host must be on the same local network
- RTSP streams require local network connectivity
- Password-required cameras: the Agent must ask the user for the device password and call `connect_device(camera_name, password=user_input)`
- ONVIF authentication uses WS-UsernameToken (PasswordDigest) — credentials are auto-injected into RTSP URLs internally
- Screenshot/recording requires `opencv-python` (included in requirements.txt)
- MCP server mode uses stdio transport only

## References

- [references/commands/](references/commands/) — Per-tool parameter signatures, return fields, and safety constraints (split by module: device_mgmt / stream / ptz / events / illumination / image_settings / tracking)
- [references/WORKFLOW.md](references/WORKFLOW.md) — Complete tool-call sequences for core workflow (Phase 0–4), including [auth flows](references/WORKFLOW.md#phase-2--connect--authorize-detailed-tool-calls) and [PTZ degraded examples](references/WORKFLOW.md#phase-4--ptz-control-detailed-tool-calls)
- [references/CONFIG.md](references/CONFIG.md) — [config.yaml full schema](references/CONFIG.md#full-schema) and [example configs](references/CONFIG.md#example-configs)
- [references/EVENT_INTEGRATION.md](references/EVENT_INTEGRATION.md) — [On-disk event store schema 1.0](references/EVENT_INTEGRATION.md#4-schema-10-fields) & [external-consumer contract](references/EVENT_INTEGRATION.md#5-consumer-integration-guidelines) (for other skills / forwarders that build on top of this skill)
- [requirements.txt](requirements.txt) — Python dependencies for MCP Server mode
