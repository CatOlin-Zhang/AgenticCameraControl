# Configuration Reference

Full schema for `config.yaml` — the configuration file for the Camera Control skill.

## File Location

Place `config.yaml` at the skill root (`xpai-camera-control/config.yaml`) to define camera configurations. Cameras discovered at runtime via WS-Discovery, Skyworth private protocol, or USB scanning do not need to be pre-configured.

---

## Full Schema

```yaml
# ── Machine identity ──
claw_id: string             # Auto-generated machine ID (claw-{MAC}-{timestamp}), persisted on first use

# ── Camera definitions ──
cameras:
  - name: string              # Required. Unique camera identifier
    connection_type: string   # "usb" | "onvif"

    # USB-specific
    device_index: int         # OpenCV device index (default: 0)
    device_model: string      # Model name (e.g. "LC2418")
    product_version: string   # Product version (e.g. "ZCR461")

    # ONVIF-specific (dual-format fields for cross-scheme compatibility)
    ip: string                # Camera IP address
    port: int                 # ONVIF service port (0 = unknown/unverified; auto-probed & written back by connect_device — Skyworth: 2000)
    onvif_port: int           # Alias for port (password auth scheme compatibility)
    username: string          # Login username (default: "admin")
    password: string          # Login password
    rtsp_port: int            # RTSP port (default: 554)
    rtsp_path: string         # Main stream path (default: "/stream1")
    rtsp_path_main: string    # Alias for rtsp_path (password auth scheme compatibility)
    rtsp_sub_path: string     # Sub stream path (default: "/stream2")
    rtsp_path_sub: string     # Alias for rtsp_sub_path (password auth scheme compatibility)

    # Device identity (populated by discovery or manual entry)
    sn_code: string           # Device serial number
    sn: string                # Alias for sn_code (password auth scheme compatibility)
    pkdk: string              # Device public key identifier (for identity verification)

    # Device classification
    device_class: string      # "password_required" | "direct_connect" (auto-detected via RTSP probe)

# ── Auth configuration ──
auth:
  local_auth_url: string      # Local auth server URL (default: "http://127.0.0.1:18899")
  cloud_url: string           # Cloud authorization API endpoint (reserved for future use)
  token_timeout: int          # Token validity in seconds (default: 300)
  auth_timeout: int           # Cloud HTTP request timeout in seconds (default: 30)
  auto_request_auth: bool     # Auto-request auth on connect (default: true)
```

---

## Camera Config Details

### `name` (required)

Unique string identifier for the camera.

- Static cameras: use descriptive names like `living_room`, `front_door`
- Auto-discovered cameras: registered as `discovered_<ip>` (e.g. `discovered_172_28_234_22`)

### `connection_type` (required)

| Value | Protocol | Use case |
|-------|----------|----------|
| `usb` | UVC / OpenCV | Local USB webcams |
| `onvif` | ONVIF + RTSP | LAN IP cameras |

### USB Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `device_index` | `0` | OpenCV `VideoCapture` index. Scan indices 0–9 with OpenCV to find available cameras. |
| `device_model` | `""` | Informational only. |
| `product_version` | `""` | Informational only. |

### ONVIF Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `ip` | `""` | Required for ONVIF cameras. |
| `port` | `0` (unknown) | ONVIF service port. **Only verified ports are persisted** — `connect_device` probes candidates (2000/80/8000/8899) and writes back the real port automatically (Skyworth cameras: 2000; port 80 is the web UI). `0` means not yet verified. |
| `onvif_port` | — | Alias for `port`. Written for compatibility with password auth scheme. |
| `username` | `"admin"` | ONVIF login username. |
| `password` | `""` | ONVIF login password. Auto-cached to config.yaml after successful connection. |
| `rtsp_port` | `554` | RTSP streaming port. |
| `rtsp_path` | `"/stream1"` | Main stream RTSP path. Aliases: `rtsp_path_main`. Skyworth cameras use `/stream0`, `/stream1`, `/md0_0`. |
| `rtsp_sub_path` | `"/stream2"` | Sub stream RTSP path. Aliases: `rtsp_path_sub`. Skyworth cameras use `/md0_1`, `/stream2`. |

### Device Identity Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `sn_code` | `""` | Device serial number. Populated by ONVIF `GetDeviceInformation` or Skyworth discovery during registration. |
| `sn` | `""` | Alias for `sn_code`. Written for compatibility with password auth scheme. |
| `pkdk` | `""` | Device public key identifier. Exposed by device firmware / private protocol for identity verification. |
| `device_class` | auto | Auto-detected by RTSP probe: 401 response → `"password_required"` (needs username/password); 200 response → `"direct_connect"` (no password, connects immediately). |

### RTSP URL Construction

The system builds RTSP URLs internally by auto-injecting credentials:

```
rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}
```

When ONVIF is available, the URL is fetched dynamically via `GetStreamUri` which may return a different path. Bare RTSP URLs from ONVIF are auto-injected with auth credentials (existing credentials in the URL are replaced). URL encoding is applied to username and password.

### Claw ID

Auto-generated machine identifier persisted at the top level of `config.yaml`:

| Field | Format | Notes |
|-------|--------|-------|
| `claw_id` | `claw-{MAC12}-{yyyyMMddHHmmssSSS}` | Generated on first use via `get_or_create_claw_id()`. Used in `request_cloud_auth()` to identify the requesting machine. Re-using the same claw_id prevents duplicate browser popups. |

---

## Auth Config Details

The `auth` section configures authorization settings for the camera control system.

| Field | Default | Notes |
|-------|---------|-------|
| `local_auth_url` | `"http://127.0.0.1:18899"` | Local authorization server URL. Must be running for browser-based auth flow with password-required cameras. Start with `python local_auth_server/server.py`. |
| `cloud_url` | `""` | Cloud authorization API endpoint (reserved for future use; currently `local_auth_url` handles all auth requests). |
| `token_timeout` | `300` | Reserved. Token validity in seconds. |
| `auth_timeout` | `30` | Reserved. Cloud HTTP request timeout in seconds. |
| `auto_request_auth` | `true` | Reserved. |

---

## Example Configs

### Single ONVIF camera (password-required, with local auth)

```yaml
claw_id: "claw-AABBCCDDEEFF-20260727143052000"

cameras:
  - name: office_cam
    connection_type: onvif
    ip: 192.168.1.100
    port: 2000          # verified ONVIF port (written back by connect_device)
    onvif_port: 2000
    username: admin
    password: "my_password"
    rtsp_port: 554
    rtsp_path: /stream1
    rtsp_path_main: /stream1
    rtsp_sub_path: /stream2
    rtsp_path_sub: /stream2
    sn_code: "SN20240001"
    sn: "SN20240001"
    device_class: password_required

auth:
  local_auth_url: "http://127.0.0.1:18899"
  cloud_url: ""
  auto_request_auth: true
```

### Direct-connect camera (no password)

```yaml
cameras:
  - name: front_cam
    connection_type: onvif
    ip: 192.168.1.50
    port: 2000
    username: admin
    password: ""
    rtsp_port: 554
    rtsp_path: /stream1
    device_class: direct_connect

auth:
  local_auth_url: "http://127.0.0.1:18899"
  cloud_url: ""
  auto_request_auth: true
```

### Mixed: ONVIF (password) + USB + direct-connect

```yaml
claw_id: "claw-AABBCCDDEEFF-20260727143052000"

cameras:
  - name: main_ipc
    connection_type: onvif
    ip: 192.168.1.100
    port: 2000
    onvif_port: 2000
    username: admin
    password: secret123
    rtsp_port: 554
    rtsp_path: /stream1
    rtsp_path_main: /stream1
    sn_code: "SN20240001"
    sn: "SN20240001"
    device_class: password_required

  - name: desk_webcam
    connection_type: usb
    device_index: 1

  - name: garden_cam
    connection_type: onvif
    ip: 192.168.1.200
    port: 2000
    username: admin
    password: ""
    rtsp_port: 554
    rtsp_path: /stream1
    device_class: direct_connect

auth:
  local_auth_url: "http://127.0.0.1:18899"
  cloud_url: ""
  auto_request_auth: true
```

