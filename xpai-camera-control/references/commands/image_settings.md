# Image Settings

Camera image parameter query and adjustment — exposed as the single MCP tool `manage_image_settings` by `scripts/mcp_server.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

**Prerequisite:** Camera must be connected via `connect_device()` and present in the server's connection state (or have cached credentials in `config.yaml`).

---

## Architecture

Image settings follow a **dual-protocol strategy** (same pattern as Illumination / PTZ):

### Primary — Skyworth Private Protocol (TCP 9010)

For Skyworth cameras, three TCP commands provide full image control:

| Command | Purpose |
|---------|---------|
| `SK_SETTING_GET_IMAGE_OPTION` | Query device capability (parameter ranges and descriptions) |
| `SK_SETTING_GET_IMAGE` | Read all current image parameters |
| `SK_SETTING_SET_IMAGE` | Write image parameters (full-payload delivery) |

> **Response naming convention:** Same as illumination — device appends `_R` to `cmd_name`, success is `code: "C0000"`.

This protocol exposes **9 controllable parameters**:

**Continuous parameters:**

| Parameter | Type | Typical Range | Description |
|-----------|------|---------------|-------------|
| `brightness` | int | device-reported | Brightness |
| `contrast` | int | device-reported | Contrast |
| `saturation` | int | device-reported | Color saturation |
| `sharpness` | int | device-reported | Sharpness |

**Multi-level enum parameters:**

| Parameter | Type | Values | Description |
|-----------|------|--------|-------------|
| `flip` | int | 0–3 | Image flip: 0=normal, 1=diagonal, 2=horizontal, 3=vertical |
| `whitebalance` | int | 0–4 | White balance: 0=auto, 1=white-light, 2=incandescent, 3=natural, 4=warm |

**Boolean toggle parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `wdr` | bool (0/1) | Wide Dynamic Range toggle |
| `face_mode` | bool (0/1) | Face clarity optimization toggle |
| `plate_mode` | bool (0/1) | License plate clarity optimization toggle |

**Special action:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `restore_default` | bool | When `true`, sets the protocol `default` field to 1, resetting all image parameters to factory defaults |

**Set behavior:** the device requires the **full parameter set** when writing (`SK_SETTING_SET_IMAGE`). The tool handles this internally — it first reads current settings via `SK_SETTING_GET_IMAGE`, merges only the user-specified parameters, then sends the complete set. The Agent only needs to pass the parameters it wants to change.

### Fallback — ONVIF Imaging Service (ver20)

For non-Skyworth devices (or firmware like ZCR461 that does not implement SK image commands), the tool falls back to ONVIF:

1. `GetImagingSettings` → read current `Brightness`/`Contrast`/`ColorSaturation`/`Sharpness`
2. `GetOptions` → read parameter min/max ranges
3. `SetImagingSettings` → write changed parameters

ONVIF fallback provides coarser control — **only 4 parameters**: `brightness`, `contrast`, `saturation`, `sharpness`. The remaining parameters (`flip`, `whitebalance`, `wdr`, `face_mode`, `plate_mode`) are SK-private-protocol only.

---

## `manage_image_settings(camera_name, action, **params) -> ImageQueryResult | ImageSetResult`

**The single MCP entry point for all image settings operations.**

| `action` | Mode | Returns |
|----------|------|---------|
| `get` | Query capability & current settings | `ImageQueryResult` |
| `set` | Set image parameters | `ImageSetResult` |

---

### `action="get"`

Query the device's image parameter capabilities and all current values.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (read-only query) |
| **Parameters** | `camera_name` only |
| **Agent behavior** | Report capabilities (with ranges and current values) to the user. If capabilities is empty, the device does not support image settings. |

**Returns** `ImageQueryResult` with:
- `channel`: `"sk"` or `"onvif"` (which protocol was used)
- `capabilities`: list of parameter descriptions with ranges and current values (e.g. `[{"name": "brightness", "type": "int", "specs": {"min": "1", "max": "255"}, "current": 128, "current_text": "128"}, ...]`)
- `current`: raw dict of all current parameter values from the device

---

### `action="set"`

Change one or more image parameters. **Requires explicit user confirmation.**

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt — hardware setting change; confirm with the user |
| **Parameters** | `camera_name` + any subset of the image parameters |
| **Agent behavior** | Call `get` first to retrieve capabilities and validate parameter ranges, then call `set` with only the parameters the user wants to change. Report `updated` fields and `current` full state after change. |

**All settable parameters** (all optional — specify only what you want to change):

| Parameter | Type | Range |
|-----------|------|-------|
| `brightness` | int | device-reported |
| `contrast` | int | device-reported |
| `saturation` | int | device-reported |
| `sharpness` | int | device-reported |
| `flip` | int | 0–3 |
| `whitebalance` | int | 0–4 |
| `wdr` | bool | true/false |
| `face_mode` | bool | true/false |
| `plate_mode` | bool | true/false |
| `restore_default` | bool | true to reset all to factory defaults |

---

## ImageQueryResult return fields

| Field | Type | Description |
|-------|------|-------------|
| `ok` | bool | Whether the operation succeeded |
| `camera` | string | Camera name |
| `channel` | string | `"sk"` or `"onvif"` |
| `capabilities` | list | Parameter capability descriptions (name, type, specs with min/max, current value, current_text) |
| `current` | dict | Raw device current parameter values |
| `error_code` | string | Error code on failure |
| `message` | string | Human-readable status message |
| `hint` | string | Suggested next step on failure |

## ImageSetResult return fields

| Field | Type | Description |
|-------|------|-------------|
| `ok` | bool | Whether the operation succeeded |
| `camera` | string | Camera name |
| `channel` | string | `"sk"` or `"onvif"` |
| `updated` | dict | Fields that were changed, with post-write readback values |
| `current` | dict | Full current parameter state after the change |
| `error_code` | string | Error code on failure |
| `message` | string | Human-readable status message |
| `hint` | string | Suggested next step on failure |

---

## Error codes

| `error_code` | Cause |
|--------------|-------|
| `DEVICE_UNREACHABLE` | Both SK TCP 9010 and ONVIF are unreachable — verify camera is online |
| `OPTION_QUERY_FAILED` | Capability query rejected by device |
| `CURRENT_QUERY_FAILED` | Current-value query rejected by device |
| `SET_FAILED` | Device rejected the write command |
| `PARAM_NOT_SUPPORTED` | Requested parameter not supported by this camera model |
| `PARAM_OUT_OF_RANGE` | Parameter value outside allowed range |
| `INVALID_PARAM_TYPE` | Wrong type for parameter (e.g. string instead of int) |
| `NO_PARAMS` | No parameters were passed to set |
