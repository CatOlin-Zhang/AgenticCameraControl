# Architecture Reference

Runtime-relevant architecture details. Connection flows are encapsulated inside the tool layer — the agent receives structured results with clear status codes and does not need to understand protocol internals.

## Module Map

```
Toolkit modules (exposed via MCP tools):
  device_mgmt   — Device discovery, connection, config, management
  stream        — Audio/video streaming, snapshot, recording, storage
  ptz           — PTZ control (ONVIF + private protocol dual-channel)
  events        — Event/alarm receiving (ONVIF PullPoint + private RTSP-channel push), schema 1.0 store
  illumination  — Illumination mode query & control (Skyworth private protocol + ONVIF Imaging fallback)

Internal modules (not exposed, accessed only through MCP tools above):
  discovery     — Skyworth private protocol discovery & TCP command channel
```

## Connection & Authorization Flow

The connection process involves two actors: the **Agent** (AI) and the **Tool** (device_mgmt.py + discovery.py). The tool handles protocol details internally; the Agent manages user interaction when password is needed.

### ONVIF Port Verification (inside `connect_device`)

Before ONVIF authentication, `connect_device` verifies the real ONVIF port internally: candidate ports (config/argument hint → 2000/80/8000/8899) are probed with an unauthenticated `GetSystemDateAndTime` request, and a port is only accepted if it returns a SOAP Envelope (not an HTML page). Verified ports are written back to config.yaml automatically; unverified ports stay `0` (= unknown). Skyworth cameras: ONVIF is on **2000** — port 80 is the web UI.

### Flow for Cached Cameras (config.yaml has credentials)

```
1. Agent → calls connect_device(cam_name)
   └─ Tool reads username/password from config.yaml automatically
   └─ Tool retries ONVIF WS-UsernameToken authentication up to 3 times (1s interval)
   └─ Success → ConnectResult(success=True, auth_method="password")
   └─ No user interaction required
   └─ All retries fail → Tool removes the camera from config.yaml (_remove_camera_config)
      → ConnectResult(success=False, status="failed", needs_password=True)
      → Agent must re-discover via search_devices() and re-connect
```

### Flow for Password-Required Cameras (No Cached Credentials)

```
1. Agent → calls connect_device(camera_name)
   └─ Tool checks config.yaml → no cached password
   └─ Tool detects device_class == "password_required"
   └─ Tool returns ConnectResult(success=False, status="needs_password", needs_password=True)

2. Agent prompts user for the device management password

3. Agent → calls connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)
   └─ Single attempt with user-provided password (no retry, no cache cleanup)
   └─ Tool attempts ONVIF WS-UsernameToken auth → TCP channel (port 9010)
   └─ Success → registers to config.yaml → ConnectResult(success=True)
   └─ Failure → ConnectResult(success=False, status="failed", needs_password=True)
```

### Flow for Password-Required Cameras (User Provides Password)

```
1. Agent → calls connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)
   └─ Single attempt with user-provided password (no retry, no cache cleanup)
   └─ Tool attempts ONVIF WS-UsernameToken auth → TCP channel (port 9010)
   └─ Success → registers to config.yaml → ConnectResult(success=True)
   └─ Failure → ConnectResult(success=False, status="failed", needs_password=True)
```

### Flow for Direct-Connect Cameras

```
1. Agent → calls connect_device(camera_name)
   └─ Tool sends RTSP DESCRIBE probe → receives 200 OK
   └─ Tool connects directly via RTSP (no auth needed)
   └─ Tool returns ConnectResult(success=True, auth_method="direct")
```

### ONVIF WS-UsernameToken Authentication

When connecting with credentials, the tool uses ONVIF WS-UsernameToken PasswordDigest:

```
PasswordDigest = Base64(SHA-1(nonce + created + password))
```

This is injected as a SOAP header for ONVIF service calls. RTSP URLs are auto-constructed with embedded credentials internally (credentials from connection state are injected, URL encoding applied).


## Device Discovery

### WS-Discovery Protocol (ONVIF)

| Parameter | Value |
|-----------|-------|
| Multicast address | `239.255.255.250:3702` |
| Hello | Camera broadcasts on boot |
| Probe | Client multicast to trigger responses |
| ProbeMatch | Camera response with device info |
| Types filter | Must contain `NetworkVideoTransmitter` |
| Scopes | May contain brand/model info |

### Skyworth Private Protocol

| Parameter | Value |
|-----------|-------|
| Multicast address | `239.230.236.230:9008` (IPC listens) |
| Tool receive port | `9028` |
| NVR receive port | `9018` |
| TCP command port | `9010` (HTTP + Basic Auth) |
| ONVIF port | `2000` (field-verified on ZCY121/ZCR461 — **not** 80; port 80 serves the web UI and returns 404 for `/onvif/device_service`) |
| Broadcast address | `255.255.255.255` |
| Protocol | JSON over UDP (SK_DISCOVERY_SEARCH / SK_DISCOVERY_SEARCH_R) |
| TCP path | `POST /xiaopaitech/device_service HTTP/1.1` |
| RTSP main stream | `/stream0`, `/stream1`, `/md0_0` (2560x1440) |
| RTSP sub stream | `/md0_1` (1280x720) |

### Key Discovery Fields

| Field | Source | Purpose |
|-------|--------|---------|
| SN (Serial Number) | ONVIF GetDeviceInformation | Unique device identifier |
| Model | WS-Discovery Scopes / ONVIF | Device model identification |
| ONVIF Port | WS-Discovery XAddrs parsing | **Parse from XAddrs — not always 80**. `sky_discovery` returns `onvif_port=0` (private protocol only reports the web port); the real port is probed & persisted by `connect_device`. |
| IP Address | WS-Discovery source address | LAN communication address |

### Fallback Discovery

When WS-Discovery fails (firewall, non-ONVIF cameras, wrong subnet):
1. Enumerate local IPs via `psutil.net_if_addrs()`
2. Scan each subnet for port 80 (HTTP) and 554 (RTSP)
3. Fingerprint HTTP responses for camera signatures (e.g. "Skyworth", "Hikvision")
4. Try RTSP connection with common URL patterns

## Device Classification

| Type | Auth | Agent Behavior |
|------|------|---------------|
| Password-Required (cached) | ONVIF WS-UsernameToken from config.yaml (retry 3x) | Auto-connect — no user input needed. All retries fail → registration auto-removed, re-discover needed |
| Password-Required (uncached) | User provides password → ONVIF WS-UsernameToken auth | Agent detects `needs_password` → prompts user → connects with password → registers credentials |
| Direct-Connect | None | Auto-connect — RTSP probe returns 200 OK |
| Pending Auth | Cloud authorization required | Agent calls `big_connect` or `poll_auth_status` → device password auto-written to config.yaml upon authorization |

## Cloud Authorization Flow

When a device requires cloud-based authorization (e.g. Skyworth cameras with SN-based authentication), the system supports a cloud authorization workflow:

```
1. Agent → calls connect_device(camera_name)
   └─ Tool returns ConnectResult(success=False, status="pending_auth")
   └─ Agent notifies user that authorization is needed

2. Agent → calls big_connect(name=camera_name)   [one-call flow]
   └─ Tool resolves target camera from config.yaml
   └─ POST /deviceAuthReq with {claw_id, sn, device_ip, device_model}
   └─ Polls GET /checkAuth every 5 seconds (up to 10 minutes / 120 polls)
   └─ authStatus=1 (AUTHORIZED) → devicePwd auto-written to config.yaml
      → AuthOrchestrateResult(success=True, status="authorized")
   └─ authStatus=2 (REJECTED) → user declined in app
      → AuthOrchestrateResult(success=False, status="rejected")
   └─ Timeout → AuthOrchestrateResult(success=False, status="timeout")

   Alternative: Agent → calls poll_auth_status(camera_name)   [manual polling]
   └─ Single GET /checkAuth with signed request
   └─ Returns AuthStatusResult(status=PENDING|AUTHORIZED|REJECTED|ERROR)
   └─ Agent loops with 5s interval until AUTHORIZED or REJECTED
```

**Cloud auth signing:** Each request includes `requestId`, `timestamp`, and `scSign` (HMAC-based signature using `clawID + sn + timestamp`). The `clawID` is auto-generated and persisted for the agent session.

**Password auto-persist:** Upon authorization, the cloud returns `devicePwd` (MD5-based), which is automatically written to `config.yaml` via `register_camera()`. Subsequent connections use the cached password.

## PTZ Dual-Protocol Architecture

PTZ control in `scripts/toolkit/ptz.py` implements a **dual-protocol strategy** with automatic fallback:

```
1. Agent calls control_ptz(camera_name, direction, speed)
   └─ Tool tries ONVIF PTZ Service (ContinuousMove + auto Stop)
   └─ If ONVIF succeeds → returns PTZMoveResult(protocol="onvif")
   └─ If ONVIF fails (no onvif_camera, no PTZ service, timeout)...
   └─ Tool falls back to Skyworth private protocol (SK_SETTING_SET_PTZ via TCP 9010)
   └─ If private succeeds → returns PTZMoveResult(protocol="sky_private")
   └─ If both fail → returns PTZMoveResult(success=False, error_message=...)
```

**Connection state** is held in-memory by the MCP server process (avoids cross-process state issues). Each connection entry contains:
- ONVIF camera object (for ONVIF PTZ Service calls)
- IP, username, password, TCP port (credentials for private protocol fallback)

**Protocol capability matrix:**

| Function | ONVIF | Private Protocol |
|----------|:-----:|:----------------:|
| `control_ptz` (direction) | `ContinuousMove` + `Stop` | `SK_SETTING_SET_PTZ` cmd |
| `get_ptz_parameters` | `GetStatus` | `SK_SETTING_GET_PTZ` |
| `stop_ptz` | `Stop` | `SK_SETTING_SET_PTZ` stop |
| `calibrate_ptz` | — | `SK_SETTING_SET_PTZ` calibrate |

## Event Monitoring Architecture (Guardian Mode Foundation)

Event receiving in `scripts/toolkit/events.py` follows the same **dual-protocol strategy** as PTZ, exposed as the single MCP tool `manage_camera_events(action=start|stop|poll|wait)`:

```
1. manage_camera_events(action="start") — after explicit user confirmation
   └─ Spawns one background listener thread per camera (the ONLY background threads in this skill)
   └─ Persists the monitoring intent to events/monitor_state.json (cleared only by action="stop")
   └─ Channel 1: ONVIF Event Service — CreatePullPointSubscription + PullMessages long-poll (auto-renew)
   └─ Channel 2: Skyworth private protocol — alarm JSON pushed over a persistent RTSP session (vendor doc §5.24)

2. On event arrival (either channel):
   └─ Normalize topic to the shared namespace (motion / human / tamper / …)
   └─ Dedup by (camera, topic) within the debounce window (default 5 s, collapses cross-protocol duplicates)
   └─ Capture snapshot in-process (rate-limited to one per camera per window)
   └─ A processing layer converts the raw protocol message into schema 1.0 (raw fields are never persisted)
   └─ Append one JSON line to events/camera_events.txt (single source of truth)

3. manage_camera_events(action="poll" / "wait") — always reads the disk store, advances the
   per-camera cursor in events/events_cursor.json → backlog survives MCP server restarts

4. Auto-resume (resume_persisted_monitors) — the host may recycle the MCP server process at any
   time, killing the listener threads. On server startup (async daemon thread, never blocks the
   stdio handshake) and at every poll/wait entry, persisted intents in events/monitor_state.json
   are re-armed for cameras whose listener is not running. Guards: non-blocking mutex (no double
   resume), 60 s retry cooldown per failed camera (offline devices are not probed on every poll),
   and an intent re-read before each start (a concurrent stop cancels the resume). This adds no
   authorization surface: only listeners the user enabled and never stopped are restored.
```

**State ownership:** listener threads and the in-memory hot cache live inside the MCP server process; the on-disk store under `events/` is the only cross-session state — event lines, per-camera cursors, and the monitoring intent (`monitor_state.json`) all survive process recycling. Writes are limited to the `snapshots/` and `events/` whitelist paths.

For the schema 1.0 field reference, alarm code mapping, and per-action tool details, see [commands/events.md](commands/events.md).

## Illumination Mode Control Architecture

Illumination control in `scripts/toolkit/illumination.py` follows the same **dual-protocol strategy** as PTZ, exposed as the single MCP tool `manage_illumination(action=get|set)`:

```
1. connect_device() succeeds (Phase 0 or Phase 2)
   └─ _probe_and_save_illumination() fires after connection
   └─ probe_illumination_capability():
      ├─ Try Skyworth private protocol (SK_SETTING_GET_FILLLIGHT_OPTION via TCP 9010)
      │  └─ Success → 15 parameter capabilities parsed, protocol="sky_private"
      └─ Fallback: ONVIF Imaging Service (GetMoveOptions)
         └─ Success → IlluminationConfiguration modes, protocol="onvif"
   └─ Results persisted to config.yaml as illumination_modes
   └─ Probe is non-blocking: failures are silently ignored (never blocks connection)

2. manage_illumination(action="get")
   └─ Route: always-try-TCP strategy (asymmetric with PTZ):
      ├─ Has IP → Try Skyworth private protocol first (TCP 9010)
      │  ├─ SK_SETTING_GET_FILLLIGHT_OPTION → parameter capabilities & ranges
      │  └─ SK_SETTING_GET_FILLLIGHT → all 15 current parameter values
      │  └─ TCP success → write back tcp_port to _connected_devices
      └─ TCP failed or no IP → Fallback to ONVIF Imaging Service
         ├─ GetMoveOptions → supported illumination modes
         └─ GetImagingSettings → current IlluminationConfiguration.Mode
   └─ Returns IlluminationResult(protocol, current_settings, capabilities, ...)

3. manage_illumination(action="set", daynightmode=2, brightness=80, ...)
   └─ Same always-try-TCP routing as get:
   └─ Skyworth private protocol path:
      ├─ GET current settings (SK_SETTING_GET_FILLLIGHT)
      ├─ Merge user-specified params into current settings (full-set write required by device)
      ├─ SET merged settings (SK_SETTING_SET_FILLLIGHT)
      └─ Re-query to confirm → returns previous_settings + current_settings
   └─ ONVIF fallback path:
      └─ SetImagingSettings with IlluminationConfiguration.Mode only
```

**Routing rationale (defense in depth):** The `manage_illumination` router checks for IP availability (not `tcp_port` presence) and always attempts TCP 9010 first. This addresses a three-layer defect: (1) `_try_connect_with_password` only stores `tcp_port` when the TCP path succeeds — ONVIF/RTSP paths omit it; (2) `_probe_and_save_illumination` writes back `tcp_port` to `_connected_devices` when TCP probe succeeds; (3) `_get_device_connection` always includes `tcp_port` in cached-fallback connection info. Together these ensure Skyworth devices always get a TCP attempt regardless of how they were connected.

**Protocol capability matrix:**

| Function | Skyworth Private (TCP 9010) | ONVIF Imaging ver20 |
|----------|:---------------------------:|:-------------------:|
| Query capability | `SK_SETTING_GET_FILLLIGHT_OPTION` (15 params) | `GetMoveOptions` (mode list) |
| Read settings | `SK_SETTING_GET_FILLLIGHT` (15 params) | `GetImagingSettings` (mode only) |
| Write settings | `SK_SETTING_SET_FILLLIGHT` (full-set merge) | `SetImagingSettings` (mode only) |
| Granularity | 15 parameters (daynight/filllight/brightness/timer/sensitivity) | 1 parameter (mode string) |

**Key design decisions:**
- **Non-blocking probe**: capability detection at connect time never delays the connection flow — failures are silently dropped.
- **Cached capability**: `illumination_modes` in config.yaml avoids re-probing on every session.
- **Full-set merge on write**: the Skyworth device requires all 15 parameters in every SET command. The tool handles this internally (GET → merge → SET); the Agent only passes the parameters it wants to change.
- **Imaging path probing** (ONVIF fallback): candidate paths (`/onvif/imaging_service`, `/onvif/Imaging`, `/onvif/device_service`) are tried in order; first SOAP Envelope response wins.
- **Minimal side-effects**: ONVIF `SetImagingSettings` only touches `IlluminationConfiguration.Mode` — exposure, white balance, and all other imaging parameters are left untouched.

For per-action tool details, parameter tables, and return field reference, see [commands/illumination.md](commands/illumination.md).

## Session Rules

| Rule | Value |
|------|-------|
| Idle timeout | **30 seconds** — agent must disconnect and release control when user stops interacting |
| Heartbeat mechanism | Agent sends periodic keepalive to IPC; IPC releases connection on timeout |
| Concurrent control | FIFO: only one agent has full control; others are view-only |


## Known Issues & Implementation Notes

### Chinese character paths (Windows)

OpenCV's `cv2.imwrite()` and `cv2.VideoWriter()` silently fail when the file path contains non-ASCII characters (e.g. Chinese usernames in the Windows user directory). The toolkit works around this by:
- **Screenshots:** Using `cv2.imencode()` + `numpy.tofile()` instead of `cv2.imwrite()`
- **Recordings:** Writing to a temporary file via `tempfile.mkstemp()` (ASCII path), then moving to the final destination on stop

If `save_path` is provided, ensure it is writable. The default `snapshots/` and `recordings/` directories are created automatically.

### Same-process connection requirement

The toolkit stores connection state in-memory inside the **MCP server process**. This means `connect_device` and subsequent operations (`capture_video_screenshot`, `get_audio_video_stream`, etc.) must be served by the same long-running `scripts/mcp_server.py` process — which is exactly what happens when all operations go through MCP tool calls.

This is also why bypassing the MCP layer breaks the system: a standalone script or a separate Python process has its own empty connection state, so any operation after `connect_device` fails or silently reconnects. **Never import toolkit modules directly — interact only via the MCP tools.**

### Skyworth camera RTSP paths

Skyworth IP cameras (discovered via `sky_discovery`) use non-standard RTSP paths. When the configured path fails, the toolkit tries fallback paths in order — standard ONVIF paths first (`/Streaming/Channels/101`, `/h264/ch1/main/av_stream`, `/live`), then the Skyworth paths below:

| Path | Stream | Typical Resolution |
|------|--------|-------------------|
| `/stream0` | Main stream | 2560x1440 |
| `/stream1` | Main stream (alt) | 2560x1440 |
| `/md0_0` | Main stream (alt) | 2560x1440 |
| `/md0_1` | Sub stream | 1280x720 |

## Dependencies

```
onvif-zeep      # ONVIF protocol (SOAP/WS-Discovery)
opencv-python   # Video capture, frame processing, snapshot
requests        # HTTP client (TCP channel, device probing)
psutil          # Network interface enumeration for LAN scanning
pyyaml          # config.yaml read/write (credential persistence)
```

