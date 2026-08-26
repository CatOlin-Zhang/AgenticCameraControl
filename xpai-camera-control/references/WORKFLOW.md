# Workflow Reference

Detailed workflow examples with MCP tool-call sequences. This file supplements the concise instructions in `SKILL.md`.

> **MCP-Only Interaction.** Every example below is an **MCP tool invocation** (tool name + JSON arguments) against the running `scripts/mcp_server.py` — **not** Python code to execute. Never import `scripts.toolkit` or write standalone scripts to reproduce these flows; doing so bypasses the skill's security constraints and the server's in-memory connection state. See [SKILL.md — MCP-Only Interaction](../SKILL.md#mcp-only-interaction-hard-rule).

Notation used below: `tool_name(arg1=value, arg2=value)` describes a single MCP tool call with its JSON arguments; `→` describes the returned result fields.

---

## Phase 0 — Session Init: Detailed Tool Calls

```text
1. get_registered_cameras()
   → list of CameraConfig entries from config.yaml (name, ip, ports, credentials, device_class)

2. For each registered camera:
   connect_device(camera_name=<cam.name>)
   → success=true  : connected using cached credentials (auth_method reported)
   → success=false, status="failed", needs_password=true, error contains "缓存凭据连接失败":
      the tool has retried 3x and auto-removed the registration from config.yaml
      → fall through to Phase 1 to re-discover this device
   → success=false (other): note error_message, fall through to Phase 1 for this device

3. If config.yaml is empty or all connections failed → Phase 1
```

---

## Phase 1 — Discover Cameras: Detailed Tool Calls

`search_devices()` is the unified discovery tool — it automatically selects the best protocol(s) and returns normalized results.

```text
search_devices()
→ result.devices[]: ip, onvif_port, rtsp_port, device_class, model, manufacturer,
                    sn_code, discovery_method, sky_subtype, sky_name, sky_channels,
                    sky_mac, sky_hw_version, sky_sw_version, ...
```

- `discovery_method` tells you which protocol found each device (`"ws_discovery"` / `"sky_discovery"` / `"usb"`)
- `sky_*` fields are populated for Skyworth devices, empty for others
- `device_class` is auto-classified via RTSP probe: `"password_required"` or `"direct_connect"`

For the unified discovery tool usage, see [SKILL.md — Phase 1](../SKILL.md#phase-1--discover-cameras).

---

## Phase 2 — Connect & Authorize: Detailed Tool Calls

### Direct-connect camera (no password needed)

```text
connect_device(camera_name="书房摄像头")
→ tool probes RTSP → receives 200 OK → connects directly
→ auth_method="direct"
```

### Password-required camera with cached credentials

```text
# Credentials already in config.yaml from a previous session
connect_device(camera_name="客厅摄像头")
→ tool reads username/password from config.yaml
→ retries ONVIF WS-UsernameToken auth up to 3 times (1s interval)
→ success: auth_method="password"
→ all retries fail: auto-removes registration from config.yaml
   → status="failed", needs_password=true
   → error: "缓存凭据连接失败（已重试 3 次）..."
   → Agent should re-discover via search_devices() and re-connect
```

### Password-required camera (no cached credentials)

```text
Step 1 — Connect without password:
  connect_device(camera_name="discovered_192_168_1_100", sn_code="SN123456")
  → tool internally triggers cloud authorization
  → waiting for user to confirm on APP (blocks until timeout)
  → success=true: cloud authorized, auto-connected, credentials persisted
  → status="needs_password": cloud service unreachable, inform user
  → status="auth_rejected": user denied authorization, cannot connect
  → status="cloud_pwd_failed": cloud password mismatch, ask user for correct password

Step 2a — Cloud authorized (success=true):
  No further action needed. Credentials auto-persisted to config.yaml.
  Future sessions will auto-connect via Phase 0.

Step 2b — Cloud unavailable (needs_password):
  (conversationally — the Agent informs user that cloud service is unreachable)
  connect_device(
    camera_name="discovered_192_168_1_100",
    password=<user_input>,
    ip="192.168.1.100",     # from Phase 1 discovery result (DiscoveredDevice.ip)
    rtsp_port=554            # from DiscoveredDevice.rtsp_port
  )
  → future sessions will auto-connect via Phase 0

Step 2c — Cloud password mismatch (cloud_pwd_failed):
  (conversationally — the Agent informs user that cloud password doesn't match,
   device may have changed password)
  connect_device(
    camera_name="discovered_192_168_1_100",
    password=<user_input>,
    ip="192.168.1.100",
    rtsp_port=554
  )
  → future sessions will auto-connect via Phase 0

Step 2d — Authorization rejected (auth_rejected):
  (conversationally — inform user that authorization was denied, cannot connect)
  No further action available unless user provides password directly.
```

### Cloud-authorized camera (handled internally)

Cloud authorization is now fully handled inside `connect_device`. The Agent does **not** need to call any separate cloud auth tool. The `big_connect` and `poll_auth_status` tools have been deprecated as external MCP tools.

```text
# Cloud auth flow is automatic:
connect_device(camera_name="discovered_192_168_1_100", sn_code="SN123456")
→ internally: triggers cloud auth request → polls for result with timeout
→ if authorized: auto-connect with cloud password, credentials persisted
→ if rejected/timeout/error: return appropriate status for Agent to handle
```

---

## Phase 3 — Stream & Capture: Detailed Tool Calls

```text
# Capture a snapshot
capture_video_screenshot(camera_name="客厅摄像头")
→ file_path of the saved JPEG

# Get stream URL
get_audio_video_stream(camera_name="客厅摄像头")
→ stream_url (RTSP), codec, resolution, fps

# Start/stop recording
toggle_recording(camera_name="客厅摄像头", action="start")
toggle_recording(camera_name="客厅摄像头", action="stop")
```

> For non-ASCII path handling and same-process connection requirements, see [SKILL.md — Gotchas](../SKILL.md#gotchas).

### End-to-End: User says "I want to see the camera"

```text
# Assumes camera is already connected (Phase 0/2 complete)

Step 1 — Capture screenshot for preview:
  capture_video_screenshot(camera_name="客厅摄像头")
  → file_path: "snapshots/客厅摄像头_20260727_143052.jpg"

Step 2 — Get RTSP stream URL for live viewing:
  get_audio_video_stream(camera_name="客厅摄像头")
  → stream_url: "rtsp://admin:pass@192.168.1.100:554/stream1"
  → codec: "H.264", resolution: "2560x1440", fps: 25

Step 3 — Agent delivers BOTH results to the user:
  (a) Show the screenshot image using markdown:
      ![客厅摄像头截图](snapshots/客厅摄像头_20260727_143052.jpg)
  (b) Tell user the RTSP URL:
      "RTSP live stream: rtsp://admin:***@192.168.1.100:554/stream1
       You can open this URL in VLC, ffplay, or PotPlayer for live viewing."
```

---

## Phase 4 — PTZ Control: Detailed Tool Calls

PTZ uses a **dual-protocol strategy**: ONVIF is tried first, automatically falling back to the Skyworth private protocol when unavailable. All return results include a `protocol` field indicating which protocol was actually used.

### Directional movement (8 directions + Chinese aliases)

```text
# Basic 4 directions (auto-stop after duration_seconds, default 1.0s)
control_ptz(camera_name="客厅摄像头", direction="up", speed=0.5)
control_ptz(camera_name="客厅摄像头", direction="left", speed=0.5, duration_seconds=2.0)

# Diagonal directions
control_ptz(camera_name="客厅摄像头", direction="upleft", speed=0.5)
control_ptz(camera_name="客厅摄像头", direction="downright", speed=0.5)

# Chinese direction aliases are supported
control_ptz(camera_name="客厅摄像头", direction="上", speed=0.5)
control_ptz(camera_name="客厅摄像头", direction="左上", speed=0.5)
```

### Physical limit guard (degraded results)

`control_ptz` guards against commands that exceed the PTZ's physical travel range. When the requested duration cannot be fulfilled, the tool executes the feasible portion and marks the result as degraded:

```text
# User asks: "右转 5 秒" — but only ~3s of travel remains
control_ptz(camera_name="客厅摄像头", direction="right", duration_seconds=5.0)
→ success=true, degraded=true, limit_reached=true
→ requested_duration_seconds=5.0, actual_duration_seconds=3.2
→ degrade_reason="请求朝 right 方向移动 5.0 秒，但云台在 3.2 秒后到达物理极限，已提前自动停止。..."

# Head already at the right limit — command intercepted, nothing sent to the device
control_ptz(camera_name="客厅摄像头", direction="right", duration_seconds=5.0)
→ success=true, degraded=true, limit_reached=true, actual_duration_seconds=0.0
→ degrade_reason="云台在 right 方向已处于物理极限位置（...），移动指令已被拦截..."
```

**Agent MUST relay `degrade_reason` to the user whenever `degraded=true`** — e.g. "You requested a 5-second right turn, but the PTZ head reached its physical limit after 3.2 seconds and stopped early". Never report a degraded move as fully completed.

### Get current PTZ status

```text
get_ptz_parameters(camera_name="客厅摄像头")
→ pan, tilt, zoom positions
→ pan_range, tilt_range, zoom_range
→ is_moving, protocol
```

### Stop PTZ immediately

```text
# Stop all PTZ movement (ONVIF first, private fallback)
stop_ptz(camera_name="客厅摄像头")
```

### Physical calibration (private protocol only)

```text
# Calibrate PTZ zero point (takes 10-30 seconds, Skyworth cameras only)
calibrate_ptz(camera_name="客厅摄像头")
→ success / error_message
```

> Note: absolute coordinate movement is handled internally and is NOT available as an MCP tool.

---

## Extended Tools

The following tools extend the skill beyond the core workflow (Phase 0–4). They are available when the user explicitly requests them but are not part of the typical camera operation flow.

### Event Monitoring (`manage_camera_events`)

Receive alarm events (motion, human, vehicle, tamper, line-crossing, …) with linked snapshots. Single tool, `action` switches mode: `start` / `stop` / `poll` / `wait`.

| Aspect | Detail |
|--------|--------|
| **Prerequisite** | Camera connected via `connect_device()` |
| **Safety** | `action="start"` spawns a background listener — requires explicit user confirmation |
| **Detailed reference** | [commands/events.md](commands/events.md) — full parameter/return fields, schema 1.0 format, event store contract |

### Illumination Mode Control (`manage_illumination`)

Query and adjust camera illumination parameters. Dual-protocol: Skyworth private (TCP channel) + ONVIF Imaging fallback (mode only). Single tool, `action` switches mode: `get` / `set`.

| Aspect | Detail |
|--------|--------|
| **Prerequisite** | Camera connected via `connect_device()`; capability auto-probed at connect time and cached in `config.yaml` as `illumination_modes` |
| **Safety** | `action="set"` modifies a hardware setting — requires explicit user confirmation. Always call `get` first to retrieve `capabilities` (parameter ranges), then call `set` with only the parameters to change |
| **Detailed reference** | [commands/illumination.md](commands/illumination.md) — full parameter table, return fields, error codes |
