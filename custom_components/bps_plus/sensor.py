from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    CONF_STALE_AFTER,
    CONF_SCAN_INTERVAL,
    DEFAULT_STALE_AFTER,
    DEFAULT_SCAN_INTERVAL,
)
from .__init__ import (
    cache_discovery_data,
    discover_distance_entities,
    get_scanner,
)
from .ble_scanner import normalize_mac as scanner_normalize_mac

_LOGGER = logging.getLogger(__name__)

# HA's default sensor poll interval is 30 s. That's far too slow for a
# real-time positioning system: the user sees the distance go stale
# between updates even when the scanner is receiving advertisements
# every few hundred ms. Override at module level — the actual cadence
# is reconciled with the user-configurable CONF_SCAN_INTERVAL when the
# entry is set up.
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)


def _options(hass: HomeAssistant) -> dict:
    entry = hass.data.get(DOMAIN, {}).get("config_entry")
    if entry is None:
        return {}
    return {**entry.data, **entry.options}


def _get_cached_discovery(
    hass: HomeAssistant,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]], dict[str, dict[str, str]]]:
    domain_data = hass.data.get(DOMAIN, {})
    canonical_map = domain_data.get("distance_entity_map")
    entity_options = domain_data.get("entity_options")
    target_metadata = domain_data.get("target_metadata")

    if canonical_map is None or entity_options is None or target_metadata is None:
        canonical_map, entity_options, target_metadata = discover_distance_entities(hass)
        cache_discovery_data(hass, canonical_map, entity_options, target_metadata)

    return canonical_map, entity_options, target_metadata


def _all_receivers(canonical_map: dict[str, dict[str, str]]) -> list[str]:
    receivers = set()
    for receiver_map in canonical_map.values():
        receivers.update(receiver_map.keys())
    return sorted(receivers)


def _is_valid_id(value: str) -> bool:
    return bool(value) and len(value) <= 80 and re.fullmatch(r"[a-z0-9_]+", value) is not None


def _looks_repeated(value: str) -> bool:
    parts = value.split("_")
    if len(parts) < 2 or len(parts) % 2 != 0:
        return False
    half = len(parts) // 2
    return parts[:half] == parts[half:]


_MAC_SLUG_RE = re.compile(r"^[0-9a-f]{2}(_[0-9a-f]{2}){5}$")
_UNIQUE_ID_PREFIX = f"{DOMAIN}_distance_"


def _split_unique_id(unique_id: str) -> tuple[str, str] | None:
    """Parse `<DOMAIN>_distance_<target>_<r1>_<r2>_<r3>_<r4>_<r5>_<r6>`.

    Receiver id MAY be a MAC slug (6 hex pairs joined by `_`) or a
    friendly slug. Try MAC slug first (last 6 underscored chunks); if
    they look like hex pairs, treat the rest as target. Otherwise fall
    back to a single split on the last `_`.
    """
    if not unique_id.startswith(_UNIQUE_ID_PREFIX):
        return None
    rest = unique_id[len(_UNIQUE_ID_PREFIX):]
    parts = rest.split("_")
    if len(parts) >= 7:
        tail = "_".join(parts[-6:])
        if _MAC_SLUG_RE.match(tail):
            head = "_".join(parts[:-6])
            if head:
                return head, tail
    return None


def _cleanup_legacy_mac_receivers(
    hass: HomeAssistant, managed: dict
) -> int:
    """Remove legacy registry entries whose receiver id is a bare MAC slug
    when the live discovery now resolves the same proxy to a friendly
    slug. These are the `Distance to <mac>` rows that stay stuck as
    "unavailable" forever after a rename.

    Walks the entity registry directly so it catches entries even when
    they have not been loaded into `hass.states`.
    """
    entity_registry = er.async_get(hass)

    # Targets that currently own a friendly-receiver sensor.
    friendly_targets: set[str] = set()
    valid_unique_ids: set[str] = set()
    for sensor in managed.values():
        if not isinstance(sensor, BpsDistanceSensor):
            continue
        valid_unique_ids.add(sensor.unique_id or "")
        rid = sensor._receiver_id
        if rid and not _MAC_SLUG_RE.match(rid):
            friendly_targets.add(sensor._target_id)

    if not friendly_targets:
        return 0

    removed = 0
    for entry in list(entity_registry.entities.values()):
        if entry.platform != DOMAIN:
            continue
        uid = entry.unique_id or ""
        if uid in valid_unique_ids:
            continue
        parsed = _split_unique_id(uid)
        if parsed is None:
            continue
        target_id, receiver_id = parsed
        if not _MAC_SLUG_RE.match(receiver_id):
            continue
        if target_id not in friendly_targets:
            continue
        entity_registry.async_remove(entry.entity_id)
        removed += 1
    return removed


def _cleanup_corrupt_managed_entities(hass: HomeAssistant) -> int:
    """Remove legacy / zombie BPS-managed sensors from entity registry.

    Drops:
      * malformed ids (legacy bug),
      * sensors targeting a bare MAC slug whose entity name is still the
        raw MAC (no friendly name was ever resolved — these are the
        `Distance to aa_bb_cc_..` rows that flooded the dashboard).
    """
    entity_registry = er.async_get(hass)
    removed = 0

    for state in hass.states.async_all():
        if not state.entity_id.startswith("sensor."):
            continue
        attrs = state.attributes
        if attrs.get("managed_by") != DOMAIN:
            continue
        target_id = str(attrs.get("target_id", ""))
        receiver_id = str(attrs.get("receiver_id", ""))

        malformed = (
            not _is_valid_id(target_id)
            or not _is_valid_id(receiver_id)
            or _looks_repeated(target_id)
            or _looks_repeated(receiver_id)
        )

        zombie = False
        if not malformed and _MAC_SLUG_RE.match(target_id):
            friendly = str(attrs.get("friendly_name") or "")
            # Zombie if the friendly name still embeds the raw MAC slug
            # (i.e. discovery never resolved a real device name) AND the
            # sensor has no current value (state is unknown).
            if target_id in friendly and state.state in ("unknown", "unavailable", None):
                zombie = True

        # MAC-named leftover from earlier versions: friendly_name itself
        # is just a colon-separated MAC. Sweep these on every restart so
        # they don't pollute the device list under their HW address.
        mac_named = False
        if not malformed and not zombie:
            friendly_first = str(attrs.get("friendly_name") or "").split(" ")[0].strip()
            if re.fullmatch(r"[0-9A-Fa-f]{2}(?:[:_-][0-9A-Fa-f]{2}){5}", friendly_first):
                mac_named = True

        if not malformed and not zombie and not mac_named:
            continue

        if entity_registry.async_get(state.entity_id) is not None:
            entity_registry.async_remove(state.entity_id)
            removed += 1

    return removed


class BpsDistanceSensor(SensorEntity):
    """Distance from one BLE target to one proxy (receiver), owned by BPS+."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "m"
    # Driven by the platform refresh loop so the cadence honours
    # CONF_SCAN_INTERVAL instead of HA's 30 s poll default.
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        target_id: str,
        receiver_id: str,
        display_name: str,
        receiver_display_name: str | None = None,
    ) -> None:
        self.hass = hass
        self._target_id = target_id
        self._receiver_id = receiver_id
        self._display_name = display_name
        self._receiver_display_name = receiver_display_name or receiver_id
        self._attr_unique_id = f"{DOMAIN}_distance_{target_id}_{receiver_id}"
        # _attr_has_entity_name=True means HA composes
        # "<device_name> <_attr_name>" so this string must be
        # entity-specific only.
        self._attr_name = f"Distance to {self._receiver_display_name}"
        self._attr_native_value = None
        self._source_entity_id: str | None = None
        self._cached_reading: dict | None = None
        self._cached_reading_ts: float = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"target_{self._target_id}")},
            name=self._display_name,
            manufacturer="BPS+",
            model="BLE Target",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "target_id": self._target_id,
            "receiver_id": self._receiver_id,
            "source_entity_id": self._source_entity_id,
            "managed_by": DOMAIN,
        }
        reading = getattr(self, "_cached_reading", None)
        if reading:
            attrs["rssi"] = round(float(reading["rssi"]), 1)
            attrs["tx_power"] = round(float(reading["tx_power"]), 1)
            attrs["path_loss_n"] = round(float(reading["path_loss"]), 2)
            attrs["calibration_samples"] = int(reading["samples"])
            attrs["age_s"] = round(float(reading["age_s"]), 1)
        return attrs

    async def async_update(self) -> None:
        canonical_map, _, _ = _get_cached_discovery(self.hass)
        synthetic = canonical_map.get(self._target_id, {}).get(self._receiver_id)
        self._source_entity_id = synthetic

        scanner = get_scanner(self.hass)
        if scanner is None:
            # Integration broken — the scanner subsystem is not running.
            # Only here is "unavailable" the right state.
            self._attr_available = False
            self._attr_native_value = None
            return

        from .__init__ import _resolve_target_identity
        identity = _resolve_target_identity(self.hass, self._target_id)
        source = scanner.resolve_receiver(self._receiver_id)
        if not identity or not source:
            # Configured target/receiver we can't resolve yet (proxy not
            # connected, IRK alias not bound...). Stay "unknown" instead
            # of "unavailable" so the entity remains in the dashboard
            # and recovers cleanly when the link returns.
            self._attr_available = True
            self._attr_native_value = None
            return

        opts = _options(self.hass)
        try:
            stale_after = float(opts.get(CONF_STALE_AFTER, DEFAULT_STALE_AFTER))
        except (TypeError, ValueError):
            stale_after = float(DEFAULT_STALE_AFTER)
        # Ask the scanner for the reading using the configured stale
        # window so a brief gap in advertisements does NOT immediately
        # nuke the sensor. Sticky behaviour below keeps the last value
        # visible until `stale_after` seconds without any update.
        reading = scanner.get_distance(identity, source, max_age=stale_after)
        now = time.monotonic()

        if reading is not None:
            self._attr_native_value = round(float(reading["distance_m"]), 2)
            self._attr_available = True
            self._cached_reading = reading
            self._cached_reading_ts = now
            return

        # No fresh reading. Keep the previous value if still within the
        # configured stale window — preserves a stable distance for live
        # triangulation between sparse advertisements.
        if (
            self._cached_reading is not None
            and (now - self._cached_reading_ts) < stale_after
        ):
            self._attr_available = True
            return

        # Beyond the stale window: surface as "unknown" (None value with
        # available=True) instead of "unavailable" so the entity does not
        # disappear from automations / dashboards and resumes as soon as
        # the next advertisement lands.
        self._attr_native_value = None
        self._attr_available = True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BPS+ managed sensors."""
    _LOGGER.info("Setting up BPS+ distance sensors")
    hass.data.setdefault(DOMAIN, {})
    managed: dict[str, Entity] = hass.data[DOMAIN].setdefault("managed_sensors", {})
    refresh_task: asyncio.Task | None = None
    last_refresh_ts = 0.0
    min_refresh_interval = 1.5

    removed = _cleanup_corrupt_managed_entities(hass)
    if removed:
        _LOGGER.warning("Removed %s malformed BPS entities from registry", removed)

    @callback
    def _ensure_entities() -> None:
        canonical_map, entity_options, _ = _get_cached_discovery(hass)
        if not canonical_map:
            return

        target_name_map = {
            item["id"]: item.get("name") or item["id"] for item in entity_options
        }
        receiver_friendly = (
            hass.data.get(DOMAIN, {}).get("receiver_friendly_names") or {}
        )

        # Restrict receivers to those the user actually placed on a map.
        # Otherwise we'd cross-multiply every BLE proxy with every visible
        # device and pollute the entity registry with hundreds of unused
        # sensors.
        from .__init__ import global_data
        placed_receivers: set[str] = set()
        try:
            for floor in (global_data or {}).get("floor", []):
                for receiver in floor.get("receivers", []):
                    rid = receiver.get("entity_id")
                    if rid:
                        placed_receivers.add(rid)
        except AttributeError:
            placed_receivers = set()

        if not placed_receivers:
            placed_receivers = set(_all_receivers(canonical_map))
        if not placed_receivers:
            return

        # Only materialise sensors for targets that have a friendly name
        # distinct from the bare MAC token AND not just a MAC string.
        # Drops random rotating Apple chaff and devices whose only "name"
        # is their colon-separated MAC.
        mac_re = re.compile(r"^[0-9A-Fa-f]{2}(?:[:_-][0-9A-Fa-f]{2}){5}$")
        meaningful_targets = [
            target_id
            for target_id, receiver_map in canonical_map.items()
            if receiver_map
            and target_name_map.get(target_id)
            and target_name_map[target_id] != target_id
            and not mac_re.match(target_name_map[target_id].strip())
        ]

        new_entities: list[Entity] = []
        for target_id in meaningful_targets:
            if not _is_valid_id(target_id):
                continue
            if _looks_repeated(target_id):
                continue
            for receiver_id in placed_receivers:
                if not _is_valid_id(receiver_id):
                    continue
                if _looks_repeated(receiver_id):
                    continue
                key = f"{target_id}__{receiver_id}"
                if key in managed:
                    continue
                sensor = BpsDistanceSensor(
                    hass=hass,
                    target_id=target_id,
                    receiver_id=receiver_id,
                    display_name=target_name_map.get(target_id, target_id),
                    receiver_display_name=receiver_friendly.get(receiver_id),
                )
                managed[key] = sensor
                new_entities.append(sensor)

        if new_entities:
            async_add_entities(new_entities)

    _ensure_entities()

    legacy_removed = _cleanup_legacy_mac_receivers(hass, managed)
    if legacy_removed:
        _LOGGER.warning(
            "Removed %s legacy MAC-receiver BPS entities from registry",
            legacy_removed,
        )

    async def _async_refresh_entities() -> None:
        nonlocal refresh_task
        try:
            canonical_map, entity_options, target_metadata = discover_distance_entities(hass)
            cache_discovery_data(hass, canonical_map, entity_options, target_metadata)
            _ensure_entities()
            # Re-run legacy cleanup once friendly proxies become known
            # (initial setup races with proxies coming online).
            removed_legacy = _cleanup_legacy_mac_receivers(hass, managed)
            if removed_legacy:
                _LOGGER.warning(
                    "Removed %s legacy MAC-receiver BPS entities from registry",
                    removed_legacy,
                )
        except Exception as err:
            _LOGGER.exception("Error refreshing BPS discovery: %s", err)
        finally:
            refresh_task = None

    @callback
    def _state_changed(event: Event) -> None:
        nonlocal refresh_task, last_refresh_ts
        entity_id = event.data.get("entity_id")
        if not entity_id:
            return

        new_state = event.data.get("new_state")
        attrs = getattr(new_state, "attributes", {})

        # Ignore updates from sensors already managed by BPS+ to avoid
        # recursive discovery/add loops under heavy state churn.
        if attrs.get("managed_by") == DOMAIN:
            return

        should_refresh = (
            "_distance_to_" in entity_id
            or attrs.get("source_type") == "bluetooth_le"
        )
        if not should_refresh:
            return

        now = time.monotonic()
        if now - last_refresh_ts < min_refresh_interval:
            return
        last_refresh_ts = now

        if refresh_task is not None and not refresh_task.done():
            return

        refresh_task = hass.async_create_task(_async_refresh_entities())

    unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, _state_changed)
    config_entry.async_on_unload(unsub)

    # Push-style refresh loop. Polls every CONF_SCAN_INTERVAL seconds
    # (default 2 s, vs. HA's 30 s) and pushes the result to each
    # registered sensor via async_write_ha_state. Combined with the
    # sticky logic in BpsDistanceSensor.async_update this gives
    # near-real-time distances while surviving brief gaps in the
    # advertisement stream.
    stop_event = asyncio.Event()

    async def _refresh_loop() -> None:
        while not stop_event.is_set():
            opts = _options(hass)
            try:
                interval = float(opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            except (TypeError, ValueError):
                interval = float(DEFAULT_SCAN_INTERVAL)
            interval = max(0.5, min(60.0, interval))

            sensors = [s for s in list(managed.values()) if isinstance(s, BpsDistanceSensor)]
            for sensor in sensors:
                if stop_event.is_set():
                    break
                try:
                    await sensor.async_update()
                    if sensor.hass is not None and sensor.entity_id:
                        sensor.async_write_ha_state()
                except Exception as err:
                    _LOGGER.debug("Sensor refresh error for %s: %s", sensor.entity_id, err)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    refresh_loop_task = hass.async_create_task(_refresh_loop())

    def _cancel_refresh_loop() -> None:
        stop_event.set()
        if not refresh_loop_task.done():
            refresh_loop_task.cancel()

    config_entry.async_on_unload(_cancel_refresh_loop)
