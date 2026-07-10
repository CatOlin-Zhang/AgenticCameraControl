# Command Reference

Complete reference for all slash commands and LLM-recognised commands.

## Slash Commands

### Discovery

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/discover_net` | `[seconds]` | Passive WS-Discovery heartbeat listen + optional active Probe. Default 15s. Discovers ONVIF cameras on LAN. |
| `/discover` | — | Scan USB cameras (OpenCV enumerate, indices 0–9). |
| `/listen` | — | Start background continuous WS-Discovery heartbeat listener. New cameras are auto-registered. |
| `/stop_listen` | — | Stop the background heartbeat listener. Reports total devices found. |

### Connection

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/connect` | `[name]` | Connect a camera. Defaults to first discovered camera. |
| `/disconnect` | `[name]` | Disconnect a camera. |
| `/password` | `<pwd>` | Set default connection password. Syncs to all ONVIF cameras immediately. Without argument, shows current password length. |
| `/probe_all` | — | Sequentially probe all registered cameras, report success/failure summary with stream URLs. |

### Streaming & Capture

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/stream` | `[name]` | USB: open preview window. ONVIF: show RTSP URL + open OpenCV preview window. |
| `/preview` | `[name]` | Open live preview window (press `q` to close, `s` to snapshot). |
| `/snapshot` | `[name]` | Capture one frame, save as JPEG to `snapshots/` directory. |

### PTZ Control

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/ptz` | `direction [speed]` | Move PTZ. Directions: `up`/`down`/`left`/`right` (or 上/下/左/右). Speed: 0.1–1.0, default 0.5. Auto-stops after 1s. |
| `/ptz_stop` | — | Immediately stop PTZ movement. |
| `/ptz_zoom` | `in\|out` | Zoom in or out. Auto-stops after 1.5s. |
| `/presets` | — | List all PTZ presets for the current camera. |

### Info & Management

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/status` | `[name]` | Show detailed camera status (connection, resolution, model, firmware, stream URL, etc.). |
| `/list` | — | List all registered cameras with connection state. |
| `/devinfo` | — | Fetch ONVIF device details (manufacturer, model, firmware, serial, hardware ID). |
| `/models` | — | List available LLM models and current selection. |
| `/events` | — | Show last 20 events from the event bus. |
| `/clear` | — | Clear LLM conversation history. |
| `/help` | — | Show help text. |
| `/quit` / `/exit` | — | Exit the program. Disconnects all cameras. |

---

## LLM Commands

These are the structured commands the LLM can output in its response. The system extracts them and auto-fills all parameters.

| Command | What it does | Auto-filled params |
|---------|-------------|-------------------|
| `discover_network` | Trigger ONVIF camera discovery | — |
| `discover_usb` | Trigger USB camera scan | — |
| `connect_camera` | Connect a camera | Camera name (from context) |
| `disconnect_camera` | Disconnect a camera | Camera name (from context) |
| `watch_camera` | Connect + stream + preview (compound) | Camera name |
| `get_stream` | Get video stream URL + preview | Camera name |
| `get_snapshot` | Capture a frame | Camera name |
| `take_photo` | Connect + capture (compound) | Camera name |
| `open_preview` | Open live preview window | Camera name |
| `get_status` | Show camera status | Camera name |
| `list_cameras` | List all cameras | — |
| `set_password` | Set connection password | `password` field (from user input) |
| `auto_setup` | Full pipeline: discover → register → connect → stream | — |
| `ptz_move` | PTZ directional move | Direction, speed |
| `ptz_stop` | Stop PTZ | — |
| `ptz_zoom` | PTZ zoom in/out | Action (in/out) |
| `ptz_preset` | Jump to PTZ preset | Preset name |
| `list_presets` | List PTZ presets | — |
| `get_device_info` | ONVIF device info | — |
| `chat` | Plain conversation (no action) | — |

---

## Camera Name Resolution

The system auto-resolves camera names from multiple input formats:

- **Exact name**: `discovered_172_28_234_22` → direct match
- **IP address**: `172.28.234.22` → converted to `discovered_172_28_234_22`
- **Empty / omitted**: defaults to first `discovered_*` camera, or first registered camera
- **Fuzzy**: if no match, falls back to default camera
