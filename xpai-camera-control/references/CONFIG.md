# Configuration Reference

Full schema for `config.yaml` — the configuration file for the Camera Control skill.

## File Location

Place `config.yaml` at the skill root (`xpai-camera-control/config.yaml`) to define static camera configurations. Cameras discovered at runtime via WS-Discovery or USB scanning do not need to be pre-configured.

---

## Full Schema

```yaml
# ── Camera definitions ──
cameras:
  - name: string              # Required. Unique camera identifier
    connection_type: string   # "usb" | "onvif"

    # USB-specific
    device_index: int         # OpenCV device index (default: 0)
    device_model: string      # Model name (e.g. "LC2418")
    product_version: string   # Product version (e.g. "ZCR461")

    # ONVIF-specific
    ip: string                # Camera IP address
    port: int                 # ONVIF service port (default: 80, parsed from XAddrs)
    username: string          # Login username (default: "admin")
    password: string          # Login password
    rtsp_port: int            # RTSP port (default: 554)
    rtsp_path: string         # Main stream path (default: "/stream1")
    rtsp_sub_path: string     # Sub stream path (default: "/stream2")

    # Device identity (populated by discovery or manual entry)
    sn_code: string           # Device serial number (for cloud binding)
    pkdk: string              # Device public key identifier (for identity verification)

    # Device classification
    device_class: string      # "password_required" | "direct_connect" (default: auto-detect)

# ── Cloud Authorization ──
auth:
  cloud_url: string           # Smart Cloud API endpoint for authorization requests
  token_timeout: int          # Token validity period in seconds (default: 300)
  auth_timeout: int           # Cloud request timeout in seconds (default: 30)
  auto_request_auth: bool     # Auto-request cloud auth when connecting password-required devices (default: true)
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
| `port` | `80` | ONVIF service port. **Discovered cameras auto-fill from WS-Discovery XAddrs** (may not be 80). |
| `username` | `"admin"` | ONVIF login username. |
| `password` | `""` | ONVIF login password. |
| `rtsp_port` | `554` | RTSP streaming port. |
| `rtsp_path` | `"/stream1"` | Main stream RTSP path. When unknown, try common paths: `/stream1`, `/Streaming/Channels/101`, `/h264/ch1/main/av_stream`. |
| `rtsp_sub_path` | `"/stream2"` | Sub (lower quality) stream RTSP path. |

### Device Identity Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `sn_code` | `""` | Device serial number. Populated by ONVIF `GetDeviceInformation` during discovery or manually entered. Used for cloud binding. |
| `pkdk` | `""` | Device public key identifier. Exposed by device firmware / private protocol for identity verification. |
| `device_class` | auto | `"password_required"` (needs cloud Token auth) or `"direct_connect"` (no password needed). Auto-detected from device response. |

### RTSP URL Construction

The system builds RTSP URLs as:

```
rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}
```

When ONVIF is available, the URL is fetched dynamically via `GetStreamUri` which may return a different path. Bare RTSP URLs from ONVIF are auto-injected with auth credentials.

---

## Auth Config Details

The `auth` section configures cloud-based authorization for password-required devices.

| Field | Default | Notes |
|-------|---------|-------|
| `cloud_url` | `""` | Smart Cloud API endpoint. WorkBuddy sends connection requests here. Example: `https://smart-cloud.skyworth.com/api/camera/auth` |
| `token_timeout` | `300` | Token validity in seconds (5 min). Token expires after this period if unused. |
| `auth_timeout` | `30` | Timeout for cloud HTTP requests in seconds. |
| `auto_request_auth` | `true` | When `true`, automatically request cloud authorization when connecting a password-required device. When `false`, authorization must be triggered manually. |

---

## Example Configs

### Single ONVIF camera + cloud auth

```yaml
cameras:
  - name: office_cam
    connection_type: onvif
    ip: 192.168.1.100
    port: 80
    username: admin
    password: ""
    rtsp_port: 554
    rtsp_path: /stream1
    sn_code: ""
    device_class: password_required

auth:
  cloud_url: https://smart-cloud.skyworth.com/api/camera/auth
  token_timeout: 300
  auth_timeout: 30
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
  cloud_url: https://smart-cloud.skyworth.com/api/camera/auth
  auto_request_auth: true
```

### Mixed: ONVIF (cloud auth) + USB + direct-connect

```yaml
cameras:
  - name: main_ipc
    connection_type: onvif
    ip: 192.168.1.100
    port: 80
    username: admin
    password: secret123
    rtsp_port: 554
    rtsp_path: /Streaming/Channels/101
    sn_code: "SN20240001"
    device_class: password_required

  - name: desk_webcam
    connection_type: usb
    device_index: 1

  - name: garden_cam
    connection_type: onvif
    ip: 192.168.1.200
    port: 80
    username: admin
    password: ""
    rtsp_port: 554
    rtsp_path: /stream1
    device_class: direct_connect

auth:
  cloud_url: https://smart-cloud.skyworth.com/api/camera/auth
  token_timeout: 300
  auto_request_auth: true
```

### Discovery-only mode

```yaml
# No static cameras — rely entirely on WS-Discovery and USB scanning
cameras: []

auth:
  cloud_url: https://smart-cloud.skyworth.com/api/camera/auth
  auto_request_auth: true
```
