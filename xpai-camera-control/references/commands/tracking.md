# AI Tracking

AI-powered object tracking and zone monitoring — `scripts/toolkit/tracking.py`

---

### `track_vehicles(camera_name, action: TrackingAction = TrackingAction.START) -> TrackingResult`

Start or stop vehicle detection and tracking.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `TrackingResult` (success, is_tracking state, algorithm name) |
| **Parameters** | `action`: `TrackingAction.START` or `TrackingAction.STOP`. |
| **Implementation** | ONVIF Analytics / Skyworth private protocol |

### `track_human_shapes(camera_name, action: TrackingAction = TrackingAction.START) -> TrackingResult`

Start or stop human shape detection and tracking. PTZ head will auto-follow the target.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt + Code Validation |
| **Returns** | `TrackingResult` (success, is_tracking state, algorithm name) |
| **Parameters** | `action`: `TrackingAction.START` or `TrackingAction.STOP`. |
| **Implementation** | ONVIF Analytics / Skyworth private protocol |

### `monitor_zone_entry(camera_name, action: ZoneAction = ZoneAction.START, zone=None) -> ZoneMonitorResult`

Start or stop zone entry/exit detection.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Prompt |
| **Returns** | `ZoneMonitorResult` (success, is_monitoring state, zone_triggered state, trigger_type) |
| **Parameters** | `action`: `ZoneAction.START` or `ZoneAction.STOP`. `zone`: dict of zone name to vertex coordinates, e.g. `{"大门": [(100,200), (300,200), (300,400), (100,400)]}`. |
| **Implementation** | ONVIF Analytics RuleEngine / private protocol |

### `stop_tracking_service(camera_name) -> StopTrackingResult` _(not yet exposed as MCP tool)_

Stop all currently running tracking services.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | `StopTrackingResult` (success, list of stopped service names) |
