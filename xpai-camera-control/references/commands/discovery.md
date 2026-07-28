# Skyworth Discovery

Skyworth private protocol discovery and TCP channel — `scripts/toolkit/discovery.py`

> **MCP-only:** All tools below are invoked exclusively through the MCP server (`scripts/mcp_server.py`). Never import this module directly or write standalone scripts to call these functions.

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

Internal function used by `ptz.py` and `device_mgmt.py` for private protocol communication over TCP channel (HTTP + Basic Auth). Not available as an MCP tool — all private protocol operations are encapsulated in higher-level tools (`connect_device`, `control_ptz`, `calibrate_ptz`, etc.). Do not call it directly; use the higher-level MCP tools instead.

### `SkyDiscoveryListener(interval: float = 30.0, timeout: float = 5.0, bind_port: int = 9028, on_found=None)` _(not yet exposed as MCP tool)_

Background discovery listener that periodically searches for Skyworth devices.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Parameters** | `interval`: seconds between search rounds. `timeout`: per-round listen duration. `bind_port`: UDP receive port. `on_found`: optional callback. |
| **Methods** | `start()`, `stop()`, `get_devices()` |
| **Callback** | `on_found` receives a single `SkDiscoveredDevice` argument for each newly discovered device |
