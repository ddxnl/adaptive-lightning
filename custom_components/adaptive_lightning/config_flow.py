"""Config and options flow for Adaptive Lightning."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AFTERNOON_SHIFT,
    CONF_CONTINUOUS,
    CONF_EVENING_BRIGHTNESS,
    CONF_INTERVAL,
    CONF_LIGHTS,
    CONF_MAX_BRIGHTNESS,
    CONF_MAX_KELVIN,
    CONF_MIN_KELVIN,
    CONF_NIGHT_BRIGHTNESS,
    CONF_SLEEP_START,
    CONF_TURN_ON_TRANSITION,
    CONF_UPDATE_TRANSITION,
    CONF_USE_WEATHER,
    CONF_WAKE_TIME,
    CONF_WEATHER_ENTITY,
    CONF_WIND_DOWN_START,
    DEFAULTS,
    DOMAIN,
)

LIGHTS_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="light", multiple=True)
)


def _number(
    minimum: float, maximum: float, step: float, unit: str, slider: bool = False
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.SLIDER
            if slider
            else selector.NumberSelectorMode.BOX,
        )
    )


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIGHTS): LIGHTS_SELECTOR,
        vol.Required(CONF_MIN_KELVIN): _number(1000, 10000, 50, "K"),
        vol.Required(CONF_MAX_KELVIN): _number(1000, 10000, 50, "K"),
        vol.Required(CONF_MAX_BRIGHTNESS): _number(1, 100, 1, "%", slider=True),
        vol.Required(CONF_EVENING_BRIGHTNESS): _number(1, 100, 1, "%", slider=True),
        vol.Required(CONF_NIGHT_BRIGHTNESS): _number(1, 100, 1, "%", slider=True),
        vol.Required(CONF_WIND_DOWN_START): selector.TimeSelector(),
        vol.Required(CONF_SLEEP_START): selector.TimeSelector(),
        vol.Required(CONF_WAKE_TIME): selector.TimeSelector(),
        vol.Required(CONF_AFTERNOON_SHIFT): _number(0, 50, 1, "%", slider=True),
        vol.Required(CONF_CONTINUOUS): selector.BooleanSelector(),
        vol.Required(CONF_INTERVAL): _number(30, 3600, 10, "s"),
        vol.Required(CONF_TURN_ON_TRANSITION): _number(0, 10, 0.5, "s"),
        vol.Required(CONF_UPDATE_TRANSITION): _number(0, 300, 1, "s"),
        vol.Required(CONF_USE_WEATHER): selector.BooleanSelector(),
        vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="weather")
        ),
    }
)


class AdaptiveLightningConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create an adaptive profile: a name and the lights it controls."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return AdaptiveLightningOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_LIGHTS):
                errors[CONF_LIGHTS] = "no_lights"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_LIGHTS: user_input[CONF_LIGHTS]},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Adaptive Lightning"): str,
                vol.Required(CONF_LIGHTS): LIGHTS_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )


class AdaptiveLightningOptionsFlow(OptionsFlow):
    """Tune the profile; the optional weather entity lives here."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_LIGHTS):
                errors[CONF_LIGHTS] = "no_lights"
            if user_input[CONF_MIN_KELVIN] >= user_input[CONF_MAX_KELVIN]:
                errors[CONF_MAX_KELVIN] = "kelvin_range"
            if not (
                user_input[CONF_NIGHT_BRIGHTNESS]
                <= user_input[CONF_EVENING_BRIGHTNESS]
                <= user_input[CONF_MAX_BRIGHTNESS]
            ):
                errors[CONF_EVENING_BRIGHTNESS] = "brightness_order"
            if user_input[CONF_USE_WEATHER] and not user_input.get(CONF_WEATHER_ENTITY):
                errors[CONF_WEATHER_ENTITY] = "weather_required"
            if not errors:
                return self.async_create_entry(data=user_input)

        current = user_input or {
            **DEFAULTS,
            **self.config_entry.data,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, current),
            errors=errors,
        )
