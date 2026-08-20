# Detection & Tracking

Camera intelligent detection and tracking control — exposed as two MCP tools by `scripts/mcp_server.py`:

- `query_tracking_capabilities` — read-only query of detection capabilities and current settings
- `set_tracking` — enable/disable detection and tracking features

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

**Prerequisite:** Camera must be connected via `connect_device()` and present in the server's connection state (or have cached credentials in `config.yaml`).

---

## Architecture

Detection & tracking uses **Skyworth Private Protocol only** (TCP channel, dynamic-token HTTP). There is **no ONVIF fallback** — tracking is a Skyworth-specific feature set.

Five detection types are supported, each with its own protocol section:

| Type | Protocol Section | Response Key | Description |
|------|-----------------|--------------|-------------|
| `human` | Human Detect | `humandetect` | Human-shape detection & auto-tracking |
| `vehicle` | Object Detect | `objectdetect` | Vehicle detection (requires `object=vehicle` in payload) |
| `area` | VG Rect Detect | `vgrectdetect` | Area/region-based detection (line-crossing, enter/leave) |
| `motion` | Motion Detect | `motiondetect` | Motion detection with region grid (18x32) |
| `line` | VG Line Detect | `vglinedetect` | Line-crossing detection with directional alarm |

### Private Protocol Commands (15 total)

Each detection type has three vendor-specific commands (query capability, read current, write) handled internally by the tool. The Agent interacts only through the `query_tracking_capabilities` and `set_tracking` MCP tools.

### Common parameters across detection types

| Parameter | Type | Values | Applicable To | Description |
|-----------|------|--------|---------------|-------------|
| `enable` | int | 0/1 | all | Enable/disable this detection feature |
| `tracking` | int | 0/1 | human, vehicle, motion | Enable/disable auto-tracking (area/line does not support tracking) |
| `level` | int | 0–3 | all | Sensitivity level: 0=off, 1=low, 2=medium, 3=high |
| `indoor` | int | 0–2 | human, motion, line | Scene mode: 0=outdoor, 1=indoor, 2=outdoor-person-vehicle |
| `screenenable` | int | 0/1 | human | Target marker overlay on video |
| `blink` | int | 0/1 | human, motion, line | Bounding-box/line blink effect |
| `drag` | int | 0/1 | vehicle | Target marker display |
| `alarm_enable` | int | 0/1 | human, vehicle, motion | Audio alarm on detection |
| `alarm_type` | int | — | human, vehicle, motion | Alarm type selector |
| `white_light` | int | 0/1 | human, vehicle, motion, line | White-light alarm on detection |
| `duration` | int | — | human, vehicle, motion, line | White-light duration (seconds) |
| `timestrategy` | int/string | — | human, vehicle, motion, line | Detection schedule |
| `humandistance` | int | — | human | Min human size threshold |
| `thresh` | int | — | area, motion, line | Sensitivity threshold |
| `distance` | int | — | vehicle | Min target size threshold |
| `object` | string | `vehicle` | vehicle | Target type selector (auto-injected by tool) |
| `trigger` | string/int | — | vehicle | Trigger target type |
| `idenable` | int | 0/1 | vehicle | License plate detection toggle |
| `mbdesc` | string | — | motion, area | Detection region grid description |

**Area-detection-specific parameters** (region/line configuration):

| Parameter | Type | Description |
|-----------|------|-------------|
| `x0`/`y0` | int | Line start coordinates |
| `x1`/`y1` | int | Line end coordinates |
| `x2`/`y2` | int | Direction start coordinates |
| `x3`/`y3` | int | Direction end coordinates |
| `dir` | int | Detection direction: 0=enter, 1=leave, 2=both |
| `enter_alarm_enable` | int | Enter-region alarm toggle |
| `enter_alarm_type` | int | Enter-region alarm type |
| `leave_alarm_enable` | int | Leave-region alarm toggle |
| `leave_alarm_type` | int | Leave-region alarm type |
| `mbdesc` | string | Region description |

**Motion-detection-specific parameters** (移动侦测，协议 5.8):

| Parameter | Type | Description |
|-----------|------|-------------|
| `mbdesc` | string | Detection region grid: 18 rows x 32 cols, each char 1=selected/0=not, rows comma-separated |
| `tracking` | int | Motion tracking: 0=off, 1=on |

**Line-crossing-detection-specific parameters** (越界侦测，协议 5.9):

| Parameter | Type | Description |
|-----------|------|-------------|
| `x0`/`y0` | int | Line start coordinates (1–1920 / 1–1080) |
| `x1`/`y1` | int | Line end coordinates |
| `dx0`/`dy0` | int | Direction point A coordinates |
| `dx1`/`dy1` | int | Direction point B coordinates |
| `AtoB_alarm_enable` | int | A-to-B direction alarm toggle: 0=off, 1=on |
| `AtoB_alarm_type` | int | A-to-B alarm type |
| `BtoA_alarm_enable` | int | B-to-A direction alarm toggle: 0=off, 1=on |
| `BtoA_alarm_type` | int | B-to-A alarm type |

**Set behavior:** same as illumination — the device requires the **full parameter set** when writing. The tool reads current settings first, merges only the user-specified parameters, then sends the complete set. The Agent only needs to pass the parameters it wants to change.

---

## `query_tracking_capabilities(camera_name, detect_type?) -> TrackingQueryResult`

Read-only query of the camera's detection and tracking capabilities.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (read-only query) |
| **Parameters** | `camera_name` (required), `detect_type` (optional, default `"all"`) |
| **Agent behavior** | Report capabilities and current settings to the user. Use before `set_tracking` to determine supported parameters. |

**`detect_type` values:**

| Value | Scope |
|-------|-------|
| `all` | Query all five types (default) |
| `human` | Human detection only |
| `vehicle` | Vehicle detection only |
| `area` | Area/region detection only |
| `motion` | Motion detection only |
| `line` | Line-crossing detection only |

**Returns** `TrackingQueryResult` with:
- `channel`: always `"sk"` (no ONVIF fallback)
- `*_capabilities` / `*_current`: filtered to **only the 3 settable parameters** (`enable`, `tracking`, `level`) — device-only parameters (alarm_enable, white_light, timestrategy, etc.) are excluded
- `human_capabilities` / `human_current`: human detection
- `vehicle_capabilities` / `vehicle_current`: vehicle detection
- `area_capabilities` / `area_current`: area detection
- `motion_capabilities` / `motion_current`: motion detection
- `line_capabilities` / `line_current`: line-crossing detection

---

## `set_tracking(camera_name, detect_type, **params) -> TrackingSetResult`

Enable, disable, or configure detection and tracking features. **Requires explicit user confirmation.**

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt — hardware setting change; confirm with the user |
| **Parameters** | `camera_name` (required), `detect_type` (required) + any subset of tracking parameters |
| **Agent behavior** | Call `query_tracking_capabilities` first to confirm the camera supports the desired detection type, then call `set_tracking` with only the parameters to change. Report `updated` fields after change. |

**Settable parameters** (all optional — specify only what you want to change):

| Parameter | Type | Description |
|-----------|------|-------------|
| `enable` | bool | Enable/disable this detection feature |
| `tracking` | bool | Enable/disable auto-tracking (human/vehicle/motion only; ignored for area/line) |
| `sensitivity_level` | int | Sensitivity level 0–3 (0=off, 1=low, 2=medium, 3=high) |

---

## TrackingQueryResult return fields

| Field | Type | Description |
|-------|------|-------------|
| `ok` | bool | Whether the operation succeeded |
| `camera` | string | Camera name |
| `channel` | string | Always `"sk"` |
| `human_capabilities` | list[dict] | Human detection: only `enable`/`tracking`/`level` with ranges and current values |
| `human_current` | dict | Human detection: only `enable`/`tracking`/`level` current values |
| `vehicle_capabilities` | list[dict] | Vehicle detection: only `enable`/`tracking`/`level` with ranges and current values |
| `vehicle_current` | dict | Vehicle detection: only `enable`/`tracking`/`level` current values |
| `area_capabilities` | list[dict] | Area detection: only `enable`/`level` with ranges and current values (no tracking) |
| `area_current` | dict | Area detection: only `enable`/`level` current values |
| `motion_capabilities` | list[dict] | Motion detection: only `enable`/`tracking`/`level` with ranges and current values |
| `motion_current` | dict | Motion detection: only `enable`/`tracking`/`level` current values |
| `line_capabilities` | list[dict] | Line-crossing detection: only `enable`/`level` with ranges and current values (no tracking) |
| `line_current` | dict | Line-crossing detection: only `enable`/`level` current values |
| `error_code` | string | Error code on failure |
| `message` | string | Human-readable status message |
| `hint` | string | Suggested next step on failure |

## TrackingSetResult return fields

| Field | Type | Description |
|-------|------|-------------|
| `ok` | bool | Whether the operation succeeded |
| `camera` | string | Camera name |
| `channel` | string | Always `"sk"` |
| `detect_type` | string | Which detection type was modified (`human`/`vehicle`/`area`/`motion`/`line`) |
| `updated` | dict | Fields that were changed, with post-write readback values |
| `current` | dict | Current state of settable parameters only (`enable`/`tracking`/`level`) after the change |
| `error_code` | string | Error code on failure |
| `message` | string | Human-readable status message |
| `hint` | string | Suggested next step on failure |

---

## Error codes

| `error_code` | Cause |
|--------------|-------|
| `DEVICE_UNREACHABLE` | SK TCP 9010 unreachable — verify camera is online; retry after 2-3 s (transient port flapping) |
| `OPTION_QUERY_FAILED` | Capability query rejected by device |
| `CURRENT_QUERY_FAILED` | Current-value query rejected by device |
| `SET_FAILED` | Device rejected the write command |
| `PARAM_NOT_SUPPORTED` | Requested parameter not supported by this camera's detection type |
| `PARAM_OUT_OF_RANGE` | Parameter value outside allowed range |
| `INVALID_DETECT_TYPE` | `detect_type` is not `human`, `vehicle`, `area`, `motion`, or `line` |
| `NO_PARAMS` | No parameters were passed to set |
