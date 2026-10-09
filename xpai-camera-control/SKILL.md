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

`scripts/mcp_server.py` runs as an MCP server using **stdio transport only**. It is **not** a network service — no port is opened and there is no `localhost` URL to connect to. Instead, the MCP client (Claude Desktop, etc.) **launches the script as a child process** (via the config below) and exchanges JSON-RPC messages over the process's stdin/stdout. The Agent interacts with all camera control tools exclusively through this stdio channel; per-session connection state lives in the memory of that child process.

## Installation

If `xpai-camera-control` tools are not present in the available tool set, follow these steps:

**Step 1 — Determine SKILL_ROOT:** the absolute path of the directory containing this SKILL.md, or run:
```bash
python -c "from scripts._paths import get_skill_root; print(get_skill_root())"
```

**Step 2 — Install dependencies:** use the same 64-bit Python interpreter configured for the MCP server:
```bash
pip install -r <SKILL_ROOT>/requirements.txt
```

**Step 3 — Write MCP config:** append the following JSON to the host's MCP config file (replace `<SKILL_ROOT>` with the actual path from Step 1):
```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "python",
      "args": ["scripts/mcp_server.py"],
      "cwd": "<SKILL_ROOT>"
    }
  }
}
```
Common config locations:
- Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json` (Win) / `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
- Cursor: Settings → MCP → Add Server
- Cline: `.cline/mcp_settings.json`

**Native runtime preparation:** the skill ships without native libraries. After acquiring the single-instance lock and starting its lease heartbeat, `mcp_server.py` calls `prepare_runtime.py` before restoring event monitors or starting the MCP transport. Preparation uses the reviewed local `scripts/runtime_artifacts.json` shipped with this skill to select a pinned wheel and resource hashes. It installs from the fixed PyPI index only when the package is missing, using the current interpreter's isolated pip, binary-only installation, no dependencies, and a required wheel SHA256. After validating installed resource paths and hashes, it stages and atomically replaces only the selected native library and `cacert.pem` in `scripts/toolkit/`. An already installed package is checked by version and resource hashes; this does not verify the original wheel archive. If preparation fails, the server writes the error to stderr and exits with a nonzero status; it does not start serving tools. Installation output also goes to stderr, never to the JSON-RPC stdout channel.

The wheel is used only as a native-resource carrier, not as a Python API dependency. This skill retains its own `ctypes` bindings in `scripts/toolkit/camera_proto.py`, including the `2.0.0` ABI check and native string release. Preparation/loading code selects `camera_proto.dll` on Windows x64, `camera_proto.so` on Linux glibc x64, and `camera_proto.dylib` on macOS Intel/ARM64 according to the 64-bit interpreter architecture. Linux ARM, musl/Alpine, Windows ARM interpreters, 32-bit interpreters, and unknown combinations are not supported.

**Current artifact boundary:** the default manifest still pins the existing production `camera-proto==0.1.0` Windows x64 wheel and its original verified hashes. No four-platform `0.2.0` artifact set has been built or released for this integration. Linux and macOS therefore fail before pip with an explicit missing-verified-artifact message; cross-platform code support is not a claim that those artifacts are ready.

To enable a future release, maintainers must review the pipeline's manifest against the final wheels from the same build batch, then ship that complete local manifest with the skill. Its `package`, `version`, `environment`, and `platforms` records must agree; supported keys are `win_amd64`, `linux_x86_64`, `macos_x86_64`, and `macos_arm64`. Each record pins `wheel_filename`, `wheel_sha256`, `library`, and exactly the native library and `cacert.pem` hashes under `resources`. Linux wheels require matching manylinux x64 tags, and macOS wheels require matching architecture tags and deployment targets. Preparation checks the host glibc/macOS version against those tags before accepting cached or installed resources; unknown or insufficient versions fail before pip or copying. The runtime never downloads a trusted manifest or trusts hashes reported by the installed package. Missing or invalid records fail closed, even if old local files exist. A new manifest's hashes, not the presence of a previous cache, determine readiness.

Production manifests use release versions (`x.y.z`). Testing requires a separate skill directory and virtual environment with a reviewed local `environment=test` manifest pinned to an isolated development version (`x.y.z.devN`); changing that field alone does not change a library's compiled environment. There is no runtime cloud-domain switch, alternate download endpoint, or automatic environment fallback. Test wheels not published on the fixed PyPI index must be provisioned separately in that isolated environment from the reviewed wheel; preparation does not add a test download source.

Initial wheel installation requires network access; startup with local files matching the selected manifest works offline without running pip. Preparation does not upgrade or downgrade an existing different package version: use a dedicated virtual environment for this skill if versions conflict. Camera tool calls and the library loader never run pip automatically.

If the first download exceeds the MCP client's startup timeout, run `python scripts/prepare_runtime.py` manually with the same interpreter, then restart the MCP server after preparation succeeds. This optional pre-install step does not access cameras.

## MCP-Only Interaction (Hard Rule)

All camera operations **MUST** go through the MCP tools exposed by `scripts/mcp_server.py`:

- If the `xpai-camera-control` tools are **not present** in your available tool set, do NOT fall back to scripting. Follow the [Installation](#installation) steps first, then call the tools. If server startup fails (e.g. a protocol preparation error on stderr), report the stderr reason and resolve it before retrying — the preparation script only installs dependencies and does not access cameras.
- **NEVER** import `scripts.toolkit` (or any module inside this package) directly, and **NEVER** write standalone scripts that re-implement or wrap tool functionality.
- Rationale: direct imports bypass the security constraints of this skill (explicit user confirmation, parameter validation) and the in-memory connection state held by the MCP server process — scripted calls in a separate process will silently violate both.

## Single-Instance Limitation

The MCP server is **stateful and single-instance**: camera connections and RTSP sessions live in one server process's memory, and the instance lock (port bind + lease heartbeat + watchdog, see Gotchas) allows only one running instance at a time. This is by design — concurrent instances would fight for the device's RTSP session slots and hang the camera.

**Agent instruction:** before starting camera work (or the first time camera tools are invoked in a session), proactively tell the user in plain language:

> The camera feature has a usage limitation: only one session can "take over" the camera at a time (the connection state is stored in a single background service). If another session is currently using the camera, the camera tools in this session may become unavailable or fail when called — this is not a malfunction. Please end or close the camera task in the other session first, then ask me to retry.

If startup fails with an instance-lock conflict (exit code 71), do NOT silently retry — tell the user about the conflict and ask them to close any other session's camera work first. Missing tools alone do not establish a lock conflict: check registration and startup stderr. If protocol preparation failed, report that error instead and stop until it is resolved.

## Core Workflow

### Phase 0 — Session Init (must be done at the very beginning of the session)

At the beginning of each session, check if there are any registered cameras in config.yaml:

1. Call `get_registered_cameras()` to read the camera configurations (including credentials) saved in config.yaml
2. For each registered camera, call `connect_device(cam.name)` — the tool will automatically use the credentials in config.yaml to connect, **no need for the user to input a password again**
   - Cached credentials are verified via TCP/ONVIF/RTSP three-channel check (password must pass RTSP auth). Retried up to 3 times on failure; if all attempts fail, the tool **automatically attempts cloud re-authorization** to fetch a fresh password; cloud also fails → registration auto-removed from config.yaml → `status="needs_password"`
   - **If this is the first camera work after a long idle period (hours/days), or a call on a previously working camera fails, call `search_devices()` first** — a camera's IP can change while idle (DHCP lease renewal) and the cached IP in config.yaml goes stale. `search_devices()` re-registers reachable cameras with their current IP and removes cameras that are gone; then retry the connection. Never retry repeatedly against a stale cached IP.
3. If config.yaml is empty or all registered cameras fail to connect → enter Phase 1

### Phase 1 — Discover Cameras

When Phase 0 cache is unavailable, call `search_devices()` to discover cameras on the local network. The tool **automatically selects the best discovery protocol** — the Agent does not need to choose:

- The tool tries all available methods internally
- Results are returned as a unified `DiscoveredDevice` list — XPAI-specific metadata (SN, channels, MAC, etc.) is included under `sky_*` prefixed fields when available
- Each result includes a `discovery_method` field indicating which protocol found the device
- Each result carries a `protocol_type`: **`S`** (device answered SK private discovery — conclusive, full feature set) or **empty** (found via JCP/WS-Discovery only; no class is asserted, see capability matrix below). `connect_device` resolves and persists the final class (`S`/`J`/`O`) via an authoritative SK-first unicast probe — a JCP answer alone proves nothing, since JCP discovery is shared by both S- and J-class firmware. **`O`** (third-party ONVIF-only) is asserted only at connect time: a WS-Discovery device that never answers SK/JCP but passes the ONVIF admission probe (port probe + `GetDeviceInformation`) connects in degraded mode (see capability matrix)
- **Search also syncs config.yaml**: every discovered camera that is reachable is written into config.yaml with its basic info (name, IP, SN, device class, ports — never a password), and registered cameras that are no longer discoverable **and** whose IP no longer responds are removed. Re-running `search_devices()` is therefore the supported way to refresh the registry after an IP change, a newly added camera, or a camera that left the network.

**Camera Naming:** When multiple cameras are found, list them (IP, model, SN) and assign a friendly name to each. Two naming strategies are available:

1. **User-provided names** — Ask the user to name each camera (e.g. "front door", "parking lot").
2. **Auto-naming by multimodal model** — Capture a screenshot from each camera via `capture_video_screenshot()`, then analyze the image content to generate a descriptive name that reflects the scene (e.g. "entrance hallway", "backyard", "loading dock"). Present the generated names to the user for confirmation before saving.

If the user already provides names, use strategy 1. Otherwise, default to strategy 2 (auto-naming). Pass the chosen name as `name` to `connect_device()` / `register_camera()`. `register_camera` matches by name → IP → SN, so calling with a new name + same IP renames in-place.

### Phase 2 — Connect & Authorize

Call `connect_device()` for each camera. The tool handles auth internally (cloud authorization, cached credentials, direct connect). **Agent only reacts to the returned `status`** — see [Decision Table](#decision-table--error--status--action) for mapping.

### Phase 3 — Stream & Capture

After a successful connection, perform streaming operations:
- `capture_video_screenshot()` — captures a single frame from the RTSP stream and saves it as JPEG (uses OpenCV, auto-discards initial buffered frames for a clean capture)
- `get_audio_video_stream()` — retrieves the RTSP stream URL and validates stream availability, returns codec/resolution/fps metadata
- `toggle_recording()` — starts/stops local MP4 recording from the RTSP stream via ffmpeg remux (`-c:v copy`)
- `manage_storage_status()` — queries disk usage and configures storage path/format/policy
- `start_webrtc_stream()` / `stop_webrtc_stream()` — converts RTSP to WebRTC for browser-based live preview, returns HTTP access URL

Screenshot files are saved to `snapshots/` directory by default; recordings go to `video/`.

**Result delivery (when user wants to "see" a camera):**
After capturing a screenshot and fetching the stream URL, the Agent **MUST** deliver both results to the user:
1. **Show the screenshot** — display the image from `file_path` to the user (e.g. via markdown image syntax `![screenshot](file_path)`)
2. **Provide the RTSP URL** — output the `stream_url` from `get_audio_video_stream()` so the user can open it in a media player (VLC, ffplay, PotPlayer, etc.) for live viewing
3. **Or start WebRTC preview** — call `start_webrtc_stream()` for browser-based live viewing when the user prefers a visual player over a raw RTSP URL

### Phase 4 — PTZ Control

PTZ backend is chosen by `protocol_type`. **SK-class** cameras use the XPAI private protocol (vendor command via TCP channel). **J-class and O-class** cameras use **ONVIF only** (`ContinuousMove` / `Stop` / `GetStatus` on the ONVIF PTZ service) — no private-protocol fallback.

| Capability                          | Tools | SK-class | J-class | O-class |
|-------------------------------------|-------|----------|---------|---------|
| Directional movement (4 directions) | `control_ptz` | private protocol | ONVIF | ONVIF |
| Get position & ranges               | `get_ptz_parameters` | private protocol | ONVIF | ONVIF |
| Stop all movement                   | `stop_ptz` | private protocol | ONVIF | ONVIF |
| Physical calibration                | `calibrate_ptz` | private protocol | **not supported** (returns a clear message) | **not supported** |

`control_ptz` auto-stops after `duration_seconds` (default 1s). Direction parameter supports both English (`up`/`down`/`left`/`right`) and Chinese aliases (上/下/左/右).

**J/O-class limits:** the ONVIF backend moves by normalized velocity vectors over `duration_seconds`, so **`degrees` mode is not supported** (the tool returns a message asking the user to use `duration_seconds` instead) and there is **no calibration** (`calibrate_ptz` returns an explicit unsupported message). Diagonal directions are sent as a single composite (x, y) velocity vector.

**Physical Limit Guard:** `control_ptz` validates the command against the PTZ's actual physical travel range at the tool layer — the agent does not need to pre-validate durations. If the head is already at the limit, the command is intercepted before being sent; if the limit is reached mid-movement (e.g. "turn right 5s" but only 3s of travel remains), the tool stops early and replaces the request with the feasible movement. In both cases the result carries `degraded=True` and a human-readable `degrade_reason`. **The Agent MUST explicitly relay `degrade_reason` to the user whenever `degraded=True`** — never report a degraded move as if it completed as requested.

**PTZ Movement Estimation:** The SDK does not report absolute PTZ angles. To estimate how far the view has shifted after a rotation, the Agent should capture a screenshot before and after the movement, compare the two frames visually, and report the estimated shift as a percentage of the frame width/height to the user. This is best-effort — in featureless scenes (blank walls, sky) the estimate may be unreliable; say so when it is.

If PTZ detailed sequences, degrees mode, or calibration (`calibrate_ptz` set_home/go_home) are needed → [WORKFLOW.md — Phase 4](references/WORKFLOW.md#phase-4--ptz-control-detailed-tool-calls).

## Extended Capabilities

Available when the user explicitly requests them (all require camera connected):

| Tool | Actions | Reference |
|------|---------|----------|
| `manage_camera_events` | Alarm events (motion/human/vehicle/tamper/…, with linked snapshots): `start`/`stop`/`poll`/`wait` | [events.md](references/commands/events.md) |
| `manage_illumination` | Illumination (daynight mode + fill light mode, integer value or string alias): `get`/`set` | [illumination.md](references/commands/illumination.md) |
| `manage_image_settings` | Image params (brightness/contrast/saturation/sharpness/flip): `get`/`set` | [image_settings.md](references/commands/image_settings.md) |
| `query_tracking_capabilities` / `set_tracking` | Detection & tracking query/config (human/vehicle/area/motion/line-crossing) | [tracking.md](references/commands/tracking.md) |

> `manage_camera_events(action="start")` spawns a background listener thread; `manage_illumination(action="set")` and `set_tracking` modify hardware settings — all require **explicit user confirmation** before calling. Cloud authorization is handled internally by `connect_device` (blocking call, may wait for user confirmation on APP).

> **J/O-class not supported:** all four extended capabilities above (`manage_camera_events`, `manage_illumination`, `manage_image_settings`, `query_tracking_capabilities` / `set_tracking`) rely on the Skyworth private protocol and are **not available on J-class or O-class cameras**. Calling them on a J/O-class device returns immediately with `error_code="UNSUPPORTED_PROTOCOL"` and a clear reason — it is not a malfunction or timeout.

### Protocol Capability Matrix

| Capability | SK-class (`S`) | JCP-class (`J`) | ONVIF-only (`O`) |
|-----------|:-------------:|:--------------:|:----------------:|
| Discovery | ✅ SK private | ✅ JCP (UDP multicast + broadcast) | ✅ WS-Discovery |
| Connect / cloud authorization | ✅ | ✅ | ⚠️ password only — **no cloud authorization** (no SK/JCP SN) |
| Streaming / screenshot / recording / WebRTC | ✅ RTSP | ✅ RTSP (ONVIF-authoritative paths) | ✅ RTSP (ONVIF-authoritative paths) |
| PTZ move / stop / status | ✅ private | ✅ ONVIF | ✅ ONVIF |
| PTZ `degrees` mode | ✅ | ❌ use `duration_seconds` | ❌ use `duration_seconds` |
| PTZ calibration (`calibrate_ptz`) | ✅ | ❌ | ❌ |
| Illumination / image settings | ✅ | ❌ | ❌ |
| Detection & tracking | ✅ | ❌ | ❌ |
| Alarm event monitoring | ✅ | ❌ | ❌ |

**O-class admission:** a WS-Discovery device that never answers SK/JCP discovery is admitted to the connected state only when the ONVIF admission probe passes (ONVIF port probe + authenticated `GetDeviceInformation`); its ONVIF SerialNumber is persisted as `onvif_sn` (identity/matching only — **never** fed to cloud auth or SK HTTP as `sn_code`). Devices that are RTSP-reachable but fail ONVIF admission are rejected with `status="no_sn"` and an explicit message; this rejection is final — do not retry with workarounds.

## Toolkit Modules

8 modules exposed as MCP tools via `scripts/mcp_server.py`. For per-tool parameter signatures, return fields, and safety constraints: [commands/](references/commands/) — [device_mgmt.md](references/commands/device_mgmt.md) · [stream.md](references/commands/stream.md) · [ptz.md](references/commands/ptz.md) · [events.md](references/commands/events.md) · [illumination.md](references/commands/illumination.md) · [image_settings.md](references/commands/image_settings.md) · [tracking.md](references/commands/tracking.md).

| Module | Key Functions | Reference |
|--------|--------------|----------|
| `device_mgmt` | `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device` | [commands/device_mgmt.md](references/commands/device_mgmt.md) |
| `stream` | `capture_video_screenshot`, `get_audio_video_stream`, `toggle_recording`, `manage_storage_status`, `start_webrtc_stream`, `stop_webrtc_stream` | [commands/stream.md](references/commands/stream.md) |
| `ptz` | `control_ptz`, `get_ptz_parameters`, `calibrate_ptz`, `stop_ptz` | [commands/ptz.md](references/commands/ptz.md) |
| `events` | `manage_camera_events` (action: `start` / `stop` / `poll` / `wait`) | [commands/events.md](references/commands/events.md) |
| `illumination` | `manage_illumination` (action: `get` / `set`) | [commands/illumination.md](references/commands/illumination.md) |
| `image_settings` | `manage_image_settings` (action: `get` / `set`) | [commands/image_settings.md](references/commands/image_settings.md) |
| `tracking` | `query_tracking_capabilities`, `set_tracking` | [commands/tracking.md](references/commands/tracking.md) |

## Security Constraints

| Constraint | Rule |
|------------|------|
| **Explicit Prompt** | Inform user and wait for confirmation before: PTZ, streaming, screenshots, event monitor start, illumination/image/tracking changes |
| **Code Validation** | Tool-layer validation for: recording, storage configuration |
| **Background Thread** | Event listeners start **only** after `events(action="start")`; auto-resume only re-arms previously-enabled listeners |

## Gotchas

- **TCP port flaps (DEVICE_UNREACHABLE)** → for illumination/image/tracking tools, retry up to 3× at 2-3s intervals; do not reconnect. Report only after all retries fail.
- **Never hardcode ONVIF port 80** → always use `onvif_port` from `search_devices()` / config.yaml.
- **Never manually construct RTSP URLs** → always use `stream_url` from `get_audio_video_stream()` (credentials auto-injected).
- **Chinese characters in Windows paths cause `cv2.imwrite()` to silently fail** → no manual workaround needed (the toolkit handles it internally); if you pass a custom `save_path`, prefer ASCII-only paths.
- **Connection state is in-memory only** → on `success=false` with connection error, call `connect_device()` first, then retry.
- **Fixed-duration recording** → always use `toggle_recording(action="start", duration=<seconds>)`. Never implement agent-side sleep → stop.
- **Zombie lock: MCP tools all unavailable, stderr shows instance lock conflict.** → The server uses a three-layer defense (stdio watchdog + lease heartbeat + triple-verification recovery) to auto-recover stale locks. If auto-recovery fails (exit code 71), manually recover:
  ```
  netstat -ano | findstr 49740
  Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" | Select CommandLine
  taskkill /PID <PID> /F
  ```
  Exit codes: `70` = watchdog self-cleanup (host abandoned instance); `71` = instance lock conflict (another live instance holds the lock, or manual intervention needed).
- **Orphaned MCP server process across sessions — the new session cannot connect.** Some Agent host architectures do not terminate the MCP server process when a session ends. The orphaned process stays alive and keeps its lease heartbeat fresh, so it legitimately holds the instance lock — lease-based auto-recovery only reclaims *expired* leases and never kills a live instance. → **Action:** find the original process's PID, kill it, then let the client start a new instance. Fastest: read the `pid` field from `.instance_lease.json` in the skill root (the heartbeat writes `pid`/`port`/`ts` every 5 s), or `netstat -ano | findstr 49740` (lock port is derived from the skill path). Verify the PID really belongs to this skill's `mcp_server.py` before killing (`Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" | Select CommandLine`), then `taskkill /PID <PID> /F /T`, and restart the session / MCP client so it spawns a fresh server. Caution: killing the PID breaks whatever session still owns it — confirm with the user that the previous session is truly gone first.
- **Pure-numeric passwords/SNs must be sent as JSON strings.** → when relaying a user-provided password or SN (e.g. `847226`) into any tool argument, quote it as a string (`"847226"`), never emit a bare JSON number. The MCP input schema accepts numbers and auto-stringifies them as a safety net, but string-first is the correct habit; a numeric value that survives as a number into YAML/config can later load back as an integer and break credential handling.

## Decision Table — error / status → action

This table is the **single runtime source of truth** for error handling. On any tool failure: analyze the error → apply the mapped action. Do NOT write workaround scripts or re-implement tool functionality. Report to the user what failed / why / how to fix, then wait for the user's decision — **except** the bounded auto-retry row below.

| `error_message` pattern / `status` | Agent Action |
|------------------------------------|--------------|
| `not_connected` / `device not found` | Call `connect_device()` first, then retry the failed operation. If it still fails — or this is the first operation after a long idle period — call `search_devices()` to refresh stale IPs in the registry, then retry |
| `needs_password` (status) | Cached credentials expired (cloud re-auth also failed), cloud service unreachable, or the device has no SN so cloud auth cannot start (incl. O-class third-party ONVIF) — ask user for password → `connect_device(camera_name, password=user_input)` |
| `no_sn` (status) | Connection refused: an S/J-asserted XPAI device lost its SN (retry after `search_devices()`), or a WS-Discovery device failed ONVIF admission (RTSP-only, no ONVIF control plane) — report to user; check ONVIF support/port or supply ONVIF credentials. **Forbidden workaround:** manual `register_camera` / hand-editing config.yaml to bypass the gate |
| `error_code="UNSUPPORTED_PROTOCOL"` | J/O-class camera asked for an SK-only capability (illumination / image settings / tracking / events) — inform user of the device-class limitation; not a malfunction or timeout |
| `auth_rejected` (status) | User denied cloud authorization — inform user, cannot connect |
| `cloud_pwd_failed` (status) | Cloud password doesn't match — device may have changed password, ask user for correct password |
| `cached credentials cleared` (in error_message) | Tool already attempted cloud re-authorization; prompt user for password → `connect_device(camera_name, password=user_input)` |
| `degraded=true` (PTZ result) | **MUST** relay `degrade_reason` to user verbatim |
| `limit_reached=true` | Stop sending PTZ commands in that direction — physical limit reached |
| `stream unavailable` / RTSP failure | Check camera is online, verify network connectivity |
| `error_code="timeout"` (stream/screenshot) | Tool hit its hard timeout budget. Retry once with a larger `timeout_seconds` (max 120); if still failing, check device online status |
| `stream busy` (another stream operation already in progress) | Global stream slot occupied (screenshot/stream-probe/recording establishment are serialized). Wait a few seconds and retry |
| `recording in progress` (screenshot rejected on the same camera) | Camera is recording; stop recording (`toggle_recording` action=stop) before screenshotting the same camera |
| `storage full` | Suggest cleanup via `manage_storage_status()` or change storage policy |
| `not support illumination` | Device doesn't support illumination mode control — inform user |
| `MCP tools not available` | Follow [Installation](#installation) steps and check MCP registration + startup stderr (see [MCP-Only Interaction](#mcp-only-interaction-hard-rule)); do not assume a lock conflict or write workaround scripts |
| `协议库准备失败` / startup exit code 1 with preparation error | Report the stderr reason and resolve the environment, network, version, or file-access issue before restarting; do not attempt camera tools |
| `DEVICE_UNREACHABLE` (from private protocol / SK HTTP, on illumination / image / tracking tools, ONVIF connection healthy) | **Bounded auto-retry, no user confirmation needed:** retry the same call with unchanged parameters after 2-3 seconds, up to 3 attempts. Transient private-protocol port flapping; do not reconnect or rediscover. Report only after all retries fail |
| `exit code 71` / instance lock conflict | Another session holds the camera, or stale lock. Auto-recovery usually handles this; if not → see Gotchas (zombie lock / orphaned process) above |

## Conditional Loading Index

Load a reference **only when its trigger fires** — do not pre-read.

| Trigger | Read |
|---------|------|
| PTZ detailed sequences, degrees mode, calibration needed | [references/WORKFLOW.md — Phase 4](references/WORKFLOW.md#phase-4--ptz-control-detailed-tool-calls) |
| Auth flow details beyond the Decision Table (cloud auth internals, direct_connect) | [references/WORKFLOW.md — Phase 2](references/WORKFLOW.md#phase-2--connect--authorize-detailed-tool-calls) |
| Zombie lock / orphaned process recovery | Gotchas — zombie lock / orphaned MCP server process bullets above |
| Building an external consumer on the event store | [references/EVENT_INTEGRATION.md](references/EVENT_INTEGRATION.md) |
| config.yaml full schema or example configs | [references/CONFIG.md](references/CONFIG.md) |
| Per-tool parameter signatures, return fields, safety constraints | [references/commands/](references/commands/) — device_mgmt · discovery · stream · ptz · events · illumination · image_settings · tracking |

## Configuration

Camera configurations are saved in `config.yaml` (skill root). Credentials auto-persist after first successful connection. When config.yaml full schema or example configs are needed → [references/CONFIG.md](references/CONFIG.md).

## Limitations

- Cameras and host must be on the same LAN
- Password-required cameras: ask user for password → `connect_device(camera_name, password=user_input)`
- Screenshot/recording requires `opencv-python` (in requirements.txt)

