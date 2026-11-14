"""Constants for the Adaptive Lightning integration."""

from __future__ import annotations

from typing import Any

DOMAIN = "adaptive_lightning"

SUN_ENTITY = "sun.sun"

CONF_LIGHTS = "lights"
CONF_MIN_KELVIN = "min_kelvin"
CONF_MAX_KELVIN = "max_kelvin"
CONF_MAX_BRIGHTNESS = "max_brightness"
CONF_EVENING_BRIGHTNESS = "evening_brightness"
CONF_NIGHT_BRIGHTNESS = "night_brightness"
CONF_WIND_DOWN_START = "wind_down_start"
CONF_SLEEP_START = "sleep_start"
CONF_WAKE_TIME = "wake_time"
CONF_AFTERNOON_SHIFT = "afternoon_shift"
CONF_CONTINUOUS = "continuous"
CONF_INTERVAL = "interval"
CONF_TURN_ON_TRANSITION = "turn_on_transition"
CONF_UPDATE_TRANSITION = "update_transition"
CONF_USE_WEATHER = "use_weather"
CONF_WEATHER_ENTITY = "weather_entity"

DEFAULTS: dict[str, Any] = {
    CONF_MIN_KELVIN: 2200,
    CONF_MAX_KELVIN: 5500,
    CONF_MAX_BRIGHTNESS: 100,
    CONF_EVENING_BRIGHTNESS: 70,
    CONF_NIGHT_BRIGHTNESS: 20,
    CONF_WIND_DOWN_START: "21:00:00",
    CONF_SLEEP_START: "23:00:00",
    CONF_WAKE_TIME: "06:00:00",
    CONF_AFTERNOON_SHIFT: 15,
    CONF_CONTINUOUS: True,
    CONF_INTERVAL: 300,
    CONF_TURN_ON_TRANSITION: 1,
    CONF_UPDATE_TRANSITION: 30,
    CONF_USE_WEATHER: False,
}

# Attribute groups tracked for "manual control".
ATTR_GROUP_BRIGHTNESS = "brightness"
ATTR_GROUP_COLOR = "color"

# light.turn_on parameters that mean the caller chose a value explicitly.
EXPLICIT_BRIGHTNESS_KEYS = frozenset(
    {"brightness", "brightness_pct", "brightness_step", "brightness_step_pct"}
)
EXPLICIT_COLOR_KEYS = frozenset(
    {
        "color_temp",
        "color_temp_kelvin",
        "kelvin",
        "hs_color",
        "rgb_color",
        "rgbw_color",
        "rgbww_color",
        "xy_color",
        "color_name",
        "white",
        "effect",
    }
)
# A profile may set both brightness and colour.
EXPLICIT_BOTH_KEYS = frozenset({"profile"})

EXPLICIT_CONTEXT_TTL = 10.0  # seconds a service-call context is remembered
OWN_CONTEXT_TTL = 120.0
MANUAL_GRACE = 5.0  # seconds after a transition during which reports are ignored
