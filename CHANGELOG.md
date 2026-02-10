# Changelog

All notable changes to this project are documented in this file.

## [1.5.6] - 2026-02-09
- Forced visible verification update:
  - frontend header now shows `v1.5.6`,
  - cache-busting tags updated to `v=1.5.6` for CSS/JS.

## [1.5.5] - 2026-02-09
- Fixed realtime tracking config loading by allowing frontend config endpoint to be read by the panel:
  - `GET /api/bps/frontend_config` now available without auth barrier in panel context.
- Improved position stability for non-realtime tracking:
  - trilateration now falls back to raw receiver points when r-change filtering leaves fewer than 3 points.
- Updated frontend cache-busting tags to `v=1.5.5` for CSS and JS.

## [1.5.4] - 2026-02-09
- Fixed realtime tracking auth UX by loading token/base URL from integration settings through new API:
  - `GET /api/bps/frontend_config` (auth required),
  - frontend now auto-builds websocket URL from configured `base_url`.
- Added **Quitar marcador de posición** in Pro mode to remove/reposition the calibration marker at any time.
- Kept cache-busting updated for frontend assets to reduce stale UI after updates.

## [1.5.3] - 2026-02-09
- Final hardening pass for frontend stability:
  - added additional null-guards in calibration status handling to tolerate partial cache mismatches.
- Added cache-busting to both frontend assets in `index.html`:
  - `bpsstyle.css?v=1.5.3`
  - `script.js?v=1.5.3`
- Keeps Modo Pro (beta), wall drawing and full Spanish UI active after forced refresh.

## [1.5.2] - 2026-02-09
- Added **Modo Pro (beta)** in frontend calibration:
  - mark real position on map (person marker),
  - 15-second multi-proxy auto-capture,
  - automatic per-receiver recalibration from captured samples,
  - guidance message listing proxies still pending calibration.
- Added frontend cache-busting for `script.js` to reduce stale UI issues after updates.
- Added null-safe guards in calibration controls to avoid frontend crashes on partial cache mismatches.

## [1.5.1] - 2026-02-09
- Added wall-penalty presets in UI for faster setup:
  - open space, light partition, standard partition, brick, concrete, concrete+metal.
- Hardened frontend data safety:
  - fixed receiver duplicate checks to use actual payload ids,
  - prevented saving receivers with invalid coordinates,
  - guarded save flow to validate scale from the currently selected floor,
  - kept floor-delete flow working without false scale validation errors.
- Improved wall-penalty UX:
  - preset selector syncs with manual penalty value when loading/saving floors.

## [1.5.0] - 2026-02-09
- Added wall-aware trilateration model:
  - per-floor `walls` support with line segments,
  - per-floor `wall_penalty` (meters),
  - optimization now adds wall-crossing penalty to distance residuals.
- Added wall editing in frontend:
  - new **Dibujar pared** tool (2-click segment creation),
  - wall list with delete action,
  - persisted wall data in floor config.
- Added per-floor wall-penalty controls in calibration panel.
- Translated main frontend UI to Spanish (labels, calibration flow, tracking actions and key alerts).

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
