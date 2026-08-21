# Skyworth Discovery

Skyworth private protocol discovery — `scripts/toolkit/discovery.py`

> **MCP-only:** Device discovery is performed exclusively through the MCP tool `search_devices()` (in `device_mgmt.py`). This module (`discovery.py`) is an internal implementation detail — never import it directly or reference its functions.

---

## How Discovery Works (Internal)

`search_devices()` internally dispatches to the appropriate discovery protocol based on the `method` parameter (or auto-selects when omitted):

| Protocol | Transport | What it finds |
|----------|-----------|---------------|
| WS-Discovery (ONVIF) | Multicast (standard ONVIF) | All ONVIF cameras (including Skyworth) |
| Skyworth private | UDP broadcast/unicast | Skyworth devices only (richer metadata: SN, channels, MAC) |
| USB enumeration | Local | USB webcams |

Results are normalized into a unified `DiscoveredDevice` structure. Skyworth-specific fields (SN, subtype, channels, MAC, etc.) are populated under `sky_*` prefixed attributes when the Skyworth protocol is used.

