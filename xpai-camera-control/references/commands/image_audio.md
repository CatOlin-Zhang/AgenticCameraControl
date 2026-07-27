# Image & Audio

Video picture settings, night vision, floodlight, and audio — `scripts/toolkit/image_audio.py`

---

### `adjust_picture_settings(camera_name, brightness=None, contrast=None, saturation=None, sharpness=None) -> PictureSettingsResult`

Adjust picture brightness, contrast, saturation, and sharpness.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `PictureSettingsResult` (current picture parameters) |
| **Parameters** | `brightness`/`contrast`/`saturation`/`sharpness`: 0–255 (omit to leave unchanged). |
| **Implementation** | ONVIF Imaging Service `SetImagingSettings` |

### `flip_video_display(camera_name, mode) -> FlipResult`

Flip the video display.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `FlipResult` (success/failure) |
| **Parameters** | `mode`: `"horizontal"`, `"vertical"`, `"both"`, or `"none"`. |

### `configure_night_vision(camera_name, mode) -> NightVisionResult`

Switch night vision mode.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `NightVisionResult` (current night vision state) |
| **Parameters** | `mode`: `"infrared"`, `"full_color"`, or `"low_light"`. |
| **Implementation** | Skyworth private protocol / ONVIF Device Service |

### `set_floodlight_mode(camera_name, mode) -> FloodlightResult`

Set floodlight operating mode.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `FloodlightResult` (current floodlight state) |
| **Parameters** | `mode`: `"auto"`, `"always_on"`, `"always_off"`, or `"timed"`. |

### `configure_floodlight_type(camera_name, type) -> FloodlightTypeResult` _(not yet exposed as MCP tool)_

Set floodlight type (white light / infrared).

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Parameters** | `type`: `"white"` or `"infrared"`. |

### `configure_microphone(camera_name, enabled, gain=None, noise_reduction=None) -> MicrophoneResult`

Configure microphone input settings.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `MicrophoneResult` (microphone state) |
| **Parameters** | `enabled`: turn on/off. `gain`: gain level (optional). `noise_reduction`: enable noise reduction (optional). |

### `configure_speaker(camera_name, enabled, volume=None) -> SpeakerResult`

Configure speaker output settings.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `SpeakerResult` (speaker state) |
| **Parameters** | `enabled`: turn on/off. `volume`: 0–100 (optional). |
