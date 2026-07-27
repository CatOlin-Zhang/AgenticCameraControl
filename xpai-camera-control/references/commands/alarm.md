# Alarm

Alarm sound and push notification configuration — `scripts/toolkit/alarm.py`

---

### `configure_alarm_settings(camera_name, sound_enabled=None, trigger_frequency=None, sensitivity=None) -> AlarmSettingsResult`

Configure alarm sound and trigger frequency.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation |
| **Returns** | `AlarmSettingsResult` (success, sound state, trigger frequency, sensitivity level) |
| **Parameters** | `sound_enabled`: enable/disable alarm sound. `trigger_frequency`: e.g. `"30s"`, `"1min"`, `"5min"`. `sensitivity`: 0–100. |
| **Implementation** | ONVIF Event Service / Skyworth private protocol |

### `configure_alarm_push(camera_name, push_type=None, time_range=None, enabled=None) -> AlarmPushResult`

Configure alarm push notification type and active time range.

| Aspect | Detail |
|--------|--------|
| **Safety** | Explicit Authorization + Explicit Prompt + Code Validation |
| **Returns** | `AlarmPushResult` (success, push type, time range, enabled state) |
| **Parameters** | `push_type`: `PushType.APP`, `PushType.EMAIL`, or `PushType.BOTH`. `time_range`: e.g. `"08:00-22:00"`. `enabled`: enable/disable push. |
