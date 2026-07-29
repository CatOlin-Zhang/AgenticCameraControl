## Roadmap: Guardian Mode (Foundation implemented — tiers pending)

> ✅ **Status: Foundation (skill-side) implemented.** Event receiving is exposed as a **single MCP tool** `manage_camera_events(action=start|stop|poll|wait)` (merged from the original four tools to reduce MCP schema load), with dual-protocol listening, on-disk event store, and dedup. Remaining items below are unchecked. Tiered guardian modes are agent-side runtime behavior (no further skill code needed for T1–T3).

Goal: when the camera detects an alarm/event (motion, tamper, line-crossing…), the system captures a snapshot at the moment of the event and the Agent proactively reports it to the user — a "smart guardian" experience. The achievable level depends on **host (MCP client) capabilities**, so the design is tiered: the skill-side foundation is built once, and higher tiers unlock automatically as the host provides scheduling/trigger mechanisms.

**Local-first principle:** all received events and snapshots are persisted **locally on disk**; the on-disk event store is the single source of truth. Any outbound push (e.g. the WeChat alert leg) is an optional, consent-gated extra on top of the local store — never a replacement for it.

### Foundation (skill-side, host-independent)

- [x] **Verify camera event capability (dual-protocol)** — *implemented as runtime probing in `manage_camera_events(action="start")`*: ONVIF Event Service tried first (`CreatePullPointSubscription`, port auto-probed, Skyworth = 2000); Skyworth private alarm channel as fallback — **corrected by vendor doc §5.24: private alarms are pushed over the RTSP channel (not TCP 9010)**, alarm JSON `{"serv":"alarm","alm":"MD|HD|VGR|VGL|VS|VD|HTD|LTD",...}`; per-camera protocol recording in config.yaml still TODO
- [x] **`toolkit/events.py`** — dual-protocol event listener (ONVIF PullPoint + private RTSP-channel alarm push) running as a background thread inside the MCP server process; on event arrival it applies debounce, immediately calls the internal snapshot function (same-process, no Agent involvement), then persists the event to the on-disk store
- [x] **On-disk event store (single source of truth)** — raw protocol messages are converted by a processing layer in the receive path and appended to `events/camera_events.txt` as schema 1.0 JSON lines `{schema_version, event_id, event_type, camera_id, camera_name, timestamp, severity, title, message, label, confidence, snapshot_path, tags}`; per-camera consumer cursor in `events/events_cursor.json`; snapshots go to `snapshots/`. All received messages and images stay local
- [x] **Snapshot debounce / rate limit** — per-camera dedup by `(camera, normalized topic)` within the debounce window (default 5 s, also collapses cross-protocol duplicates); snapshot capture rate-limited to one per camera per window
- [x] **New MCP tool (single entry):** `manage_camera_events(action, ...)` — one registered tool, `action` switches the working mode (the per-mode functions remain exported for secondary development but are not registered):
  - [x] `action="start"` (`camera_name`, `protocols`, `debounce_seconds`) / `action="stop"` (`camera_name`) — user-controlled on/off switch for the background listener
  - [x] `action="poll"` (`camera_name?`, `limit`) — returns unconsumed events + snapshot paths, advances persisted cursor; reads the on-disk store
  - [x] `action="wait"` (`camera_name?`, `timeout_seconds=60`) — long-poll blocking mode, default/cap 60 s, Agent loops the call
- [x] **Monitor intent persistence & auto-resume** — fixes the WorkBuddy-reported bug where the host recycling the MCP process silently killed listener threads (`monitors: {}`): `start` persists the monitoring intent to `events/monitor_state.json`, `stop` clears it; `resume_persisted_monitors()` re-arms persisted-but-dead listeners on server startup (async daemon thread) and at every `poll`/`wait` entry, with a non-blocking mutex, 60 s per-camera retry cooldown, and an intent re-read before each start (concurrent `stop` cancels the resume). No new authorization surface — only listeners the user enabled and never stopped are restored
- [ ] **Snapshot & event retention** — wire `events/` and event snapshots into `manage_storage_status` policies (max age / max count cleanup) so the store never accumulates unbounded
- [ ] **Desktop notification fallback** — MCP server process raises a Windows toast on event (works even with no active Agent session; user opens a chat to get the full analysis)
- [x] **Revise [Security Constraints](#security-constraints)** — SKILL.md now states: *background threads only for per-camera event listeners, only after explicit user enablement via `manage_camera_events(action="start")`, behavior limited to alarm subscription plus writes into the `snapshots/` and `events/` whitelist paths*; off-LAN snapshot push authorization note still applies to the WeChat forwarder
- [x] **Docs sync** — `references/commands/events.md` done; WORKFLOW.md gained a Phase 5 event-monitoring section (start/stop, T1 poll, T2 wait loop) and ARCHITECTURE.md gained an Event Monitoring Architecture section (dual-protocol listener → schema 1.0 processing layer → on-disk store); README.md security boundary & module tables updated to include events

### Tiered Guardian Modes (agent-side, selected at runtime)

When the user first asks for monitoring ("帮我看着家里" / "watch the camera"), the Agent runs this capability-detection decision tree **once**, then applies the highest tier available:

| Tier | Host Capability Detected | Agent Behavior |
|------|--------------------------|----------------|
| **T1 — On-demand** | None (baseline, always works) | User asks → Agent calls `manage_camera_events(action="poll")` → reads snapshots → reports backlog |
| **T2 — In-session guard** | None (baseline, always works) | User says "watch" → Agent loops `manage_camera_events(action="wait")` (60 s polls) → on event: read snapshot, analyze, report immediately → continue loop until user stops or session ends |
| **T3 — Heartbeat guard** | Host exposes a schedule mechanism as an **agent-writable file** (e.g. heartbeat checklist) or a **scheduling tool** (cron / reminder tool in the Agent's tool list) | Agent registers a recurring task: "every N minutes call `manage_camera_events(action=\"poll\")`; if non-empty, analyze snapshots and notify the user; otherwise stay silent" — works across independent sessions because events are read from the on-disk store, not server memory |
| **T4 — Event-driven wake** | Host exposes a webhook / hook entry that spawns an Agent session | `toolkit/events.py` gains an outbound webhook POST on event → host wakes the Agent with the event payload as prompt → second-level proactive analysis with no session dependency |

**Capability detection order:** scheduling tool present in own tool list → agent-writable heartbeat/checklist file documented by host → host webhook/hook config → none found = T1/T2 only, and the Agent should tell the user what host capability would unlock T3/T4.

**Registration rules (hard):**
- Registering any persistent scheduled task (T3) or webhook (T4) **requires explicit user consent first**, and the Agent must tell the user how to cancel it
- The event listener thread and desktop notifications are off by default — they start only via `manage_camera_events(action="start")` after user confirmation
- Tier selection is by capability probing, never by hard-coding host product names

### External alert channel (outbound forwarder — outside the skill)

- An agent-hosted forwarder (in a **separate** skill or a separate module on the agent host) consumes `events/camera_events.txt` (schema 1.0 JSON lines) and the snapshot files **directly from disk** — no MCP dependency, no requirement that the MCP server process is alive
- The skill package itself does not implement, ship, or know about any particular forwarder — it only defines the on-disk event store as the **single public integration contract**. Forwarder integration details live in `xpai-camera-control/references/EVENT_INTEGRATION.md`
- **Alert, not analysis:** the forwarder leg only sends a short notification (e.g. "前门 09:30 检测到移动 + 附图"); deep analysis happens when the user opens a chat and the Agent reads the local snapshot
- **Consent-gated:** pushing snapshots outside the LAN means the image leaves the network — off by default, enabled only after explicit user authorization, and the user must be told how to disable it; the local store remains the authoritative copy regardless