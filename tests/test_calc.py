"""Unit tests for the pure calculation module (no Home Assistant needed)."""

from __future__ import annotations

from datetime import datetime, time
import importlib.util
from pathlib import Path
import sys

import pytest

_PATH = (
    Path(__file__).parent.parent / "custom_components" / "adaptive_lightning" / "calc.py"
)
_spec = importlib.util.spec_from_file_location("adaptive_lightning_calc", _PATH)
calc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = calc
_spec.loader.exec_module(calc)

WARSAW = 52.2
S = calc.Settings()


def run(elevation, azimuth, when, *, lat=WARSAW, cloud=None, settings=S, rising=None):
    return calc.compute(
        calc.Inputs(
            elevation=elevation,
            azimuth=azimuth,
            rising=rising,
            latitude=lat,
            now=when,
            cloudiness=cloud,
        ),
        settings,
    )


def test_summer_noon_is_cool_and_bright():
    t = run(61, 180, datetime(2026, 6, 21, 12, 45))
    assert t.kelvin == 5500
    assert t.brightness_pct == 100


def test_winter_noon_still_reaches_full_daylight():
    # Noon elevation in Warsaw in December is only about 14 degrees.
    t = run(14.3, 180, datetime(2026, 12, 21, 11, 40))
    assert t.kelvin == 5500
    assert t.brightness_pct == 100


def test_afternoon_is_warmer_than_morning_at_same_elevation():
    morning = run(20, 100, datetime(2026, 6, 21, 7, 0))
    afternoon = run(20, 260, datetime(2026, 6, 21, 17, 30))
    assert afternoon.kelvin < morning.kelvin
    assert afternoon.brightness_pct < morning.brightness_pct


def test_no_jump_at_solar_noon():
    before = run(40, 179.5, datetime(2026, 6, 21, 12, 44))
    after = run(40, 180.5, datetime(2026, 6, 21, 12, 46))
    assert abs(before.kelvin - after.kelvin) < 30


def test_azimuth_missing_falls_back_to_rising():
    rising = run(20, None, datetime(2026, 6, 21, 7, 0), rising=True)
    setting = run(20, None, datetime(2026, 6, 21, 17, 30), rising=False)
    assert setting.kelvin < rising.kelvin


def test_winter_sunset_keeps_evening_brightness():
    # 16:30 in December: dark outside, but far from bedtime.
    t = run(-10, 245, datetime(2026, 12, 21, 16, 30))
    assert t.kelvin == 2200
    assert t.brightness_pct == 70


def test_wind_down_ramps_to_night():
    half = run(-20, 300, datetime(2026, 12, 21, 22, 0))
    assert half.brightness_pct == pytest.approx(45)
    night = run(-30, 350, datetime(2026, 12, 21, 23, 30))
    assert night.brightness_pct == 20
    assert night.kelvin == 2200


def test_night_window_crosses_midnight():
    t = run(-40, 10, datetime(2026, 12, 22, 3, 0))
    assert t.brightness_pct == 20
    assert t.night_factor == 1


def test_night_caps_a_bright_summer_evening():
    # Sun is still up at 21:30 in June, but it is wind-down time.
    with_night = run(5, 300, datetime(2026, 6, 21, 22, 30))
    same_sun_daytime = run(5, 300, datetime(2026, 6, 21, 20, 0))
    assert with_night.kelvin < same_sun_daytime.kelvin
    assert with_night.brightness_pct < same_sun_daytime.brightness_pct


def test_wake_ramp():
    assert calc.night_factor(time(5, 59), S) == 1
    assert calc.night_factor(time(6, 15), S) == pytest.approx(0.5)
    assert calc.night_factor(time(6, 30), S) == 0
    assert calc.night_factor(time(12, 0), S) == 0
    assert calc.night_factor(time(21, 0), S) == 0


def test_night_window_with_sleep_after_midnight():
    s = calc.Settings(
        wind_down_start=time(23, 0), sleep_start=time(1, 0), wake_time=time(7, 0)
    )
    assert calc.night_factor(time(0, 0), s) == pytest.approx(0.5)
    assert calc.night_factor(time(3, 0), s) == 1
    assert calc.night_factor(time(22, 0), s) == 0


def test_overcast_is_warmer_and_brighter_in_daytime():
    when = datetime(2026, 10, 10, 9, 0)
    clear = run(15, 130, when, cloud=0.0)
    overcast = run(15, 130, when, cloud=1.0)
    assert overcast.kelvin < clear.kelvin
    assert overcast.brightness_pct > clear.brightness_pct


def test_weather_ignored_when_sun_is_down():
    when = datetime(2026, 12, 21, 18, 0)
    assert run(-15, 260, when, cloud=1.0) == run(-15, 260, when, cloud=None)


def test_southern_hemisphere():
    # Sydney, December (summer): sun passes north; azimuth > 180 is still afternoon.
    morning = run(30, 80, datetime(2026, 12, 21, 9, 0), lat=-33.9)
    afternoon = run(30, 280, datetime(2026, 12, 21, 16, 0), lat=-33.9)
    assert morning.kelvin == 5500
    assert afternoon.kelvin < morning.kelvin


def test_polar_night_stays_warm():
    t = run(-8, 180, datetime(2026, 12, 21, 12, 0), lat=70)
    assert t.kelvin == 2200


def test_results_stay_within_configured_bounds():
    for month in (1, 4, 7, 10):
        for hour in range(24):
            for elevation in (-30, -6, 0, 5, 20, 60):
                for azimuth in (0, 90, 180, 270, 359):
                    t = run(
                        elevation, azimuth, datetime(2026, month, 15, hour, 20), cloud=0.7
                    )
                    assert 2200 <= t.kelvin <= 5500
                    assert 20 <= t.brightness_pct <= 100


def test_clamp_kelvin_to_light_range():
    assert calc.clamp_kelvin(2200, 2700, 6500) == 2700
    assert calc.clamp_kelvin(5500, 2000, 4000) == 4000
    assert calc.clamp_kelvin(3000, 2000, 4000) == 3000
    assert calc.clamp_kelvin(3000, None, None) == 3000


def test_brightness_to_255():
    assert calc.brightness_to_255(100) == 255
    assert calc.brightness_to_255(20) == 51
    assert calc.brightness_to_255(0) == 1


def test_cloudiness_from_weather():
    assert calc.cloudiness_from_weather("sunny", None) == 0
    assert calc.cloudiness_from_weather("rainy", None) == 1
    assert calc.cloudiness_from_weather("sunny", 80) == 0.8
    assert calc.cloudiness_from_weather("something-new", None) is None
    assert calc.cloudiness_from_weather(None, None) is None
