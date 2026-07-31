# Architecture Reference

Runtime-relevant architecture details. Connection flows are encapsulated inside the tool layer — the agent receives structured results with clear status codes and does not need to understand protocol internals.

## Module Map

```
Toolkit modules (exposed via MCP tools):
  device_mgmt   — Device discovery, connection, config, management, cloud auth
  stream        — Audio/video streaming, snapshot, recording, storage
  ptz           — PTZ control (ONVIF + private protocol dual-channel)
  events        — Event/alarm receiving (ONVIF PullPoint + private RTSP-channel push), schema 1.0 store

Internal modules (not exposed, accessed only through MCP tools above):
  discovery     — Skyworth private protocol discovery & TCP command channel
  auth/         — Token lifecycle, cloud API client, session management

Standalone (outside skill package):
  local_auth_server/ — HTTP server + Web UI (authorization server, currently local)
```

## Connection & Authorization Flow

The connection process involves two actors: the **Agent** (AI) and the **Tool** (device_mgmt.py + discovery.py). The tool handles protocol details internally; the Agent manages user interaction when password is needed.

### ONVIF Port Verification (inside `connect_device`)

Before ONVIF authentication, `connect_device` verifies the real ONVIF port internally: candidate ports (config/argument hint → 2000/80/8000/8899) are probed with an unauthenticated `GetSystemDateAndTime` request, and a port is only accepted if it returns a SOAP Envelope (not an HTML page). Verified ports are written back to config.yaml automatically; unverified ports stay `0` (= unknown). Skyworth cameras: ONVIF is on **2000** — port 80 is the web UI.

### Flow for Cached Cameras (config.yaml has credentials)

```
1. Agent → calls connect_device(cam_name)
   └─ Tool reads username/password from config.yaml automatically
   └─ Tool verifies credentials via ONVIF WS-UsernameToken authentication
   └─ Tool connects via ONVIF auth / TCP channel with cached credentials
   └─ Tool returns ConnectResult(success=True, auth_method="password")
   └─ No user interaction required
```

### Flow for Password-Required Cameras (with Local Auth Server)

```
1. Agent → calls connect_device(camera_name)
   └─ Tool checks config.yaml → no cached password
   └─ Tool detects device_class == "password_required"
   └─ Tool calls request_cloud_auth() → POST to local auth server
   └─ Tool returns ConnectResult(status="pending_auth", needs_password=True)
      (claw_id is included in error_message and persisted to config.yaml)

2. Agent → calls poll_auth_status() repeatedly (every ~5s, max 120s)
   └─ Tool GETs /api/auth/status from local auth server
   └─ User opens browser at http://127.0.0.1:18899 and clicks "Authorize"
   └─ poll_auth_status returns AuthStatus.AUTHORIZED

3. Agent → prompts user for camera password

4. Agent → calls connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)
   └─ Tool attempts ONVIF WS-UsernameToken auth → TCP channel (port 9010)
   └─ Tool returns ConnectResult(success=True, auth_method="password")

5. Agent → calls register_camera(...)
   └─ Credentials written to config.yaml (dual-format fields for compatibility)
   └─ Future sessions: Phase 0 reads config.yaml → auto-connect, no password needed
```

### Flow for Password-Required Cameras (Auth Server Unreachable — Fallback)

```
1. Agent → calls connect_device(camera_name)
   └─ Tool detects device_class == "password_required"
   └─ Tool calls request_cloud_auth() → connection refused
   └─ Tool returns ConnectResult(status="needs_password", needs_password=True)

2. Agent → prompts user for password directly (no browser step)

3. Agent → calls connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)
   └─ Same as step 4 above
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

### Claw ID

A **Claw ID** uniquely identifies the local machine for authorization requests. Format: `claw-{MAC}-{timestamp}`. Generated once and persisted to `config.yaml` to ensure re-sending auth requests doesn't create duplicate popups in the browser UI.

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
| Password-Required (cached) | ONVIF WS-UsernameToken from config.yaml | Auto-connect — no user input needed |
| Password-Required (uncached, auth server available) | `request_cloud_auth()` → browser confirmation → `poll_auth_status()` → user provides password | Detect `pending_auth` → poll auth → prompt password → connect → register |
| Password-Required (uncached, no auth server) | RTSP probe → 401 → user provides password | Detect `needs_password` → prompt user → connect with password → register credentials |
| Direct-Connect | None | Auto-connect — RTSP probe returns 200 OK |

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
requests        # HTTP client (TCP channel, device probing, local auth server)
psutil          # Network interface enumeration for LAN scanning
pyyaml          # config.yaml read/write (credential persistence, claw_id)
```

## Authorization Server Architecture

The authorization server (`local_auth_server/server.py`) is a **standalone Python process** outside the skill package that implements the authorization flow. Currently runs locally; the architecture is pluggable — `local_auth_url` in config.yaml can point to a cloud service in the future.

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/auth/request` | Skill submits auth request `{sn, claw_id, device_ip, device_model}` |
| `GET` | `/api/auth/status` | Skill polls status `?sn=xxx&claw_id=yyy` |
| `POST` | `/api/auth/action` | User submits browser action `{sn, claw_id, action}` |
| `GET` | `/api/auth/list` | List all auth requests (used by Web UI) |
| `GET` | `/` | Authorization management Web UI |

**State Management:** In-memory dict keyed by `(sn, claw_id)` tuple, thread-safe via `threading.Lock`. States: `pending` → `authorized` or `rejected`.

**Web UI:** Auto-refreshes every 3 seconds. Shows pending requests with Authorize/Reject buttons. Auto-opens browser on server start.

**Configuration:** Default port `18899`, configurable via `--port` argument or `LOCAL_AUTH_URL` environment variable.
