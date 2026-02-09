# Changelog

All notable changes to this project are documented in this file.

## [1.3.5] - 2026-02-09
- Added additional anti-loop hardening in BLE discovery:
  - ignores all entities owned by `bps_plus` via entity registry platform lookup,
  - collapses recursively repeated target ids,
  - rejects malformed/oversized ids.
- Added stricter creation guards in `sensor.py` to skip repeated/invalid target and receiver ids.
- Added cleanup for malformed legacy managed entities to reduce startup load after previous loop incidents.
- Added refresh throttling/debounce to reduce event storms and websocket saturation risk.
- Optimized discovery by reading entity-registry ownership once per cycle instead of per entity.

## [1.3.4] - 2026-02-09
- Fixed critical recursive entity-generation loop that could saturate Home Assistant Core.
- Added strict filtering in BLE discovery to ignore BPS-managed entities and malformed chained IDs.
- Added defensive ID validation and length limits to prevent runaway entity creation.
- Added refresh debounce and single-task refresh guard in `sensor.py` to reduce event storms.
- Added cleanup of malformed legacy BPS entities from the entity registry at setup.

## [1.3.3] - 2026-02-09
- Fixed blocking I/O warning by moving `os.scandir` in `/api/bps/maps` to executor job.
- Improved stability for heavy-load scenarios in Home Assistant event loop.

## [1.3.2] - 2026-02-09
- Hardened calibration capture resolution:
  - `/api/bps/distance` now supports `target_id + receiver_id` lookup.
  - Added fallback lookup to BPS-managed distance sensors when direct source entity is missing.
- Reduced capture failures for private/rotating BLE addresses.

## [1.3.1] - 2026-02-09
- Fixed calibration flow regressions in UI.
- Improved floor/device/receiver selection handling and tracking robustness.
- Synchronized README and manifest versions.

## [1.3.0] - 2026-02-09
- Added automatic BLE target/proxy discovery.
- Added canonical mapping for private BLE rotating MAC addresses using Home Assistant metadata.
- Added friendly target names in UI selectors.
- Added receiver suggestions in UI from discovered proxies.
- Added BPS internal API `/api/bps/distance` and switched calibration capture away from `/api/states`.
- Reworked BPS-managed distance sensor platform for dynamic target/receiver entity management.
