# Architecture Reference

Runtime-relevant architecture details. Connection flows are encapsulated in `scripts/toolkit/device_mgmt.py` and `scripts/toolkit/discovery.py` — the agent receives structured results with clear status codes.

## Script Map

```
scripts/
├── toolkit/
│   ├── discovery.py      # Skyworth private protocol discovery & TCP channel
│   ├── stream.py         # Audio/video streaming & storage
│   ├── ptz.py            # PTZ control (ONVIF + private protocol dual-channel)
│   ├── tracking.py       # AI tracking algorithms
│   ├── image_audio.py    # Picture & audio settings
│   ├── device_mgmt.py    # Device discovery, connection, config, management, cloud auth
│   ├── alarm.py          # Alarm settings
│   └── encoding_osd.py   # Video encoding & OSD
└── auth/
    ├── token_manager.py  # Token lifecycle (generate → validate → destroy)
    ├── cloud_client.py   # Smart Cloud API client
    └── session.py        # Keepalive & session management

local_auth_server/         # Standalone local auth server (OUTSIDE skill package)
├── server.py             # HTTP server + Web UI (authorization server, currently local)
├── config.py             # Server configuration constants
└── __init__.py
```

## Connection & Authorization Flow

The connection process involves two actors: the **Agent** (AI) and the **Tool** (device_mgmt.py + discovery.py). The tool handles protocol details internally; the Agent manages user interaction when password is needed.

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
   └─ Tool returns ConnectResult(status="pending_auth", needs_password=True, claw_id=...)

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

This is injected as a SOAP header for ONVIF service calls. RTSP URLs are auto-constructed with embedded credentials:

```
rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}
```

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
| ONVIF Port | WS-Discovery XAddrs parsing | **Parse from XAddrs — not always 80** |
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

**Connection state** is read from `device_mgmt._connected_devices` via a lazy import (avoids circular dependency at module load time). Each connection entry contains:
- `onvif_camera`: the ONVIF camera object (for ONVIF PTZ Service calls)
- `ip`, `username`, `password`, `tcp_port`: credentials for TCP channel (private protocol)

**Protocol capability matrix:**

| Function | ONVIF | Private Protocol |
|----------|:-----:|:----------------:|
| `control_ptz` (direction) | `ContinuousMove` + `Stop` | `SK_SETTING_SET_PTZ` cmd |
| `control_lens_zoom` | `ContinuousMove` (zoom axis) | `SK_SETTING_SET_PTZ` zoom+/zoom- |
| `get_ptz_parameters` | `GetStatus` | `SK_SETTING_GET_PTZ` |
| `stop_ptz` | `Stop` | `SK_SETTING_SET_PTZ` stop |
| `save_ptz_preset` | `SetPreset` | — |
| `go_to_preset` | `GotoPreset` | — |
| `calibrate_ptz` | — | `SK_SETTING_SET_PTZ` calibrate |
| `move_to_position` | — | `SK_SETTING_SET_PTZ` move (x/y/z) |
| `start_patrol_cruise` | Loop `GotoPreset` | — |

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
