# Configuration Reference

Full schema for `config.yaml` — the configuration file for the Camera Control skill.

## File Location

Place `config.yaml` at the skill root (`xpai-camera-control/config.yaml`) to define camera configurations. Cameras discovered at runtime via WS-Discovery, Skyworth private protocol, or USB scanning do not need to be pre-configured.

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
    sn_code: string           # Device serial number
    pkdk: string              # Device public key identifier (for identity verification)

    # Device classification
    device_class: string      # "password_required" | "direct_connect" (default: auto-detect)
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
| `sn_code` | `""` | Device serial number. Populated by ONVIF `GetDeviceInformation` or Skyworth discovery during registration. |
| `pkdk` | `""` | Device public key identifier. Exposed by device firmware / private protocol for identity verification. |
| `device_class` | auto | `"password_required"` (needs username/password auth) or `"direct_connect"` (no password needed). Auto-detected from RTSP probe response. |

### RTSP URL Construction

The system builds RTSP URLs as:

```
rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}
```

When ONVIF is available, the URL is fetched dynamically via `GetStreamUri` which may return a different path. Bare RTSP URLs from ONVIF are auto-injected with auth credentials.

---

## Auth Config Details _(reserved for future use)_

The `auth` section is reserved for future cloud-based authorization support. Currently unused.

| Field | Default | Notes |
|-------|---------|-------|
| `cloud_url` | `""` | Reserved. Smart Cloud API endpoint for future authorization service. |
| `token_timeout` | `300` | Reserved. Token validity in seconds. |
| `auth_timeout` | `30` | Reserved. Cloud HTTP request timeout in seconds. |
| `auto_request_auth` | `true` | Reserved. |

---

## Example Configs

### Single ONVIF camera (password-required)

```yaml
cameras:
  - name: office_cam
    connection_type: onvif
    ip: 192.168.1.100
    port: 80
    username: admin
    password: "my_password"
    rtsp_port: 554
    rtsp_path: /stream1
    device_class: password_required

auth:
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
  cloud_url: ""
  auto_request_auth: true
```

### Mixed: ONVIF (password) + USB + direct-connect

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
  cloud_url: ""
  auto_request_auth: true
```

