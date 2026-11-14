"""Tests against a real Home Assistant core (needs pytest-homeassistant-custom-component)."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import Context, HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_mock_service,
)

from custom_components.adaptive_lightning import manager as manager_mod  # noqa: E402
from custom_components.adaptive_lightning.calc import brightness_to_255  # noqa: E402
from custom_components.adaptive_lightning.const import DEFAULTS, DOMAIN  # noqa: E402

CT = "light.ct"  # colour temperature, 2700-6500 K, supports transition
NARROW = "light.narrow"  # colour temperature, 2000-4000 K
DIM = "light.dim"  # brightness only
RGB = "light.rgb"  # colour only, no colour temperature mode
ONOFF = "light.onoff"

ATTRS = {
    CT: {
        "supported_color_modes": ["color_temp", "hs"],
        "min_color_temp_kelvin": 2700,
        "max_color_temp_kelvin": 6500,
        "supported_features": 32,
    },
    NARROW: {
        "supported_color_modes": ["color_temp"],
        "min_color_temp_kelvin": 2000,
        "max_color_temp_kelvin": 4000,
    },
    DIM: {"supported_color_modes": ["brightness"]},
    RGB: {"supported_color_modes": ["hs"]},
    ONOFF: {"supported_color_modes": ["onoff"]},
}


@pytest.fixture
def expected_lingering_timers() -> bool:
    # The core sun integration (a dependency) leaves its own polling timer behind.
    return True


@pytest.fixture(autouse=True)
async def _environment(hass: HomeAssistant, enable_custom_integrations, freezer):
    # 13:00 local time (the test instance runs in US/Pacific): outside the night window.
    freezer.move_to("2026-06-21 20:00:00+00:00")
    yield
    for entry in hass.config_entries.async_entries():
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def set_sun(hass: HomeAssistant, elevation: float, azimuth: float = 180.0) -> None:
    hass.states.async_set(
        "sun.sun",
        "above_horizon" if elevation > 0 else "below_horizon",
        {"elevation": elevation, "azimuth": azimuth, "rising": azimuth < 180},
    )


def set_light(hass: HomeAssistant, entity_id: str, state: str, context=None, **extra):
    hass.states.async_set(
        entity_id, state, {**ATTRS[entity_id], **extra}, context=context
    )


async def setup(hass: HomeAssistant, **options):
    calls = async_mock_service(hass, "light", "turn_on")
    for entity_id in ATTRS:
        set_light(hass, entity_id, "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={"lights": list(ATTRS)},
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


def data_of(call) -> dict:
    return {k: v for k, v in call.data.items() if k != "entity_id"}


async def test_turn_on_clamps_to_each_lights_range(hass: HomeAssistant) -> None:
    entry, calls = await setup(hass)
    set_sun(hass, 60)  # high sun -> target is the coolest setting (5500 K)
    target = entry.runtime_data.compute_target()

    for entity_id in ATTRS:
        set_light(hass, entity_id, "on")
    await hass.async_block_till_done()

    by_light = {c.data["entity_id"]: data_of(c) for c in calls}
    bri = brightness_to_255(target.brightness_pct)
    assert target.kelvin > 4000
    assert by_light[CT] == {
        "brightness": bri,
        "color_temp_kelvin": target.kelvin,
        "transition": 1.0,
    }
    assert by_light[NARROW] == {"brightness": bri, "color_temp_kelvin": 4000}
    assert by_light[DIM] == {"brightness": bri}
    assert by_light[RGB] == {"brightness": bri}  # never a colour
    assert ONOFF not in by_light


async def test_warm_end_is_clamped_too(hass: HomeAssistant) -> None:
    _, calls = await setup(hass)
    set_sun(hass, -30)  # night -> 2200 K wanted
    set_light(hass, CT, "on")
    set_light(hass, NARROW, "on")
    await hass.async_block_till_done()
    by_light = {c.data["entity_id"]: data_of(c) for c in calls}
    assert by_light[CT]["color_temp_kelvin"] == 2700
    assert by_light[NARROW]["color_temp_kelvin"] == 2200


async def test_explicit_brightness_is_respected(hass: HomeAssistant) -> None:
    entry, calls = await setup(hass)
    set_sun(hass, -30)
    ctx = Context()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": CT, "brightness": 30}, context=ctx
    )
    calls.clear()
    set_light(hass, CT, "on", context=ctx, brightness=30)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert "brightness" not in calls[0].data
    assert calls[0].data["color_temp_kelvin"] == 2700
    assert entry.runtime_data.manual_lights() == {CT: ["brightness"]}

    # Turning off and on again (plain) restores full adaptation.
    set_light(hass, CT, "off")
    calls.clear()
    set_light(hass, CT, "on")
    await hass.async_block_till_done()
    assert "brightness" in calls[0].data


async def test_explicit_colour_is_respected(hass: HomeAssistant) -> None:
    _, calls = await setup(hass)
    set_sun(hass, -30)
    ctx = Context()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": CT, "rgb_color": [255, 0, 0]}, context=ctx
    )
    calls.clear()
    set_light(hass, CT, "on", context=ctx, color_mode="hs")
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert "color_temp_kelvin" not in calls[0].data
    assert "brightness" in calls[0].data


async def test_manual_change_pauses_periodic_updates(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manager_mod, "MANUAL_GRACE", -100.0)
    entry, calls = await setup(hass)
    manager = entry.runtime_data
    set_sun(hass, -30)
    set_light(hass, NARROW, "on")
    await hass.async_block_till_done()
    applied = data_of(calls[0])

    # The device reports what we set (our context) - not manual.
    set_light(hass, NARROW, "on", context=calls[0].context, **applied)
    await hass.async_block_till_done()
    assert manager.manual_lights() == {}

    # Someone dims the light by hand.
    set_light(hass, NARROW, "on", **{**applied, "brightness": 200})
    await hass.async_block_till_done()
    assert manager.manual_lights() == {NARROW: ["brightness"]}

    # The sun rises; a periodic update only touches the colour temperature.
    calls.clear()
    set_sun(hass, 60)
    await manager.async_update_all(30)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert data_of(calls[0]) == {"color_temp_kelvin": 4000}


async def test_periodic_update_skips_lights_already_on_target(
    hass: HomeAssistant,
) -> None:
    entry, calls = await setup(hass)
    set_sun(hass, -30)
    set_light(hass, NARROW, "on")
    await hass.async_block_till_done()
    set_light(
        hass,
        NARROW,
        "on",
        context=calls[0].context,
        color_mode="color_temp",
        **data_of(calls[0]),
    )
    calls.clear()
    await entry.runtime_data.async_update_all(30)
    await hass.async_block_till_done()
    assert calls == []


async def test_switch_disables_adaptation(hass: HomeAssistant) -> None:
    _, calls = await setup(hass)
    set_sun(hass, 60)
    switch = hass.states.async_entity_ids("switch")[0]
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    set_light(hass, CT, "on")
    await hass.async_block_till_done()
    assert calls == []

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch}, blocking=True
    )
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in calls] == [CT]


async def test_weather_changes_target_only_when_enabled(hass: HomeAssistant) -> None:
    hass.states.async_set("weather.home", "rainy")
    entry, _ = await setup(hass)
    set_sun(hass, 20, 120)
    without = entry.runtime_data.compute_target()

    hass.config_entries.async_update_entry(
        entry, options={"use_weather": True, "weather_entity": "weather.home"}
    )
    await hass.async_block_till_done()
    set_sun(hass, 20, 120)
    with_weather = entry.runtime_data.compute_target()
    assert with_weather.kelvin < without.kelvin


async def test_sensors_expose_target(hass: HomeAssistant) -> None:
    entry, _ = await setup(hass)
    set_sun(hass, -30)
    entry.runtime_data.compute_target()
    await hass.async_block_till_done()
    values = {
        s.attributes["unit_of_measurement"]: s.state
        for s in hass.states.async_all("sensor")
        if s.entity_id.startswith("sensor.test_")
    }
    assert values["K"] == "2200"


async def test_config_and_options_flow(hass: HomeAssistant) -> None:
    async_mock_service(hass, "light", "turn_on")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Salon", "lights": [CT]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"lights": [CT]}
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    # Weather is off unless the user turns it on.
    assert entry.runtime_data.weather_entity is None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    base = {**DEFAULTS, "lights": [CT]}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "use_weather": True}
    )
    assert result["errors"] == {"weather_entity": "weather_required"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**base, "use_weather": True, "weather_entity": "weather.home"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.weather_entity == "weather.home"
