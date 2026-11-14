"""End-to-end test with real light entities (Home Assistant's demo lights)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import Platform  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.adaptive_lightning.calc import brightness_to_255  # noqa: E402
from custom_components.adaptive_lightning.const import DOMAIN  # noqa: E402

LIGHT = "light.bed_light"


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


@pytest.fixture(autouse=True)
async def _environment(hass: HomeAssistant, enable_custom_integrations, freezer):
    freezer.move_to("2026-06-21 20:00:00+00:00")  # 13:00 local
    # Only the demo lights are needed; skip demo's heavy "conversation" dependency.
    hass.config.components.add("conversation")
    with patch(
        "homeassistant.components.demo.COMPONENTS_WITH_CONFIG_ENTRY_DEMO_PLATFORM",
        [Platform.LIGHT],
    ):
        assert await async_setup_component(hass, "demo", {"demo": {}})
        await hass.async_block_till_done()
    yield
    for entry in hass.config_entries.async_entries():
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _add_entry(hass: HomeAssistant):
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": LIGHT}, blocking=True
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Test", data={"lights": [LIGHT]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(
        "sun.sun", "above_horizon", {"elevation": 60, "azimuth": 180, "rising": False}
    )
    return entry


async def test_plain_turn_on_gets_adaptive_values(hass: HomeAssistant) -> None:
    entry = await _add_entry(hass)
    target = entry.runtime_data.compute_target()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await hass.async_block_till_done()

    state = hass.states.get(LIGHT)
    assert state.state == "on"
    assert state.attributes["color_mode"] == "color_temp"
    assert state.attributes["brightness"] == brightness_to_255(target.brightness_pct)
    lo = state.attributes["min_color_temp_kelvin"]
    hi = state.attributes["max_color_temp_kelvin"]
    assert state.attributes["color_temp_kelvin"] == max(lo, min(hi, target.kelvin))
    assert entry.runtime_data.manual_lights() == {}


async def test_turn_on_with_brightness_keeps_it(hass: HomeAssistant) -> None:
    entry = await _add_entry(hass)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": LIGHT, "brightness": 40}, blocking=True
    )
    await hass.async_block_till_done()

    state = hass.states.get(LIGHT)
    assert state.attributes["brightness"] == 40
    assert state.attributes["color_mode"] == "color_temp"
    assert entry.runtime_data.manual_lights() == {LIGHT: ["brightness"]}
