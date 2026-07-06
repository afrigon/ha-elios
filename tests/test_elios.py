import pytest

from elios import (
    LEADING_GAP,
    LEADING_PULSE,
    MAX_CELSIUS,
    MAX_FAHRENHEIT,
    MIN_CELSIUS,
    MIN_FAHRENHEIT,
    ONE_PULSE,
    FanSpeed,
    Mode,
    State,
    Temperature,
    bitreverse,
)


def test_bitreverse():
    assert bitreverse(0b10010111) == 0b11101001


# Golden values from the acproto (Rust) test suite.
GOLDEN = [
    (
        dict(mode=Mode.COLD, powered=True, temperature=Temperature.celsius(17), fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_10100000_01000000_11111111_11111111_01101110,
    ),
    (
        dict(mode=Mode.COLD, powered=True, temperature=Temperature.celsius(18), fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_10100000_01000001_11111111_11111111_01101111,
    ),
    (
        dict(mode=Mode.COLD, powered=True, temperature=Temperature.from_fahrenheit(62), fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_10100000_01100000_11111111_11111111_01001110,
    ),
    (
        dict(mode=Mode.COLD, powered=False, temperature=Temperature.celsius(17), fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_00100000_01000000_11111111_11111111_11101110,
    ),
    (
        dict(mode=Mode.COLD, powered=True, temperature=Temperature.celsius(17), fan_speed=FanSpeed.AUTOMATIC, sleep=True),
        0b10100001_11100000_01000000_11111111_11111111_00101110,
    ),
    (
        dict(mode=Mode.HEAT, powered=True, temperature=Temperature.celsius(30), fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_10100011_01001101_11111111_11111111_01100000,
    ),
    (
        dict(mode=Mode.FAN, powered=True, fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_10100100_01011110_11111111_11111111_01111011,
    ),
    (
        dict(mode=Mode.DRY, powered=True, temperature=Temperature.celsius(30)),
        0b10100001_10000001_01001101_11111111_11111111_01010010,
    ),
    (
        dict(mode=Mode.COLD, powered=True, temperature=Temperature.from_fahrenheit(78), fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_10100000_01110000_11111111_11111111_01010110,
    ),
    (
        dict(mode=Mode.COLD, powered=True, temperature=Temperature.from_fahrenheit(84), fan_speed=FanSpeed.AUTOMATIC),
        0b10100001_10100000_01110110_11111111_11111111_01010000,
    ),
    (
        dict(mode=Mode.AUTOMATIC, powered=True, temperature=Temperature.celsius(30)),
        0b10100001_10000010_01001101_11111111_11111111_01010001,
    ),
]


@pytest.mark.parametrize("kwargs, expected", GOLDEN)
def test_golden_values_match_acproto(kwargs, expected):
    assert State.new(**kwargs).as_value() == expected


def test_automatic_mode_rejects_fan_speed():
    with pytest.raises(ValueError):
        State.new(
            mode=Mode.AUTOMATIC,
            powered=True,
            temperature=Temperature.celsius(24),
            fan_speed=FanSpeed.HIGH,
        )


def test_fan_mode_rejects_temperature():
    with pytest.raises(ValueError):
        State.new(
            mode=Mode.FAN,
            powered=True,
            temperature=Temperature.celsius(24),
            fan_speed=FanSpeed.LOW,
        )


def test_non_fan_mode_requires_temperature():
    with pytest.raises(ValueError):
        State.new(mode=Mode.COLD, powered=True)


@pytest.mark.parametrize("mode", [Mode.DRY, Mode.FAN])
def test_sleep_unavailable_outside_cold_heat_automatic(mode):
    kwargs = {} if mode is Mode.FAN else {"temperature": Temperature.celsius(24)}
    state = State.new(mode=mode, powered=True, sleep=True, **kwargs)
    assert state.sleep is False


def test_out_of_range_temperature_is_clamped():
    low = State.new(mode=Mode.COLD, powered=True, temperature=Temperature.celsius(MIN_CELSIUS - 1))
    high = State.new(mode=Mode.COLD, powered=True, temperature=Temperature.celsius(MAX_CELSIUS + 1))
    low_f = State.new(mode=Mode.COLD, powered=True, temperature=Temperature.from_fahrenheit(MIN_FAHRENHEIT - 1))
    high_f = State.new(mode=Mode.COLD, powered=True, temperature=Temperature.from_fahrenheit(MAX_FAHRENHEIT + 1))

    assert low.temperature.value == MIN_CELSIUS
    assert high.temperature.value == MAX_CELSIUS
    assert low_f.temperature.value == MIN_FAHRENHEIT
    assert high_f.temperature.value == MAX_FAHRENHEIT


def test_pulses_shape():
    pulses = State.new(
        mode=Mode.COLD, powered=True, temperature=Temperature.celsius(24)
    ).pulses()

    assert len(pulses) == 2 + 48 * 2 + 1
    assert pulses[0] == LEADING_PULSE
    assert pulses[1] == LEADING_GAP
    assert pulses[-1] == ONE_PULSE
