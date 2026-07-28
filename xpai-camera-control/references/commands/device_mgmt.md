# Device Management

Device discovery, connection, and management — `scripts/toolkit/device_mgmt.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

---

## Safety Constraints

| Constraint | Meaning |
|------------|---------|
| **Explicit Prompt** | Inform the user what operation will be performed and wait for confirmation before executing. |
| **Code Validation** | Validate parameter legality, device state, and connection availability before executing. |

---

### `search_devices(method: str = "ws_discovery", timeout: float = 15.0) -> SearchResult`

Search for available cameras on the local network.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `SearchResult` (success, error_message, `devices`: list of `DiscoveredDevice` objects — IP address, ONVIF port, model, SN, media capabilities, Skyworth protocol fields) |
| **Parameters** | `method`: `"ws_discovery"` for ONVIF WS-Discovery (multicast Probe to `239.255.255.250:3702` on every local interface — **the only method that finds standard/non-Skyworth ONVIF cameras**; ONVIF port parsed from XAddrs, device_class classified via anonymous RTSP probe), `"sky_discovery"` for Skyworth private protocol (multicast `239.230.236.230:9008`; returns `onvif_port=0` — the private protocol only reports the web port, the real ONVIF port is probed & verified by `connect_device`), `"usb"` for USB enumeration. `timeout`: discovery timeout in seconds (WS-Discovery caps its probe window at 5s). |
| **Implementation** | WS-Discovery multicast Probe/ProbeMatch / Skyworth UDP multicast via `discovery.py` / OpenCV USB enumeration |

### `get_registered_cameras() -> List[CameraConfig]`

Read all camera entries from `config.yaml` and return their configurations.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | List of `CameraConfig` objects (all fields from config.yaml cameras section) |
| **Parameters** | None |
| **When to call** | At session start (Phase 0) — always call before any discovery |

### `register_camera(name, ip="", port=0, username="admin", password="", rtsp_port=554, rtsp_path="/stream1", device_class="direct_connect", **kwargs) -> RegisterResult`

Write a camera entry to `config.yaml`, persisting credentials for future auto-connect. Writes dual-format fields (`port`/`onvif_port`, `rtsp_path`/`rtsp_path_main`, `sn_code`/`sn`, etc.) for cross-scheme compatibility.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (internal config write; does not expose credentials to user) |
| **Returns** | `RegisterResult` (success, camera name) |
| **Parameters** | `name`: unique camera name. `ip`: camera IP. `port`: ONVIF port — **only pass a verified port; omit when unknown (0 = unknown)**, `connect_device` probes the real port and writes it back automatically. `username`/`password`: credentials (saved to config.yaml, never displayed). `rtsp_port`/`rtsp_path`: stream parameters. `device_class`: `"password_required"` or `"direct_connect"`. Additional kwargs: `sn_code`, `pkdk`, `rtsp_sub_path`. |
| **When to call** | After first successful `connect_device()` |

### `connect_device(camera_name, password=None, ip=None, port=None, rtsp_port=None, rtsp_path="/stream1", username="admin") -> ConnectResult`

Establish connection to a camera. Uses cached credentials → ONVIF WS-UsernameToken auth → authorization server → RTSP probe, in that order.

**ONVIF port verification:** before ONVIF auth, the tool probes candidate ports (hint → 2000/80/8000/8899) with an unauthenticated `GetSystemDateAndTime` and only treats a port as ONVIF if it returns a SOAP Envelope (Skyworth cameras: 2000; port 80 is the web UI). The `port` argument is just a hint — wrong or missing values are corrected automatically, and only **verified** ports are persisted to config.yaml (unverified stays 0).

**Connection flow:**

1. Check `config.yaml` for cached credentials → if found, verify via ONVIF WS-UsernameToken → connect
2. If password provided → probe & verify ONVIF port → attempt ONVIF auth → TCP channel → auto-cache credentials + verified port on success
3. If no password and `device_class == "password_required"`:
   - Authorization server reachable → `request_cloud_auth()` → return `status="pending_auth"`
   - Authorization server unreachable → return `status="needs_password"` (fallback)
4. If non `password_required` → probe RTSP stream:
   - `200 OK` → direct-connect (`auth_method="direct"`, ONVIF port also probed & persisted if verified)
   - `401 Unauthorized` → return `needs_password=True`
   - Unreachable → fail

| Aspect | Detail |
|--------|--------|
| **Safety** | None (credentials are local-only; authorization server backend is pluggable) |
| **Returns** | `ConnectResult` (success, auth_method, status, needs_password, onvif_port — the verified ONVIF port, 0 = not verified). Status: `"connected"`, `"pending_auth"`, `"needs_password"`, `"failed"` |
| **When to call** | Phase 0 (cached cameras), Phase 2 (new cameras) |

### `request_cloud_auth(camera_name, sn="", device_ip="", device_model="") -> CloudAuthRequestResult`

Submit an authorization request to the authorization server (currently local, pluggable for cloud). Used internally by `connect_device()` for password-required cameras, or can be called directly.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (only sends device info, no credentials) |
| **Returns** | `CloudAuthRequestResult` (success, claw_id, error_message) |
| **Parameters** | `camera_name`: camera identifier. `sn`: device serial number (auto-lookup from config if omitted). `device_ip`: device IP (optional). `device_model`: device model (optional). |
| **Implementation** | POST `{sn, claw_id, device_ip, device_model}` to `http://127.0.0.1:18899/api/auth/request`. Claw ID is auto-generated and persisted to config.yaml. |
| **When to call** | After `connect_device()` returns `status="pending_auth"` (normally handled internally) |

### `poll_auth_status(camera_name) -> AuthStatusResult`

Poll the authorization server to check if the user has confirmed authorization in the browser.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `AuthStatusResult` (status, camera_name, message). Status: `AuthStatus.PENDING`, `AuthStatus.AUTHORIZED`, `AuthStatus.REJECTED`, `AuthStatus.ERROR` |
| **Parameters** | `camera_name`: camera identifier |
| **Implementation** | GET `http://127.0.0.1:18899/api/auth/status?sn=xxx&claw_id=yyy` |
| **When to call** | After `connect_device()` returns `status="pending_auth"`. Poll every ~5s, max 120s. |

### `disconnect_device(camera_name) -> DisconnectResult`

Disconnect a camera and release all resources (ONVIF connection, session state).

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `DisconnectResult` (success, session_released, error_message) |
| **When to call** | When the user is done with a camera or before re-connecting with new credentials |
