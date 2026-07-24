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

WS-Discovery sends Probe multicast to `239.255.255.250:3702`, listens for ProbeMatch responses. Extracts IP and ONVIF port from XAddrs, brand/model from Scopes.

### Skyworth Private Protocol Discovery

```python
import scripts.toolkit as tk
result = tk.search_devices(method="sky_discovery", timeout=10)
for d in result.devices:
    print(f"{d.ip} — SN:{d.sn} — {d.sky_subtype} — {d.sky_name}")
    print(f"  RTSP port: {d.rtsp_port}, Web port: {d.sky_web_port}, MAC: {d.sky_mac}")
```

Sends SK_DISCOVERY_SEARCH via UDP broadcast + multicast to `239.230.236.230:9008`, listens for SK_DISCOVERY_SEARCH_R responses on port 9028. Returns device SN, subtype (1=bullet, 2=dome, 3=hemisphere, 5=PT, 6=linkage), manufacturer, model, channels, and network info.

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

**Path note:** Screenshots use `cv2.imencode()` + `numpy.tofile()` instead of `cv2.imwrite()` to support paths containing non-ASCII characters (e.g. Chinese usernames on Windows). Recordings use a temporary file (via `tempfile.mkstemp()`) and are moved to the final path on stop.

**Same-process note:** `connect_device()` and `capture_video_screenshot()` must run in the same Python process — connection state is in-memory and does not persist across separate process invocations.

---

## Phase 4 — PTZ Control: Detailed Code

```python
# Directional movement (auto-stop after ~1 second)
tk.control_ptz("客厅摄像头", tk.PTZDirection.UP, speed=0.5)
tk.control_ptz("客厅摄像头", tk.PTZDirection.LEFT, speed=0.5)

# Zoom
tk.control_lens_zoom("客厅摄像头", tk.ZoomAction.IN, speed=0.5)

# Preset positions
tk.save_ptz_preset("客厅摄像头", "大门")
tk.go_to_preset("客厅摄像头", "大门")

# Get current PTZ status
params = tk.get_ptz_parameters("客厅摄像头")
print(f"Pan: {params.pan}, Tilt: {params.tilt}, Zoom: {params.zoom}")
```
---
ONVIF `GetStreamUri` may return a different path — prefer the dynamic URL when ONVIF is available.
