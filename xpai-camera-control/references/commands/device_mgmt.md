# Device Management

Device discovery, connection, and management — `scripts/toolkit/device_mgmt.py`

---

## Safety Constraints

| Constraint | Meaning |
|------------|---------|
| **Explicit Prompt** | Inform the user what operation will be performed and wait for confirmation before executing. |
| **Code Validation** | Validate parameter legality, device state, and connection availability before executing. |
| **Explicit Authorization** | Requires user password input for sensitive operations. |

---

### `search_devices(method: str = "ws_discovery", timeout: int = 15) -> List[DeviceInfo]`

Search for available cameras on the local network.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | List of `DeviceInfo` objects (IP address, ONVIF port, model, SN, media capabilities, Skyworth protocol fields) |
| **Parameters** | `method`: `"ws_discovery"` for ONVIF WS-Discovery, `"sky_discovery"` for Skyworth private protocol (multicast `239.230.236.230:9008`), `"usb"` for USB enumeration. `timeout`: discovery timeout in seconds. |
| **Implementation** | WS-Discovery Probe + Passive Listen via `onvif-zeep` / Skyworth UDP multicast via `discovery.py` / OpenCV USB enumeration |

### `get_registered_cameras() -> List[CameraConfig]`

Read all camera entries from `config.yaml` and return their configurations.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | List of `CameraConfig` objects (all fields from config.yaml cameras section) |
| **Parameters** | None |
| **When to call** | At session start (Phase 0) — always call before any discovery |

### `register_camera(name, ip, port=80, username="admin", password="", rtsp_port=554, rtsp_path="/stream1", device_class="direct_connect", **kwargs) -> RegisterResult`

Write a camera entry to `config.yaml`, persisting credentials for future auto-connect.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (internal config write; does not expose credentials to user) |
| **Returns** | `RegisterResult` (success, camera name) |
| **Parameters** | `name`: unique camera name. `ip`: camera IP. `port`: ONVIF port. `username`/`password`: credentials (saved to config.yaml, never displayed). `rtsp_port`/`rtsp_path`: stream parameters. `device_class`: `"password_required"` or `"direct_connect"`. Additional kwargs: `sn_code`, `pkdk`, `rtsp_sub_path`. |
| **When to call** | After first successful `connect_device()` |

### `connect_device(camera_name, password=None, ip=None, port=None, rtsp_port=None, rtsp_path="/stream1", username="admin") -> ConnectResult`

Establish connection to a camera. Probes RTSP stream first to detect auth requirement.

**Connection flow:**

1. Check `config.yaml` for cached credentials → if found, connect directly
2. If password provided → attempt ONVIF auth → RTSP auth → TCP channel
3. If no password → probe RTSP stream:
   - `200 OK` → direct-connect (`auth_method="direct"`)
   - `401 Unauthorized` → return `needs_password=True`
   - Unreachable → try alternate RTSP paths, then fail

| Aspect | Detail |
|--------|--------|
| **Safety** | None (password is local-only, no cloud auth) |
| **Returns** | `ConnectResult` (success, auth_method, status, needs_password) |
| **When to call** | Phase 0 (cached cameras), Phase 2 (new cameras) |

### `query_device_model(camera_name) -> DeviceModelResult`

Query device model, firmware version, and status information.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `DeviceModelResult` (manufacturer, model, firmware version, serial number, hardware ID) |
| **Implementation** | ONVIF `GetDeviceInformation` |

### `update_firmware(camera_name, firmware_path=None) -> FirmwareResult` _(not yet exposed as MCP tool)_

Update device firmware.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation |

### `system_maintenance(camera_name, action) -> MaintenanceResult` _(not yet exposed as MCP tool)_

Perform system maintenance operations.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation |
| **Parameters** | `action`: `"reboot"`, `"calibrate_ptz"`, or `"factory_reset"` |
