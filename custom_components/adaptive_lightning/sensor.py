"""Sensors exposing the currently computed target values."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .manager import AdaptiveConfigEntry, AdaptiveManager, signal_update
from .switch import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AdaptiveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(
        [
            TargetSensor(entry, "color_temperature", "K"),
            TargetSensor(entry, "brightness", PERCENTAGE),
        ]
    )


class TargetSensor(SensorEntity):
    """One computed target value."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: AdaptiveConfigEntry, key: str, unit: str) -> None:
        self._manager: AdaptiveManager = entry.runtime_data
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._manager.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        target = self._manager.target
        if target is None:
            return None
        if self._key == "color_temperature":
            return target.kelvin
        return target.brightness_pct
