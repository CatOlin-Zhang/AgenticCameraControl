# PTZ Control

Pan/tilt/zoom control with **dual-protocol strategy** — `scripts/toolkit/ptz.py`

ONVIF PTZ Service is tried first, automatically falling back to the Skyworth private protocol (`SK_SETTING_SET_PTZ` via TCP port 9010) when ONVIF is unavailable.

**Prerequisite:** Camera must be connected via `connect_device()` and present in `_connected_devices`.

---

### `control_ptz(camera_name, direction: PTZDirection, speed: float = 0.5, duration_seconds: float = 1.0) -> PTZMoveResult`

Directional movement of the PTZ head. Auto-stops after `duration_seconds`.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `PTZMoveResult` (success, protocol, current pan/tilt/zoom) |
| **Parameters** | `direction`: `PTZDirection` enum — `UP`/`DOWN`/`LEFT`/`RIGHT`/`UPLEFT`/`UPRIGHT`/`DOWNLEFT`/`DOWNRIGHT`. Chinese aliases supported (上/下/左/右/左上/右上/左下/右下). `speed`: 0.1–1.0. `duration_seconds`: 0.1–10.0. |
| **Implementation** | ONVIF: `ContinuousMove` + auto `Stop`. Private: `SK_SETTING_SET_PTZ` + auto stop. |

### `control_lens_zoom(camera_name, zoom_action: ZoomAction, speed: float = 0.5) -> PTZMoveResult`

Control optical zoom. Auto-stops after 1.5 seconds.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZMoveResult` (success, protocol, current zoom value) |
| **Parameters** | `zoom_action`: `ZoomAction.IN` or `ZoomAction.OUT`. `speed`: 0.1–1.0. |
| **Implementation** | ONVIF: `ContinuousMove` (zoom axis) + auto `Stop`. Private: `SK_SETTING_SET_PTZ` zoom+/zoom-. |

### `get_ptz_parameters(camera_name) -> PTZParameters`

Get current PTZ position, range, and movement state.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZParameters` (pan, tilt, zoom positions; pan_range, tilt_range, zoom_range; is_moving; protocol) |
| **Implementation** | ONVIF: `GetStatus`. Private: `SK_SETTING_GET_PTZ`. |

### `save_ptz_preset(camera_name, preset_name) -> PTZPresetResult`

Save the current PTZ position as a named preset.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZPresetResult` (success, preset_name, preset_token, protocol) |
| **Implementation** | ONVIF `SetPreset` only. |

### `go_to_preset(camera_name, preset_name, speed: float = 1.0) -> PTZMoveResult`

Move the PTZ head to a previously saved preset position.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `PTZMoveResult` (success, protocol) |
| **Implementation** | ONVIF `GotoPreset` only. |

### `calibrate_ptz(camera_name) -> CalibrateResult`

Execute PTZ physical calibration (return to home position and re-calibrate zero point). Takes 10–30 seconds.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `CalibrateResult` (success, protocol) |
| **Implementation** | Private protocol only: `SK_SETTING_SET_PTZ` calibrate. |

### `move_to_position(camera_name, x: int, y: int, z: float = 1.0) -> PTZMoveResult`

Move the PTZ head to an absolute (x, y, z) coordinate. Use `get_ptz_parameters()` to query valid ranges.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZMoveResult` (success, protocol, current pan/tilt/zoom) |
| **Implementation** | Private protocol only: `SK_SETTING_SET_PTZ` move. |

### `stop_ptz(camera_name) -> PTZMoveResult`

Stop all PTZ movement immediately.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZMoveResult` (success, protocol) |
| **Implementation** | ONVIF: `Stop`. Private: `SK_SETTING_SET_PTZ` stop. ONVIF tried first. |

### `start_patrol_cruise(camera_name, cruise_name=None) -> CruiseResult`

Start PTZ patrol cruise along a preset path (background thread).

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `CruiseResult` (success, cruise_name, preset_count, protocol) |
| **Implementation** | ONVIF only: loops `GotoPreset` + 5s delay per preset in a daemon thread. |
