import pytest

from simple_train.core import decoder
from simple_train.core.manufacturers import manufacturer_name


def test_long_address_round_trip():
    assert decoder.long_address_cvs(1234) == (196, 210)
    assert decoder.long_address_from(196, 210) == 1234
    assert decoder.long_address_cvs(10239) == (231, 255)
    with pytest.raises(ValueError):
        decoder.long_address_cvs(10240)


def test_active_address():
    assert decoder.active_address(3, 196, 210, 0x06) == (3, False)
    assert decoder.active_address(3, 196, 210, 0x26) == (1234, True)


def test_address_writes_keep_other_cv29_bits():
    assert decoder.address_writes(1234, True, 0x07) == [(17, 196), (18, 210), (29, 0x27)]
    assert decoder.address_writes(5, False, 0x27) == [(1, 5), (29, 0x07)]
    with pytest.raises(ValueError):
        decoder.address_writes(128, False, 0)


def test_config_round_trip():
    for value in (0, 0x06, 0x27, 0x3F, 0xC6):
        assert decoder.Config.from_cv29(value).cv29() == value
    config = decoder.Config.from_cv29(0x06)
    assert config.speed_steps_28 and config.analogue and not config.reversed


def test_manufacturers():
    assert manufacturer_name(11).startswith("NCE")
    assert manufacturer_name(48) == "Hornby"
    assert "Unknown" in manufacturer_name(250)


def test_long_address_that_did_not_read():
    assert decoder.active_address(3, None, None, 0x26) == (None, True)
