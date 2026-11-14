"""Runtime logic: watch lights and apply adaptive brightness / colour temperature."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging
from time import monotonic
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_MAX_COLOR_TEMP_KELVIN,
    ATTR_MIN_COLOR_TEMP_KELVIN,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    DOMAIN as LIGHT_DOMAIN,
    ColorMode,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    EVENT_CALL_SERVICE,
    SERVICE_TOGGLE,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .calc import (
    Inputs,
    Settings,
    Target,
    brightness_to_255,
    clamp_kelvin,
    cloudiness_from_weather,
    compute,
)
from .const import (
    ATTR_GROUP_BRIGHTNESS,
    ATTR_GROUP_COLOR,
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
    EXPLICIT_BOTH_KEYS,
    EXPLICIT_BRIGHTNESS_KEYS,
    EXPLICIT_COLOR_KEYS,
    EXPLICIT_CONTEXT_TTL,
    MANUAL_GRACE,
    OWN_CONTEXT_TTL,
    SUN_ENTITY,
)

_LOGGER = logging.getLogger(__name__)

# Tolerances below which a value counts as "what we asked for".
BRIGHTNESS_TOLERANCE = 8  # of 255 (~3%)
KELVIN_TOLERANCE = 0.03  # relative; covers mired rounding in devices
# Differences too small to be worth sending a command.
BRIGHTNESS_SKIP = 2
KELVIN_SKIP = 25


@dataclass
class _Applied:
    """What we last asked a light to do."""

    brightness: int | None
    kelvin: int | None
    settle_at: float  # monotonic time after which device reports are trusted


def _parse_time(value: Any, default: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return time.fromisoformat(default)


def build_settings(config: Mapping[str, Any]) -> Settings:
    """Build calculation settings from config entry data."""
    return Settings(
        min_kelvin=int(config[CONF_MIN_KELVIN]),
        max_kelvin=int(config[CONF_MAX_KELVIN]),
        max_brightness=float(config[CONF_MAX_BRIGHTNESS]),
        evening_brightness=float(config[CONF_EVENING_BRIGHTNESS]),
        night_brightness=float(config[CONF_NIGHT_BRIGHTNESS]),
        wind_down_start=_parse_time(
            config[CONF_WIND_DOWN_START], DEFAULTS[CONF_WIND_DOWN_START]
        ),
        sleep_start=_parse_time(config[CONF_SLEEP_START], DEFAULTS[CONF_SLEEP_START]),
        wake_time=_parse_time(config[CONF_WAKE_TIME], DEFAULTS[CONF_WAKE_TIME]),
        afternoon_shift=float(config[CONF_AFTERNOON_SHIFT]) / 100.0,
    )


def signal_update(entry_id: str) -> str:
    """Dispatcher signal sent whenever the target values are recomputed."""
    return f"{DOMAIN}_{entry_id}_update"


def supports_brightness(modes: list[str]) -> bool:
    """Return True if any supported colour mode is dimmable."""
    return any(mode not in (ColorMode.ONOFF, ColorMode.UNKNOWN) for mode in modes)


class AdaptiveManager:
    """Applies adaptive values to the lights of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        config = {**DEFAULTS, **entry.data, **entry.options}
        self.config = config
        self.lights: list[str] = list(config.get(CONF_LIGHTS, []))
        self.settings = build_settings(config)
        self.weather_entity: str | None = (
            config.get(CONF_WEATHER_ENTITY) if config[CONF_USE_WEATHER] else None
        )
        self.continuous: bool = bool(config[CONF_CONTINUOUS])
        self.interval = timedelta(seconds=max(10, int(config[CONF_INTERVAL])))
        self.turn_on_transition = float(config[CONF_TURN_ON_TRANSITION])
        self.update_transition = float(config[CONF_UPDATE_TRANSITION])

        self.enabled = True
        self.target: Target | None = None
        self._manual: dict[str, set[str]] = {}
        self._applied: dict[str, _Applied] = {}
        self._own_contexts: dict[str, float] = {}
        self._explicit: dict[str, tuple[set[str], float]] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._warned_no_sun = False

    # ------------------------------------------------------------------ setup

    async def async_start(self) -> None:
        """Start listening and adapt lights that are already on."""
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, self.lights, self._handle_light_event
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._handle_call_service)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._handle_interval, self.interval)
        )
        if self.weather_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.weather_entity], self._handle_weather_event
                )
            )
        await self.async_update_all(self.turn_on_transition)

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        while self._unsubs:
            self._unsubs.pop()()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable adaptation."""
        self.enabled = enabled
        if enabled:
            await self.async_update_all(self.turn_on_transition)

    def manual_lights(self) -> dict[str, list[str]]:
        """Return lights currently under manual control, for diagnostics."""
        return {eid: sorted(attrs) for eid, attrs in self._manual.items() if attrs}

    # ------------------------------------------------------------ calculation

    def compute_target(self, now: datetime | None = None) -> Target | None:
        """Compute target values from the sun, the clock and the weather."""
        sun = self.hass.states.get(SUN_ENTITY)
        elevation = None
        if sun is not None:
            try:
                elevation = float(sun.attributes.get("elevation"))
            except (TypeError, ValueError):
                elevation = None
        if sun is None or elevation is None:
            if not self._warned_no_sun:
                _LOGGER.warning(
                    "%s is not available; adaptive lighting is paused until it is",
                    SUN_ENTITY,
                )
                self._warned_no_sun = True
            return None
        self._warned_no_sun = False

        azimuth: float | None
        try:
            azimuth = float(sun.attributes.get("azimuth"))
        except (TypeError, ValueError):
            azimuth = None

        cloudiness = None
        if self.weather_entity:
            weather = self.hass.states.get(self.weather_entity)
            if weather is not None and weather.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                cloudiness = cloudiness_from_weather(
                    weather.state, weather.attributes.get("cloud_coverage")
                )

        inputs = Inputs(
            elevation=elevation,
            azimuth=azimuth,
            rising=sun.attributes.get("rising"),
            latitude=self.hass.config.latitude,
            now=now or dt_util.now(),
            cloudiness=cloudiness,
        )
        self.target = compute(inputs, self.settings)
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
        return self.target

    # ----------------------------------------------------------------- events

    def _prune(self) -> None:
        now = monotonic()
        for ctx_id, created in list(self._own_contexts.items()):
            if now - created > OWN_CONTEXT_TTL:
                del self._own_contexts[ctx_id]
        for ctx_id, (_, created) in list(self._explicit.items()):
            if now - created > EXPLICIT_CONTEXT_TTL:
                del self._explicit[ctx_id]

    @callback
    def _handle_call_service(self, event: Event) -> None:
        """Remember service calls that set brightness or colour explicitly."""
        data = event.data
        if data.get("domain") != LIGHT_DOMAIN or data.get("service") not in (
            SERVICE_TURN_ON,
            SERVICE_TOGGLE,
        ):
            return
        if event.context.id in self._own_contexts:
            return
        keys = set(data.get("service_data") or {})
        explicit: set[str] = set()
        if keys & EXPLICIT_BRIGHTNESS_KEYS:
            explicit.add(ATTR_GROUP_BRIGHTNESS)
        if keys & EXPLICIT_COLOR_KEYS:
            explicit.add(ATTR_GROUP_COLOR)
        if keys & EXPLICIT_BOTH_KEYS:
            explicit.update((ATTR_GROUP_BRIGHTNESS, ATTR_GROUP_COLOR))
        if not explicit:
            return
        self._prune()
        self._explicit[event.context.id] = (explicit, monotonic())

    def _explicit_for(self, context_id: str) -> set[str]:
        entry = self._explicit.get(context_id)
        if entry is None or monotonic() - entry[1] > EXPLICIT_CONTEXT_TTL:
            return set()
        return entry[0]

    @callback
    def _handle_light_event(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old = event.data["old_state"]
        new = event.data["new_state"]

        if new is None or new.state == STATE_OFF:
            # Turning off ends manual control: next turn-on adapts again.
            self._manual.pop(entity_id, None)
            self._applied.pop(entity_id, None)
            return
        if new.state != STATE_ON:
            return

        own = new.context.id in self._own_contexts
        was_on = old is not None and old.state == STATE_ON

        if not was_on:
            if own or not self.enabled:
                return
            explicit = self._explicit_for(new.context.id)
            if explicit:
                self._manual.setdefault(entity_id, set()).update(explicit)
            self.hass.async_create_task(
                self._async_apply(entity_id, self.turn_on_transition),
                f"{DOMAIN} adapt {entity_id}",
            )
            return

        if not own and old is not None:
            self._detect_manual(entity_id, old, new)

    def _detect_manual(self, entity_id: str, old: State, new: State) -> None:
        """Mark attributes changed by someone else as manually controlled."""
        manual = self._manual.setdefault(entity_id, set())
        before = set(manual)
        manual.update(self._explicit_for(new.context.id))

        applied = self._applied.get(entity_id)
        if applied is not None and monotonic() >= applied.settle_at:
            new_bri = new.attributes.get(ATTR_BRIGHTNESS)
            old_bri = old.attributes.get(ATTR_BRIGHTNESS)
            if (
                applied.brightness is not None
                and new_bri is not None
                and new_bri != old_bri
                and abs(new_bri - applied.brightness) > BRIGHTNESS_TOLERANCE
            ):
                manual.add(ATTR_GROUP_BRIGHTNESS)

            if applied.kelvin is not None:
                new_k = new.attributes.get(ATTR_COLOR_TEMP_KELVIN)
                old_k = old.attributes.get(ATTR_COLOR_TEMP_KELVIN)
                new_mode = new.attributes.get(ATTR_COLOR_MODE)
                old_mode = old.attributes.get(ATTR_COLOR_MODE)
                if new_mode != old_mode and new_mode != ColorMode.COLOR_TEMP:
                    # Someone switched the light to a colour.
                    manual.add(ATTR_GROUP_COLOR)
                elif (
                    new_k is not None
                    and new_k != old_k
                    and abs(new_k - applied.kelvin) > KELVIN_TOLERANCE * applied.kelvin
                ):
                    manual.add(ATTR_GROUP_COLOR)

        if manual != before:
            _LOGGER.debug(
                "%s: manual control of %s detected; paused until turned off",
                entity_id,
                sorted(manual - before),
            )

    @callback
    def _handle_weather_event(self, event: Event[EventStateChangedData]) -> None:
        old = event.data["old_state"]
        new = event.data["new_state"]
        if old is not None and new is not None and old.state == new.state:
            if old.attributes.get("cloud_coverage") == new.attributes.get(
                "cloud_coverage"
            ):
                return
        self.hass.async_create_task(
            self._async_periodic(), f"{DOMAIN} weather update"
        )

    async def _handle_interval(self, _now: datetime) -> None:
        await self._async_periodic()

    async def _async_periodic(self) -> None:
        self._prune()
        if self.enabled and self.continuous:
            await self.async_update_all(self.update_transition)
        else:
            self.compute_target()  # keep the sensors fresh

    # ------------------------------------------------------------------ apply

    async def async_update_all(self, transition: float) -> None:
        """Adapt every light that is currently on."""
        target = self.compute_target()
        if target is None or not self.enabled:
            return
        for entity_id in self.lights:
            await self._async_apply(entity_id, transition, target)

    async def _async_apply(
        self, entity_id: str, transition: float, target: Target | None = None
    ) -> None:
        """Send adaptive values to one light, respecting its capabilities."""
        if not self.enabled:
            return
        state = self.hass.states.get(entity_id)
        if state is None or state.state != STATE_ON:
            return
        if target is None:
            target = self.compute_target()
            if target is None:
                return

        attrs = state.attributes
        modes = list(attrs.get(ATTR_SUPPORTED_COLOR_MODES) or [])
        manual = self._manual.get(entity_id, set())
        service_data: dict[str, Any] = {}
        applied_bri: int | None = None
        applied_kelvin: int | None = None

        if ATTR_GROUP_BRIGHTNESS not in manual and supports_brightness(modes):
            applied_bri = brightness_to_255(target.brightness_pct)
            current = attrs.get(ATTR_BRIGHTNESS)
            if current is None or abs(current - applied_bri) > BRIGHTNESS_SKIP:
                service_data[ATTR_BRIGHTNESS] = applied_bri

        # Only ever colour temperature, never colours. Each light is clamped
        # to the range it reports.
        if ATTR_GROUP_COLOR not in manual and ColorMode.COLOR_TEMP in modes:
            applied_kelvin = clamp_kelvin(
                target.kelvin,
                attrs.get(ATTR_MIN_COLOR_TEMP_KELVIN),
                attrs.get(ATTR_MAX_COLOR_TEMP_KELVIN),
            )
            current = attrs.get(ATTR_COLOR_TEMP_KELVIN)
            if (
                current is None
                or attrs.get(ATTR_COLOR_MODE) != ColorMode.COLOR_TEMP
                or abs(current - applied_kelvin) > KELVIN_SKIP
            ):
                service_data[ATTR_COLOR_TEMP_KELVIN] = applied_kelvin

        use_transition = 0.0
        if service_data:
            features = attrs.get(ATTR_SUPPORTED_FEATURES) or 0
            if transition > 0 and features & LightEntityFeature.TRANSITION:
                use_transition = transition
                service_data[ATTR_TRANSITION] = transition

        self._applied[entity_id] = _Applied(
            brightness=applied_bri,
            kelvin=applied_kelvin,
            settle_at=monotonic() + use_transition + MANUAL_GRACE,
        )
        if not service_data:
            return

        context = Context()
        self._own_contexts[context.id] = monotonic()
        service_data[ATTR_ENTITY_ID] = entity_id
        _LOGGER.debug("Adapting %s: %s", entity_id, service_data)
        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_ON,
                service_data,
                blocking=False,
                context=context,
            )
        except Exception:  # noqa: BLE001 - one bad light must not stop the rest
            _LOGGER.exception("Failed to adapt %s", entity_id)


AdaptiveConfigEntry = ConfigEntry[AdaptiveManager]