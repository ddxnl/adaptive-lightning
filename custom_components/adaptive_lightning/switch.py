"""Switch that enables or disables adaptation for one profile."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .manager import AdaptiveConfigEntry, AdaptiveManager, signal_update


def device_info(entry: AdaptiveConfigEntry) -> DeviceInfo:
    """Device that groups the entities of one profile."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        entry_type=DeviceEntryType.SERVICE,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AdaptiveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch."""
    async_add_entities([AdaptiveSwitch(entry)])


class AdaptiveSwitch(SwitchEntity, RestoreEntity):
    """Turns adaptation on and off."""

    _attr_has_entity_name = True
    _attr_translation_key = "adaptation"
    _attr_should_poll = False

    def __init__(self, entry: AdaptiveConfigEntry) -> None:
        self._manager: AdaptiveManager = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_adaptation"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Restore the previous state."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_OFF:
            self._manager.enabled = False
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
    def is_on(self) -> bool:
        return self._manager.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "lights": self._manager.lights,
            "manual_control": self._manager.manual_lights(),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._manager.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._manager.async_set_enabled(False)
        self.async_write_ha_state()
