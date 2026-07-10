# Configuration Reference

Full schema for `config.yaml` — the main configuration file for the Camera Control skill.

## File Location

The config file is located at `phase3/config.yaml` (project root of the phase3 module). Override with `--config` flag:

```bash
python -m phase3.main --config /path/to/custom/config.yaml
```

## Full Schema

```yaml
# ── Camera definitions ──
cameras:
  - name: string              # Required. Unique camera identifier
    connection_type: string   # "usb" | "onvif"

    # USB-specific
    device_index: int         # OpenCV device index (default: 0)
    device_model: string      # Model name (e.g. "LC2418")
    product_version: string   # Product version (e.g. "ZCR461")

    # ONVIF-specific
    ip: string                # Camera IP address
    port: int                 # ONVIF service port (default: 80)
    username: string          # Login username (default: "admin")
    password: string          # Login password (can be set at runtime via /password)
    rtsp_port: int            # RTSP port (default: 554)
    rtsp_path: string         # Main stream path (default: "/stream1")
    rtsp_sub_path: string     # Sub stream path (default: "/stream2")

# ── LLM backend ──
llm:
  backend: string             # "local" | "ollama" (default: "local")

  # Local backend (llama-cpp-python)
  model_path: string          # Path to GGUF model file

  # Ollama backend
  base_url: string            # Ollama API URL (default: "http://localhost:11434")
  model: string               # Ollama model name (default: "qwen2.5:0.5b")

  # Common
  timeout: int                # Request timeout in seconds (default: 60)
  temperature: float          # Generation temperature (default: 0.3)
```

## Camera Config Details

### `name` (required)

Unique string identifier for the camera. Used in all CLI commands and API calls.

- Static cameras: use descriptive names like `M50_main`, `front_door`
- Auto-discovered cameras: registered as `discovered_<ip>` (e.g. `discovered_172_28_234_22`)

### `connection_type` (required)

| Value | Protocol | Use case |
|-------|----------|----------|
| `usb` | UVC / OpenCV | Local USB webcams |
| `onvif` | ONVIF + RTSP | LAN IP cameras |

### USB Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `device_index` | `0` | OpenCV `VideoCapture` index. Use `/discover` to find available indices. |
| `device_model` | `""` | Informational only. |
| `product_version` | `""` | Informational only. |

### ONVIF Parameters

| Field | Default | Notes |
|-------|---------|-------|
| `ip` | `""` | Required for ONVIF cameras. |
| `port` | `80` | ONVIF service port. Discovered cameras auto-fill from WS-Discovery XAddrs. |
| `username` | `"admin"` | ONVIF login username. |
| `password` | `""` | ONVIF login password. Recommended to set at runtime with `/password` for security. |
| `rtsp_port` | `554` | RTSP streaming port. |
| `rtsp_path` | `"/stream1"` | Main stream RTSP path. Auto-tried in fallback mode. |
| `rtsp_sub_path` | `"/stream2"` | Sub (lower quality) stream RTSP path. |

### RTSP URL Construction

The system builds RTSP URLs as:

```
rtsp://{username}:{password}@{ip}:{rtsp_port}{rtsp_path}
```

When ONVIF is available, the URL is fetched dynamically via `GetStreamUri` which may return a different path.

## LLM Config Details

### `backend`

| Value | Description |
|-------|-------------|
| `local` | Uses `llama-cpp-python` for in-process inference. No external service needed. |
| `ollama` | Connects to a running Ollama service via HTTP API. |

### Local Backend

| Field | Default | Notes |
|-------|---------|-------|
| `model_path` | `D:\OllamaModels\qwen2.5-0.5b-instruct-q4_k_m.gguf` | Path to GGUF model. Auto-downloads if missing. |

The model is auto-downloaded on first use from (in order): hf-mirror.com → huggingface.co → ModelScope → huggingface_hub SDK.

### Ollama Backend

| Field | Default | Notes |
|-------|---------|-------|
| `base_url` | `http://localhost:11434` | Ollama API base URL. |
| `model` | `qwen2.5:0.5b` | Ollama model tag. Pull with `ollama pull qwen2.5:0.5b`. |

### Common

| Field | Default | Notes |
|-------|---------|-------|
| `timeout` | `60` | HTTP request timeout (Ollama backend). |
| `temperature` | `0.3` | Low temperature for reliable command extraction. |

## Example Configs

### Single ONVIF camera + local LLM

```yaml
cameras:
  - name: office_cam
    connection_type: onvif
    ip: 192.168.1.100
    port: 80
    username: admin
    password: ""
    rtsp_port: 554
    rtsp_path: /stream1

llm:
  backend: local
  model_path: D:\OllamaModels\qwen2.5-0.5b-instruct-q4_k_m.gguf
```

### USB webcam + Ollama

```yaml
cameras:
  - name: usb_cam
    connection_type: usb
    device_index: 0

llm:
  backend: ollama
  base_url: http://localhost:11434
  model: qwen2.5:0.5b
  timeout: 60
  temperature: 0.3
```

### Mixed: ONVIF + USB

```yaml
cameras:
  - name: front_door
    connection_type: onvif
    ip: 192.168.1.50
    port: 80
    username: admin
    password: secret123
    rtsp_port: 554
    rtsp_path: /Streaming/Channels/101

  - name: desk_webcam
    connection_type: usb
    device_index: 1

llm:
  backend: local
  model_path: D:\OllamaModels\qwen2.5-0.5b-instruct-q4_k_m.gguf
  temperature: 0.3
```
