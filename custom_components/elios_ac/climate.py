"""Climate entity that transmits complete Elios states through a remote entity.

The AC is transmit-only, so entity state is optimistic: it reflects the last
state sent (restored across restarts). Input is debounced — a burst of
adjustments becomes a single frame once the state has settled.
"""

import base64
import logging

from broadlink6 import pulses_to_data

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_NONE,
    PRESET_SLEEP,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, HomeAssistant, State as HassState, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_HUMIDITY_SENSOR,
    CONF_REMOTE_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)
from .elios import MAX_CELSIUS, MIN_CELSIUS, FanSpeed, Mode, State, Temperature

_LOGGER = logging.getLogger(__name__)

TRANSMIT_DELAY_SECONDS = 2.0

HVAC_TO_MODE = {
    HVACMode.COOL: Mode.COLD,
    HVACMode.HEAT: Mode.HEAT,
    HVACMode.DRY: Mode.DRY,
    HVACMode.FAN_ONLY: Mode.FAN,
    HVACMode.AUTO: Mode.AUTOMATIC,
}
FAN_TO_SPEED = {
    FAN_AUTO: FanSpeed.AUTOMATIC,
    FAN_LOW: FanSpeed.LOW,
    FAN_MEDIUM: FanSpeed.MEDIUM,
    FAN_HIGH: FanSpeed.HIGH,
}

FAN_CONTROLLABLE = (HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY)
SLEEP_CAPABLE = (HVACMode.COOL, HVACMode.HEAT, HVACMode.AUTO)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([EliosClimate(entry)])


class EliosClimate(ClimateEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = MIN_CELSIUS
    _attr_max_temp = MAX_CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, *HVAC_TO_MODE]
    _attr_fan_modes = list(FAN_TO_SPEED)
    _attr_preset_modes = [PRESET_NONE, PRESET_SLEEP]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, entry: ConfigEntry) -> None:
        self._remote_entity = entry.data[CONF_REMOTE_ENTITY]
        self._temperature_sensor = entry.data.get(CONF_TEMPERATURE_SENSOR)
        self._humidity_sensor = entry.data.get(CONF_HUMIDITY_SENSOR)
        self._cancel_transmit = None

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Elios AC",
            manufacturer="Elios",
        )
        self._attr_hvac_mode = HVACMode.OFF
        self._last_active_mode = HVACMode.COOL
        self._attr_target_temperature = 24.0
        self._attr_fan_mode = FAN_AUTO
        self._attr_preset_mode = PRESET_NONE

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last = await self.async_get_last_state()
        if last is not None:
            if last.state in self._attr_hvac_modes:
                self._attr_hvac_mode = HVACMode(last.state)
                if self._attr_hvac_mode != HVACMode.OFF:
                    self._last_active_mode = self._attr_hvac_mode
            if (temperature := last.attributes.get(ATTR_TEMPERATURE)) is not None:
                self._attr_target_temperature = temperature
            if last.attributes.get("fan_mode") in FAN_TO_SPEED:
                self._attr_fan_mode = last.attributes["fan_mode"]
            if last.attributes.get("preset_mode") in self._attr_preset_modes:
                self._attr_preset_mode = last.attributes["preset_mode"]

        sensors = [
            entity_id
            for entity_id in (self._temperature_sensor, self._humidity_sensor)
            if entity_id
        ]
        if sensors:
            self.async_on_remove(
                async_track_state_change_event(self.hass, sensors, self._sensor_updated)
            )
            for entity_id in sensors:
                self._apply_sensor(entity_id, self.hass.states.get(entity_id))

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel_transmit is not None:
            self._cancel_transmit()
            self._cancel_transmit = None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        if hvac_mode != HVACMode.OFF:
            self._last_active_mode = hvac_mode
        self._schedule_transmit()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(self._last_active_mode)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temperature
            self._schedule_transmit()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._attr_fan_mode = fan_mode
        self._schedule_transmit()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self._attr_preset_mode = preset_mode
        self._schedule_transmit()

    @callback
    def _schedule_transmit(self) -> None:
        """Arm (or re-arm) the settle timer; the frame carries the full state,
        so only the last state of a burst needs to reach the AC."""
        if self._cancel_transmit is not None:
            self._cancel_transmit()
        self._cancel_transmit = async_call_later(
            self.hass, TRANSMIT_DELAY_SECONDS, self._transmit
        )
        self.async_write_ha_state()

    async def _transmit(self, _now) -> None:
        self._cancel_transmit = None
        state = self._build_state()
        command = "b64:" + base64.b64encode(pulses_to_data(state.pulses())).decode()

        await self.hass.services.async_call(
            "remote",
            "send_command",
            {"entity_id": self._remote_entity, "command": command},
            blocking=True,
        )

    def _build_state(self) -> State:
        active = self._attr_hvac_mode
        powered = active != HVACMode.OFF
        if not powered:
            active = self._last_active_mode
        mode = HVAC_TO_MODE[active]

        return State.new(
            mode=mode,
            powered=powered,
            temperature=(
                Temperature.celsius(int(round(self._attr_target_temperature)))
                if active != HVACMode.FAN_ONLY
                else None
            ),
            fan_speed=(
                FAN_TO_SPEED[self._attr_fan_mode]
                if active in FAN_CONTROLLABLE
                else None
            ),
            sleep=(
                self._attr_preset_mode == PRESET_SLEEP and active in SLEEP_CAPABLE
            ),
        )

    @callback
    def _sensor_updated(self, event: Event) -> None:
        self._apply_sensor(event.data["entity_id"], event.data["new_state"])
        self.async_write_ha_state()

    def _apply_sensor(self, entity_id: str, state: HassState | None) -> None:
        value = _parse_sensor(state)
        if entity_id == self._temperature_sensor:
            self._attr_current_temperature = value
        elif entity_id == self._humidity_sensor:
            self._attr_current_humidity = value


def _parse_sensor(state: HassState | None) -> float | None:
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None
