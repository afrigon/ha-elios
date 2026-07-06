"""Elios air conditioner infrared protocol.

Python port of acproto (Rust); the golden bit patterns in the test suite are
taken from its test suite so the two implementations stay in agreement.
"""

from dataclasses import dataclass
from enum import Enum

MIN_CELSIUS = 17
MAX_CELSIUS = 30
MIN_FAHRENHEIT = 62
MAX_FAHRENHEIT = 86

_FAN_MODE_TEMPERATURE = 0b11110
_HEADER = 0b10100001

LEADING_PULSE = 4350
LEADING_GAP = 4350
ONE_PULSE = 550
ONE_GAP = 1550
ZERO_PULSE = 550
ZERO_GAP = 550
FRAME_GAP = 5600


def _frame_pulses(data: bytes) -> list[int]:
    result = [LEADING_PULSE, LEADING_GAP]

    for byte in data:
        for bit in range(7, -1, -1):
            if byte >> bit & 1:
                result += [ONE_PULSE, ONE_GAP]
            else:
                result += [ZERO_PULSE, ZERO_GAP]

    # a closing mark terminates the final gap; without it the receiver
    # cannot delimit the last bit
    result.append(ONE_PULSE)
    return result


class Mode(Enum):
    COLD = 0b000
    DRY = 0b001
    AUTOMATIC = 0b010
    HEAT = 0b011
    FAN = 0b100


class FanSpeed(Enum):
    OFF = 0b000
    LOW = 0b001
    MEDIUM = 0b010
    HIGH = 0b011
    AUTOMATIC = 0b100


@dataclass(frozen=True)
class Temperature:
    value: int
    fahrenheit: bool = False

    @classmethod
    def celsius(cls, value: int) -> "Temperature":
        return cls(value)

    @classmethod
    def from_fahrenheit(cls, value: int) -> "Temperature":
        return cls(value, fahrenheit=True)

    def clamped(self) -> "Temperature":
        if self.fahrenheit:
            return Temperature(min(max(self.value, MIN_FAHRENHEIT), MAX_FAHRENHEIT), True)
        return Temperature(min(max(self.value, MIN_CELSIUS), MAX_CELSIUS))


def bitreverse(value: int) -> int:
    result = 0
    for i in range(8):
        result |= (value >> i & 1) << (7 - i)
    return result


@dataclass(frozen=True)
class State:
    """A complete remote state, the unit of every Elios transmission."""

    fan_speed: FanSpeed
    mode: Mode
    temperature: Temperature
    powered: bool
    sleep: bool

    @classmethod
    def new(
        cls,
        mode: Mode,
        powered: bool,
        temperature: Temperature | None = None,
        fan_speed: FanSpeed | None = None,
        sleep: bool = False,
    ) -> "State":
        if mode is Mode.FAN:
            if temperature is not None:
                raise ValueError("fan mode does not take a temperature")
            temperature = Temperature.celsius(MIN_CELSIUS + _FAN_MODE_TEMPERATURE)
        else:
            if temperature is None:
                raise ValueError(f"{mode.name} mode requires a temperature")
            temperature = temperature.clamped()

        if mode in (Mode.AUTOMATIC, Mode.DRY):
            if fan_speed not in (None, FanSpeed.OFF):
                raise ValueError(f"{mode.name} mode does not take a fan speed")
            fan_speed = FanSpeed.OFF
        else:
            fan_speed = fan_speed if fan_speed is not None else FanSpeed.AUTOMATIC

        sleep = sleep and mode in (Mode.COLD, Mode.HEAT, Mode.AUTOMATIC)

        return cls(fan_speed, mode, temperature, powered, sleep)

    def _raw_parts(self) -> bytes:
        options = (
            int(self.powered) << 7
            | int(self.sleep) << 6
            | self.fan_speed.value << 3
            | self.mode.value
        )

        if self.temperature.fahrenheit:
            temperature = self.temperature.value - MIN_FAHRENHEIT | 0b1 << 5
        else:
            temperature = self.temperature.value - MIN_CELSIUS
        temperature |= 1 << 6  # unknown 2-bit field, always observed as 01

        timer_off = 0b11111111
        timer_on = 0b11111111

        return bytes((_HEADER, options, temperature, timer_off, timer_on))

    @staticmethod
    def _checksum(data: bytes) -> int:
        # the Midea-family formula (the Elios is a rebadged Midea)
        total = sum(bitreverse(byte) for byte in data)
        return bitreverse((256 - total) & 0xFF)

    def as_bytes(self) -> bytes:
        data = self._raw_parts()
        return data + bytes((self._checksum(data),))

    def as_value(self) -> int:
        return int.from_bytes(self.as_bytes(), "big")

    def pulses(self) -> list[int]:
        """Encode the state as an IR pulse/gap sequence in microseconds.

        Midea transmissions send the frame followed by its bitwise
        complement — the receiver's error check.
        """
        frame = self.as_bytes()
        inverted = bytes(byte ^ 0xFF for byte in frame)

        result = _frame_pulses(frame)
        result.append(FRAME_GAP)
        result += _frame_pulses(inverted)
        return result
