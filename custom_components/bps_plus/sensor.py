from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .__init__ import discover_distance_entities, cache_discovery_data

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
        return {
            "target_id": self._target_id,
            "receiver_id": self._receiver_id,
            "source_entity_id": self._source_entity_id,
            "managed_by": DOMAIN,
        }

    async def async_update(self) -> None:
        canonical_map, _, _ = _get_cached_discovery(self.hass)
        source = canonical_map.get(self._target_id, {}).get(self._receiver_id)
        self._source_entity_id = source

        if not source:
            self._attr_native_value = None
            self._attr_available = False
            return

        state = self.hass.states.get(source)
        if state is None:
            self._attr_native_value = None
            self._attr_available = False
            return

        try:
            self._attr_native_value = float(state.state)
            self._attr_available = True
        except (TypeError, ValueError):
            self._attr_native_value = None
            self._attr_available = False


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

    @callback
    def _ensure_entities() -> None:
        canonical_map, entity_options, _ = _get_cached_discovery(hass)
        receivers = _all_receivers(canonical_map)
        if not receivers:
            return

        target_name_map = {item["id"]: item.get("name") or item["id"] for item in entity_options}

        new_entities: list[Entity] = []
        for target_id in target_name_map:
            for receiver_id in receivers:
                key = f"{target_id}__{receiver_id}"
                if key in managed:
                    continue
                sensor = BpsDistanceSensor(
                    hass=hass,
                    target_id=target_id,
                    receiver_id=receiver_id,
                    display_name=target_name_map[target_id],
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
        nonlocal refresh_task
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

        if refresh_task is not None and not refresh_task.done():
            return

        refresh_task = hass.async_create_task(_async_refresh_entities())

    unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, _state_changed)
    config_entry.async_on_unload(unsub)
