# Workflow Reference

Detailed workflow examples, code snippets. This file supplements the concise instructions in `SKILL.md`.

---

## Phase 0 — Session Init: Detailed Code

```python
import scripts.toolkit as tk

# 1. Read registered cameras from config.yaml
registered = tk.get_registered_cameras()

# 2. Auto-connect each registered camera using cached credentials
for cam in registered:
    result = tk.connect_device(cam.name)
    if result.success:
        print(f"Connected: {cam.name} (auth: {result.auth_method})")
    else:
        print(f"Failed: {cam.name} — {result.error_message}")
        # Fall through to Phase 1 to rediscover this device

# 3. If config.yaml empty or all connections failed → Phase 1
```

---

## Phase 1 — Discover Cameras: Detailed Code

### ONVIF WS-Discovery

```python
import scripts.toolkit as tk
result = tk.search_devices(method="ws_discovery", timeout=15)
for d in result.devices:
    print(f"{d.ip} — {d.model} — {d.device_class}")
```

For protocol details (multicast addresses, message types, key fields), see [ARCHITECTURE.md — Device Discovery](ARCHITECTURE.md#device-discovery).

### Skyworth Private Protocol Discovery

```python
import scripts.toolkit as tk
result = tk.search_devices(method="sky_discovery", timeout=10)
for d in result.devices:
    print(f"{d.ip} — SN:{d.sn} — {d.sky_subtype} — {d.sky_name}")
    print(f"  RTSP port: {d.rtsp_port}, Web port: {d.sky_web_port}, MAC: {d.sky_mac}")
```

For message format and field definitions, see [ARCHITECTURE.md — Skyworth Private Protocol](ARCHITECTURE.md#skyworth-private-protocol).

### USB Camera Enumeration

```python
import scripts.toolkit as tk
result = tk.search_devices(method="usb")
# Returns list of local USB cameras with device indices
```

---

## Phase 2 — Connect & Authorize: Detailed Code

### Direct-connect camera (no password needed)

```python
result = tk.connect_device("书房摄像头")
# Tool probes RTSP → receives 200 OK → connects directly
# auth_method will be "direct"
```

### Password-required camera with cached credentials

```python
# Credentials already in config.yaml from previous session
result = tk.connect_device("客厅摄像头")
# Tool reads username/password from config.yaml, connects via ONVIF/TCP auth
# auth_method will be "password"
```

### Password-required camera with no cached credentials (probe flow)

```python
# Step 1: Initiate connection — tool probes RTSP stream
result = tk.connect_device("discovered_192_168_1_100")

# Step 2: Check if password is needed
if result.status == "needs_password":
    # Agent prompts user for password
    password = input("Please enter the camera password: ")

    # Step 3: Re-connect with user-provided password
    result = tk.connect_device(
        "discovered_192_168_1_100",
        password=password,
        ip=result.ip or "192.168.1.100",
        rtsp_port=result.rtsp_port or 554,
    )

if result.success:
    # Step 4: Register to config.yaml — credentials saved for future sessions
    tk.register_camera(
        name="客厅摄像头",
        ip="192.168.1.100",
        port=80,
        username="admin",
        password=password,
        device_class="password_required",
    )
    print("Connected and registered. Future sessions will auto-connect.")
else:
    print(f"Connection failed: {result.error_message}")
```

---

## Phase 3 — Stream & Capture: Detailed Code

```python
# Capture a snapshot
result = tk.capture_video_screenshot("客厅摄像头")
print(f"Screenshot saved to: {result.file_path}")

# Get stream URL
result = tk.get_audio_video_stream("客厅摄像头")
print(f"RTSP URL: {result.stream_url}")

# Start/stop recording
result = tk.toggle_recording("客厅摄像头", action="start")
# ...
result = tk.toggle_recording("客厅摄像头", action="stop")
```

> For non-ASCII path handling and same-process connection requirements, see [ARCHITECTURE.md — Known Issues](ARCHITECTURE.md#known-issues--implementation-notes).

---

## Phase 4 — PTZ Control: Detailed Code

PTZ uses a **dual-protocol strategy**: ONVIF is tried first, automatically falling back to the Skyworth private protocol when unavailable. All return results include a `protocol` field indicating which protocol was actually used.

### Directional movement (8 directions + Chinese aliases)

```python
# Basic 4 directions (auto-stop after duration_seconds, default 1.0s)
tk.control_ptz("客厅摄像头", tk.PTZDirection.UP, speed=0.5)
tk.control_ptz("客厅摄像头", tk.PTZDirection.LEFT, speed=0.5, duration_seconds=2.0)

# Diagonal directions
tk.control_ptz("客厅摄像头", tk.PTZDirection.UPLEFT, speed=0.5)
tk.control_ptz("客厅摄像头", tk.PTZDirection.DOWNRIGHT, speed=0.5)

# Chinese direction aliases are supported
tk.control_ptz("客厅摄像头", "上", speed=0.5)
tk.control_ptz("客厅摄像头", "左上", speed=0.5)
```

### Zoom control

```python
# Zoom in (auto-stop after 1.5s)
tk.control_lens_zoom("客厅摄像头", tk.ZoomAction.IN, speed=0.5)

# Zoom out
tk.control_lens_zoom("客厅摄像头", tk.ZoomAction.OUT, speed=0.5)
```

### Preset positions (ONVIF only)

```python
# Save current position as preset
tk.save_ptz_preset("客厅摄像头", "大门")

# Go to saved preset
tk.go_to_preset("客厅摄像头", "大门")
```

### Get current PTZ status

```python
params = tk.get_ptz_parameters("客厅摄像头")
print(f"Position: pan={params.pan}, tilt={params.tilt}, zoom={params.zoom}")
print(f"Range: x_range={params.pan_range}, y_range={params.tilt_range}, z_range={params.zoom_range}")
print(f"Moving: {params.is_moving}, Protocol: {params.protocol}")
```

### Stop PTZ immediately

```python
# Stop all PTZ movement (ONVIF first, private fallback)
tk.stop_ptz("客厅摄像头")
```

### Physical calibration (private protocol only)

```python
# Calibrate PTZ zero point (takes 10-30 seconds, Skyworth cameras only)
result = tk.calibrate_ptz("客厅摄像头")
print(f"Calibration: {'OK' if result.success else result.error_message}")
```

### Move to absolute coordinate (private protocol only)

```python
# First query the valid coordinate ranges
params = tk.get_ptz_parameters("客厅摄像头")
print(f"Valid range: x=[0,{params.pan_range}], y=[0,{params.tilt_range}], z=[0,{params.zoom_range}]")

# Move to specific absolute position
tk.move_to_position("客厅摄像头", x=1000, y=500, z=1.0)
```

### Patrol cruise (ONVIF only)

```python
# Start patrol through all saved presets (background thread)
result = tk.start_patrol_cruise("客厅摄像头")
print(f"Cruise started: {result.preset_count} presets, protocol={result.protocol}")
```

