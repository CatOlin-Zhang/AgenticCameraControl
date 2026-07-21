# Architecture Reference

Runtime-relevant architecture details only. Auth flows and token management are encapsulated in `scripts/auth/` — the agent receives success/failure + status codes.

## Script Map

```
scripts/
├── toolkit/
│   ├── stream.py         # Audio/video streaming & storage
│   ├── ptz.py            # PTZ & cruise control
│   ├── tracking.py       # AI tracking algorithms
│   ├── image_audio.py    # Picture & audio settings
│   ├── device_mgmt.py    # Device discovery, connection, config, auth polling
│   ├── alarm.py          # Alarm settings
│   └── encoding_osd.py   # Video encoding & OSD
└── auth/
    ├── token_manager.py  # Token lifecycle (generate → validate → destroy)
    ├── cloud_client.py   # Smart Cloud API client
    └── session.py        # Keepalive & session management
```

## Connection & Authorization Flow

The connection process involves two actors: the **Agent** (AI) and the **Tool** (device_mgmt.py). The tool handles protocol details internally; the Agent manages user interaction and authorization polling.

### Flow for Password-Required Cameras (no cached credentials)

```
1. Agent → calls connect_device(camera_name)
   └─ Tool sends authorization request to remote cloud server
   └─ Tool returns ConnectResult(status="pending_auth")

2. Agent → calls poll_auth_status(camera_name) in a loop
   └─ Tool queries remote server for authorization status update
   ─ Possible statuses:
     · "pending"    → user has not yet approved on camera app
     · "authorized" → user approved on camera app side
     · "rejected"   → user rejected or timeout expired
     · "error"      → server error

3. When status == "authorized":
   └─ Tool lists LAN cameras available for connection
   └─ Agent presents camera list to user
   └─ Agent prompts user to input camera password

4. Agent → calls connect_device(camera_name, password=user_input)
   └─ Tool uses ONVIF auth with username + user-provided password
   └─ Tool returns ConnectResult(success=True, auth_method="password")

5. Agent → calls register_camera(...)
   └─ Credentials written to config.yaml
   └─ Future sessions: Phase 0 reads config.yaml → auto-connect, no password needed
```

### Flow for Direct-Connect Cameras

```
1. Agent → calls connect_device(camera_name)
   └─ Tool connects directly via RTSP (no auth needed)
   └─ Tool returns ConnectResult(success=True, auth_method="direct")
```

### Flow for Cached Cameras (config.yaml has credentials)

```
1. Agent → calls connect_device(cam_name)
   └─ Tool reads username/password from config.yaml automatically
   └─ Tool connects via ONVIF auth with cached credentials
   └─ Tool returns ConnectResult(success=True, auth_method="password")
   └─ No user interaction required
```

## Device Discovery

### WS-Discovery Protocol

| Parameter | Value |
|-----------|-------|
| Multicast address | `239.255.255.250:3702` |
| Hello | Camera broadcasts on boot |
| Probe | Client multicast to trigger responses |
| ProbeMatch | Camera response with device info |
| Types filter | Must contain `NetworkVideoTransmitter` |
| Scopes | May contain brand/model info |

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
| Password-Required (uncached) | Cloud authorization + user password | Poll auth status → prompt user for password → connect → register credentials |
| Direct-Connect | None | Auto-connect — no auth needed |

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
requests        # HTTP client (cloud auth, device probing)
psutil          # Network interface enumeration for LAN scanning
```
