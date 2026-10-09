# Configuration Reference

Full schema for `config.yaml` — the configuration file for the Camera Control skill.

## File Location

Place `config.yaml` at the skill root (`xpai-camera-control/config.yaml`) to define camera configurations. Cameras discovered at runtime via WS-Discovery, XPAI private protocol, or USB scanning do not need to be pre-configured.

**Automatic sync:** `search_devices()` writes every discovered and reachable camera into this file (basic info only — name, IP, SN, device class, ports; never a password) and removes entries that are no longer discoverable **and** unreachable. `connect_device()` persists credentials and the verified ONVIF port after a successful connection. Manual edits are possible but not required.

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
    onvif_sn: string          # ONVIF GetDeviceInformation SerialNumber (O-class identity/matching only — NEVER used as sn_code / for cloud auth)
    pkdk: string              # Device identity token (populated during registration)

    # Device classification
    device_class: string      # "password_required" | "direct_connect" (auto-detected via RTSP probe)

    # Illumination capability (auto-probed at connect time, cached)
    illumination_modes: list   # Supported illumination modes (e.g. ["OFF", "AUTO", "ON"]); empty = unsupported or not yet probed

    # Protocol classification (resolved and persisted by connect_device via the authoritative SK-first unicast probe)
    protocol_type: string      # "S" (Skyworth private) | "J" (JCP, ONVIF PTZ + RTSP media) | "O" (third-party ONVIF-only, degraded) | "" (not yet resolved; legacy values incl. "W" are treated as SK)

```

---

## Camera Config Details

### `name` (required)

Unique string identifier for the camera.

- Static cameras: use descriptive names like `living_room`, `front_door`
- Auto-discovered cameras: registered as `<model|SN|"camera">_<last IP octet>` (e.g. `CSDE2_107` for a camera at `192.168.1.107`). The name is derived from the discovery result — when a camera's IP changes, the next `search_devices()` re-registers it under a name derived from the new IP.

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
| `rtsp_path` | `"/stream1"` | Main stream RTSP path. Aliases: `rtsp_path_main`. XPAI cameras use vendor-specific paths; the toolkit auto-tries fallback paths when the configured path fails. |
| `rtsp_sub_path` | `"/stream2"` | Sub stream RTSP path. Aliases: `rtsp_path_sub`. Same fallback behavior as main stream. |

### Device Identity Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `sn_code` | `""` | Device serial number from SK/JCP discovery — the key of the SK private-protocol ecosystem (cloud authorization, SK HTTP illumination/image). Never populate it with an ONVIF serial. |
| `sn` | `""` | Alias for `sn_code`. Written for compatibility with password auth scheme. |
| `onvif_sn` | `""` | ONVIF `GetDeviceInformation` SerialNumber, persisted only for O-class entries. Identity/matching only (e.g. re-aligning a registry entry after a DHCP IP change) — **never** used as `sn_code`, never sent to cloud auth or SK HTTP. |
| `pkdk` | `""` | Device identity token. Populated automatically during registration. |
| `device_class` | auto | Auto-detected by RTSP probe: 401 response → `"password_required"` (needs username/password); 200 response → `"direct_connect"` (no password, connects immediately). |
| `illumination_modes` | `[]` | Auto-probed by `connect_device()` via ONVIF Imaging Service `GetMoveOptions`. Contains supported illumination mode strings (e.g. `["OFF", "AUTO", "ON"]`) or empty list when the device does not support illumination mode switching or has not been probed yet. Written to config.yaml after the first successful connection; subsequent sessions read the cache and skip re-probing. |
| `protocol_type` | `""` | Protocol class resolved and persisted by `connect_device` via the authoritative SK-first unicast probe: `"S"` (Skyworth private — full feature set), `"J"` (JCP — media over RTSP + PTZ over ONVIF; illumination/image/tracking/events and PTZ calibration/degrees are unsupported), or `"O"` (third-party ONVIF-only — same degradation as J plus **no cloud authorization**; asserted only when SK/JCP probes are empty and the ONVIF admission probe passes). `search_devices` only asserts `"S"` when the device answered SK private discovery (conclusive); devices found via JCP/WS-Discovery carry no asserted class, since both protocols are shared with S-class firmware. Empty = not yet resolved (legacy values incl. `"W"` are treated as SK). |

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

### JCP (J-class) camera

```yaml
cameras:
  - name: garage_jcp
    connection_type: onvif
    ip: 192.168.1.112
    port: 2000              # verified ONVIF port (JCP devices commonly use 2000)
    onvif_port: 2000
    username: admin
    password: "76b2f1"
    rtsp_port: 554
    rtsp_path: /md0_0       # ONVIF-authoritative main stream path (from GetStreamUri)
    rtsp_sub_path: /md0_1   # ONVIF-authoritative sub stream path
    sn_code: "0336143000123440001025"
    device_class: password_required
    protocol_type: J        # media over RTSP, PTZ over ONVIF; SK-only features unsupported
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

### Third-party ONVIF camera (O-class, degraded)

```yaml
cameras:
  - name: office_thirdparty
    connection_type: onvif
    ip: 192.168.1.120
    port: 80                # verified ONVIF port (written back by connect_device)
    onvif_port: 80
    username: admin
    password: "847226"      # quote pure-numeric passwords so YAML keeps them strings
    rtsp_port: 554
    rtsp_path: /Streaming/Channels/101    # ONVIF GetStreamUri-authoritative path
    rtsp_sub_path: /Streaming/Channels/102
    device_class: password_required
    protocol_type: O        # asserted by connect_device: SK/JCP silent, ONVIF admission passed
    onvif_sn: "0123456789ABCDEF"   # ONVIF SerialNumber — identity only, never sn_code
    # sn_code / sn intentionally absent: O-class has no SK/JCP SN; cloud auth unavailable
```

