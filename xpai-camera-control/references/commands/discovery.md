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

### `send_tcp_command(ip, command: dict, username="admin", password="", timeout: float = 10.0, port: int = 9010) -> dict`

Send a JSON command to a Skyworth camera via TCP channel (HTTP protocol with Basic Auth).

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Returns** | Parsed JSON response dict |
| **Parameters** | `ip`: camera IP. `command`: JSON-serializable command dict (e.g. `{"cmd": "SK_DEVICE_GET_INFO"}`). `username`/`password`: Basic Auth credentials. `timeout`: socket timeout. `port`: TCP port (default 9010). |
| **Implementation** | `POST /xiaopaitech/device_service HTTP/1.1` with Basic Auth header + JSON body |

### `SkyDiscoveryListener(callback, interval: float = 30.0)` _(not yet exposed as MCP tool)_

Background discovery listener that periodically searches for Skyworth devices.

| Aspect | Detail |
|--------|--------|
| **Safety** | None |
| **Methods** | `start()`, `stop()`, `get_devices()` |
| **Callback** | Receives a single `SkDiscoveredDevice` argument for each newly discovered device |
