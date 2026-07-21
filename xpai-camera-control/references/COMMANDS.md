# Toolkit Function Reference

Complete reference for all toolkit functions in `scripts/toolkit/`. Each function is implemented in its respective module as a standalone callable.

The AI agent should import and call these functions directly — there is no CLI or LLM command layer between the agent and the toolkit.

---

## Safety Constraints

All toolkit functions carry one or more safety constraints that the calling code must enforce:

| Constraint | Meaning |
|------------|---------|
| **Explicit Prompt** | Inform the user what operation will be performed and wait for confirmation before executing. |
| **Code Validation** | Validate parameter legality, device state, and connection availability before executing. |
| **Explicit Authorization** | Requires cloud-side (APP) authorization for sensitive operations. |

---

## Module: `scripts/toolkit/dev ce_mgmt.py`

Device discovery, connection, and management.

### `search_devices(method: str = "ws_discovery", timeout: int = 15) -> List[DeviceInfo]`

Search for available cameras on the local network.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | List of `DeviceInfo` objects (IP address, ONVIF port, model, SN, media capabilities) |
| **Parameters** | `method`: `"ws_discovery"` for ONVIF WS-Discovery, `"usb"` for USB enumeration. `timeout`: discovery timeout in seconds. |
| **Implementation** | WS-Discovery Probe + Passive Listen via `onvif-zeep` / OpenCV USB enumeration |

### `get_registered_cameras() -> List[CameraConfig]`

Read all camera entries from `config.yaml` and return their configurations (name, ip, port, username, password, device_class, etc.).

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | List of `CameraConfig` objects (all fields from config.yaml cameras section) |
| **Parameters** | None |
| **Implementation** | Read and parse `config.yaml` from skill root |
| **When to call** | At session start (Phase 0) — always call before any discovery to check if cached cameras are available |

### `register_camera(name: str, ip: str, port: int = 80, username: str = "admin", password: str = "", rtsp_port: int = 554, rtsp_path: str = "/stream1", device_class: str = "direct_connect", **kwargs) -> RegisterResult`

Write a camera entry to `config.yaml`, persisting its connection info and credentials for future auto-connect.

| Aspect | Detail |
|--------|--------|
| **Safety** | None (internal config write; does not expose credentials to user) |
| **Returns** | `RegisterResult` (success, camera name) |
| **Parameters** | `name`: unique camera name. `ip`: camera IP. `port`: ONVIF port. `username`/`password`: credentials (saved to config.yaml, never displayed). `rtsp_port`/`rtsp_path`: stream parameters. `device_class`: `"password_required"` or `"direct_connect"`. Additional kwargs: `sn_code`, `pkdk`, `rtsp_sub_path`. |
| **Implementation** | Append/update entry in `config.yaml` cameras section |
| **When to call** | After first successful `connect_device()` — persist credentials so future sessions can auto-connect without re-entering password |

### `connect_device(camera_name: str, password: Optional[str] = None) -> ConnectResult`

Establish connection to a camera. The tool handles the full connection flow internally; the Agent's role is to call this function, poll authorization status if needed, and prompt the user for password.

**Behavior by scenario:**

| Scenario | Tool Behavior | Agent Action |
|----------|--------------|-------------|
| Cached camera (config.yaml has credentials) | Auto-load username/password from config.yaml → ONVIF auth | No user interaction needed |
| Direct-connect camera | Connect via RTSP directly (no auth) | No user interaction needed |
| Password-required (no cached credentials) | Send auth request to remote server → return `pending_auth` | Agent polls `poll_auth_status()`, prompts user for password, then calls `connect_device()` again with password |

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization (password-required devices need cloud authorization + user password input) |
| **Returns** | `ConnectResult` (success/failure, auth_method, status) |
| **Parameters** | `camera_name`: camera identifier. `password`: user-provided password for ONVIF auth (optional; auto-loaded from config.yaml when available) |
| **Implementation** | Config lookup → ONVIF connection → cloud auth request → RTSP fallback |
| **When to call** | Phase 0 (cached cameras), Phase 2 (new cameras, possibly with password from user) |

### `poll_auth_status(camera_name: str) -> AuthStatusResult`

Poll the remote authorization server to check whether the agent has been authorized to connect to a password-required camera. The Agent calls this in a loop after `connect_device()` returns `pending_auth`.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `AuthStatusResult` (status: `"pending"` / `"authorized"` / `"rejected"` / `"error"`, camera_name, message) |
| **Parameters** | `camera_name`: the camera whose authorization is being checked |
| **Implementation** | HTTP GET to remote authorization server endpoint |
| **When to call** | After `connect_device()` returns `pending_auth` — poll every 5 seconds until status is `authorized` or `rejected` (max 120 seconds recommended) |
| **Next step after `authorized`** | Agent prompts user for camera password → calls `connect_device(camera_name, password)` |

### `query_device_model(camera_name: str) -> DeviceModelResult`

Query device model, firmware version, and status information.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `DeviceModelResult` (manufacturer, model, firmware version, serial number, hardware ID) |
| **Parameters** | `camera_name`: camera identifier |
| **Implementation** | ONVIF `GetDeviceInformation` |

### `update_firmware(camera_name: str, firmware_path: Optional[str] = None) -> FirmwareResult`

Update device firmware.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation (validate firmware version, device state, battery level) |
| **Returns** | `FirmwareResult` (success/failure) |
| **Parameters** | `camera_name`: camera identifier. `firmware_path`: path to firmware file (optional). |
| **Implementation** | ONVIF Device Service / Skyworth private protocol |

### `system_maintenance(camera_name: str, action: str) -> MaintenanceResult`

Perform system maintenance operations.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation |
| **Returns** | `MaintenanceResult` (success/failure) |
| **Parameters** | `camera_name`: camera identifier. `action`: `"reboot"`, `"calibrate_ptz"`, or `"factory_reset"`. |
| **Implementation** | ONVIF Device Service `SystemReboot` |

---

## Module: `scripts/toolkit/stream.py`

Audio/video streaming, snapshot capture, and recording.

### `get_audio_video_stream(camera_name: str, sub_stream: bool = False) -> StreamResult`

Fetch the real-time video stream URL.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation (validate device is connected, stream URL is reachable) |
| **Returns** | `StreamResult` (success, stream URL, codec, resolution, frame rate) |
| **Parameters** | `camera_name`: camera identifier. `sub_stream`: use sub-stream (lower quality) if `True`. |
| **Implementation** | ONVIF: `GetStreamUri` → RTSP URL; USB: OpenCV `VideoCapture` |

### `capture_video_screenshot(camera_name: str, save_path: str = "snapshots/") -> ScreenshotResult`

Capture a single frame from the current video stream and save as JPEG.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation (validate device connected, frame available) |
| **Returns** | `ScreenshotResult` (success, file path) |
| **Parameters** | `camera_name`: camera identifier. `save_path`: output directory path. |
| **Implementation** | OpenCV `VideoCapture.read()` → `cv2.imwrite()` |

**Note:** Prefer the system temp directory for `save_path` to avoid encoding issues with non-ASCII workspace paths.

### `toggle_recording(camera_name: str, action: str, save_path: Optional[str] = None) -> RecordingResult`

Start or stop local video recording.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation (validate device connected, sufficient storage space) |
| **Returns** | `RecordingResult` (recording state, file path) |
| **Parameters** | `camera_name`: camera identifier. `action`: `"start"` or `"stop"`. `save_path`: output file path (optional). |
| **Implementation** | OpenCV `VideoWriter` (MP4/H.264 encoding) |

### `manage_storage_status(action: str, path: Optional[str] = None, format: Optional[str] = None, policy: Optional[str] = None) -> StorageResult`

Query storage usage or configure storage path, format, and policy.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation (validate path is writable, policy parameters are legal) |
| **Returns** | `StorageResult` (used/available space, storage path, policy name) |
| **Parameters** | `action`: `"query"` or `"set"`. `path`, `format`, `policy`: set mode parameters (optional). |

---

## Module: `scripts/toolkit/ptz.py`

Pan/tilt/zoom control. **Prerequisite:** ONVIF connection only. USB and RTSP-only cameras do not support PTZ.

### `control_ptz(camera_name: str, direction: PTZDirection, speed: float = 0.5) -> PTZMoveResult`

Step-based directional movement of the PTZ head.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `PTZMoveResult` (success, current pan angle, current tilt angle, current zoom) |
| **Parameters** | `camera_name`: camera identifier. `direction`: `PTZDirection.UP` / `DOWN` / `LEFT` / `RIGHT`. `speed`: 0.1–1.0. |
| **Implementation** | ONVIF PTZ `ContinuousMove` + auto `Stop` after 1 second |

Supports Chinese direction aliases: 上/下/左/右.

### `control_lens_zoom(camera_name: str, action: ZoomAction, speed: float = 0.5) -> PTZMoveResult`

Control optical zoom.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZMoveResult` (success, current zoom value) |
| **Parameters** | `camera_name`: camera identifier. `action`: `ZoomAction.IN` or `ZoomAction.OUT`. `speed`: 0.1–1.0. |
| **Implementation** | ONVIF PTZ `ContinuousMove` (zoom axis) + auto `Stop` after 1.5 seconds |

### `get_ptz_parameters(camera_name: str) -> PTZParameters`

Get current PTZ position and speed data.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZParameters` (pan, tilt, zoom positions; current speeds; whether head is moving) |
| **Parameters** | `camera_name`: camera identifier |
| **Implementation** | ONVIF PTZ `GetStatus` |

### `save_ptz_preset(camera_name: str, preset_name: str) -> PTZPresetResult`

Save the current PTZ position as a named preset.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `PTZPresetResult` (success, preset name, preset token) |
| **Parameters** | `camera_name`: camera identifier. `preset_name`: preset name (e.g. "大门", "客厅"). |
| **Implementation** | ONVIF PTZ `SetPreset` |

### `calibrate_ptz(camera_name: str) -> CalibrateResult`

Execute PTZ physical calibration (return to home position and re-calibrate zero point).

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `CalibrateResult` (success/failure) |
| **Parameters** | `camera_name`: camera identifier |
| **Implementation** | ONVIF PTZ `Home` / private protocol. Takes 10–30 seconds. |

### `start_patrol_cruise(camera_name: str, cruise_name: Optional[str] = None) -> CruiseResult`

Start PTZ patrol cruise along a preset path.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `CruiseResult` (success, cruise name, preset count) |
| **Parameters** | `camera_name`: camera identifier. `cruise_name`: cruise path name (optional, defaults to all presets in order). |
| **Implementation** | Loop `GotoPreset` + delay / ONVIF PTZ `Tour` |

---

## Module: `scripts/toolkit/tracking.py`

AI-powered object tracking and zone monitoring algorithms.

### `track_vehicles(camera_name: str, action: TrackingAction = TrackingAction.START) -> TrackingResult`

Start or stop vehicle detection and tracking.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `TrackingResult` (success, is_tracking state, algorithm name) |
| **Parameters** | `camera_name`: camera identifier. `action`: `TrackingAction.START` or `TrackingAction.STOP`. |
| **Implementation** | ONVIF Analytics / Skyworth private protocol |

### `track_human_shapes(camera_name: str, action: TrackingAction = TrackingAction.START) -> TrackingResult`

Start or stop human shape detection and tracking. PTZ head will auto-follow the target.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation (validate device supports this algorithm) |
| **Returns** | `TrackingResult` (success, is_tracking state, algorithm name) |
| **Parameters** | `camera_name`: camera identifier. `action`: `TrackingAction.START` or `TrackingAction.STOP`. |
| **Implementation** | ONVIF Analytics / Skyworth private protocol |

### `monitor_zone_entry(camera_name: str, action: ZoneAction = ZoneAction.START, zone: Optional[Dict[str, List[Tuple[int, int]]]] = None) -> ZoneMonitorResult`

Start or stop zone entry/exit detection.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `ZoneMonitorResult` (success, is_monitoring state, zone_triggered state, trigger_type) |
| **Parameters** | `camera_name`: camera identifier. `action`: `ZoneAction.START` or `ZoneAction.STOP`. `zone`: dict of zone name to vertex coordinates, e.g. `{"大门": [(100,200), (300,200), (300,400), (100,400)]}`. |
| **Implementation** | ONVIF Analytics RuleEngine / private protocol |

### `stop_tracking_service(camera_name: str) -> StopTrackingResult`

Stop all currently running tracking services.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `StopTrackingResult` (success, list of stopped service names) |
| **Parameters** | `camera_name`: camera identifier |

---

## Module: `scripts/toolkit/image_audio.py`

Video picture settings, night vision, floodlight, and audio configuration.

### `adjust_picture_settings(camera_name: str, brightness: Optional[int] = None, contrast: Optional[int] = None, saturation: Optional[int] = None, sharpness: Optional[int] = None) -> PictureSettingsResult`

Adjust picture brightness, contrast, saturation, and sharpness.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `PictureSettingsResult` (current picture parameters) |
| **Parameters** | `camera_name`: camera identifier. `brightness`/`contrast`/`saturation`/`sharpness`: 0–255 (omit to leave unchanged). |
| **Implementation** | ONVIF Imaging Service `SetImagingSettings` |

### `flip_video_display(camera_name: str, mode: str) -> FlipResult`

Flip the video display.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `FlipResult` (success/failure) |
| **Parameters** | `camera_name`: camera identifier. `mode`: `"horizontal"`, `"vertical"`, `"both"`, or `"none"`. |

### `configure_night_vision(camera_name: str, mode: str) -> NightVisionResult`

Switch night vision mode.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `NightVisionResult` (current night vision state) |
| **Parameters** | `camera_name`: camera identifier. `mode`: `"infrared"`, `"full_color"`, or `"low_light"`. |
| **Implementation** | Skyworth private protocol / ONVIF Device Service |

### `set_floodlight_mode(camera_name: str, mode: str) -> FloodlightResult`

Set floodlight operating mode.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `FloodlightResult` (current floodlight state) |
| **Parameters** | `camera_name`: camera identifier. `mode`: `"auto"`, `"always_on"`, `"always_off"`, or `"timed"`. |

### `configure_floodlight_type(camera_name: str, type: str) -> FloodlightTypeResult`

Set floodlight type (white light / infrared).

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `FloodlightTypeResult` (current floodlight type) |
| **Parameters** | `camera_name`: camera identifier. `type`: `"white"` or `"infrared"`. |

### `configure_microphone(camera_name: str, enabled: bool, gain: Optional[int] = None, noise_reduction: Optional[bool] = None) -> MicrophoneResult`

Configure microphone input settings.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `MicrophoneResult` (microphone state) |
| **Parameters** | `camera_name`: camera identifier. `enabled`: turn on/off. `gain`: gain level (optional). `noise_reduction`: enable noise reduction (optional). |

### `configure_speaker(camera_name: str, enabled: bool, volume: Optional[int] = None) -> SpeakerResult`

Configure speaker output settings.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `SpeakerResult` (speaker state) |
| **Parameters** | `camera_name`: camera identifier. `enabled`: turn on/off. `volume`: 0–100 (optional). |

---

## Module: `scripts/toolkit/alarm.py`

Alarm sound and push notification configuration.

### `configure_alarm_settings(camera_name: str, sound_enabled: Optional[bool] = None, trigger_frequency: Optional[str] = None, sensitivity: Optional[int] = None) -> AlarmSettingsResult`

Configure alarm sound and trigger frequency.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation |
| **Returns** | `AlarmSettingsResult` (success, sound state, trigger frequency, sensitivity level) |
| **Parameters** | `camera_name`: camera identifier. `sound_enabled`: enable/disable alarm sound. `trigger_frequency`: e.g. `"30s"`, `"1min"`, `"5min"`. `sensitivity`: 0–100. |
| **Implementation** | ONVIF Event Service / Skyworth private protocol |

### `configure_alarm_push(camera_name: str, push_type: Optional[PushType] = None, time_range: Optional[str] = None, enabled: Optional[bool] = None) -> AlarmPushResult`

Configure alarm push notification type and active time range.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation |
| **Returns** | `AlarmPushResult` (success, push type, time range, enabled state) |
| **Parameters** | `camera_name`: camera identifier. `push_type`: `PushType.APP`, `PushType.EMAIL`, or `PushType.BOTH`. `time_range`: e.g. `"08:00-22:00"`. `enabled`: enable/disable push. |

---

## Module: `scripts/toolkit/encoding_osd.py`

Video encoding and OSD overlay configuration.

### `configure_video_encoding(camera_name: str, stream_type: str, codec: Optional[str] = None, resolution: Optional[str] = None, bitrate: Optional[int] = None, fps: Optional[int] = None, gop: Optional[int] = None) -> EncodingResult`

Configure video encoding parameters for main or sub stream.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation (validate parameter combinations) |
| **Returns** | `EncodingResult` (success, configured parameters) |
| **Parameters** | `camera_name`: camera identifier. `stream_type`: `"main"` or `"sub"`. `codec`: `"H.264"` or `"H.265"`. `resolution`: e.g. `"1920x1080"`. `bitrate`: in kbps. `fps`: frame rate. `gop`: I-frame interval. |
| **Implementation** | ONVIF Media Service `SetVideoEncoderConfiguration` |

### `configure_osd_settings(camera_name: str, show_time: Optional[bool] = None, show_weekday: Optional[bool] = None, device_name: Optional[str] = None, osd_name: Optional[str] = None, alignment: Optional[str] = None) -> OSDResult`

Configure OSD overlay: time, weekday, device name, OSD name, and alignment.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `OSDResult` (success/failure) |
| **Parameters** | `camera_name`: camera identifier. `show_time`: display timestamp. `show_weekday`: display weekday. `device_name`: custom device name text. `osd_name`: OSD channel name. `alignment`: text alignment position. |
| **Implementation** | ONVIF Media Service `SetOSD` |
