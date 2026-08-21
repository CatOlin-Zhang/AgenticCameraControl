# Architecture Reference

Runtime-relevant architecture details. Connection flows are encapsulated inside the tool layer — the agent receives structured results with clear status codes and does not need to understand protocol internals.

## Module Map

```
Toolkit modules (exposed via MCP tools):
  device_mgmt   — Device discovery, connection, config, management
  stream        — Audio/video streaming, snapshot, recording, storage
  ptz           — PTZ control (ONVIF + private protocol dual-channel)
  events        — Event/alarm receiving (Skyworth private RTSP-channel push), schema 1.0 store
  illumination  — Illumination mode query & control (Skyworth private protocol + ONVIF Imaging fallback)
  image_settings— Image parameter query & control (Skyworth private protocol + ONVIF Imaging fallback)
  tracking      — Detection & tracking query & control (Skyworth private protocol only)

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
   └─ Three-channel verification: TCP 9010 + ONVIF + RTSP (password must pass RTSP auth)
   └─ Retries up to 3 times (1s interval)
   └─ Success → ConnectResult(success=True, auth_method="password")
   └─ No user interaction required
   └─ All retries fail → Tool attempts cloud re-authorization (if SN available)
      ├─ Cloud succeeds → auto-connect with cloud password, credentials persisted
      ├─ Cloud fails or no SN → Tool removes registration from config.yaml
         → ConnectResult(success=False, status="needs_password", needs_password=True)
         → Agent prompts user for password
```

### Flow for Password-Required Cameras (No Cached Credentials — Cloud Auth Auto-Triggered)

```
1. Agent → calls connect_device(camera_name, sn_code="SN123456")
   └─ Tool checks config.yaml → no cached password
   └─ Tool detects device_class == "password_required"
   └─ Tool internally triggers cloud authorization:
      ├─ SN available → request cloud auth → poll for result
      │  ├─ AUTHORIZED → auto-connect with cloud password → credentials persisted
      │  │  → ConnectResult(success=True, auth_method="password")
      │  ├─ REJECTED → user declined in app
      │  │  → ConnectResult(success=False, status="auth_rejected")
      │  ├─ Cloud unreachable (network error)
      │  │  → ConnectResult(success=False, status="needs_password")
      │  ├─ Cloud password mismatch (authorized but connect fails)
      │  │  → ConnectResult(success=False, status="cloud_pwd_failed")
      │  └─ Timeout
      │     → ConnectResult(success=False, status="needs_password")
      └─ SN unavailable → ConnectResult(success=False, status="needs_password")

2. Agent handles result by status:
   ├─ success=True → no action, credentials auto-persisted
   ├─ needs_password → prompt user, call connect_device(name, password=..., ip=..., rtsp_port=...)
   ├─ auth_rejected → inform user, cannot connect
   └─ cloud_pwd_failed → inform user password mismatch, ask for correct password
```

### Flow for Password-Required Cameras (User Provides Password)

```
1. Agent → calls connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)
   └─ Single attempt with user-provided password (no retry, no cache cleanup)
   └─ Three-channel verification: TCP 9010 + ONVIF + RTSP (password must pass RTSP auth)
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

Skyworth cameras use a vendor-specific protocol for discovery, PTZ control, illumination, image settings, and tracking. Protocol details are handled internally by the toolkit; this section describes the architecture at a high level.

| Aspect | Description |
|--------|-------------|
| Discovery | Vendor-specific broadcast/unicast over UDP; supplements WS-Discovery with additional device metadata (SN, MAC, channels) |
| Command channel | HTTP-based TCP command channel (port auto-detected during connection) |
| ONVIF port | Auto-probed during `connect_device` (not always 80; port 80 typically serves the web UI) |
| RTSP paths | Non-standard paths; the toolkit auto-tries multiple fallback paths when the configured path fails |

### Key Discovery Fields

| Field | Source | Purpose |
|-------|--------|---------|
| SN (Serial Number) | Skyworth private protocol unicast probe after WS-Discovery | Unique device identifier, required for cloud authorization. WS-Discovery does **not** provide SN; it is supplemented via the Skyworth discovery protocol. |
| Model | WS-Discovery Scopes / ONVIF | Device model identification |
| ONVIF Port | WS-Discovery XAddrs parsing | **Parse from XAddrs — not always 80**. The real port is probed & persisted by `connect_device`. |
| IP Address | WS-Discovery source address | LAN communication address |

### SN Supplement Probe (WS-Discovery → Skyworth Private)

WS-Discovery (ONVIF) does not return the device SN, which blocks the cloud authorization path. To solve this, after WS-Discovery finds a device, a **unicast SN probe** is performed using the Skyworth private protocol:

```
1. WS-Discovery discovers device at IP X
   └─ A unicast SN probe is sent to the device via Skyworth private protocol

2. Probe result:
   └─ SN extracted from response → attached to DiscoveredDevice.sn_code
   └─ Timeout / non-Skyworth device / network error → sn_code=""

3. Agent passes sn_code to connect_device() for cloud auth
   └─ Non-Skyworth devices: sn_code="" → cloud auth skipped, falls back to needs_password
```

This probe is **non-blocking** for the main discovery flow — a short timeout ensures non-Skyworth devices do not slow down discovery.

### Fallback Discovery

When WS-Discovery fails (firewall, non-ONVIF cameras, wrong subnet):
1. Enumerate local IPs via `psutil.net_if_addrs()`
2. Scan each subnet for port 80 (HTTP) and 554 (RTSP)
3. Fingerprint HTTP responses for camera signatures 
4. Try RTSP connection with common URL patterns

## Device Classification

| Type | Auth | Agent Behavior |
|------|------|---------------|
| Password-Required (cached) | Three-channel verification (TCP 9010 + ONVIF + RTSP) from config.yaml (retry 3x) | Auto-connect — no user input needed. All retries fail → cloud re-auth attempted (if SN available) → still fails → registration auto-removed, Agent prompts for password |
| Password-Required (uncached, cloud auth) | Cloud authorization auto-triggered inside `connect_device` | Tool handles cloud auth internally. Agent handles returned status: `success` / `needs_password` / `auth_rejected` / `cloud_pwd_failed` |
| Password-Required (uncached, user password) | User provides password → three-channel verification (TCP + ONVIF + RTSP) | Agent detects `needs_password` → prompts user → connects with password → registers credentials |
| Direct-Connect | None | Auto-connect — RTSP probe returns 200 OK |

## Cloud Authorization Flow (Internal)

Cloud authorization is fully encapsulated inside `connect_device` via internal functions. The Agent does **not** call any separate cloud auth tool — `big_connect` and `poll_auth_status` have been deprecated as external MCP tools.

```
1. connect_device() detects password_required / auth_required
   └─ Internal cloud auth function is invoked

2. Cloud auth process:
   ├─ Check SN availability → no SN → return needs_password
   ├─ Request authorization from cloud server (with device identity info)
   │  └─ Failure (network/server error) → return needs_password
   ├─ Register device info to config.yaml
   ├─ Poll authorization status (with timeout)
   │  ├─ AUTHORIZED → try connect with cloud-provided credentials
   │  │  ├─ Connect success → persist credentials → return connected
   │  │  └─ Connect failure → return cloud_pwd_failed
   │  ├─ REJECTED → return auth_rejected
   │  ├─ ERROR → return needs_password
   │  └─ PENDING → continue polling
   └─ Timeout → return needs_password
```

**ConnectResult status values (cloud auth):**

| Status | Meaning |
|--------|--------|
| `connected` | Cloud authorized and connected successfully |
| `needs_password` | Cloud unavailable / no SN / timeout — Agent asks user for password |
| `auth_rejected` | User denied authorization in app — cannot connect |
| `cloud_pwd_failed` | Cloud authorized but password mismatch — device may have changed password |

**Password auto-persist:** Upon successful cloud authorization, the returned credentials are automatically written to `config.yaml` via `register_camera()`. Subsequent connections use the cached password.

## PTZ Dual-Protocol Architecture

PTZ control in `scripts/toolkit/ptz.py` implements a **dual-protocol strategy** with automatic fallback:

```
1. Agent calls control_ptz(camera_name, direction, speed)
   └─ Tool tries ONVIF PTZ Service (ContinuousMove + auto Stop)
   └─ If ONVIF succeeds → returns PTZMoveResult(protocol="onvif")
   └─ If ONVIF fails (no onvif_camera, no PTZ service, timeout)...
   └─ Tool falls back to Skyworth private protocol (vendor command via TCP channel)
   └─ If private succeeds → returns PTZMoveResult(protocol="sky_private")
   └─ If both fail → returns PTZMoveResult(success=False, error_message=...)
```

**Connection state** is held in-memory by the MCP server process (avoids cross-process state issues). Each connection entry contains:
- ONVIF camera object (for ONVIF PTZ Service calls)
- IP, username, password, TCP port (credentials for private protocol fallback)

**Protocol capability matrix:**

| Function | ONVIF | Private Protocol |
|----------|:-----:|:----------------:|
| `control_ptz` (direction) | `ContinuousMove` + `Stop` | Vendor PTZ command |
| `get_ptz_parameters` | `GetStatus` | Vendor status query |
| `stop_ptz` | `Stop` | Vendor stop command |
| `calibrate_ptz` | — | Vendor calibration command |

## Event Monitoring Architecture (Guardian Mode Foundation)

Event receiving in `scripts/toolkit/events.py` is **private-protocol only** (the former ONVIF pull-point channel has been removed), exposed as the single MCP tool `manage_camera_events(action=start|stop|poll|wait)`:

```
1. manage_camera_events(action="start") — after explicit user confirmation
   └─ Spawns one background listener thread per camera (the ONLY background threads in this skill)
   └─ Persists the monitoring intent to events/monitor_state.json (cleared only by action="stop")
   └─ Skyworth private protocol — alarm JSON (~94 bytes) pushed over a persistent RTSP session
      (User-Agent "skyworth", interleaved channel 0x65, endpoint = config.yaml main stream /md0_0)
   └─ Handshake is real: any non-200 DESCRIBE/SETUP/PLAY aborts into a reconnect backoff
      (2 s → 30 s exponential cap); status exposes rtsp_session / last_error

2. On event arrival:
   └─ Normalize topic to the shared namespace (motion / human / tamper / …)
   └─ Dedup by (camera, topic) within the debounce window (default 5 s)
   └─ Snapshot is sampled, not triggered: at most one per camera per fixed 30 s interval,
      captured asynchronously on a background thread with a pre-generated path (never blocks
      the alarm socket — a synchronous snapshot once stalled it and the device killed the
      session after its 30 s send timeout)
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
      ├─ Try Skyworth private protocol (vendor capability query via TCP channel)
      │  └─ Success → 15 parameter capabilities parsed, protocol="sky_private"
      └─ Fallback: ONVIF Imaging Service (GetMoveOptions)
         └─ Success → IlluminationConfiguration modes, protocol="onvif"
   └─ Results persisted to config.yaml as illumination_modes
   └─ Probe is non-blocking: failures are silently ignored (never blocks connection)

2. manage_illumination(action="get")
   └─ Route: always-try-TCP strategy (asymmetric with PTZ):
      ├─ Has IP → Try Skyworth private protocol first
      │  ├─ Query parameter capabilities & ranges
      │  └─ Query all 15 current parameter values
      │  └─ TCP success → cache port info
      └─ TCP failed or no IP → Fallback to ONVIF Imaging Service
         ├─ GetMoveOptions → supported illumination modes
         └─ GetImagingSettings → current IlluminationConfiguration.Mode
   └─ Returns IlluminationResult(protocol, current_settings, capabilities, ...)

3. manage_illumination(action="set", daynightmode=2, brightness=80, ...)
   └─ Same always-try-TCP routing as get:
   └─ Skyworth private protocol path:
      ├─ GET current settings
      ├─ Merge user-specified params into current settings (full-set write required by device)
      ├─ SET merged settings
      └─ Re-query to confirm → returns previous_settings + current_settings
   └─ ONVIF fallback path:
      └─ SetImagingSettings with IlluminationConfiguration.Mode only
```

**Routing rationale (defense in depth):** The `manage_illumination` router checks for IP availability (not cached port presence) and always attempts the private protocol TCP channel first. This ensures Skyworth devices always get a TCP attempt regardless of how they were initially connected.

**Protocol capability matrix:**

| Function | Skyworth Private (TCP channel) | ONVIF Imaging ver20 |
|----------|:------------------------------:|:-------------------:|
| Query capability | Vendor command (15 params) | `GetMoveOptions` (mode list) |
| Read settings | Vendor command (15 params) | `GetImagingSettings` (mode only) |
| Write settings | Vendor command (full-set merge) | `SetImagingSettings` (mode only) |
| Granularity | 15 parameters (daynight/filllight/brightness/timer/sensitivity) | 1 parameter (mode string) |

**Key design decisions:**
- **Non-blocking probe**: capability detection at connect time never delays the connection flow — failures are silently dropped.
- **Cached capability**: `illumination_modes` in config.yaml avoids re-probing on every session.
- **Full-set merge on write**: the Skyworth device requires all 15 parameters in every SET command. The tool handles this internally (GET → merge → SET); the Agent only passes the parameters it wants to change.
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

If `save_path` is provided, ensure it is writable. The default `snapshots/` and `vido/` directories are created automatically.

### Same-process connection requirement

The toolkit stores connection state in-memory inside the **MCP server process**. This means `connect_device` and subsequent operations (`capture_video_screenshot`, `get_audio_video_stream`, etc.) must be served by the same long-running `scripts/mcp_server.py` process — which is exactly what happens when all operations go through MCP tool calls.

This is also why bypassing the MCP layer breaks the system: a standalone script or a separate Python process has its own empty connection state, so any operation after `connect_device` fails or silently reconnects. **Never import toolkit modules directly — interact only via the MCP tools.**

### Skyworth camera RTSP paths

Skyworth IP cameras use non-standard RTSP paths. When the configured path fails, the toolkit automatically tries multiple fallback paths — standard ONVIF paths first, then vendor-specific alternatives. The fallback order and path list are handled internally; no configuration is needed from the Agent or user.

## Dependencies

```
onvif-zeep      # ONVIF protocol (SOAP/WS-Discovery)
opencv-python   # Video capture, frame processing, snapshot
requests        # HTTP client (TCP channel, device probing)
psutil          # Network interface enumeration for LAN scanning
pyyaml          # config.yaml read/write (credential persistence)
```

