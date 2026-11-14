"""Adaptive Lightning: sun-driven brightness and colour temperature for lights."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .manager import AdaptiveConfigEntry, AdaptiveManager

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: AdaptiveConfigEntry) -> bool:
    """Set up Adaptive Lightning from a config entry."""
    manager = AdaptiveManager(hass, entry)
    entry.runtime_data = manager
    # Platforms first, so the switch can restore "disabled" before we touch lights.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await manager.async_start()
    entry.async_on_unload(manager.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AdaptiveConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: AdaptiveConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
