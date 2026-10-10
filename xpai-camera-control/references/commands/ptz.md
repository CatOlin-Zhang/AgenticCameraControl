# PTZ Control

Pan/tilt control with a **per-protocol backend** — exposed as MCP tools by `scripts/mcp_server.py`

The backend is selected by the camera's `protocol_type`: **SK-class** (`S`) uses the XPAI private protocol (vendor command via TCP channel); **JCP-class** (`J`) uses **ONVIF only** (`ContinuousMove` / `Stop` / `GetStatus` on the ONVIF PTZ service, moving by normalized velocity vectors). Selection is handled internally — the Agent only sees the `protocol` field in the result (`"sky_private"` or `"onvif"`).

**J/O-class limits:** `degrees` mode and `calibrate_ptz` are **not supported** on J-class or O-class cameras (ONVIF exposes normalized velocity vectors, not absolute angles); both return an explicit unsupported message. Use `duration_seconds` for J/O-class movement.

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

**Prerequisite:** Camera must be connected via `connect_device()` and present in the server's connection state.

---

### `control_ptz(camera_name, direction: PTZDirection, speed: float = 0.5, duration_seconds: Optional[float] = None, degrees: Optional[float] = None) -> PTZMoveResult`

Directional movement of the PTZ head. Auto-stops after `duration_seconds` (defaults to 1.0 s when neither `duration_seconds` nor `degrees` is given). `duration_seconds` and `degrees` are mutually exclusive.

**Physical Limit Guard (built-in):** the tool intercepts commands that exceed the PTZ's physical travel range — the agent does NOT need to pre-validate durations itself:

- **Pre-check:** if the head is already at the physical limit in the requested direction, the command is intercepted (no move command is sent to the device) and the result returns `degraded=True` with `actual_duration_seconds=0`.
- **In-flight guard:** during movement the tool polls the head position (every ~0.4s); when the range boundary is reached or displacement stalls, it stops early. E.g. a "turn right 5s" request with only ~3s of travel left stops at ~3s with `degraded=True`.
- **Graceful fallback:** on devices where position polling is unavailable (no XPAI private channel), the guard silently degrades to plain timed movement — behavior is unchanged from before.

**Agent behavior (MANDATORY):** whenever the result has `degraded=True`, the agent MUST explicitly relay `degrade_reason` to the user (e.g. "You requested a 5-second right turn, but the PTZ head reached its physical limit after 3.2 seconds and stopped early"). Never silently swallow a degraded result.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Physical Limit Guard |
| **Returns** | `PTZMoveResult` (see field table below) |
| **Parameters** | `direction`: `up`/`down`/`left`/`right`/`upleft`/`upright`/`downleft`/`downright`/`zoom_in`/`zoom_out`. Chinese aliases supported (上/下/左/右/左上/右上/左下/右下). `speed`: 0.1–1.0. `duration_seconds`: 0.1–10.0. `degrees`: rotation angle (SK-class only, converted at 1 s ≈ 34°; J/O-class returns an explicit unsupported notice) |

**PTZMoveResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the move succeeded |
| `protocol` | string | Protocol actually used: `"onvif"` or `"sky_private"` |
| `current_pan` | float | Current horizontal position after the move |
| `current_tilt` | float | Current vertical position after the move |
| `current_zoom` | float | Current zoom level after the move |
| `error_message` | string | Failure reason (empty on success) |
| `requested_duration_seconds` | float | Duration the Agent requested |
| `actual_duration_seconds` | float | Duration actually moved (less than requested when limit guard intervened) |
| `limit_reached` | bool | Whether a physical travel limit was detected |
| `degraded` | bool | Whether the command was intercepted or truncated |
| `degrade_reason` | string | Human-readable explanation of the degradation (for Agent to relay to user) |
| `degrees` | float | Requested angle in degrees mode (0 when unused) |
| `method` | string | Execution method: `"sk_time"` / `"sk_degrees"` / `"sk_zoom"` / `"onvif_time"` / `"onvif_zoom"` |

---

### `get_ptz_parameters(camera_name) -> PTZParameters`

Get current PTZ position, range, and movement state.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZParameters` (see field table below) |

**PTZParameters return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pan` | float | Current horizontal position / angle |
| `tilt` | float | Current vertical position / angle |
| `zoom` | float | Current zoom position |
| `pan_range` | float | Maximum horizontal range |
| `tilt_range` | float | Maximum vertical range |
| `zoom_range` | float | Maximum zoom range |
| `is_moving` | bool | Whether the PTZ is currently in motion |
| `protocol` | string | Protocol used: `"onvif"` or `"sky_private"` |
| `error_message` | string | Query failure reason (empty on success) |

---

### `calibrate_ptz(camera_name, action: str = "set_home") -> CalibrateResult`

Execute PTZ physical calibration or return to stored home position.

> **J/O-class not supported:** on JCP or O-class cameras (`protocol_type="J"`/`"O"`) this returns `success=false`, `protocol="onvif"`, with a message stating calibration is unsupported — use `control_ptz` with `duration_seconds` to adjust the view manually.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `CalibrateResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `action`: `"set_home"` (execute firmware-level calibration and store home position, ~10-30s) or `"go_home"` (move precisely to stored home position). Default: `"set_home"`. |

**CalibrateResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether calibration completed |
| `protocol` | string | Protocol used: `"sky_private"` (SK-class) or `"onvif"` (J/O-class; calibration always unsupported there) |
| `action` | string | Action executed: `"set_home"` / `"go_home"` |
| `home_position` | string | Home position coordinates (e.g. `"x=0,y=0"`) |
| `error_message` | string | Failure reason (empty on success) |

---

### `stop_ptz(camera_name) -> PTZMoveResult`

Stop all PTZ movement immediately.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZMoveResult` (same structure as `control_ptz`; `degraded` and limit guard fields are always `false`/default for stop) |
