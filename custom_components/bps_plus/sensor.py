from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .__init__ import (
    cache_discovery_data,
    discover_distance_entities,
    get_scanner,
)
from .ble_scanner import normalize_mac as scanner_normalize_mac

_LOGGER = logging.getLogger(__name__)


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

        if not malformed and not zombie:
            continue

        if entity_registry.async_get(state.entity_id) is not None:
            entity_registry.async_remove(state.entity_id)
            removed += 1

    return removed


class BpsDistanceSensor(SensorEntity):
    """Distance from one BLE target to one proxy (receiver), owned by BPS-Plus."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "m"
    _attr_should_poll = True

    def __init__(
        self,
        hass: HomeAssistant,
        target_id: str,
        receiver_id: str,
        display_name: str,
    ) -> None:
        self.hass = hass
        self._target_id = target_id
        self._receiver_id = receiver_id
        self._display_name = display_name
        self._attr_unique_id = f"{DOMAIN}_distance_{target_id}_{receiver_id}"
        self._attr_name = f"{display_name} distance to {receiver_id}"
        self._attr_native_value = None
        self._source_entity_id: str | None = None
        self._cached_reading: dict | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"target_{self._target_id}")},
            name=self._display_name,
            manufacturer="BPS-Plus",
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
            self._attr_native_value = None
            self._attr_available = False
            return

        from .__init__ import _resolve_target_identity
        identity = _resolve_target_identity(self.hass, self._target_id)
        source = scanner.resolve_receiver(self._receiver_id)
        if not identity or not source:
            self._attr_native_value = None
            self._attr_available = False
            return

        reading = scanner.get_distance(identity, source)
        if reading is None:
            self._attr_native_value = None
            self._attr_available = False
            return

        self._attr_native_value = round(float(reading["distance_m"]), 2)
        self._attr_available = True
        self._cached_reading = reading


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BPS-Plus managed sensors."""
    _LOGGER.info("Setting up BPS-Plus distance sensors")
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
        # distinct from the bare MAC token. Drops random rotating Apple
        # chaff that has no name and would only ever be "desconocido".
        meaningful_targets = [
            target_id
            for target_id, receiver_map in canonical_map.items()
            if receiver_map
            and target_name_map.get(target_id)
            and target_name_map[target_id] != target_id
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
                )
                managed[key] = sensor
                new_entities.append(sensor)

        if new_entities:
            async_add_entities(new_entities)

    _ensure_entities()

    async def _async_refresh_entities() -> None:
        nonlocal refresh_task
        try:
            canonical_map, entity_options, target_metadata = discover_distance_entities(hass)
            cache_discovery_data(hass, canonical_map, entity_options, target_metadata)
            _ensure_entities()
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

        # Ignore updates from sensors already managed by BPS-Plus to avoid
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
