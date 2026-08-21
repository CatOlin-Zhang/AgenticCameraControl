# PTZ Control

Pan/tilt control with **dual-protocol strategy** — exposed as MCP tools by `scripts/mcp_server.py`

ONVIF PTZ Service is tried first, automatically falling back to the Skyworth private protocol (vendor command via TCP channel) when ONVIF is unavailable. Protocol selection and fallback are handled internally — the Agent only sees the `protocol` field in the result.

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

**Prerequisite:** Camera must be connected via `connect_device()` and present in the server's connection state.

---

### `control_ptz(camera_name, direction: PTZDirection, speed: float = 0.5, duration_seconds: float = 1.0) -> PTZMoveResult`

Directional movement of the PTZ head. Auto-stops after `duration_seconds`.

**Physical Limit Guard (built-in):** the tool intercepts commands that exceed the PTZ's physical travel range — the agent does NOT need to pre-validate durations itself:

- **Pre-check:** if the head is already at the physical limit in the requested direction, the command is intercepted (no move command is sent to the device) and the result returns `degraded=True` with `actual_duration_seconds=0`.
- **In-flight guard:** during movement the tool polls the head position (every ~0.4s); when the range boundary is reached or displacement stalls, it stops early. E.g. a "turn right 5s" request with only ~3s of travel left stops at ~3s with `degraded=True`.
- **Graceful fallback:** on devices where position polling is unavailable (no Skyworth private channel), the guard silently degrades to plain timed movement — behavior is unchanged from before.

**Agent behavior (MANDATORY):** whenever the result has `degraded=True`, the agent MUST explicitly relay `degrade_reason` to the user (e.g. "You requested a 5-second right turn, but the PTZ head reached its physical limit after 3.2 seconds and stopped early"). Never silently swallow a degraded result.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Physical Limit Guard |
| **Returns** | `PTZMoveResult` (see field table below) |
| **Parameters** | `direction`: `UP`/`DOWN`/`LEFT`/`RIGHT`/`UPLEFT`/`UPRIGHT`/`DOWNLEFT`/`DOWNRIGHT`. Chinese aliases supported (上/下/左/右/左上/右上/左下/右下). `speed`: 0.1–1.0. `duration_seconds`: 0.1–10.0. |

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

---

### `calibrate_ptz(camera_name, action: str = "set_home") -> CalibrateResult`

Execute PTZ physical calibration or return to stored home position.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `CalibrateResult` (see field table below) |
| **Parameters** | `camera_name`: camera identifier. `action`: `"set_home"` (execute firmware-level calibration and store home position, ~10-30s) or `"go_home"` (move precisely to stored home position). Default: `"set_home"`. |

**CalibrateResult return fields:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether calibration completed |
| `protocol` | string | Protocol used (currently always `"sky_private"`) |
| `error_message` | string | Failure reason (empty on success) |

---

### `stop_ptz(camera_name) -> PTZMoveResult`

Stop all PTZ movement immediately.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZMoveResult` (same structure as `control_ptz`; `degraded` and limit guard fields are always `false`/default for stop) |
