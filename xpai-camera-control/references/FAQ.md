# FAQ & Troubleshooting Index

> English reference for **Agent self-healing** and English-speaking users · Chinese version (manual self-service): [FAQ.zh-CN.md](FAQ.zh-CN.md) · **Keep both files in sync when editing either one.**

**Self-healing posture:** this system is Agent-readable by design — on failure, the Agent diagnoses and recovers **by itself**, guided by the [SKILL.md Decision Table](../SKILL.md#decision-table--error--status--action) first and this FAQ second. Manual troubleshooting (below, and the Chinese version) is a fallback for users who explicitly want to fix things themselves.

## FAQ

### Install & Startup

**Q: `pip install -r requirements.txt` is slow or fails.**
A: Use a 64-bit Python 3.10+ interpreter. If PyPI is slow in your region, install the Python dependencies through a local mirror (`pip install -r requirements.txt -i <mirror-url>`). Native libraries are different: their download source and SHA256 hashes are pinned in `scripts/runtime_artifacts.json` (supply-chain protection) and cannot be switched to a mirror — if that download times out, see the next entry.

**Q: First startup takes forever / MCP tools never appear (download timeout).**
A: The first start downloads pinned native resources via `prepare_runtime.py`. If it exceeds the host's startup timeout, run `python scripts/prepare_runtime.py` manually with the same interpreter, then restart the MCP server. Once local files match the manifest, startup works offline.

**Q: Startup fails with "协议库准备失败" (native preparation error), exit code 1.**
A: Read the stderr reason (network / version / file access), fix the environment, then restart. Do not call camera tools until startup succeeds.

**Q: The camera tools are not in my tool list at all.**
A: The MCP server is not registered. Follow the three-step [Installation](../SKILL.md#installation) in SKILL.md — never fall back to importing `scripts.toolkit` directly or writing wrapper scripts.

**Q: Server exits immediately; all tools unavailable; exit code 70 or 71.**
A: Exit 71 = instance-lock conflict: a previous session's server may still be alive. Read `pid` from `.instance_lease.json` in the skill root, verify the process belongs to this skill's `mcp_server.py`, confirm with the user that the old session is really finished, then `taskkill /PID <PID> /F /T` (Windows) or `kill -9` (macOS/Linux) and restart. Exit 70 = watchdog self-cleanup; restarting is enough. Details: [SKILL.md Gotchas](../SKILL.md#gotchas).

**Q: Tools fail because "another session is using the camera".**
A: By design only one session can hold the camera (single-instance server). Ask the user to finish the camera task in the other session first, then retry — not a malfunction.

### Discovery & Connection

**Q: `search_devices()` finds nothing.**
A: Check camera and host share the same LAN and the camera is online. Discovery auto-selects SK private / JCP / WS-Discovery — no protocol choice needed. USB webcams are not auto-discovered (manual `config.yaml` entry; no PTZ/device management).

**Q: A camera worked yesterday but fails today.**
A: Its IP likely changed (DHCP lease renewal) and config.yaml holds a stale IP. Call `search_devices()` once to refresh the registry, then retry. Never retry repeatedly against the cached IP.

**Q: The tool keeps asking for a password (`needs_password`).**
A: Cached credentials expired and cloud re-auth also failed, the cloud service is unreachable, or the device has no SN for cloud auth. Ask the user for the device password, then `connect_device(camera_name, password=user_input)`.

**Q: The cloud authorization prompt never gets confirmed.**
A: `connect_device` blocks waiting for confirmation in the vendor's mobile APP. Ask the user to confirm it there; the call then completes by itself.

**Q: Third-party ONVIF camera (O-class) — what works?**
A: Password connection only (no cloud auth, no SK/JCP SN). RTSP streaming and PTZ via ONVIF work; SK-private-only capabilities (events, illumination, image settings, tracking) return `UNSUPPORTED_PROTOCOL` — a device-class limitation, not a failure.

**Q: Connection refused with `no_sn`.**
A: Either an S/J-class device lost its SN (retry after `search_devices()`), or an RTSP-only device failed ONVIF admission — final, do not retry or bypass. Manually registering it or hand-editing config.yaml is forbidden.

### Stream · Screenshot · Recording

**Q: WebRTC preview is black or stutters.**
A: The browser likely lacks H265 WebRTC (e.g. Edge). Retry with `start_webrtc_stream(video_codec="h264")` — it switches the device encoder (briefly interrupting its RTSP sessions) and restarts the preview.

**Q: go2rtc is not detected.**
A: go2rtc is not bundled. Download the platform binary from the go2rtc GitHub Releases (author AlexxIT; zip archive on Windows), place it in the skill root or on `PATH`, then retry `start_webrtc_stream()`. Details: [SKILL.md Phase 3](../SKILL.md#phase-3--stream--capture).

**Q: Where are screenshots/recordings saved?**
A: `snapshots/` and `video/` (events in `events/`). If you pass a custom `save_path`, use ASCII-only paths — Chinese characters in Windows paths make `cv2.imwrite()` fail silently.

**Q: Recording never stops.**
A: Always start with `toggle_recording(action="start", duration=<seconds>)`; the server auto-stops when time is up. Agent-side "sleep then stop" buries the stop call and holds the camera's RTSP session indefinitely.

**Q: `stream busy` or `error_code="timeout"`.**
A: Busy: the global stream slot is occupied — wait a few seconds and retry. Timeout: retry once with a larger `timeout_seconds` (max 120); if it still fails, check the device is online.

### PTZ · Events · Data

**Q: PTZ result shows `degraded=true` or `limit_reached=true`.**
A: Physical-limit guard. Relay `degrade_reason` to the user verbatim (never report a degraded move as completed); on `limit_reached`, stop sending commands in that direction.

**Q: PTZ `degrees` mode / calibration unsupported.**
A: The J/O-class ONVIF backend supports velocity + duration only. Use `duration_seconds`; `calibrate_ptz` is S-class only.

**Q: No events / no illumination / no image settings / no tracking.**
A: These are S-class-only capabilities. J/O-class returns `UNSUPPORTED_PROTOCOL` with a reason — inform the user of the device-class limitation; not a malfunction or timeout.

**Q: The event listener receives nothing.**
A: Events require an S-class camera and `manage_camera_events(action="start")` with explicit user confirmation; auto-resume only re-arms listeners enabled before. Poll/wait semantics: [commands/events.md](commands/events.md).

**Q: `DEVICE_UNREACHABLE` on illumination/image/tracking.**
A: Transient private-protocol port flapping — bounded auto-retry: same parameters after 2-3 s, up to 3 attempts, no user confirmation needed. Do not reconnect or rediscover mid-retry.

**Q: Does my data leave the LAN? Are passwords stored in plaintext?**
A: Usage-phase traffic is LAN-only; the connection phase talks to the vendor cloud only to verify connection status. Files are written only to `config.yaml`, `snapshots/`, `video/`, `events/`. Credentials (`password`/`sn_code`/`sn`/`pkdk`) are stored obfuscated and restored in memory only at the point of use.

## Best Practices

1. Session start: `get_registered_cameras()` → `connect_device()` per camera; after a long idle period, `search_devices()` first (stale DHCP IPs).
2. Fixed-duration recording only via `duration=<seconds>` — never sleep-then-stop.
3. Custom save paths: ASCII only.
4. Pure-numeric passwords/SNs must be JSON strings (`"847226"`), never bare numbers.
5. Never hand-build RTSP URLs — use the `stream_url` returned by `get_audio_video_stream()`.
6. Never hardcode ONVIF port 80 — use `onvif_port` from `search_devices()` / config.yaml.
7. Get explicit user confirmation before PTZ, streaming, screenshots, event-monitor start, and illumination/image/tracking changes.
8. Finish camera work in other sessions before starting a new one (single-instance design).
9. O-class identity uses `onvif_sn` for matching only — never feed it to cloud auth or SK HTTP as `sn_code`.
10. Building an external consumer on the event store → [EVENT_INTEGRATION.md](EVENT_INTEGRATION.md).

## Troubleshooting Index

Symptom-first map to the authoritative source (this FAQ paraphrases; the sources win on conflict):

| Symptom | Quick fix | Authoritative source |
|---------|-----------|----------------------|
| Server exits at startup (exit 70/71) | Lock conflict / self-cleanup — see FAQ above | [SKILL.md Gotchas](../SKILL.md#gotchas) · README Troubleshooting |
| Native preparation failure (exit 1) | Fix environment per stderr, restart | [SKILL.md Installation](../SKILL.md#installation) · [RUNTIME.md](RUNTIME.md) |
| `not_connected` / `needs_password` / `no_sn` / auth-failure group | Reconnect / ask for password / final-refusal handling | [SKILL.md Decision Table](../SKILL.md#decision-table--error--status--action) · [WORKFLOW.md Phase 2](WORKFLOW.md) |
| `UNSUPPORTED_PROTOCOL` on events/illumination/image/tracking | Device-class limitation, inform user | [SKILL.md Capability Matrix](../SKILL.md#extended-capabilities--protocol-matrix) · `commands/*.md` |
| Stream / screenshot / recording errors (`timeout`, `busy`, `recording in progress`) | Retry rules per Decision Table | [SKILL.md Decision Table](../SKILL.md#decision-table--error--status--action) · [commands/stream.md](commands/stream.md) |
| PTZ `degraded` / `limit_reached` / J-O limits | Relay reason / stop direction / use duration | [SKILL.md Phase 4](../SKILL.md#phase-4--ptz-control) · [commands/ptz.md](commands/ptz.md) |
| `DEVICE_UNREACHABLE` (illumination/image/tracking) | Bounded auto-retry ×3 | [SKILL.md Decision Table](../SKILL.md#decision-table--error--status--action) · `## Error codes` in `commands/*.md` |
| Event store external consumption | Contract & schema | [EVENT_INTEGRATION.md](EVENT_INTEGRATION.md) · [commands/events.md](commands/events.md) |
| config.yaml schema / manual pre-configuration | Full schema | [CONFIG.md](CONFIG.md) |
