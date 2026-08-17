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

    # ONVIF-specific (dual-format fields for cross-scheme compatibility)
    ip: string                # Camera IP address
    port: int                 # ONVIF service port (0 = unknown/unverified; auto-probed & written back by connect_device)
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
    pkdk: string              # Device identity token (populated during registration)

    # Device classification
    device_class: string      # "password_required" | "direct_connect" (auto-detected via RTSP probe)

    # Illumination capability (auto-probed at connect time, cached)
    illumination_modes: list   # Supported illumination modes (e.g. ["OFF", "AUTO", "ON"]); empty = unsupported or not yet probed

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
| `port` | `0` (unknown) | ONVIF service port. **Only verified ports are persisted** — `connect_device` probes candidates and writes back the real port automatically. `0` means not yet verified. |
| `onvif_port` | — | Alias for `port`. Written for compatibility with password auth scheme. |
| `username` | `"admin"` | ONVIF login username. |
| `password` | `""` | ONVIF login password. Auto-cached to config.yaml after successful connection. |
| `rtsp_port` | `554` | RTSP streaming port. |
| `rtsp_path` | `"/stream1"` | Main stream RTSP path. Aliases: `rtsp_path_main`. Skyworth cameras use vendor-specific paths; the toolkit auto-tries fallback paths when the configured path fails. |
| `rtsp_sub_path` | `"/stream2"` | Sub stream RTSP path. Aliases: `rtsp_path_sub`. Same fallback behavior as main stream. |

### Device Identity Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `sn_code` | `""` | Device serial number. Populated by ONVIF `GetDeviceInformation` or Skyworth discovery during registration. |
| `sn` | `""` | Alias for `sn_code`. Written for compatibility with password auth scheme. |
| `pkdk` | `""` | Device identity token. Populated automatically during registration. |
| `device_class` | auto | Auto-detected by RTSP probe: 401 response → `"password_required"` (needs username/password); 200 response → `"direct_connect"` (no password, connects immediately). |
| `illumination_modes` | `[]` | Auto-probed by `connect_device()` via ONVIF Imaging Service `GetMoveOptions`. Contains supported illumination mode strings (e.g. `["OFF", "AUTO", "ON"]`) or empty list when the device does not support illumination mode switching or has not been probed yet. Written to config.yaml after the first successful connection; subsequent sessions read the cache and skip re-probing. |

### RTSP URL Construction

The system builds RTSP URLs internally by auto-injecting credentials:

```
rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}
```

When ONVIF is available, the URL is fetched dynamically via `GetStreamUri` which may return a different path. Bare RTSP URLs from ONVIF are auto-injected with auth credentials (existing credentials in the URL are replaced). URL encoding is applied to username and password.


## Example Configs

### Single ONVIF camera (password-required)

```yaml
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
    illumination_modes: ["OFF", "AUTO", "ON"]
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
```

### Mixed: ONVIF (password) + USB + direct-connect

```yaml
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
```

