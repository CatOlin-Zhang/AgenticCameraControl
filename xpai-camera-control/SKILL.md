---
name: xpai-camera-control
description: "Discover, connect, and control XPAI LAN cameras via MCP. Capabilities: device detection, streaming, WebRTC preview, snapshots, PTZ control, alarm events, illumination, image settings, detection & tracking, device management."
license: MIT
compatibility: Requires 64-bit Python 3.10+, OpenCV, onvif-zeep, requests, psutil, PyYAML, and mcp. Native preparation/loading code supports Windows x64, Linux glibc x64, and macOS Intel/ARM64; the default verified artifact manifest currently enables only Windows x64 camera-proto 0.1.0. Other platforms require reviewed artifact records. Initial wheel installation requires network access. Cameras must be on the same LAN for discovery.
metadata:
  version: "0.7.0"
---

# Camera Control Skill

## When to Use

Trigger when the user wants to discover, view, capture, record, move (PTZ), monitor (events/alarm), adjust (illumination/image), or track with IP cameras on the local network.

## Running Mode: MCP Server (stdio transport)

`scripts/mcp_server.py` runs as an MCP server over **stdio transport only** — it is **not** a network service (no port, no `localhost` URL). The MCP client **launches it as a child process** (config below) and exchanges JSON-RPC over stdin/stdout; the Agent interacts with all camera tools exclusively through this channel, and per-session connection state lives in that child process's memory.

## Installation

If `xpai-camera-control` tools are not present in the available tool set, follow these steps:

**Step 1 — Determine SKILL_ROOT:** the absolute path of the directory containing this SKILL.md, or run `python -c "from scripts._paths import get_skill_root; print(get_skill_root())"`.

**Step 2 — Install dependencies:** `pip install -r <SKILL_ROOT>/requirements.txt` — use the same 64-bit Python interpreter configured for the MCP server.

**Step 3 — Write MCP config:** append the following JSON to the host's MCP config file (replace `<SKILL_ROOT>` with the actual path from Step 1):
```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "python",
      "args": ["<SKILL_ROOT>/scripts/mcp_server.py"]
    }
  }
}
```

**Config notes:** `args` must stay an absolute path — do not rely on `cwd` (host support for `cwd` varies). On Windows, write the path with forward slashes or escaped backslashes (`\\`) so the JSON stays valid. `command` must be the same 64-bit Python interpreter used in Step 2 — use its absolute path if it is not the `PATH` `python`. Common config locations: Claude Desktop `%APPDATA%\Claude\claude_desktop_config.json` (Win) / `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS); Cursor Settings → MCP → Add Server; Cline `.cline/mcp_settings.json`.

**Native runtime preparation:** the skill ships without native libraries; at startup — after acquiring the single-instance lock and lease heartbeat, before restoring event monitors or starting the MCP transport — `mcp_server.py` calls `prepare_runtime.py` to validate/install the pinned native resources from the reviewed local `scripts/runtime_artifacts.json`. On failure the server writes the error to stderr and exits nonzero without serving tools. First install requires network access; startup works offline once local files match the manifest. Installation output goes to stderr, never to the JSON-RPC stdout channel. If the first download exceeds the MCP client's startup timeout, run `python scripts/prepare_runtime.py` manually with the same interpreter, then restart the MCP server (this step does not access cameras). Maintainer/release details (platform records, hashes, test conventions) → [RUNTIME.md](references/RUNTIME.md).

## MCP-Only Interaction (Hard Rule)

All camera operations **MUST** go through the MCP tools exposed by `scripts/mcp_server.py`. If the tools are **not present** in your available tool set, do NOT fall back to scripting — follow the [Installation](#installation) steps first, then call the tools; if server startup fails (e.g. a preparation error on stderr), report the stderr reason and resolve it before retrying.

- **NEVER** import `scripts.toolkit` (or any module inside this package) directly, and **NEVER** write standalone scripts that re-implement or wrap tool functionality — direct imports bypass the skill's security constraints (explicit user confirmation, parameter validation) and the in-memory connection state held by the MCP server process, so scripted calls in a separate process silently violate both.

## Single-Instance Limitation

The MCP server is **stateful and single-instance** — camera connections and RTSP sessions live in one server process's memory, and the instance lock (port bind + lease heartbeat + watchdog, see Gotchas) allows only one running instance at a time by design (concurrent instances would fight for the device's RTSP session slots and hang the camera).

**Agent instruction:** before starting camera work (or the first time camera tools are invoked in a session), proactively tell the user in plain language:

> The camera feature has a usage limitation: only one session can "take over" the camera at a time (the connection state is stored in a single background service). If another session is currently using the camera, the camera tools in this session may become unavailable or fail when called — this is not a malfunction. Please end or close the camera task in the other session first, then ask me to retry.

If startup fails with a lock conflict (exit code 71), do NOT silently retry — tell the user and ask them to close other sessions' camera work first. Missing tools alone do not establish a lock conflict: check registration and startup stderr; if preparation failed, report that error instead and stop until resolved.

## Core Workflow

### Phase 0 — Session Init (must be done at the very beginning of the session)

At the beginning of each session, check if there are any registered cameras in config.yaml:

1. Call `get_registered_cameras()` to read the camera configurations (including credentials) saved in config.yaml
2. For each registered camera, call `connect_device(cam.name)` — the tool uses the cached credentials in config.yaml automatically, **no need for the user to input a password again**. Credential retry and cloud re-authorization are handled internally; if credentials keep failing, the tool auto-removes the registration and returns `status="needs_password"`
   - **If this is the first camera work after a long idle period (hours/days), or a call on a previously working camera fails, call `search_devices()` first** — a camera's IP can change while idle (DHCP lease renewal) and the cached IP in config.yaml goes stale. `search_devices()` re-registers reachable cameras with their current IP and removes cameras that are gone; then retry. Never retry repeatedly against a stale cached IP.
3. If config.yaml is empty or all registered cameras fail to connect → enter Phase 1

### Phase 1 — Discover Cameras

When Phase 0 cache is unavailable, call `search_devices()` to discover cameras on the local network — it automatically selects the best available discovery protocol(s); the Agent does not choose:

- Results come back as a unified `DiscoveredDevice` list: XPAI-specific metadata (SN, channels, MAC, etc.) under `sky_*` fields when available, plus `discovery_method` and `protocol_type`
- `protocol_type` is conclusive only for **`S`** (device answered SK private discovery — full feature set); **empty** means found via JCP/WS-Discovery with no class asserted. `J`/`O` are resolved and persisted by `connect_device` via an authoritative SK-first unicast probe — a JCP answer alone proves nothing (JCP discovery is shared by both S- and J-class firmware), and **`O`** (third-party ONVIF-only) is asserted only when SK/JCP stay silent but the ONVIF admission probe passes (port probe + `GetDeviceInformation`). See the capability matrix below.
- **Search also syncs config.yaml**: reachable discovered cameras are written in with basic info (name, IP, SN, device class, ports — never a password), and registered cameras no longer discoverable **and** unreachable are removed. Re-running `search_devices()` is the supported way to refresh the registry after an IP change, a newly added camera, or a camera that left the network.

**Camera Naming:** when multiple cameras are found, list them (IP, model, SN) and assign a friendly name to each: use user-provided names if the user gives them; otherwise default to auto-naming — capture a screenshot via `capture_video_screenshot()`, generate a scene-descriptive name (e.g. "entrance hallway"), and present it for user confirmation before saving. Pass the chosen name as `name` to `connect_device()` / `register_camera()`; `register_camera` matches by name → IP → SN, so a new name + same IP renames in-place.

### Phase 2 — Connect & Authorize

Call `connect_device()` for each camera. The tool handles auth internally (cloud authorization, cached credentials, direct connect). **Agent only reacts to the returned `status`** — see [Decision Table](#decision-table--error--status--action) for mapping.

### Phase 3 — Stream & Capture

After a successful connection:
- `capture_video_screenshot()` — single JPEG frame from the RTSP stream (auto-discards initial buffered frames for a clean capture)
- `get_audio_video_stream()` — returns the RTSP `stream_url` and validates availability (codec/resolution/fps metadata)
- `toggle_recording()` — starts/stops local MP4 recording from the RTSP stream via ffmpeg remux (`-c:v copy`)
- `manage_storage_status()` — disk usage and storage path/format/policy configuration
- `start_webrtc_stream()` / `stop_webrtc_stream()` — RTSP→WebRTC browser live preview (returns HTTP access URL). If the browser preview stutters or goes black (e.g. Edge has no H265 WebRTC), retry with `start_webrtc_stream(video_codec="h264")` — switches the device encoder (device-wide, briefly interrupts its RTSP sessions) then restarts the preview

Screenshots are saved to `snapshots/` by default; recordings go to `video/`.

**Result delivery (when the user wants to "see" a camera):** after the capture + stream probe, the Agent **MUST** deliver both: (1) show the screenshot image (markdown `![screenshot](file_path)`), (2) provide the `stream_url` so the user can open it in a media player (VLC, ffplay, PotPlayer, etc.) — or (3) call `start_webrtc_stream()` for a browser-based live preview if the user prefers a visual player over a raw RTSP URL.

**Obtaining go2rtc (only when `start_webrtc_stream()` reports go2rtc is not detected):** go2rtc is a third-party single-binary RTSP→WebRTC streaming tool (~15MB) and is not bundled with this skill. When missing, obtain it as follows: search for the "go2rtc" project's GitHub Releases page (project name `go2rtc`, author AlexxIT) and download the release binary matching the current platform (on Windows it is a zip archive — extract `go2rtc.exe` from it); place the binary in the skill root directory or add it to `PATH`; then retry `start_webrtc_stream()`.

### Phase 4 — PTZ Control

PTZ backend is chosen by `protocol_type`: **SK-class** uses the XPAI private protocol (vendor command via TCP channel); **J-class and O-class** use **ONVIF only** (`ContinuousMove` / `Stop` / `GetStatus` on the ONVIF PTZ service — no private-protocol fallback). `control_ptz` auto-stops after `duration_seconds` (default 1s); the direction parameter accepts English (`up`/`down`/`left`/`right`) and Chinese aliases (上/下/左/右).

**J/O-class limits:** the ONVIF backend moves by normalized velocity vectors over `duration_seconds`, so **`degrees` mode is not supported** (the tool returns a message asking the user to use `duration_seconds` instead) and there is **no calibration** (`calibrate_ptz` returns an explicit unsupported message).

**Physical Limit Guard:** `control_ptz` validates the command against the PTZ's actual physical travel range at the tool layer — the agent does not pre-validate. If the head is already at the limit the command is intercepted before being sent; if the limit is reached mid-movement (e.g. "turn right 5s" but only 3s of travel remains), the tool stops early and replaces the request with the feasible movement. Both cases return `degraded=True` + a human-readable `degrade_reason`. **The Agent MUST explicitly relay `degrade_reason` to the user whenever `degraded=True`** — never report a degraded move as if it completed as requested.

**PTZ Movement Estimation:** the SDK does not report absolute PTZ angles. To estimate how far the view has shifted after a rotation, capture screenshots before and after, compare the frames visually, and report the estimated shift as a percentage of frame width/height. Best-effort — in featureless scenes (blank walls, sky) the estimate may be unreliable; say so when it is.

If PTZ detailed sequences, degrees mode, or calibration (`calibrate_ptz` set_home/go_home) are needed → [WORKFLOW.md — Phase 4](references/WORKFLOW.md#phase-4--ptz-control-detailed-tool-calls).

## Extended Capabilities & Protocol Matrix

These tools are available when the user explicitly requests them (all require a connected camera). The matrix doubles as the skill-wide per-device-class capability reference:

| Capability | Tools / Actions | `S` (SK) | `J` (JCP) | `O` (ONVIF-only) | Reference |
|-----------|-----------------|:--------:|:---------:|:----------------:|-----------|
| Alarm events (motion/human/vehicle/tamper/…, linked snapshots) | `manage_camera_events`: `start`/`stop`/`poll`/`wait` | ✅ | ❌ | ❌ | [events.md](references/commands/events.md) |
| Illumination (daynight + fill light; integer value or string alias) | `manage_illumination`: `get`/`set` | ✅ | ❌ | ❌ | [illumination.md](references/commands/illumination.md) |
| Image params (brightness/contrast/saturation/sharpness/flip) | `manage_image_settings`: `get`/`set` | ✅ | ❌ | ❌ | [image_settings.md](references/commands/image_settings.md) |
| Detection & tracking (human/vehicle/area/motion/line-crossing) | `query_tracking_capabilities` / `set_tracking` | ✅ | ❌ | ❌ | [tracking.md](references/commands/tracking.md) |
| PTZ move / stop / status | `control_ptz`, `stop_ptz`, `get_ptz_parameters` | ✅ private protocol | ✅ ONVIF | ✅ ONVIF | [ptz.md](references/commands/ptz.md) |
| PTZ `degrees` mode / calibration | `control_ptz` (`degrees`), `calibrate_ptz` | ✅ | ❌ use `duration_seconds` | ❌ use `duration_seconds` | [ptz.md](references/commands/ptz.md) |
| Streaming / screenshot / recording / WebRTC | stream module tools | ✅ RTSP | ✅ RTSP (ONVIF-authoritative paths) | ✅ RTSP (ONVIF-authoritative paths) | [stream.md](references/commands/stream.md) |
| Discovery | `search_devices` | ✅ SK private | ✅ JCP | ✅ WS-Discovery | [device_mgmt.md](references/commands/device_mgmt.md) |
| Cloud authorization on connect | `connect_device` | ✅ | ✅ | ⚠️ password only (no SK/JCP SN) | [device_mgmt.md](references/commands/device_mgmt.md) |

> `manage_camera_events(action="start")` spawns a background listener thread; `manage_illumination(action="set")` and `set_tracking` modify hardware settings — all require **explicit user confirmation** before calling. Cloud authorization is handled internally by `connect_device` (blocking call, may wait for user confirmation on APP). J/O-class devices asked for an SK-private-protocol-only capability return `error_code="UNSUPPORTED_PROTOCOL"` + a clear reason — not a malfunction or timeout.

> **O-class admission:** a WS-Discovery device that never answers SK/JCP discovery is admitted only when the ONVIF admission probe passes (ONVIF port probe + authenticated `GetDeviceInformation`); its ONVIF SerialNumber is persisted as `onvif_sn` (identity/matching only — **never** fed to cloud auth or SK HTTP as `sn_code`). RTSP-reachable devices that fail ONVIF admission are rejected with `status="no_sn"` — final, do not retry with workarounds.

## Security Constraints

- **Explicit prompt:** inform the user and wait for confirmation before PTZ, streaming, screenshots, event monitor start, and illumination/image/tracking changes.
- **Code validation:** tool-layer validation for recording and storage configuration.
- **Background threads:** event listeners start **only** after `events(action="start")`; auto-resume only re-arms previously-enabled listeners.

## Gotchas

- **Never hardcode ONVIF port 80** → always use `onvif_port` from `search_devices()` / config.yaml.
- **Never manually construct RTSP URLs** → always use `stream_url` from `get_audio_video_stream()` (credentials auto-injected).
- **Chinese characters in Windows paths cause `cv2.imwrite()` to silently fail** → no manual workaround needed (the toolkit handles it internally); if you pass a custom `save_path`, prefer ASCII-only paths.
- **Connection state is in-memory only** → on `success=false` with connection error, call `connect_device()` first, then retry.
- **Fixed-duration recording** → always use `toggle_recording(action="start", duration=<seconds>)`. Never implement agent-side sleep → stop.
- **Instance-lock conflict (exit 71; MCP tools all unavailable, stderr shows lock conflict)** → auto-recovery (stdio watchdog + lease heartbeat + triple-verification) reclaims *expired* leases only; an orphaned server from a previous session that the host never terminated stays alive with a fresh heartbeat and legitimately holds the lock. Recover manually: get the PID from `.instance_lease.json` (`pid` field, skill root — heartbeat writes `pid`/`port`/`ts` every 5 s) or `netstat -ano | findstr 49740` (lock port derived from the skill path); verify it is this skill's `mcp_server.py` (`Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" | Select CommandLine`), then `taskkill /PID <PID> /F /T` and restart the session / MCP client. Exit codes: `70` = watchdog self-cleanup (host abandoned instance); `71` = lock conflict / manual intervention needed. **Confirm with the user that the previous session is truly gone before killing it** — killing breaks whatever session still owns it.
- **Pure-numeric passwords/SNs must be sent as JSON strings.** → when relaying a user-provided password or SN (e.g. `847226`) into any tool argument, quote it as a string (`"847226"`), never emit a bare JSON number. Tool schemas declare these credential fields as `string` only; a numeric value that survives as a number into YAML/config can later load back as an integer and break credential handling.

## Decision Table — error / status → action

This table is the **single runtime source of truth** for error handling. On any tool failure: analyze the error → apply the mapped action. Do NOT write workaround scripts or re-implement tool functionality. Report to the user what failed / why / how to fix, then wait for the user's decision — **except** the bounded auto-retry row below.

| `error_message` pattern / `status` | Agent Action |
|------------------------------------|--------------|
| `not_connected` / `device not found` | Call `connect_device()` first, then retry the failed operation. If it still fails — or this is the first operation after a long idle period — call `search_devices()` to refresh stale IPs in the registry, then retry |
| `needs_password` (status) | Cached credentials expired (cloud re-auth also failed), cloud service unreachable, the device has no SN so cloud auth cannot start (incl. O-class third-party ONVIF), or the device has no cloud station record (submitted to the default station — the APP may not receive it) — ask user for password → `connect_device(camera_name, password=user_input)` |
| `no_sn` (status) | Connection refused: an S/J-asserted XPAI device lost its SN (retry after `search_devices()`), or a WS-Discovery device failed ONVIF admission (RTSP-only, no ONVIF control plane) — report to user; check ONVIF support/port or supply ONVIF credentials. **Forbidden workaround:** manual `register_camera` / hand-editing config.yaml to bypass the gate |
| `error_code="UNSUPPORTED_PROTOCOL"` (incl. `not support illumination`) | J/O-class camera asked for an SK-private-protocol-only capability (illumination / image settings / tracking / events) — inform user of the device-class limitation; not a malfunction or timeout |
| `auth_rejected` / `cloud_pwd_failed` / `cached credentials cleared` | Auth-failure group: user denied cloud authorization → inform user, cannot connect; cloud password mismatch → device may have changed password, ask user for the correct one; cached credentials cleared (tool already attempted cloud re-auth) → prompt user for password → `connect_device(camera_name, password=user_input)` |
| `degraded=true` (PTZ result) | **MUST** relay `degrade_reason` to user verbatim |
| `limit_reached=true` | Stop sending PTZ commands in that direction — physical limit reached |
| `stream unavailable` / RTSP failure | Check camera is online, verify network connectivity |
| `error_code="timeout"` (stream/screenshot) | Tool hit its hard timeout budget. Retry once with a larger `timeout_seconds` (max 120); if still failing, check device online status |
| `stream busy` (another stream operation already in progress) | Global stream slot occupied (screenshot/stream-probe/recording establishment are serialized). Wait a few seconds and retry |
| `recording in progress` (screenshot rejected on the same camera) | Camera is recording; stop recording (`toggle_recording` action=stop) before screenshotting the same camera |
| `storage full` | Suggest cleanup via `manage_storage_status()` or change storage policy |
| `MCP tools not available` | Follow [Installation](#installation) steps and check MCP registration + startup stderr (see [MCP-Only Interaction](#mcp-only-interaction-hard-rule)); do not assume a lock conflict or write workaround scripts |
| `协议库准备失败` / startup exit code 1 with preparation error | Report the stderr reason and resolve the environment, network, version, or file-access issue before restarting; do not attempt camera tools |
| `DEVICE_UNREACHABLE` (from private protocol / SK HTTP, on illumination / image / tracking tools, ONVIF connection healthy) | **Bounded auto-retry, no user confirmation needed:** retry the same call with unchanged parameters after 2-3 seconds, up to 3 attempts. Transient private-protocol port flapping; do not reconnect or rediscover. Report only after all retries fail |
| `exit code 71` / instance lock conflict | Another session holds the camera, or a stale lock. Auto-recovery usually handles this; if not → see Gotchas (instance-lock conflict recovery) |

## Conditional Loading Index

Load a reference **only when its trigger fires** — do not pre-read.

| Trigger | Read |
|---------|------|
| Auth flow details beyond the Decision Table (cloud auth internals, direct_connect) | [references/WORKFLOW.md — Phase 2](references/WORKFLOW.md#phase-2--connect--authorize-detailed-tool-calls) |
| Building an external consumer on the event store | [references/EVENT_INTEGRATION.md](references/EVENT_INTEGRATION.md) |
| config.yaml full schema or example configs | [references/CONFIG.md](references/CONFIG.md) |
| Per-tool parameter signatures, return fields, safety constraints | [references/commands/](references/commands/) — device_mgmt · discovery · stream · ptz · events · illumination · image_settings · tracking |

## Configuration

Camera configurations are saved in `config.yaml` (skill root). Credentials auto-persist after first successful connection; sensitive fields (`password` / `sn_code` / `sn` / `pkdk`) are stored obfuscated (never plaintext on disk) and restored in memory only at the point of use. When config.yaml full schema or example configs are needed → [references/CONFIG.md](references/CONFIG.md).

