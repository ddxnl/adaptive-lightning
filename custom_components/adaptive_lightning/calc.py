"""Pure calculation of adaptive brightness and colour temperature.

This module deliberately has no Home Assistant imports so it can be unit
tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
import math

TWILIGHT_ELEVATION = -6.0  # civil twilight: below this the sun contributes nothing
PEAK_ELEVATION_MIN = 8.0  # never require less than this for "full daylight"
PEAK_ELEVATION_MAX = 30.0  # above this it is always "full daylight"
PEAK_FRACTION = 0.9  # full daylight is reached at 90% of today's noon elevation
WEATHER_WARMTH = 0.15  # max reduction of the colour factor under full overcast
WEATHER_BRIGHTNESS_BOOST = 0.6  # how far overcast pushes brightness towards max
WAKE_RAMP_MINUTES = 30

# Weather condition -> cloudiness (0 clear .. 1 overcast).
CONDITION_CLOUDINESS: dict[str, float] = {
    "sunny": 0.0,
    "clear-night": 0.0,
    "windy": 0.2,
    "partlycloudy": 0.4,
    "windy-variant": 0.6,
    "cloudy": 0.8,
    "hail": 0.9,
    "lightning": 0.9,
    "fog": 1.0,
    "rainy": 1.0,
    "pouring": 1.0,
    "lightning-rainy": 1.0,
    "snowy": 1.0,
    "snowy-rainy": 1.0,
    "exceptional": 0.5,
}


@dataclass(frozen=True)
class Settings:
    """User settings of one adaptive profile."""

    min_kelvin: int = 2200
    max_kelvin: int = 5500
    max_brightness: float = 100.0
    evening_brightness: float = 70.0
    night_brightness: float = 20.0
    wind_down_start: time = time(21, 0)
    sleep_start: time = time(23, 0)
    wake_time: time = time(6, 0)
    afternoon_shift: float = 0.15  # 0..1, how much warmer the afternoon is


@dataclass(frozen=True)
class Inputs:
    """Current conditions."""

    elevation: float
    azimuth: float | None
    rising: bool | None
    latitude: float
    now: datetime  # local time
    cloudiness: float | None = None  # 0..1, None = weather not used


@dataclass(frozen=True)
class Target:
    """Computed target values."""

    kelvin: int
    brightness_pct: float
    sun_factor: float
    night_factor: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _smoothstep(x: float) -> float:
    x = _clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def noon_elevation(latitude: float, day_of_year: int) -> float:
    """Approximate elevation of the sun at solar noon, in degrees."""
    declination = 23.44 * math.sin(2.0 * math.pi * (284 + day_of_year) / 365.0)
    return 90.0 - abs(latitude - declination)


def sun_factor(elevation: float, latitude: float, day_of_year: int) -> float:
    """Return 0..1: how much "daylight" the sun's elevation represents today.

    The elevation is normalised against today's noon elevation, so that a low
    winter sun still reaches the full daytime setting.
    """
    peak = _clamp(
        noon_elevation(latitude, day_of_year) * PEAK_FRACTION,
        PEAK_ELEVATION_MIN,
        PEAK_ELEVATION_MAX,
    )
    raw = (elevation - TWILIGHT_ELEVATION) / (peak - TWILIGHT_ELEVATION)
    return _smoothstep(raw)


def afternoon_weight(azimuth: float | None, rising: bool | None) -> float:
    """Return 0..1: how far the sun is into the western (afternoon) sky.

    The sun is east of the meridian (azimuth < 180) before solar noon and west
    of it afterwards, in both hemispheres. The weight ramps up smoothly over
    the first 30 degrees past the meridian so there is no jump at noon.
    """
    if azimuth is None:
        return 0.0 if rising or rising is None else 1.0
    westness = -math.sin(math.radians(azimuth))
    return _clamp(westness / 0.5, 0.0, 1.0)


def night_factor(now: time, settings: Settings) -> float:
    """Return 0..1: how deep into the night window the given time is.

    0 before wind-down, ramps linearly to 1 at sleep start, stays 1 until the
    wake time, then ramps back to 0 over WAKE_RAMP_MINUTES.
    """

    def minutes(t: time) -> float:
        return t.hour * 60 + t.minute + t.second / 60.0

    day = 24 * 60
    start = minutes(settings.wind_down_start)
    x = (minutes(now) - start) % day
    to_sleep = (minutes(settings.sleep_start) - start) % day
    to_wake = max((minutes(settings.wake_time) - start) % day, to_sleep)
    to_end = min(to_wake + WAKE_RAMP_MINUTES, day)

    if x < to_sleep:
        return x / to_sleep
    if x < to_wake:
        return 1.0
    if x < to_end:
        return 1.0 - (x - to_wake) / (to_end - to_wake)
    return 0.0


def compute(inputs: Inputs, settings: Settings) -> Target:
    """Compute the target colour temperature and brightness."""
    min_k = min(settings.min_kelvin, settings.max_kelvin)
    max_k = max(settings.min_kelvin, settings.max_kelvin)
    max_bri = _clamp(settings.max_brightness, 1.0, 100.0)
    evening_bri = _clamp(settings.evening_brightness, 1.0, max_bri)
    night_bri = _clamp(settings.night_brightness, 1.0, evening_bri)

    day_of_year = inputs.now.timetuple().tm_yday
    factor = sun_factor(inputs.elevation, inputs.latitude, day_of_year)

    # Azimuth: the afternoon/evening is warmer than the morning.
    shift = _clamp(settings.afternoon_shift, 0.0, 1.0)
    factor *= 1.0 - shift * afternoon_weight(inputs.azimuth, inputs.rising)

    color_factor = factor
    brightness_factor = factor

    # Weather only matters while the sun is up; fade the effect in over the
    # first degrees above the horizon to avoid a jump at sunrise/sunset.
    if inputs.cloudiness is not None:
        cloud = _clamp(inputs.cloudiness, 0.0, 1.0) * _clamp(
            inputs.elevation / 6.0, 0.0, 1.0
        )
        color_factor *= 1.0 - WEATHER_WARMTH * cloud
        brightness_factor += (1.0 - brightness_factor) * WEATHER_BRIGHTNESS_BOOST * cloud

    kelvin = min_k + (max_k - min_k) * color_factor
    brightness = evening_bri + (max_bri - evening_bri) * brightness_factor

    # Time of day: the night window pulls everything towards warm and dim.
    night = night_factor(inputs.now.time(), settings)
    kelvin += (min_k - kelvin) * night
    brightness += (night_bri - brightness) * night

    return Target(
        kelvin=int(round(kelvin)),
        brightness_pct=round(brightness, 1),
        sun_factor=round(factor, 4),
        night_factor=round(night, 4),
    )


def clamp_kelvin(kelvin: int, light_min: int | None, light_max: int | None) -> int:
    """Clamp a colour temperature to the range a light supports."""
    if light_min is not None and light_max is not None and light_min > light_max:
        light_min, light_max = light_max, light_min
    if light_min is not None:
        kelvin = max(kelvin, int(light_min))
    if light_max is not None:
        kelvin = min(kelvin, int(light_max))
    return kelvin


def brightness_to_255(brightness_pct: float) -> int:
    """Convert a percentage to Home Assistant's 1..255 brightness."""
    return int(_clamp(round(brightness_pct * 255.0 / 100.0), 1, 255))


def cloudiness_from_weather(
    condition: str | None, cloud_coverage: float | None
) -> float | None:
    """Return cloudiness 0..1 from a weather entity, or None if unknown."""
    if cloud_coverage is not None:
        try:
            return _clamp(float(cloud_coverage) / 100.0, 0.0, 1.0)
        except (TypeError, ValueError):
            pass
    if condition is None:
        return None
    return CONDITION_CLOUDINESS.get(condition)
