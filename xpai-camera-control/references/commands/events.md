# IPC Event Receiving (Guardian Mode Foundation)

Alarm/event subscription, snapshot linkage, and on-disk event store — `scripts/toolkit/events.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

---

## Architecture

**Dual-protocol event sources** (same pattern as PTZ):

1. **ONVIF Event Service** — `CreatePullPointSubscription` + `PullMessages` long-poll loop (Skyworth ONVIF port is 2000, auto-probed if unknown). Only the *active* edge of boolean state items (`IsMotion=true`, `State=true`, …) is reported; clear edges are ignored.
2. **Skyworth private protocol** — alarm messages are pushed **over the RTSP channel** (vendor doc §5.24). The listener keeps an RTSP session open (DESCRIBE → SETUP → PLAY on the sub-stream, TCP interleaved) and scans the connection for alarm JSON:

```json
{"serv": "alarm", "alm": "MD", "date": "2023-06-16 08:08:08", "dir": 0,
 "fn": "c8138b2be056_MOTIONDETECT_1664361267.jpg", "fmt": "JPEG",
 "num": "3", "data": "SUBTYPE=SaloonCar;X=30;..."}
```

**`alm` codes → normalized topics** (shared namespace with ONVIF, prerequisite for cross-protocol dedup):

| `alm` | Topic | Meaning | | `alm` | Topic | Meaning |
|-------|-------|---------|-|-------|-------|---------|
| `MD` | `motion` | Motion detection | | `VS` | `tamper` | Tamper detection |
| `HD` | `human` | Human detection | | `VD` | `vehicle` | Vehicle detection |
| `VGR` | `region_intrusion` | Region intrusion | | `HTD` | `high_temp` | High temperature |
| `VGL` | `line_crossing` | Line crossing | | `LTD` | `low_temp` | Low temperature |

**Deduplication:** events with the same `(camera, normalized topic)` within the debounce window (default 5 s) are merged into one record — this also collapses cross-protocol duplicates (ONVIF and private protocol reporting the same motion burst). Snapshot capture is rate-limited per camera to one per window.

**On-disk event store:** after processing (raw protocol fields are dropped; a schema 1.0 JSON line is produced), the event is appended to `events/camera_events.txt`. The in-memory queue is only a hot cache; `poll` / `wait` always read the disk store, so backlog survives MCP server restarts and is readable from fresh sessions. **Schema, paths, write semantics, and the consumer contract** are defined in [references/EVENT_INTEGRATION.md](../EVENT_INTEGRATION.md) — read that file when writing any external consumer (other skills, forwarders, dashboards).

**Monitor intent persistence & auto-resume:** listener threads live inside the MCP server process and die when the host recycles it. To survive that, `start` persists the monitoring intent (protocols, debounce) to `events/monitor_state.json` and `stop` clears it. `resume_persisted_monitors()` re-arms listeners for cameras with a persisted intent but no running thread — called on server startup (async, non-blocking) and at every `poll` / `wait` entry. Failed cameras get a 60 s retry cooldown; a non-blocking mutex prevents concurrent double-resume; the intent is re-read before each start so a concurrent `stop` cancels the resume. No new authorization surface: only listeners the user enabled and never stopped are restored.

---

## `manage_camera_events(action, camera_name=None, protocols="both", debounce_seconds=5.0, limit=100, timeout_seconds=60, debug_mode="status")`

**The single MCP entry point for all event operations** — the `action` parameter switches the working mode (keeps the MCP schema footprint at one tool instead of four). Internally dispatches to `start_event_monitor` / `stop_event_monitor` / `get_pending_events` / `wait_for_events`, which remain exported for secondary development but are **not** registered as MCP tools.

| `action` | Mode | Returns | Relevant parameters |
|----------|------|---------|--------------------|
| `start` | Start the background listener | `EventMonitorResult` | `camera_name` (required), `protocols`, `debounce_seconds` |
| `stop` | Stop the listener | `EventMonitorResult` | `camera_name` (required) |
| `poll` | Read unconsumed events, advance cursor | `PendingEventsResult` | `camera_name` (optional filter), `limit` |
| `wait` | Long-poll block for new events | `PendingEventsResult` | `camera_name` (optional filter), `timeout_seconds` |
| `debug` | Toggle raw protocol packet dump | `dict` (enabled, dump_path, dump_size_bytes) | `debug_mode`: `"on"` / `"off"` / `"status"` (default) |

### `action="start"`

Start the background event listener for a camera. **Requires explicit user confirmation before calling** — this is the only action in the skill that spawns a background thread.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt — background thread starts only after user enablement; behavior limited to alarm subscription + writes into `snapshots/` and `events/` whitelist paths |
| **Returns** | `EventMonitorResult` (success, running, active_channels, error_message) |
| **Parameters** | `camera_name`: camera identifier (must be registered or connected). `protocols`: `"both"` (default) / `"onvif"` / `"private"`. `debounce_seconds`: dedup & snapshot rate-limit window. |
| **Implementation** | ONVIF: PullPoint subscription with auto-renew on expiry. Private: persistent RTSP session with OPTIONS keep-alive and exponential-backoff reconnect (cap 30 s). On event arrival the internal snapshot function is called in-process (no Agent involvement). On success the monitoring intent is persisted to `events/monitor_state.json` — if the MCP process is recycled, the listener auto-resumes on server startup or the next `poll` / `wait` call. |
| **Agent behavior** | `success=True` with partial `active_channels` (e.g. only `["private"]`) is normal — report which channels are active. If both channels fail, relay `error_message`. |

### `action="stop"`

Stop the listener, unsubscribe the ONVIF pull point, and close the RTSP alarm session. Also clears the persisted monitoring intent — the listener will **not** auto-resume after future process restarts.

| Aspect | Detail |
|--------|--------|
| **Safety** | No special constraints |
| **Returns** | `EventMonitorResult` (`running=False` after stop) |
| **Parameters** | `camera_name`: camera identifier. |

### `action="poll"`

Return unconsumed events (with snapshot paths) and advance the persisted per-camera cursor.

| Aspect | Detail |
|--------|--------|
| **Safety** | No special constraints (reads store + writes cursor file) |
| **Returns** | `PendingEventsResult` (events, remaining, monitors) |
| **Parameters** | `camera_name`: filter to one camera; omitting consumes all cameras' backlog. `limit`: max events per call. |
| **Agent behavior** | Works from a fresh session with a freshly started MCP server (reads the disk store; also auto-resumes any persisted-but-dead listeners). For each event, read the `snapshot_path` image, analyze, and report. `remaining > 0` means the backlog was truncated by `limit` — call again. |

### `action="wait"`

Long-poll blocking wait: returns immediately when an event arrives (and consumes it), or returns an empty list at timeout (`success=True` either way).

| Aspect | Detail |
|--------|--------|
| **Safety** | No special constraints |
| **Returns** | `PendingEventsResult` (events empty on timeout) |
| **Parameters** | `camera_name`: optional filter. `timeout_seconds`: default 60, **capped at 60** to stay under typical MCP client stdio tool timeouts. |
| **Agent behavior** | For continuous in-session guarding, loop this call — never expect a single long block. On each non-empty return: read snapshots, analyze, report, then continue the loop until the user stops. |

### `action="debug"`

Toggle the **raw protocol packet dump** — a diagnostic aid for when the schema 1.0 output is not enough to tell whether a suspicious `event_type` (e.g. everything arriving as the fallback `digitalinput`) is a topic-normalization gap or a protocol channel that is not working at all.

| Aspect | Detail |
|--------|--------|
| **Safety** | The dump is the **only** exception to the "raw protocol messages are never persisted" rule — debug only, turn it **off** when done. Content is the device's own reports (no credentials); writes stay inside the `events/` whitelist path. |
| **Returns** | `dict`: `success`, `enabled`, `dump_path`, `dump_exists`, `dump_size_bytes` |
| **Parameters** | `debug_mode`: `"on"` enable / `"off"` disable / `"status"` (default) query. |
| **Implementation** | The switch is a marker file `events/raw_debug.flag` (survives process recycling; auto-resumed listeners obey it too) — takes effect immediately, no listener restart needed. While enabled, both channels append to `events/raw_packets_debug.txt` (rotated to `.old.txt` past 5 MB): **onvif** — full PullMessages response containing events + a per-message parse verdict (`raw_topic` → `normalized_topic`, whether filtered as a clear edge); **private** — RTSP session lifecycle (DESCRIBE response / established / lost) + raw alarm JSON. |
| **Agent behavior** | Enable, reproduce the event, then read the dump file directly to diagnose. A dump with only `channel=onvif` entries and no `session-established` marker means the private channel never came up; a `raw_topic` that maps to an unexpected `normalized_topic` means a normalization rule is missing. Always run `debug_mode="off"` afterwards. |

