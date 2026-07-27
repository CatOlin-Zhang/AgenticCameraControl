# Encoding & OSD

Video encoding and OSD overlay configuration — `scripts/toolkit/encoding_osd.py`

---

### `configure_video_encoding(camera_name, stream_type, codec=None, resolution=None, bitrate=None, fps=None, gop=None) -> EncodingResult`

Configure video encoding parameters for main or sub stream.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `EncodingResult` (success, configured parameters) |
| **Parameters** | `stream_type`: `"main"` or `"sub"`. `codec`: `"H.264"` or `"H.265"`. `resolution`: e.g. `"1920x1080"`. `bitrate`: in kbps. `fps`: frame rate. `gop`: I-frame interval. |
| **Implementation** | ONVIF Media Service `SetVideoEncoderConfiguration` |

### `configure_osd_settings(camera_name, show_time=None, show_weekday=None, device_name=None, osd_name=None, alignment=None) -> OSDResult`

Configure OSD overlay: time, weekday, device name, OSD name, and alignment.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `OSDResult` (success/failure) |
| **Parameters** | `show_time`: display timestamp. `show_weekday`: display weekday. `device_name`: custom device name text. `osd_name`: OSD channel name. `alignment`: text alignment position. |
| **Implementation** | ONVIF Media Service `SetOSD` |
