# PTZ Control

Pan/tilt control with **dual-protocol strategy** — `scripts/toolkit/ptz.py`

ONVIF PTZ Service is tried first, automatically falling back to the Skyworth private protocol (`SK_SETTING_SET_PTZ` via TCP port 9010) when ONVIF is unavailable.

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

**Prerequisite:** Camera must be connected via `connect_device()` and present in `_connected_devices`.

---

### `control_ptz(camera_name, direction: PTZDirection, speed: float = 0.5, duration_seconds: float = 1.0) -> PTZMoveResult`

Directional movement of the PTZ head. Auto-stops after `duration_seconds`.

**Physical Limit Guard (built-in):** the tool intercepts commands that exceed the PTZ's physical travel range — the agent does NOT need to pre-validate durations itself:

- **Pre-check:** if the head is already at the physical limit in the requested direction, the command is intercepted (no move command is sent to the device) and the result returns `degraded=True` with `actual_duration_seconds=0`.
- **In-flight guard:** during movement the tool polls the head position (`SK_SETTING_GET_PTZ`, every ~0.4s); when the range boundary is reached or displacement stalls, it stops early. E.g. a "turn right 5s" request with only ~3s of travel left stops at ~3s with `degraded=True`.
- **Graceful fallback:** on devices where position polling is unavailable (no Skyworth private channel), the guard silently degrades to plain timed movement — behavior is unchanged from before.

**Agent behavior (MANDATORY):** whenever the result has `degraded=True`, the agent MUST explicitly relay `degrade_reason` to the user (e.g. "You requested a 5-second right turn, but the PTZ head reached its physical limit after 3.2 seconds and stopped early"). Never silently swallow a degraded result.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Physical Limit Guard |
| **Returns** | `PTZMoveResult` (success, protocol, current pan/tilt/zoom, requested_duration_seconds, actual_duration_seconds, limit_reached, degraded, degrade_reason) |
| **Parameters** | `direction`: `PTZDirection` enum — `UP`/`DOWN`/`LEFT`/`RIGHT`/`UPLEFT`/`UPRIGHT`/`DOWNLEFT`/`DOWNRIGHT`. Chinese aliases supported (上/下/左/右/左上/右上/左下/右下). `speed`: 0.1–1.0. `duration_seconds`: 0.1–10.0. |
| **Implementation** | ONVIF: `ContinuousMove` + auto `Stop`. Private: `SK_SETTING_SET_PTZ` + auto stop. Limit guard polls position via `SK_SETTING_GET_PTZ` regardless of the movement protocol. |

### `get_ptz_parameters(camera_name) -> PTZParameters`

Get current PTZ position, range, and movement state.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZParameters` (pan, tilt, zoom positions; pan_range, tilt_range, zoom_range; is_moving; protocol) |
| **Implementation** | ONVIF: `GetStatus`. Private: `SK_SETTING_GET_PTZ`. |

### `calibrate_ptz(camera_name) -> CalibrateResult`

Execute PTZ physical calibration (return to home position and re-calibrate zero point). Takes 10–30 seconds.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `CalibrateResult` (success, protocol) |
| **Implementation** | Private protocol only: `SK_SETTING_SET_PTZ` calibrate. |

### `stop_ptz(camera_name) -> PTZMoveResult`

Stop all PTZ movement immediately.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZMoveResult` (success, protocol) |
| **Implementation** | ONVIF: `Stop`. Private: `SK_SETTING_SET_PTZ` stop. ONVIF tried first. |

---

## Internal Functions (NOT registered as MCP tools)

### `_move_to_position(camera_name, x: int, y: int, z: float = 1.0) -> PTZMoveResult`

Move the PTZ head to an absolute (x, y, z) coordinate. Internal function for in-module use or secondary development only — **not exposed via MCP**.

| Aspect | Detail |
|--------|--------|
| **Returns** | `PTZMoveResult` (success, protocol, current pan/tilt/zoom) |
| **Implementation** | Private protocol only: `SK_SETTING_SET_PTZ` move. |

