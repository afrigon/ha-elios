"""Climate entity that transmits complete Elios states through the RM4.

The AC is transmit-only: entity state is the last state sent (restored across
restarts), while current temperature/humidity are polled from the RM4's
built-in sensors.
"""

import logging
from datetime import timedelta

import broadlink6

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
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EliosConfigEntry
from .const import DOMAIN
from .elios import MAX_CELSIUS, MIN_CELSIUS, FanSpeed, Mode, State, Temperature

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

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
    entry: EliosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([EliosClimate(entry)])


class EliosClimate(ClimateEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = None
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

    def __init__(self, entry: EliosConfigEntry) -> None:
        self._device = entry.runtime_data
        self._authenticated = False
        self._attr_unique_id = entry.unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
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
        if last is None:
            return

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

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        if hvac_mode != HVACMode.OFF:
            self._last_active_mode = hvac_mode
        await self._transmit()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(self._last_active_mode)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temperature
            await self._transmit()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._attr_fan_mode = fan_mode
        await self._transmit()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        self._attr_preset_mode = preset_mode
        await self._transmit()

    async def async_update(self) -> None:
        try:
            sensors = await self.hass.async_add_executor_job(self._read_sensors)
        except broadlink6.BroadlinkError as err:
            _LOGGER.debug("sensor poll failed: %s", err)
            self._attr_available = False
            return

        self._attr_available = True
        self._attr_current_temperature = sensors["temperature"]
        self._attr_current_humidity = sensors["humidity"]

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

    async def _transmit(self) -> None:
        state = self._build_state()
        await self.hass.async_add_executor_job(self._send, state)
        self.async_write_ha_state()

    def _send(self, state: State) -> None:
        if not self._authenticated:
            self._device.auth()
            self._authenticated = True

        try:
            self._device.send_pulses(state.pulses())
        except broadlink6.AuthorizationError:
            # The device drops sessions it has not heard from in a while.
            self._device.auth()
            self._device.send_pulses(state.pulses())

    def _read_sensors(self) -> dict[str, float]:
        if not self._authenticated:
            self._device.auth()
            self._authenticated = True

        try:
            return self._device.check_sensors()
        except broadlink6.AuthorizationError:
            self._device.auth()
            return self._device.check_sensors()
