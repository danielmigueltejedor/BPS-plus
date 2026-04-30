# Changelog

All notable changes to this project are documented in this file.

## [1.8.0] - 2026-05-01
Versión grande: estabilidad, fugas de memoria y fixes de ciclo de vida.
Engloba todos los cambios desde 1.7.7 más el trabajo nuevo.

### Sensores
- `unavailable` reservado solo a "subsistema BLE caído". Cuando el
  target/receptor no resuelve aún o se agota `stale_after`, el sensor
  pasa a `unknown` (`available=True`, `state=None`) en lugar de
  desaparecer del dashboard.
- Sticky por defecto subido a 180 s (`DEFAULT_STALE_AFTER`). Móviles
  con anuncios espaciados (iPhone con pantalla apagada) ya no
  parpadean entre ráfagas y la triangulación en directo usa
  distancias consistentes.
- Nuevo barrido en `entity_registry` que elimina las entradas legacy
  con receptor en MAC slug (`..._distance_to_aa_bb_cc_..`) cuando ya
  existe una contraparte con slug amigable
  (`..._distance_to_bluetooth_proxy_cocina`). Adiós a los
  `Distance to <mac>` zombi atascados como `unavailable`.

### Ciclo de vida
- `async_setup_entry` arranca primero `async_setup` (escáner BLE) y
  después la plataforma `sensor`, evitando que la primera ronda de
  discovery cree cero entidades por carrera.
- `async_setup` ya no espera al evento `homeassistant_started`; las
  vistas REST/WS se registran inmediatamente y el panel BPS+ carga
  los mapas al primer intento durante el arranque.
- `async_unload_entry` ahora cancela la tarea de posicionamiento,
  para el watcher de `bpsdata.txt` y el escáner BLE, y libera los
  listeners `homeassistant_stop` registrados previamente. Antes la
  recarga del entry dejaba listeners y tareas zombis acumulándose.
- `async_unload_entry` deja de borrar las entidades del registry; ese
  comportamiento se traslada al nuevo `async_remove_entry` que solo
  se ejecuta al desinstalar definitivamente la integración. Recargar
  ya no destruye personalizaciones del usuario.
- Listeners de `homeassistant_stop` y vistas dinámicas (`script.js`)
  protegidos por flag para evitar registros duplicados al recargar.
- `KeyError: 'bps_plus'` en boot frío resuelto con
  `hass.data.setdefault(DOMAIN, {})` al inicio de `async_setup`.
- Warning cosmético `BPS+ has already been initialized. Aborting`
  bajado a `debug`.

### Memoria
- `_engine_state` (smoothers, Kalman, autocal por target) se purga
  cada minuto: cualquier target que el escáner no haya visto en 30 min
  se descarta.
- `BleScanner.prune_stale()`: tira `devices`, `links` y aliases con
  `last_seen` mayor a 30 min. Bound en memoria para entornos con
  vecinos/AirTags rotando.

### Posicionamiento
- Trilateración: la elección de planta ahora prioriza la planta con
  más receptores válidos y desempata por menor radio. Antes se
  elegía solo por la baliza más cercana, lo que confundía al motor
  cuando dos plantas compartían un par de proxies.
- `PositionKalman` se re-siembra automáticamente si pasa más de 30 s
  sin medidas — el prior de velocidad constante deja de ser válido y
  arrastraba la posición filtrada hacia una extrapolación obsoleta.
- Cap de distancia bajado de 80 m a 60 m (`DISTANCE_CAP_M`); en
  interior cualquier estimación más larga es ruido / multipath.

### Concurrencia
- Lock asíncrono alrededor de `apitricords` para que las
  actualizaciones paralelas de varias entidades no se pisen.
- Escritura atómica de `bpsdata.txt`: se vuelca a `bpsdata.tmp` y se
  hace `os.replace`. El watcher ya no observa estados intermedios y
  desaparece el log "Error parsing JSON data" durante guardados.
- `update_global_data` tolera lecturas durante guardado: lo registra
  como `warning` y reintenta en el siguiente evento del watcher.

### Configuración
- `base_url` y `token` pasan a ser opcionales en el config flow. El
  motor BLE nativo no los necesita; el frontend cae al token de la
  sesión actual cuando se dejan vacíos.
- `CONF_SCAN_INTERVAL` y `CONF_STALE_AFTER` se persisten también en
  `entry.data` al crear la integración (antes solo aparecían en
  options tras editar manualmente).

## [1.7.9] - 2026-05-01
- **Fix “No se pudieron cargar los mapas” al iniciar.** La inicialización
  pesada (registro de vistas REST/WebSocket, watcher de `bpsdata.txt`,
  arranque del escáner BLE nativo) ya no espera al evento
  `homeassistant_started`: se ejecuta directamente en `async_setup`.
  Antes el endpoint `/api/bps/maps` no estaba registrado todavía si el
  usuario abría el panel BPS+ durante el arranque, lo que devolvía 404
  y disparaba el `alert()` del frontend.
- **Orden correcto de carga del entry.** `async_setup_entry` ahora
  llama primero a `async_setup` (arranca el escáner BLE) y después
  reenvía a la plataforma `sensor`. Antes el `sensor.py` corría con el
  escáner sin inicializar y la primera ronda de discovery creaba cero
  entidades, hasta que un cambio de estado externo disparaba un
  refresh.
- **Log limpio.** El warning `BPS+ has already been initialized.
  Aborting` baja a `debug`. El doble `async_setup` (uno de HA, otro
  desde `async_setup_entry`) es esperado y la flag ya lo cubre; no
  es un fallo.

## [1.7.8] - 2026-05-01
- **`unknown` en lugar de `unavailable`.** Los `BpsDistanceSensor`
  solo se marcan como `unavailable` cuando el subsistema BLE de BPS+
  está caído. Si el target/receptor no resuelve aún (proxy
  reconectando, alias IRK pendiente) o el `stale_after` se ha agotado,
  el sensor queda en `unknown` (`available=True`, `state=None`). Así
  no desaparece de automatizaciones ni dashboards y se recupera en
  cuanto llega el siguiente anuncio.
- **Sticky por defecto 180 s.** `DEFAULT_STALE_AFTER` pasa de 60 s a
  180 s para que móviles con anuncios espaciados (iPhone con pantalla
  apagada) no parpadeen entre ráfagas y la triangulación en directo
  use distancias consistentes. Sigue siendo configurable.
- **Limpieza de sensores MAC zombi.** Al arranque y tras cada refresh
  de discovery se recorre el `entity_registry` y se eliminan las
  entradas legacy cuyo `unique_id` apunta a un receptor con MAC slug
  (`..._distance_to_aa_bb_cc_dd_ee_ff`) cuando ya existe un sensor
  equivalente para el mismo target con el slug amigable del proxy
  (`..._distance_to_bluetooth_proxy_cocina`). Esto barre los
  `Distance to <mac>` que se quedaban anclados como `unavailable`
  tras un renombrado del proxy.

## [1.7.7] - 2026-04-28
- **Sticky distance values.** Each `BpsDistanceSensor` now keeps its
  last reading visible during gaps in the advertisement stream instead
  of bouncing to "desconocido"/"unavailable" between bursts. The
  sensor only goes unavailable after `CONF_STALE_AFTER` seconds (UI
  configurable, default 60 s) without any new RSSI sample.
- **Real-time refresh.** Distance sensors are pushed via a dedicated
  refresh loop instead of HA's 30 s default poll. Cadence comes from
  the new `CONF_SCAN_INTERVAL` option (default 2 s, clamped to
  [0.5 s, 60 s]). Result: `Distance to <Proxy>` updates every couple
  of seconds while you walk around.
- New options on the integration's "Configurar" dialog:
  - `scan_interval` — seconds between sensor refreshes.
  - `stale_after` — seconds without an advertisement before the
    distance is considered lost.

## [1.7.6] - 2026-04-28
- Map editor: placing a receiver now shows a dropdown of BT proxies
  that BPS+ has actually detected, populated from the new
  `GET /api/bps/scanners` endpoint. Each entry carries the friendly
  name from HA's device registry and saves the matching slug as the
  receiver `entity_id`, so users no longer have to type
  `bluetooth_proxy_cocina` by hand. The free-text input remains as a
  fallback when no proxies are detected (or all visible ones are
  already placed on the current floor).
- Already-placed proxies are filtered out of the dropdown so the same
  receiver can't be added twice on a single floor.

## [1.7.5] - 2026-04-28
- Distance entities now read **"Distance to <Proxy Friendly Name>"**
  instead of **"Distance to <proxy MAC slug>"**. The receiver id used
  as the canonical key in `discover_distance_entities` is the
  device-registry-derived slug (e.g. `bluetooth_proxy_cocina`) and
  the sensor `_attr_name` carries the proxy's actual friendly name
  pulled from a per-discovery `receiver_friendly_names` cache.
- Existing MAC-slug sensors are superseded on next discovery; the
  startup cleanup pass already removes orphans.

## [1.7.4] - 2026-04-28
- Fix: distance estimates exploding to thousands of metres. iPhones (and
  many other devices) report `0` or `+12` dBm in the advertising
  `tx_power` field — that's the radiated power, not the calibrated
  RSSI@1m the path-loss model expects. With `tx_power=0` and a typical
  indoor RSSI of ~-90 dBm, `d = 10^(90/25) ≈ 3980 m`. Advertised
  `tx_power` is now only trusted when it falls in the plausible
  RSSI@1m window (-90 dBm .. -30 dBm); otherwise BPS+ keeps the
  default and lets the stationarity-driven fitter dial it in.
- Distances above 80 m are now dropped at the scanner output rather
  than fed into trilateration as garbage.
- `STALE_AFTER` raised from 30 s to 90 s so that iPhones/Apple Watches
  in standby (advertising every ~1-2 s) actually accumulate sightings
  across the >=3 proxies the engine needs.
- Sensor cleanup: managed sensors whose visible name is just a
  colon-separated MAC (legacy from earlier versions before the
  friendly-name filter landed) are now removed on startup. Frontend
  filter also rejects targets whose only "name" is a MAC string, so
  no new ones are created.

## [1.7.3] - 2026-04-27
- Fix: chicken-and-egg in the positioning loop. Discovery (and the
  `BleScanner.set_alias()` call that maps a `private_ble_device` rotating
  MAC to its stable identity) was gated behind the candidate check, but
  no rotating-MAC device could ever reach >=3 scanner sightings without
  the alias. Net effect: iPhones / Apple Watches showed up in the panel
  selector but never produced distances and the auto-calibrator never
  collected samples ("Pro: calibrados 0/5"). Discovery + alias setup
  now run on every tick before the candidate threshold is checked.
- Diagnostic log line now also reports the number of stable aliases
  currently active.

## [1.7.2] - 2026-04-27
- Fix: sidebar panel disappeared after a config-entry reload (and after
  any HACS upgrade since 1.7.x). `async_unload_entry` removed the panel
  but the next `async_setup_entry` short-circuited inside `async_setup`
  on the one-shot init flag and never re-registered it. Panel
  registration is now in a dedicated idempotent helper called from
  `async_setup_entry` on every load.
- Branding: user-visible name is now **BPS+** everywhere — sidebar
  title, manifest, HACS card, README, frontend header, log lines,
  config-flow title. Internal identifiers (`bps_plus` domain, module
  paths, route URLs) intentionally unchanged so existing installs and
  saved maps keep working.

## [1.7.0] - 2026-04-26
- Native BLE distance engine (`ble_scanner.py`) replaces the dependency on
  external integrations like Bermuda BLE Trilateration:
  - Subscribes to every advertisement HA's bluetooth integration sees
    (local adapters + ESPHome / Shelly bluetooth proxies).
  - Per-link EWMA RSSI with log-distance path-loss model
    `d = 10^((tx_power - rssi) / (10 * n))`.
  - Online per-link fit of `tx_power` and `n` driven by the
    stationarity detector — when the target is still, the trilaterated
    position becomes ground truth for each proxy.
  - Auto-discovery: any device seen by ≥3 proxies becomes trackable.
  - Receiver resolution: existing maps with `bluetooth_proxy_cocina`-
    style ids keep working — slugs match against scanner friendly
    names from the device registry.
- Discovery loop replaced: no more Jinja `_distance_to_` template.
  Targets come straight from the scanner.
- `BpsDistanceSensor` now reads from the scanner; exposes `rssi`,
  `tx_power`, `path_loss_n`, `calibration_samples`, `age_s` as attrs.
- New `GET /api/bps/ble_snapshot` returns live devices, scanners and
  per-link RSSI/distance/fit state — useful to debug coverage and
  receiver-id mismatches without reading logs.
- IRK-stable identities via the `private_ble_device` integration:
  - any HA entity exposing `source_type: bluetooth_le` plus a
    `current_address` attribute is picked up automatically,
  - a stable token (the entity slug, e.g. `iphone_de_mama`) is bound to
    the rotating MAC inside the scanner via `set_alias()`,
  - per-link calibration migrates with the alias so MAC rotations do
    not reset path-loss fits,
  - `device_tracker.*` entities are preferred when several siblings
    point at the same MAC.
- Sensor creation discipline: only materialises `BpsDistanceSensor`
  rows for targets with a real friendly name AND for receivers actually
  placed on a saved map. The legacy
  `Distance to aa_bb_cc_..` flood is gone.
- `_cleanup_corrupt_managed_entities` now also evicts zombie sensors
  whose target is a bare MAC slug with no resolved name and no current
  reading.

## [1.6.0] - 2026-04-26
- New positioning engine (`positioning.py`):
  - robust weighted nonlinear-least-squares trilateration with soft-L1 loss,
  - 1/r² weighted-centroid initial guess (replaces (0, 0)),
  - HDOP-equivalent quality metric from solver Jacobian,
  - RANSAC-lite refit that drops the worst residual when above 6σ.
- Per-link `DistanceSmoother` with EWMA + MAD outlier rejection (replaces ±50% gate).
- Constant-velocity 2D Kalman filter (`PositionKalman`) with measurement variance derived from HDOP.
- Stationarity detector + opportunistic auto-calibrator that learns `factor·raw + offset` per receiver from rest-state samples.
- Calibration model extended to `factor·raw^exp + offset` (exponent optional, defaults to 1 for backwards compatibility).
- Wall-penalty unit bug fixed: meters are now converted to pixels via the floor scale before being added to residuals.
- New diagnostic API `GET /api/bps/diagnostics` exposing per-entity quality, sample counts, and calibration suggestions.
- New `sensor.<entity>_bps_quality` exposing label (good/fair/poor) plus HDOP, n_used, RMS residual, speed, and stationary state.

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
