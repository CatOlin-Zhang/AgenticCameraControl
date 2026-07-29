# Workflow Reference

Detailed workflow examples with MCP tool-call sequences. This file supplements the concise instructions in `SKILL.md`.

> **⚠️ MCP-Only Interaction.** Every example below is an **MCP tool invocation** (tool name + JSON arguments) against the running `scripts/mcp_server.py` — **not** Python code to execute. Never import `scripts.toolkit` or write standalone scripts to reproduce these flows; doing so bypasses the skill's security constraints and the server's in-memory connection state. See [SKILL.md — MCP-Only Interaction](../SKILL.md#mcp-only-interaction-hard-rule).

Notation used below: `tool_name(arg1=value, arg2=value)` describes a single MCP tool call with its JSON arguments; `→` describes the returned result fields.

---

## Phase 0 — Session Init: Detailed Tool Calls

```text
1. get_registered_cameras()
   → list of CameraConfig entries from config.yaml (name, ip, ports, credentials, device_class)

2. For each registered camera:
   connect_device(camera_name=<cam.name>)
   → success=true  : connected using cached credentials (auth_method reported)
   → success=false : note error_message, fall through to Phase 1 for this device

3. If config.yaml is empty or all connections failed → Phase 1
```

---

## Phase 1 — Discover Cameras: Detailed Tool Calls

### ONVIF WS-Discovery

> **Preferred for standard ONVIF cameras** (non-Skyworth devices don't answer `sky_discovery` multicast). Sends a Probe to `239.255.255.250:3702` on every local interface; the ONVIF port is parsed from XAddrs (**not always 80** — Skyworth uses 2000), and each device is classified via an anonymous RTSP probe (`direct_connect` / `password_required`).

```text
search_devices(method="ws_discovery", timeout=5)
→ result.devices[]: ip, onvif_port, model, manufacturer, device_class per device
```

For protocol details (multicast addresses, message types, key fields), see [ARCHITECTURE.md — Device Discovery](ARCHITECTURE.md#device-discovery).

### Skyworth Private Protocol Discovery

```text
search_devices(method="sky_discovery", timeout=10)
→ result.devices[]: ip, sn, sky_subtype, sky_name, rtsp_port, sky_web_port, sky_mac per device
```

For message format and field definitions, see [ARCHITECTURE.md — Skyworth Private Protocol](ARCHITECTURE.md#skyworth-private-protocol).

### USB Camera Enumeration

```text
search_devices(method="usb")
→ list of local USB cameras with device indices
```

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
→ tool reads username/password from config.yaml, verifies via ONVIF WS-UsernameToken
→ auth_method="password"
```

### Password-required camera with Local Auth Server (pending_auth flow)

```text
Step 1 — Initiate connection (tool detects password_required, sends auth request):
  connect_device(camera_name="discovered_192_168_1_100")
  → status="pending_auth" : auth server received the request, user sees it in browser

Step 2 — Poll auth status (every ~5s, max 120s ≈ 24 polls):
  poll_auth_status(camera_name="discovered_192_168_1_100")
  → status="pending"    : keep waiting, poll again after ~5s
  → status="authorized" : proceed to Step 3
  → status="rejected"   : stop — inform the user and abort

Step 3 — After authorization, ask the user for the camera password
  (conversationally — the Agent prompts the user, never reads stdin)

Step 4 — Re-connect with the password:
  connect_device(
    camera_name="discovered_192_168_1_100",
    password=<user_input>,
    ip="192.168.1.100",     # from Phase 1 discovery result (DiscoveredDevice.ip)
    rtsp_port=554            # from DiscoveredDevice.rtsp_port
  )

Step 5 — On success, persist credentials for future sessions:
  register_camera(
    name="客厅摄像头",
    ip="192.168.1.100",
    username="admin",
    password=<user_input>,
    device_class="password_required"
  )
  # NOTE: omit `port` — connect_device already probed & persisted the verified
  #       ONVIF port (Skyworth: 2000, NOT the web port 80); never pass a guess.
  → future sessions will auto-connect via Phase 0
```

### Password-required camera without Local Auth Server (fallback)

```text
Step 1 — Initiate connection (auth server unreachable, falls back):
  connect_device(camera_name="discovered_192_168_1_100")
  → status="needs_password"

Step 2 — Ask the user for the camera password directly (no browser step)

Step 3 — Re-connect with the password:
  connect_device(
    camera_name="discovered_192_168_1_100",
    password=<user_input>,
    ip="192.168.1.100",
    rtsp_port=554
  )

Step 4 — On success:
  register_camera(name="客厅摄像头", ip="192.168.1.100",
                  username="admin", password=<user_input>,
                  device_class="password_required")
  # omit `port` — the verified ONVIF port was already persisted by connect_device
```

### Cloud Auth Tools (direct usage)

```text
# Manually request authorization (normally called by connect_device internally)
request_cloud_auth(
  camera_name="客厅摄像头",
  sn="SN20240001",
  device_ip="192.168.1.100",
  device_model="LC2418"
)
→ success, claw_id

# Poll for result
poll_auth_status(camera_name="客厅摄像头")
→ status, message
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

> For non-ASCII path handling and same-process connection requirements, see [ARCHITECTURE.md — Known Issues](ARCHITECTURE.md#known-issues--implementation-notes).

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

**Agent MUST relay `degrade_reason` to the user whenever `degraded=true`** — e.g. "你要求右转 5 秒，但云台在 3.2 秒后到达右侧物理极限，已自动提前停止". Never report a degraded move as fully completed.

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

> Note: moving to an absolute coordinate is handled by the internal function `_move_to_position` (private protocol only). It is NOT registered as an MCP tool and cannot be invoked by the agent.

---

## Phase 5 — Event Monitoring (Guardian Mode): Detailed Tool Calls

All event operations go through the **single** tool `manage_camera_events` — the `action` parameter switches the working mode. See [commands/events.md](commands/events.md) for the full parameter/return reference and the schema 1.0 on-disk format.

### Start / stop the listener (requires user confirmation first)

```text
# ALWAYS ask the user for confirmation before starting — this spawns a background thread
manage_camera_events(action="start", camera_name="前门")
→ success=true, running=true, active_channels=["onvif", "private"]
  (partial channels, e.g. only ["private"], is normal — report which are active)

manage_camera_events(action="stop", camera_name="前门")
→ success=true, running=false
```

### T1 — On-demand backlog check ("看看刚才发生了什么")

```text
manage_camera_events(action="poll")            # omit camera_name to consume all cameras
→ events[]: schema 1.0 records (event_type, title, message, snapshot_path, …)
→ remaining: 0 means backlog fully consumed; >0 means truncated by limit — call again

For each returned event:
  1. Read the image at snapshot_path and analyze it
  2. Report to the user using the event's title / message plus your image analysis
```

### T2 — In-session guard loop ("帮我看着家里")

```text
Loop until the user stops:
  manage_camera_events(action="wait", timeout_seconds=60)   # single block capped at 60 s
  → events non-empty : read snapshots → analyze → report immediately → continue loop
  → events empty     : timeout with success=true → continue loop silently
```

> Backlog survives MCP server restarts: `poll` / `wait` read the on-disk store (`events/camera_events.txt`), so a fresh session can consume events recorded earlier. Raw protocol messages are never persisted — every record is already in schema 1.0.
