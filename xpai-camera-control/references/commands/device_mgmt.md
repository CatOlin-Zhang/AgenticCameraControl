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
| `illumination_modes` | list[string] | Supported illumination modes (e.g. `["OFF", "AUTO", "ON"]`); empty = unsupported or not yet probed. Auto-populated by `connect_device()` via ONVIF Imaging Service probe. |

---

### `register_camera(name, ip="", port=0, username="admin", password="", rtsp_port=554, rtsp_path="/stream1", device_class="direct_connect", **kwargs) -> RegisterResult`

Write a camera entry to `config.yaml`, persisting credentials for future auto-connect.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (internal config write; does not expose credentials to user) |
| **Returns** | `RegisterResult` (see field table below) |
| **Parameters** | `name`: unique camera name. `ip`: camera IP. `port`: ONVIF port — **only pass a verified port; omit when unknown (0 = unknown)**, `connect_device` probes the real port and writes it back automatically. `username`/`password`: credentials (saved to config.yaml, never displayed). `rtsp_port`/`rtsp_path`: stream parameters. `device_class`: `"password_required"` or `"direct_connect"`. Additional kwargs: `sn_code`, `pkdk`, `rtsp_sub_path`, `connection_type`, `illumination_modes`. |
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
| `supported_illumination_modes` | list[string] | Supported illumination modes probed during discovery (empty when not probed or unsupported; populated by `connect_device()` post-connect) |

---

### `connect_device(camera_name, password=None, ip=None, port=None, rtsp_port=None, rtsp_path="/stream1", username="admin") -> ConnectResult`

Establish connection to a camera. Uses cached credentials (retry 3x) → user-provided password → RTSP probe, in that order.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (credentials are local-only) |
| **Returns** | `ConnectResult` (see field table and scenario examples below) |
| **When to call** | Phase 0 (cached cameras), Phase 2 (new cameras) |

**ConnectResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the connection succeeded |
| `auth_method` | string | Authentication method used: `"password"` or `"direct"` (empty if not connected) |
| `status` | string | `"connected"` / `"needs_password"` / `"pending_auth"` / `"failed"` |
| `error_message` | string | Failure reason or status detail (empty on success) |
| `needs_password` | bool | `true` = Agent must prompt user for password and re-call with `password` arg |
| `onvif_port` | int | Verified ONVIF port (0 = not verified; Skyworth: 2000) |

**ONVIF port verification:** before ONVIF auth, candidate ports (hint → 2000/80/8000/8899) are probed with unauthenticated `GetSystemDateAndTime`. Only ports returning a SOAP Envelope are accepted. Verified ports are written back to config.yaml automatically.

**Illumination capability probing:** after a successful connection (both password-auth and direct-connect paths), `connect_device()` automatically probes the ONVIF Imaging Service for supported illumination modes via `probe_illumination_capability()`. The result is persisted to `config.yaml` as `illumination_modes`. The probe is non-blocking — failures are silently ignored so they never delay the connection flow. If `illumination_modes` is already cached in config.yaml from a previous session, re-probing is skipped.

**Connection flow:**

1. Check `config.yaml` for cached credentials → if found, retry ONVIF auth up to 3 times (1s interval) → connect. All retries fail → auto-remove registration from config.yaml → return `status="failed"`, `needs_password=True`
2. If password provided by user → single attempt with ONVIF auth → TCP channel (no retry, no cache cleanup)
3. If no password and `device_class == "password_required"` → return `status="needs_password"`, prompt user for password
4. If not `password_required` → probe RTSP stream:
   - `200 OK` → direct-connect (`auth_method="direct"`)
   - `401 Unauthorized` → return `needs_password=True`
5. If device requires cloud authorization (SN-based auth) → return `status="pending_auth"` → Agent should call `big_connect()` or loop `poll_auth_status()`

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

**Cached credentials failed (registration auto-removed):**
```json
{
  "success": false,
  "auth_method": "",
  "status": "failed",
  "error_message": "缓存凭据连接失败（已重试 3 次）: ONVIF 认证失败. 已从 config.yaml 清除设备 '客厅摄像头' 的注册信息，请重新搜索并连接该设备。",
  "needs_password": true,
  "onvif_port": 0
}
```
→ Agent: re-discover via `search_devices()` and re-connect.

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

**Password required (no cached credentials):**
```json
{
  "success": false,
  "auth_method": "",
  "status": "needs_password",
  "error_message": "设备 客厅摄像头(192.168.1.100) 需要密码才能访问，请提供摄像头的管理密码（默认用户名一般为 admin）。",
  "needs_password": true,
  "onvif_port": 0
}
```
→ Agent: prompt user for password, then re-call `connect_device(camera_name, password=user_input, ip=..., rtsp_port=...)`.

**Connection failed (user-provided password wrong):**
```json
{
  "success": false,
  "auth_method": "",
  "status": "failed",
  "error_message": "密码认证失败: ONVIF 认证失败: 用户名或密码错误，请确认密码后重试",
  "needs_password": true,
  "onvif_port": 2000
}
```

**Pending cloud authorization:**
```json
{
  "success": false,
  "auth_method": "",
  "status": "pending_auth",
  "error_message": "设备需要云端授权，请在 APP 端确认授权后调用 big_connect 或 poll_auth_status 轮询结果",
  "needs_password": false,
  "onvif_port": 0
}
```
→ Agent: call `big_connect(camera_name)` for one-call flow, or loop `poll_auth_status(camera_name)`.

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

### `poll_auth_status(camera_name) -> AuthStatusResult`

Poll the cloud authorization status for a device. Called after `connect_device` returns `pending_auth`. Agent should loop with ~5s intervals (max 600s / 10 minutes).

| Aspect | Detail |
|--------|--------|
| **Safety** | None (read-only query) |
| **Returns** | `AuthStatusResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier or SN code (looks up device SN from config.yaml) |
| **When to call** | After `connect_device` returns `status="pending_auth"`, or as part of manual polling loop |

**AuthStatusResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Authorization status: `PENDING` / `AUTHORIZED` / `REJECTED` / `ERROR` |
| `camera_name` | string | Camera identifier |
| `message` | string | Human-readable status description |
| `auth_status_code` | int | Raw cloud authStatus code (0=pending, 1=authorized, 2=rejected) |
| `device_pwd` | string | Device password returned on authorization (empty otherwise) |

**Agent behavior:**
- `AUTHORIZED` → devicePwd has been auto-written to config.yaml; call `connect_device()` to complete connection
- `REJECTED` → user declined authorization in the app; inform user
- `PENDING` → continue polling (5s interval)
- `ERROR` → report error to user

---

### `big_connect(name="") -> AuthOrchestrateResult`

One-call cloud authorization flow: initiates authorization request + polls status (up to 10 minutes) + auto-connects on success. The device password is automatically written to config.yaml upon authorization.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (blocking call, may wait up to 10 minutes) |
| **Returns** | `AuthOrchestrateResult` (see field table below) |
| **Parameters** | `name`: camera name (optional; empty = auto-select if only one device, or return `needs_selection` if multiple) |
| **When to call** | After `connect_device` returns `pending_auth`, as a one-call alternative to manual polling |

**AuthOrchestrateResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the full flow succeeded |
| `status` | string | `authorized` / `rejected` / `timeout` / `error` / `no_devices` / `needs_selection` / `no_sn` / `cloud_error` |
| `camera_name` | string | Camera identifier |
| `sn` | string | Device serial number |
| `claw_id` | string | Agent session identifier |
| `device_pwd` | string | Device password (on authorization) |
| `error_message` | string | Failure reason (empty on success) |
| `available_cameras` | list | Camera list (only when `status="needs_selection"`) |

**Internal flow (transparent to Agent):**
1. Resolve target camera from config.yaml
2. POST `/deviceAuthReq` with `{claw_id, sn, device_ip, device_model}`
3. Poll GET `/checkAuth` every 5s (up to 120 polls = 10 min)
4. On authorization: auto-write devicePwd to config.yaml via `register_camera()`

---
