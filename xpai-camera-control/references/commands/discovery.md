# Skyworth Discovery

Skyworth private protocol discovery and TCP channel — `scripts/toolkit/discovery.py`

---

### `discover_sky_devices(timeout: float = 5.0, target_sn="", bind_port: int = 9028, use_broadcast: bool = True, use_multicast: bool = True) -> List[SkDiscoveredDevice]`

Discover Skyworth cameras via private UDP protocol (SK_DISCOVERY_SEARCH).

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | List of `SkDiscoveredDevice` objects (ip, sn, device_type, subtype, manufacturer, model, channels, rtsp_port, web_port, mac, etc.) |
| **Parameters** | `timeout`: listen duration in seconds. `target_sn`: filter by specific SN (empty = all). `bind_port`: UDP receive port (default 9028 for tool). `use_broadcast`/`use_multicast`: enable broadcast/multicast sending. |
| **Implementation** | UDP broadcast + multicast to `239.230.236.230:9008` → listen for SK_DISCOVERY_SEARCH_R on port 9028 |

### `send_tcp_command(ip, command: dict, ...) -> dict` _(internal, not exposed as MCP tool)_

Internal function used by `ptz.py` and `device_mgmt.py` for private protocol communication over TCP channel (HTTP + Basic Auth). Not available as an MCP tool — all private protocol operations are encapsulated in higher-level tools (`connect_device`, `control_ptz`, `calibrate_ptz`, etc.).

二次开发者可通过 `from scripts.toolkit.discovery import send_tcp_command` 直接调用。

### `SkyDiscoveryListener(callback, interval: float = 30.0)` _(not yet exposed as MCP tool)_

Background discovery listener that periodically searches for Skyworth devices.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Methods** | `start()`, `stop()`, `get_devices()` |
| **Callback** | Receives a single `SkDiscoveredDevice` argument for each newly discovered device |
