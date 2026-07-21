# Workflow Reference

Detailed workflow examples, code snippets, and demo mode usage. This file supplements the concise instructions in `SKILL.md`.

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
result = tk.search_devices(method="ws_discovery", timeout=15)
for d in result.devices:
    print(f"{d.ip} — {d.model} — {d.device_class}")
```

WS-Discovery sends Probe multicast to `239.255.255.250:3702`, listens for ProbeMatch responses. Extracts IP and ONVIF port from XAddrs, brand/model from Scopes.

### Network Port Scan (fallback)

When WS-Discovery returns nothing, scan local subnet for RTSP (554) and HTTP (80) ports. Probe common RTSP paths: `/stream1`, `/Streaming/Channels/101`, `/h264/ch1/main/av_stream`, `/h264/ch1/sub/av_stream`, `/cam/realmonitor`, `/live`, `/media/video1`. Fingerprint HTTP responses for camera signatures ("Skyworth", "Hikvision", etc.).

### USB Camera Enumeration

```python
result = tk.search_devices(method="usb")
# Returns list of local USB cameras with device indices
```

---

## Phase 2 — Connect & Authorize: Detailed Code

### Direct-connect camera (no password needed)

```python
result = tk.connect_device("书房摄像头")
# auth_method will be "direct"
```

### Password-required camera with cached credentials

```python
# Credentials already in config.yaml from previous session
result = tk.connect_device("客厅摄像头")
# Tool reads username/password from config.yaml, connects via ONVIF auth
# auth_method will be "password"
```

### Password-required camera with no cached credentials (full auth flow)

```python
# Step 1: Initiate connection — tool sends authorization request to remote server
result = tk.connect_device("discovered_192_168_1_100")

# Step 2: Poll remote server for authorization status
auth_status = tk.poll_auth_status(camera_name="discovered_192_168_1_100")
while auth_status.status != "authorized":
    # Wait and re-poll (interval: 5 seconds, recommended timeout: 120 seconds)
    import time
    time.sleep(5)
    auth_status = tk.poll_auth_status(camera_name="discovered_192_168_1_100")
    if auth_status.status == "rejected":
        print("Authorization rejected by user on camera app.")
        break

# Step 3: Once authorized, tool lists LAN cameras
if auth_status.status == "authorized":
    available = tk.search_devices(method="ws_discovery")
    for d in available.devices:
        print(f"Found: {d.ip} — {d.model}")

# Step 4: Prompt user for password
password = input("请输入摄像头密码: ")  # Agent asks user

# Step 5: Connect with user-provided password
result = tk.connect_device("discovered_192_168_1_100", password=password)
if result.success:
    # Step 6: Register to config.yaml — credentials saved for future sessions
    tk.register_camera(
        name="客厅摄像头",
        ip="192.168.1.100",
        port=80,
        username="admin",
        password=password,
        device_class="password_required",
    )
    print("Connected and registered. Future sessions will auto-connect.")
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

**Path note:** Screenshot files use the system temp directory (`%TEMP%` on Windows, `/tmp` on Unix). OpenCV's `imwrite` fails on paths containing non-ASCII characters.

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
