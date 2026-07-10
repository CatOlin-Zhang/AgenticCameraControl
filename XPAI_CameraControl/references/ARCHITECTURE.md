# Architecture Reference

System architecture and module responsibilities for the Camera Control skill.

## Module Overview

```
phase3/
├── main.py               # Entry point: parse CLI args, bootstrap components
├── config.yaml           # User configuration (cameras + LLM backend)
├── core/
│   ├── config.py         # Config loading, CameraConfig / LLMConfig / AppConfig dataclasses
│   ├── camera.py         # CameraManager + connection classes (USB / ONVIF)
│   ├── llm.py            # LLM clients: LocalLLMClient (llama-cpp) + OllamaClient
│   └── events.py         # EventBus pub/sub, CameraEvent, OnvifEventListener
├── network/
│   ├── discovery.py      # WS-Discovery passive/active + USB camera enumeration
│   └── identify.py       # RTSP stream validation script (standalone)
└── ui/
    ├── base.py           # BaseUI abstract class
    ├── cli.py            # CLIApp: slash commands + natural language handling
    └── gui.py            # GUIApp (stub / future)
```

## Key Classes

### `CameraManager` (core/camera.py)

Central hub for all camera operations. Provides a uniform API regardless of connection type.

**Responsibilities:**
- Register / remove cameras dynamically
- Connect / disconnect individual or all cameras
- Proxy stream URL, snapshot, and frame reads
- Proxy PTZ commands (move, stop, zoom, presets)
- Batch password updates across all ONVIF cameras

**Key methods:**
```python
add_camera(config: CameraConfig) -> connection
connect(name) -> bool
connect_all() -> Dict[str, bool]
get_stream_url(name, sub_stream=False) -> str
get_snapshot(name) -> Optional[np.ndarray]
ptz_move(name, pan, tilt, zoom, speed) -> bool
ptz_stop(name) -> bool
ptz_goto_preset(name, preset) -> bool
list_cameras() -> List[CameraStatus]
```

### `USBCameraConnection` (core/camera.py)

Manages a local USB (UVC) camera via OpenCV `VideoCapture`.

- Opens device by index (tries DirectShow, falls back to default backend)
- Reads frames directly via `cap.read()`
- Reports resolution and FPS from device properties

### `ONVIFCameraConnection` (core/camera.py)

Manages a LAN camera via ONVIF protocol with RTSP fallback.

- Connects via `onvif-zeep` library, fetches device info (manufacturer, model, firmware, serial)
- **RTSP-only fallback**: if ONVIF fails, auto-tries 8 common stream paths
- RTSP path auto-discovery: tries configured path first, then Hikvision, Dahua, XM, generic paths
- PTZ via ONVIF PTZ Service (`ContinuousMove`, `Stop`, `GotoPreset`)
- Stream URL via ONVIF Media Service (`GetStreamUri`) or config-based RTSP URL construction

### `LocalLLMClient` (core/llm.py)

Local inference via `llama-cpp-python`. No external service required.

- **Lazy model loading**: model loaded on first use
- **Auto-download**: tries hf-mirror → HuggingFace → ModelScope → huggingface_hub
- Default model: Qwen2.5-0.5B-Instruct GGUF (~400MB)
- Two-pass command extraction: streaming chat → dedicated JSON extraction
- Conversation history management with auto-trimming (last 10 turns)

### `OllamaClient` (core/llm.py)

Ollama HTTP API client. Requires running Ollama service.

- Same public API as `LocalLLMClient` (interchangeable)
- Streaming chat via chunked HTTP response
- Error formatting for common Ollama issues (404 model not found, 500, 503)

### `EventBus` (core/events.py)

Publish/subscribe event system for camera events.

- Subscribe by event type or register global listeners
- Event history (last 1000 events), filterable by type and camera name
- Thread-safe (internal lock)
- Event types: device online/offline, motion detection, tamper alarm, line crossing, region intrusion, IO alarm, video loss

### `PassiveDiscoveryListener` (network/discovery.py)

Background daemon for continuous WS-Discovery heartbeat monitoring.

- Runs in a daemon thread, re-joins multicast group on timeout
- Callback hook (`on_found`) for auto-registration of new devices
- Thread-safe device collection with lock
- Supports incremental discovery (`get_new_devices(known_ips)`)

### `CLIApp` (ui/cli.py)

Interactive command-line interface.

- Handles slash commands via dispatch table
- Handles natural language via LLM two-pass parsing
- Smart camera name resolution (IP → registered name, fuzzy fallback)
- Auto-connect: ensures camera is connected before executing operations
- ANSI color output for status feedback

## Data Flow

```
User Input
    │
    ├─ Slash Command ──→ Dispatch Table ──→ Command Handler
    │
    └─ Natural Language ──→ LLM (Pass 1: Chat)
                              │
                              ├─ JSON found ──→ Command Executor
                              │
                              └─ No JSON ──→ LLM (Pass 2: Extract)
                                                │
                                                └─ Command ──→ Command Executor
                                                                   │
                                                                   ▼
                                                            CameraManager
                                                                   │
                                                ┌──────────────────┼──────────────────┐
                                                ▼                  ▼                  ▼
                                          USB Connection     ONVIF Connection    RTSP Fallback
```

## Connection Factory

```python
create_camera_connection(config, event_bus)
    → USBCameraConnection   if config.is_usb
    → ONVIFCameraConnection if config.is_onvif
```

## WS-Discovery Protocol

- **Multicast address**: `239.255.255.250:3702`
- **Hello**: camera broadcasts on boot to announce presence
- **Probe**: client sends to trigger responses from online cameras
- **ProbeMatch**: camera responds to Probe with device info
- **XAddrs**: contains the ONVIF service URL (parse port from here, not always 80)
- **Types**: must contain `NetworkVideoTransmitter` to identify as a camera

## Dependencies

| Package | Purpose |
|---------|---------|
| `onvif-zeep` | ONVIF protocol (SOAP/WS-Discovery) |
| `zeep` | SOAP client library |
| `opencv-python` | Video capture, frame processing, preview |
| `httpx` | HTTP client for Ollama API |
| `pyyaml` | YAML config file parsing |
| `llama-cpp-python` | Local LLM inference (optional) |
| `huggingface_hub` | Model auto-download (optional) |
