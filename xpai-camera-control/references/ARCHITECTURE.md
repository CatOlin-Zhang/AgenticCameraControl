# Architecture Reference

Runtime-relevant architecture details. Connection flows are encapsulated in `scripts/toolkit/device_mgmt.py` and `scripts/toolkit/discovery.py` — the agent receives structured results with clear status codes.

## Script Map

```
scripts/
├── toolkit/
│   ├── discovery.py      # Skyworth private protocol discovery & TCP channel
│   ├── stream.py         # Audio/video streaming & storage
│   ├── ptz.py            # PTZ & cruise control
│   ├── tracking.py       # AI tracking algorithms
│   ├── image_audio.py    # Picture & audio settings
│   ├── device_mgmt.py    # Device discovery, connection, config, management
│   ├── alarm.py          # Alarm settings
│   └── encoding_osd.py   # Video encoding & OSD
└── auth/
    ├── token_manager.py  # Token lifecycle (generate → validate → destroy)
    ├── cloud_client.py   # Smart Cloud API client
    └── session.py        # Keepalive & session management
```

## Connection & Authorization Flow

The connection process involves two actors: the **Agent** (AI) and the **Tool** (device_mgmt.py + discovery.py). The tool handles protocol details internally; the Agent manages user interaction when password is needed.

### Flow for Password-Required Cameras (no cached credentials)

```
1. Agent → calls connect_device(camera_name)
   └─ Tool sends RTSP DESCRIBE probe to camera
   └─ Tool receives 401 Unauthorized response
   └─ Tool returns ConnectResult(status="needs_password", needs_password=True, ip=..., rtsp_port=...)

2. Agent → prompts user for camera password
   └─ User provides password to Agent

3. Agent → calls connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)
   └─ Tool attempts ONVIF auth → RTSP auth → TCP channel (port 9010)
   └─ Tool returns ConnectResult(success=True, auth_method="password")

4. Agent → calls register_camera(...)
   └─ Credentials written to config.yaml
   └─ Future sessions: Phase 0 reads config.yaml → auto-connect, no password needed
```

### Flow for Direct-Connect Cameras

```
1. Agent → calls connect_device(camera_name)
   └─ Tool sends RTSP DESCRIBE probe → receives 200 OK
   └─ Tool connects directly via RTSP (no auth needed)
   └─ Tool returns ConnectResult(success=True, auth_method="direct")
```

### Flow for Cached Cameras (config.yaml has credentials)

```
1. Agent → calls connect_device(cam_name)
   └─ Tool reads username/password from config.yaml automatically
   └─ Tool connects via ONVIF auth / TCP channel with cached credentials
   └─ Tool returns ConnectResult(success=True, auth_method="password")
   └─ No user interaction required
```

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
| Password-Required (cached) | ONVIF username/password from config.yaml | Auto-connect — no user input needed |
| Password-Required (uncached) | RTSP probe → 401 → user provides password | Detect `needs_password` → prompt user → connect with password → register credentials |
| Direct-Connect | None | Auto-connect — RTSP probe returns 200 OK |

## Session Rules

| Rule | Value |
|------|-------|
| Idle timeout | **30 seconds** — agent must disconnect and release control when user stops interacting |
| Heartbeat mechanism | Agent sends periodic keepalive to IPC; IPC releases connection on timeout |
| Concurrent control | FIFO: only one agent has full control; others are view-only |

## Dependencies

```
onvif-zeep      # ONVIF protocol (SOAP/WS-Discovery)
opencv-python   # Video capture, frame processing, snapshot
requests        # HTTP client (TCP channel, device probing)
psutil          # Network interface enumeration for LAN scanning
```
