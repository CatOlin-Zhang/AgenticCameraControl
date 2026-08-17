# Illumination Mode Control

Camera illumination mode query and adjustment — exposed as the single MCP tool `manage_illumination` by `scripts/mcp_server.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

**Prerequisite:** Camera must be connected via `connect_device()` and present in the server's connection state (or have cached credentials in `config.yaml`).

---

## Architecture

Illumination control follows a **dual-protocol strategy** (same pattern as PTZ):

### Primary — Skyworth Private Protocol (TCP 9010)

For Skyworth cameras, three TCP commands provide full illumination control:

| Command | Purpose |
|---------|---------|
| `SK_SETTING_GET_FILLLIGHT_OPTION` | Query device capability (parameter ranges and descriptions) |
| `SK_SETTING_GET_FILLLIGHT` | Read all current illumination settings |
| `SK_SETTING_SET_FILLLIGHT` | Write illumination parameters |

> **Response naming convention:** The device appends `_R` to the `cmd_name` in responses. For example, request `SK_SETTING_GET_FILLLIGHT_OPTION` receives response `SK_SETTING_GET_FILLLIGHT_OPTION_R`. The `msg_id` is echoed back unchanged for request-response correlation. Response success is indicated by `code: "C0000"` and `msg: "SUCESS"`.

This protocol exposes **15 controllable parameters** across two dimensions:

**Day/Night mode** (`daynightmode`):

| Value | Mode | Description |
|-------|------|-------------|
| 0 | 白天模式 | Day mode (lights off) |
| 1 | 夜晚模式 | Night mode (lights on) |
| 2 | 自动模式 | Auto (sensor-driven) |
| 3 | 定时模式 | Timer (scheduled on/off) |
| 4 | 智能模式 | Smart (AI-driven) |

**Fill light mode** (`filllightmode`):

| Value | Mode | Description |
|-------|------|-------------|
| 0 | 全彩模式 | Full-color (white light) |
| 1 | 红外模式 | Infrared (IR) |
| 2 | 智能夜视 | Smart night vision (auto-switch) |

**Brightness & sensitivity parameters:**

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| `duration` | int | 5–60 | Smart night vision white light duration (seconds) |
| `brightnessmode` | int | 0–1 | White light brightness mode: 0=auto, 1=manual |
| `brightness` | int | 1–100 | White light manual brightness |
| `irmode` | int | 0–1 | IR brightness mode: 0=auto, 1=manual |
| `irbrightness` | int | 1–100 | IR manual brightness |
| `whiteonvalue` | int | 0–100 | White light on-sensitivity |
| `whiteoffvalue` | int | 0–100 | White light off-sensitivity |
| `ironvalue` | int | 0–100 | IR on-sensitivity |
| `iroffvalue` | int | 0–100 | IR off-sensitivity |

**Timer parameters** (active when `daynightmode=3`):

| Parameter | Type | Range | Description |
|-----------|------|-------|-------------|
| `begintime` | int | 0–86399 | Timer start time (seconds from midnight) |
| `endtime` | int | 0–172799 | Timer end time (seconds from midnight) |
| `repeatdays` | string | — | Repeat days (e.g. `"sun,mon,tue,wed,thu,fri,sat,"`) |
| `enable` | int | 0–1 | Timer enable: 0=off, 1=on |

**Set behavior:** the device requires the **full parameter set** when writing. The tool handles this internally — it first reads current settings via `SK_SETTING_GET_FILLLIGHT`, merges only the user-specified parameters, then sends the complete set via `SK_SETTING_SET_FILLLIGHT`. The Agent only needs to pass the parameters it wants to change.

### Fallback — ONVIF Imaging Service (ver20)

For non-Skyworth devices (no TCP 9010 connection), the tool falls back to ONVIF:

1. `GetMoveOptions` → detect supported illumination modes
2. `GetImagingSettings` → read current `IlluminationConfiguration.Mode`
3. `SetImagingSettings` → write mode (only `IlluminationConfiguration.Mode` is touched)

ONVIF fallback provides coarser control (mode string only, e.g. `OFF`/`AUTO`/`ON`).

### Capability probing at connect time

`connect_device()` calls `probe_illumination_capability()` after a successful connection. The probe tries TCP first, then ONVIF. Results are persisted to `config.yaml` as `illumination_modes`. The probe is non-blocking: failures are silently ignored.

---

## `manage_illumination(camera_name, action, **params) -> IlluminationResult`

**The single MCP entry point for all illumination operations.**

| `action` | Mode | Returns |
|----------|------|---------|
| `get` | Query capability & current settings | `IlluminationResult` |
| `set` | Set illumination parameters | `IlluminationResult` |

---

### `action="get"`

Query the device's illumination capability and all current settings.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (read-only query) |
| **Parameters** | `camera_name` only |
| **Agent behavior** | Report `current_settings` and `capabilities` to the user. If `capabilities` is empty, the device does not support illumination control. |

**Returns** `IlluminationResult` with:
- `protocol`: `"sky_private"` or `"onvif"` (which protocol was used)
- `current_settings`: dict of all current parameter values (e.g. `{"daynightmode": 2, "filllightmode": 1, "brightness": 80, ...}`)
- `capabilities`: list of parameter descriptions with ranges (e.g. `[{"name": "daynightmode", "type": "int", "min": 0, "max": 4, "desc": "0:off,1:on,2:auto,3:timer,4:smart"}, ...]`)
- `current_mode`: human-readable daynight mode name (e.g. `"自动模式"`)
- `supported_modes`: list of daynight mode descriptions for backward compatibility

---

### `action="set"`

Change one or more illumination parameters. **Requires explicit user confirmation.**

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt — hardware setting change; confirm with the user |
| **Parameters** | `camera_name` + any subset of the 15 illumination parameters |
| **Agent behavior** | Call `get` first to retrieve `capabilities` and validate parameter ranges, then call `set` with only the parameters the user wants to change. Report `previous_settings` → `current_settings` transition. |

**All settable parameters** (all optional — specify only what you want to change):

| Parameter | Type | Range |
|-----------|------|-------|
| `daynightmode` | int | 0–4 |
| `filllightmode` | int | 0–2 |
| `duration` | int | 5–60 |
| `brightnessmode` | int | 0–1 |
| `brightness` | int | 1–100 |
| `begintime` | int | 0–86399 |
| `endtime` | int | 0–172799 |
| `repeatdays` | string | weekday list |
| `enable` | int | 0–1 |
| `irmode` | int | 0–1 |
| `irbrightness` | int | 1–100 |
| `whiteonvalue` | int | 0–100 |
| `whiteoffvalue` | int | 0–100 |
| `ironvalue` | int | 0–100 |
| `iroffvalue` | int | 0–100 |

---

## IlluminationResult return fields

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether the operation succeeded |
| `action` | string | `"get"` or `"set"` |
| `protocol` | string | `"sky_private"` or `"onvif"` |
| `current_settings` | dict | All current parameter values |
| `previous_settings` | dict | Settings before change (only for `set`) |
| `capabilities` | list | Parameter capability descriptions (only for `get`) |
| `current_mode` | string | Human-readable daynight mode name |
| `previous_mode` | string | Mode before change (only for `set`) |
| `supported_modes` | list[string] | Daynight mode descriptions (backward compat) |
| `error_message` | string | Failure reason (empty on success) |
