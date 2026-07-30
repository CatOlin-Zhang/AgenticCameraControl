---
name: xpai-camera-control
description: Discover, connect, and control Skyworth cameras on the local network. Capabilities include device detection, streaming, snapshot capture, PTZ pan/tilt control, alarm event monitoring, and device management. Runs as an MCP Server. Use when the user wants to discover cameras, view a camera feed, capture snapshots, control PTZ, watch for motion/alarm events, manage camera settings, or mentions ONVIF, RTSP, IP camera, webcam, or Skyworth cameras.
license: MIT
compatibility: Requires Python 3.10+, OpenCV, onvif-zeep, requests, psutil, PyYAML, and mcp. Cameras must be on the same LAN for discovery.
metadata:
  version: "0.4.5"
---

# Camera Control Skill

## When to Use

Trigger this skill when the user:+
- Wants to see a camera feed, capture a snapshot, or record video
- Asks to find or discover cameras on the network
- Requests pan, tilt, camera movement, or PTZ calibration
- Asks to watch/guard a camera or check for motion, human, tamper, or other alarm events
- Mentions ONVIF, RTSP, IP camera, webcam, or specific camera brands
- Wants to set up this skill as an MCP server for use with MCP-compatible clients

## Running Mode: MCP Server

Run `scripts/mcp_server.py` as a standalone MCP server that exposes all camera control functions as MCP tools via stdio transport. Compatible with any MCP client (Claude Desktop, etc.).

```bash
# Install dependencies
pip install -r requirements.txt

# Run MCP server
python scripts/mcp_server.py
```

**MCP Configuration** — Add to your MCP client's config:
```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "python",
      "args": ["scripts/mcp_server.py"],
      "cwd": "/path/to/xpai-camera-control"
    }
  }
}
```

The MCP server exposes **17 tools** covering all 5 toolkit modules. See [references/commands/](references/commands/) for per-module tool signatures and parameters.

### MCP-Only Interaction (Hard Rule)

All camera operations **MUST** go through the MCP tools exposed by `scripts/mcp_server.py`:

- If the `xpai-camera-control` tools are **not present** in your available tool set, do NOT fall back to scripting. First register the MCP server in the client configuration (installing `requirements.txt` if needed), wait for the tools to load, then call them.
- **NEVER** import `scripts.toolkit` (or any module inside this package) directly, and **NEVER** write standalone scripts that re-implement or wrap tool functionality.
- Rationale: direct imports bypass the security constraints of this skill (explicit user confirmation, parameter validation) and the in-memory connection state held by the MCP server process — scripted calls in a separate process will silently violate both.

## Core Workflow

### Phase 0 — Session Init (must be done at the very beginning of the session)

At the beginning of each session, check if there are any registered cameras in config.yaml:

1. Call `get_registered_cameras()` to read the camera configurations (including credentials) saved in config.yaml
2. For each registered camera, call `connect_device(cam.name)` — the tool will automatically use the credentials in config.yaml to connect, **no need for the user to input a password again**
3. If config.yaml is empty or all registered cameras fail to connect → enter Phase 1

### Phase 1 — Discover Cameras

When Phase 0 cache is unavailable, call `search_devices()` to discover cameras on the local network. Try **both** network discovery methods — they cover disjoint device sets:

- `method="ws_discovery"` — standard ONVIF WS-Discovery (`239.255.255.250:3702`). **The only method that finds non-Skyworth ONVIF cameras**; also finds Skyworth IPCs. ONVIF port is parsed from XAddrs (not always 80).
- `method="sky_discovery"` — Skyworth private multicast (`239.230.236.230:9008`). Only Skyworth devices respond, but returns richer metadata (SN, channels, MAC).
- `method="usb"` — local USB camera enumeration.

### Phase 2 — Connect & Authorize

For each discovered camera, call `connect_device()` to connect. **The specific connection process is handled internally by the tool** (cached credentials → ONVIF auth → authorization server → stream probe). The Agent's responsibilities are as follows:

| Scenario | Agent Operation |
|----------|----------------|
| **Cached credentials** (config.yaml has password) | Tool auto-loads credentials → ONVIF auth verification → `ConnectResult(success=True)` — no user interaction |
| **direct_connect** (stream probe succeeds) | Tool connects directly via RTSP → `ConnectResult(auth_method="direct")` — no user interaction |
| **pending_auth** (password_required, authorization server available) | Tool sends request to authorization server → `ConnectResult(status="pending_auth", needs_password=True)` → Agent calls `poll_auth_status()` (every ~5s, max 120s) → when authorized, prompt user for password → call `connect_device(name, password=xxx)` |
| **needs_password** (stream probe returns 401 or auth server unreachable) | Tool returns `ConnectResult(status="needs_password", needs_password=True)` → Agent prompts user for password → calls `connect_device(name, password=user_input)` |
| **Connection successful** | Agent calls `register_camera()` to persist credentials to config.yaml → future sessions auto-connect via Phase 0 |

**Authorization Server:** Password-required cameras without cached credentials use the authorization server (`local_auth_url` in config.yaml). Currently backed by a local server (`local_auth_server/server.py`); future versions will point to a cloud service. The user confirms authorization in the browser, then the Agent polls for the result. See [Authorization Server](#authorization-server) section below.

### Phase 3 — Stream & Capture

After a successful connection, perform streaming operations:
- `capture_video_screenshot()` — captures a single frame from the RTSP stream and saves it as JPEG (uses OpenCV, auto-discards initial buffered frames for a clean capture)
- `get_audio_video_stream()` — retrieves the RTSP stream URL and validates stream availability, returns codec/resolution/fps metadata
- `toggle_recording()` — starts/stops local MP4 recording from the RTSP stream via OpenCV VideoWriter
- `manage_storage_status()` — queries disk usage and configures storage path/format/policy

Screenshot files are saved to `snapshots/` directory by default; recordings go to `recordings/`.

**Result delivery (when user wants to "see" a camera):**
After capturing a screenshot and fetching the stream URL, the Agent **MUST** deliver both results to the user:
1. **Show the screenshot** — display the image from `file_path` to the user (e.g. via markdown image syntax `![screenshot](file_path)`)
2. **Provide the RTSP URL** — output the `stream_url` from `get_audio_video_stream()` so the user can open it in a media player (VLC, ffplay, PotPlayer, etc.) for live viewing

### Phase 4 — PTZ Control

PTZ control uses a **dual-protocol strategy**: ONVIF is tried first, automatically falling back to the Skyworth private protocol (`SK_SETTING_SET_PTZ` via TCP port 9010) when ONVIF is unavailable.

| Capability | Tools | Protocol |
|------------|-------|----------|
| Directional movement (8 directions) | `control_ptz` | ONVIF → private fallback |
| Get position & ranges | `get_ptz_parameters` | ONVIF → private fallback |
| Stop all movement | `stop_ptz` | ONVIF → private fallback |
| Physical calibration | `calibrate_ptz` | Private protocol only |

`control_ptz` auto-stops after `duration_seconds` (default 1s). Direction parameter supports both English (`up`/`down`/`left`/`right`/`upleft`/`upright`/`downleft`/`downright`) and Chinese aliases (上/下/左/右/左上/右上/左下/右下).

**Physical Limit Guard:** `control_ptz` validates the command against the PTZ's actual physical travel range at the tool layer — the agent does not need to pre-validate durations. If the head is already at the limit, the command is intercepted before being sent; if the limit is reached mid-movement (e.g. "turn right 5s" but only 3s of travel remains), the tool stops early and replaces the request with the feasible movement. In both cases the result carries `degraded=True` and a human-readable `degrade_reason`. **The Agent MUST explicitly relay `degrade_reason` to the user whenever `degraded=True`** — never report a degraded move as if it completed as requested.

Detailed tool-call examples and parameter descriptions are available in [references/WORKFLOW.md](references/WORKFLOW.md).

### Optional — Event Monitoring

This skill can also receive alarm events (motion, human, tamper, line-crossing, …) and trigger a linked snapshot automatically — it is a **supplementary** capability, not part of the core workflow. Enabling it requires a successfully connected camera first (Phase 0 / Phase 1 / Phase 2), after which the Agent calls `manage_camera_events(action="start", camera_name=...)` — the only action that spawns a background thread (off by default; requires explicit user confirmation). The tool also supports `stop` / `poll` / `wait` via the same entry point. Once started, the monitoring intent is persisted on disk — if the host recycles the MCP server process, the listener is automatically re-armed on server startup and on the next `poll` / `wait` call, until the user explicitly calls `stop`.

Event data (schema 1.0 JSON lines) is written to a local on-disk store that **any other skill or external agent-side module may consume directly from disk** — no MCP dependency. This makes it possible to build higher-level scenarios on top (e.g. an external forwarder pushes notifications to WeChat/Slack/Telegram, a home-automation skill triggers lights on intrusion, etc.). See [references/EVENT_INTEGRATION.md](references/EVENT_INTEGRATION.md) for the on-disk format, paths, and integration contract.

## Toolkit Modules

5 modules in `scripts/toolkit/`:

| Module | Key Functions | Reference |
|--------|--------------|----------|
| `device_mgmt.py` | `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device`, `request_cloud_auth`, `poll_auth_status` | [commands/device_mgmt.md](references/commands/device_mgmt.md) |
| `discovery.py` | `discover_sky_devices`, `SkyDiscoveryListener` | [commands/discovery.md](references/commands/discovery.md) |
| `stream.py` | `capture_video_screenshot`, `get_audio_video_stream`, `toggle_recording`, `manage_storage_status` | [commands/stream.md](references/commands/stream.md) |
| `ptz.py` | `control_ptz`, `get_ptz_parameters`, `calibrate_ptz`, `stop_ptz` | [commands/ptz.md](references/commands/ptz.md) |
| `events.py` | `manage_camera_events` (action: `start` / `stop` / `poll` / `wait`) | [commands/events.md](references/commands/events.md) |

## Security Constraints

| Constraint | Rule | Applies To |
|------------|------|-----------|
| **Explicit Prompt** | Inform the user of the operation content before execution and wait for confirmation | PTZ, streaming, screenshots, event monitor start |
| **Code Validation** | Validate parameters, device status, and connection availability | Recording, storage configuration |
| **Cloud Auth Flow** | Authorization server browser confirmation + password input | Password-required cameras without cached credentials (pending_auth flow) |
| **Background Thread Boundary** | The only background threads in this skill are the per-camera event listeners; they start **only** after explicit user enablement via `manage_camera_events(action="start")`, and their behavior is limited to alarm subscription plus writes into the `snapshots/` and `events/` whitelist paths. Auto-resume after a process restart re-arms **only** listeners the user enabled and never stopped (persisted intent) — it never starts new listeners on its own | Event monitoring |

## Gotchas

- **ONVIF port is not always 80.** Discovered cameras must parse the port from WS-Discovery `XAddrs` — do not assume default 80.
- **`GetStreamUri` returns bare RTSP URLs without credentials.** The toolkit auto-injects auth via `_build_rtsp_url()` — do not use the raw URL directly.
- **Chinese characters in Windows paths cause `cv2.imwrite()` to silently fail.** The toolkit uses `cv2.imencode()` + `numpy.tofile()` as a workaround.
- **Connection state is in-memory only.** `connect_device()` and subsequent operations (`capture_video_screenshot()`, etc.) must run in the **same Python process** — cross-process calls will fail.
- **Skyworth cameras use non-standard RTSP paths.** When the configured path fails, the toolkit auto-tries fallback paths in order: standard ONVIF paths (`/Streaming/Channels/101` → `/h264/ch1/main/av_stream` → `/live`) → Skyworth paths (`/stream0` → `/md0_0` → `/stream1` → `/md0_1`).
- **Authorization server unreachable → auto-degrades.** If `local_auth_url` is not reachable, `connect_device()` falls back to `needs_password` status (direct password input).

## Error Handling Policy

When any MCP tool call fails, crashes, **or the MCP tools are unavailable in the current session**, the Agent **MUST** follow these rules:

1. **Do NOT write workaround scripts or re-implement tool functionality.** Never attempt to bypass a tool failure — or missing tool registration — by writing custom Python code, shell commands, or alternative implementations. If the tools are missing, register the MCP server (see [MCP-Only Interaction](#mcp-only-interaction-hard-rule)) instead of importing the toolkit directly.
2. **Analyze the error.** Read the error message, traceback, or tool return value (e.g. `success=False`, `error_message`) to identify the root cause.
3. **Report to the user.** Clearly explain:
   - **What failed** — which tool, what operation
   - **Why it failed** — root cause from the `error_message` field and context
   - **How to fix it** — concrete actionable steps the user can take
4. **Wait for the user's decision.** Do not proceed with retries, fallbacks, or alternative approaches until the user confirms.


## Authorization Server

A standalone authorization server (`local_auth_server/server.py`, **outside** the skill package) implements the authorization flow. Currently runs locally; the architecture is pluggable — `local_auth_url` in config.yaml can point to a cloud service in the future. Required for password-required cameras when no cached credentials exist.

**Setup & Usage:**

```bash
# Start local auth server (from project root)
python local_auth_server/server.py              # default port 18899
python local_auth_server/server.py --port 9090  # custom port
```

The server automatically opens a browser window at `http://127.0.0.1:18899`. When a camera requires authorization:
1. Skill calls `request_cloud_auth()` → POST to local server
2. A pending request appears in the browser UI
3. User clicks "Authorize" or "Reject" in the browser
4. Skill polls `poll_auth_status()` every ~5s until result is returned
5. If authorized, Agent prompts user for the camera password and calls `connect_device(camera_name, password=xxx)`

**Note:** The authorization server must be started **before** the MCP server if password-required cameras are expected. If the server is unreachable, the flow degrades gracefully to `needs_password` (direct password input without browser confirmation).


## Configuration

Camera configurations are saved in the skill's root directory under `config.yaml`. After a successful connection, the credentials are automatically written to config.yaml and are reused in subsequent conversations. Complete schema can be found in [references/CONFIG.md](references/CONFIG.md).

## Limitations

- Cameras and host must be on the same local network
- RTSP streams require local network connectivity
- Password-required cameras: authorization server must be running for browser-based auth flow; otherwise falls back to direct password input
- ONVIF authentication uses WS-UsernameToken (PasswordDigest) — credentials are auto-injected into RTSP URLs via `_build_rtsp_url()`
- Screenshot/recording requires `opencv-python` (included in requirements.txt)
- MCP server mode uses stdio transport only
- `claw_id` is auto-generated and persisted in config.yaml to prevent duplicate auth popups



## References

- [references/commands/](references/commands/) — Per-module tool reference (parameter signatures, safety constraints, implementation details)
- [references/WORKFLOW.md](references/WORKFLOW.md) — Complete workflow examples and code snippets
- [references/ARCHITECTURE.md](references/ARCHITECTURE.md) — System architecture, connection flow, device discovery protocols, session rules, and known issues
- [references/CONFIG.md](references/CONFIG.md) — config.yaml complete schema and examples
- [references/EVENT_INTEGRATION.md](references/EVENT_INTEGRATION.md) — On-disk event store schema & external-consumer contract (for other skills / external forwarders that build on top of this skill)
- [requirements.txt](requirements.txt) — Python dependencies for MCP Server mode
- [local_auth_server/](../local_auth_server/) — Standalone authorization server (outside skill package; currently local, pluggable for cloud)
