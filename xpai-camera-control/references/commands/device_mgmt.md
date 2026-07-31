# Device Management

Device discovery, connection, and management — exposed as MCP tools by `scripts/mcp_server.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

---

## Safety Constraints

| Constraint | Meaning |
|------------|---------|
| **Explicit Prompt** | Inform the user what operation will be performed and wait for confirmation before executing. |
| **Code Validation** | Validate parameter legality, device state, and connection availability before executing. |

---

### `get_registered_cameras() -> List[CameraConfig]`

Read all camera entries from `config.yaml` and return their configurations.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | List of `CameraConfig` objects (see field table below) |
| **Parameters** | None |
| **When to call** | At session start (Phase 0) — always call before any discovery |

**CameraConfig return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Camera unique identifier |
| `connection_type` | string | `"onvif"` or `"usb"` |
| `ip` | string | Camera IP address |
| `port` | int | ONVIF service port (0 = not yet verified) |
| `username` | string | Login username (default: `"admin"`) |
| `password` | string | Login password (loaded from config.yaml, never display to user) |
| `rtsp_port` | int | RTSP port (default: 554) |
| `rtsp_path` | string | Main stream RTSP path |
| `rtsp_sub_path` | string | Sub stream RTSP path |
| `device_class` | string | `"password_required"` or `"direct_connect"` |
| `sn_code` | string | Device serial number |
| `pkdk` | string | Device public key identifier |
| `device_index` | int | OpenCV device index (USB only) |
| `device_model` | string | USB device model name |
| `product_version` | string | USB product version |

---

### `register_camera(name, ip="", port=0, username="admin", password="", rtsp_port=554, rtsp_path="/stream1", device_class="direct_connect", **kwargs) -> RegisterResult`

Write a camera entry to `config.yaml`, persisting credentials for future auto-connect.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (internal config write; does not expose credentials to user) |
| **Returns** | `RegisterResult` (see field table below) |
| **Parameters** | `name`: unique camera name. `ip`: camera IP. `port`: ONVIF port — **only pass a verified port; omit when unknown (0 = unknown)**, `connect_device` probes the real port and writes it back automatically. `username`/`password`: credentials (saved to config.yaml, never displayed). `rtsp_port`/`rtsp_path`: stream parameters. `device_class`: `"password_required"` or `"direct_connect"`. Additional kwargs: `sn_code`, `pkdk`, `rtsp_sub_path`, `connection_type`. |
| **When to call** | After first successful `connect_device()` |

**RegisterResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the registration succeeded |
| `camera_name` | string | Name of the registered camera |
| `error_message` | string | Failure reason (empty on success) |

---

### `search_devices(timeout: float = 15.0) -> SearchResult`

Search for available cameras on the local network. The tool automatically selects the best discovery protocol and returns unified results.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `SearchResult` (see field tables below) |
| **Parameters** | `timeout`: discovery timeout in seconds (default 15.0). The tool internally tries all available protocols (ONVIF WS-Discovery, Skyworth private, USB) and merges results. |
| **Implementation** | Internally dispatches to the corresponding discovery protocol; results are normalized into `DiscoveredDevice` objects |

**SearchResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the search succeeded |
| `devices` | list | List of `DiscoveredDevice` objects (see table below) |
| `error_message` | string | Failure reason (empty on success) |

**DiscoveredDevice fields** (each item in `devices`):

| Field | Type | Description |
|-------|------|-------------|
| `ip` | string | Device IP address |
| `onvif_port` | int | ONVIF service port (0 = unknown; probed by `connect_device`) |
| `rtsp_port` | int | RTSP port (default: 554) |
| `device_class` | string | `"password_required"` or `"direct_connect"` (classified via RTSP probe) |
| `sn_code` | string | Device serial number |
| `model` | string | Device model |
| `manufacturer` | string | Manufacturer name |
| `supported_media` | list[string] | Supported media settings |
| `discovery_method` | string | How the device was found: `"ws_discovery"` / `"sky_discovery"` / `"usb"` |
| `sky_subtype` | string | Skyworth device subtype (1=bullet/2=dome/3=halfdome/5=PTZ/6=bullet+dome); empty for non-Skyworth |
| `sky_name` | string | Device display name (Skyworth only) |
| `sky_dtype` | string | Device type code (Skyworth only) |
| `sky_hw_version` | string | Hardware version (Skyworth only) |
| `sky_sw_version` | string | Software version (Skyworth only) |
| `sky_did` | string | Device ID (Skyworth only) |
| `sky_channels` | int | Channel count (0=non-Skyworth, 1=mono, 2=binocular) |
| `sky_channel_list` | list | Channel details with RTSP codec modes (Skyworth only) |
| `sky_web_port` | int | Web UI port (Skyworth only) |
| `sky_udp_port` | int | UDP command port (Skyworth only) |
| `sky_net_type` | string | Network type: `"eth"` / `"wifi"` (Skyworth only) |
| `sky_ip_mode` | string | IP mode: 0=DHCP, 1=adaptive, 2=manual (Skyworth only) |
| `sky_mask` | string | Subnet mask (Skyworth only) |
| `sky_gateway` | string | Gateway address (Skyworth only) |
| `sky_mac` | string | MAC address (Skyworth only) |

---

### `connect_device(camera_name, password=None, ip=None, port=None, rtsp_port=None, rtsp_path="/stream1", username="admin") -> ConnectResult`

Establish connection to a camera. Uses cached credentials → ONVIF auth → authorization server → RTSP probe, in that order.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (credentials are local-only; authorization server backend is pluggable) |
| **Returns** | `ConnectResult` (see field table and scenario examples below) |
| **When to call** | Phase 0 (cached cameras), Phase 2 (new cameras) |

**ConnectResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the connection succeeded |
| `auth_method` | string | Authentication method used: `"password"` or `"direct"` (empty if not connected) |
| `status` | string | `"connected"` / `"pending_auth"` / `"needs_password"` / `"failed"` |
| `error_message` | string | Failure reason or status detail (empty on success) |
| `needs_password` | bool | `true` = Agent must prompt user for password and re-call with `password` arg |
| `onvif_port` | int | Verified ONVIF port (0 = not verified; Skyworth: 2000) |

**ONVIF port verification:** before ONVIF auth, candidate ports (hint → 2000/80/8000/8899) are probed with unauthenticated `GetSystemDateAndTime`. Only ports returning a SOAP Envelope are accepted. Verified ports are written back to config.yaml automatically.

**Connection flow:**

1. Check `config.yaml` for cached credentials → if found, verify via ONVIF → connect
2. If password provided → probe & verify ONVIF port → attempt ONVIF auth → TCP channel
3. If no password and `device_class == "password_required"`:
   - Authorization server reachable → return `status="pending_auth"`
   - Authorization server unreachable → return `status="needs_password"`
4. If not `password_required` → probe RTSP stream:
   - `200 OK` → direct-connect (`auth_method="direct"`)
   - `401 Unauthorized` → return `needs_password=True`

#### Return JSON examples by scenario

**Cached credentials — auto-connect (Phase 0):**
```json
{
  "success": true,
  "auth_method": "password",
  "status": "connected",
  "error_message": "",
  "needs_password": false,
  "onvif_port": 2000
}
```

**Direct-connect — no password needed:**
```json
{
  "success": true,
  "auth_method": "direct",
  "status": "connected",
  "error_message": "",
  "needs_password": false,
  "onvif_port": 0
}
```

**Password required, auth server available (pending_auth):**
```json
{
  "success": false,
  "auth_method": "",
  "status": "pending_auth",
  "error_message": "设备需要密码授权，已发送授权请求。请在浏览器中确认。",
  "needs_password": true,
  "onvif_port": 0
}
```
→ Agent: call `poll_auth_status()` every ~5s (max 120s), then prompt user for password.

**Password required, auth server unreachable (needs_password):**
```json
{
  "success": false,
  "auth_method": "",
  "status": "needs_password",
  "error_message": "设备需要密码，授权服务器不可达。请直接输入密码。",
  "needs_password": true,
  "onvif_port": 0
}
```
→ Agent: prompt user for password directly, then re-call `connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)`.

**Connection failed:**
```json
{
  "success": false,
  "auth_method": "",
  "status": "failed",
  "error_message": "ONVIF 认证失败: 用户名或密码错误",
  "needs_password": false,
  "onvif_port": 2000
}
```

---

### `disconnect_device(camera_name) -> DisconnectResult`

Disconnect a camera and release all resources (ONVIF connection, session state).

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `DisconnectResult` (see field table below) |
| **When to call** | When the user is done with a camera or before re-connecting with new credentials |

**DisconnectResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the disconnect succeeded |
| `session_released` | bool | Whether the cloud session was released |
| `error_message` | string | Failure reason (empty on success) |

---

### `request_cloud_auth(camera_name, sn="", device_ip="", device_model="") -> CloudAuthRequestResult`

Submit an authorization request to the authorization server (currently local, pluggable for cloud). Normally called internally by `connect_device()` — the Agent rarely needs to call this directly.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (only sends device info, no credentials) |
| **Returns** | `CloudAuthRequestResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `sn`: device serial number (auto-lookup from config if omitted). `device_ip`: device IP (optional). `device_model`: device model (optional). |
| **When to call** | After `connect_device()` returns `status="pending_auth"` (normally handled internally) |

**CloudAuthRequestResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the POST was delivered (HTTP 200) |
| `claw_id` | string | Machine ID used for this request (persisted in config.yaml) |
| `error_message` | string | Failure reason (empty on success) |

---

### `poll_auth_status(camera_name) -> AuthStatusResult`

Poll the authorization server to check if the user has confirmed authorization in the browser.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `AuthStatusResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier |
| **When to call** | After `connect_device()` returns `status="pending_auth"`. Poll every ~5s, max 120s. |

**AuthStatusResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"pending"` (user hasn't confirmed yet) / `"authorized"` (user approved) / `"rejected"` (user denied or timeout) / `"error"` (server error) |
| `camera_name` | string | Camera identifier |
| `message` | string | Status description (e.g. `"用户已授权"` or `"超时未确认"`) |

**Agent flow after `authorized`:** prompt user for camera password → call `connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)` → on success call `register_camera()`.
