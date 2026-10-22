import pytest

from simple_train.core import nce
from simple_train.core.simulator import SimulatedCommandStation


def connect(**kwargs):
    station = SimulatedCommandStation(**kwargs)
    return station, nce.NceConnection(station)


def test_check_and_version():
    station, connection = connect()
    connection.check()
    assert str(connection.version()) == "6.3.9"
    assert station.sent == [b"\x80", b"\xaa"]


def test_direct_read_and_write_bytes():
    station, connection = connect()
    connection.enter_programming()
    connection.write_cv(3, 25, nce.DIRECT)
    assert connection.read_cv(3, nce.DIRECT) == 25
    connection.exit_programming()
    assert station.sent == [b"\x9e", b"\xa8\x00\x03\x19", b"\xa9\x00\x03", b"\x9f"]


def test_paged_mode_and_high_cvs():
    station, connection = connect()
    connection.write_cv(300, 7, nce.PAGED)
    assert station.sent[-1] == b"\xa0\x01\x2c\x07"
    assert connection.read_cv(300, nce.PAGED) == 7


def test_register_mode_maps_cv29_to_register_5():
    station, connection = connect()
    connection.write_cv(29, 0x26, nce.REGISTER)
    assert station.sent[-1] == b"\xa6\x05\x26"
    assert connection.read_cv(29, nce.REGISTER) == 0x26
    with pytest.raises(nce.NceError, match="Register mode"):
        connection.read_cv(17, nce.REGISTER)


def test_no_loco_on_track():
    _, connection = connect(loco_on_track=False)
    with pytest.raises(nce.NoDecoder):
        connection.read_cv(1, nce.DIRECT)


def test_no_programming_track_through_power_pro_usb():
    _, connection = connect(command_station=nce.POWER_PRO)
    with pytest.raises(nce.NotSupported):
        connection.enter_programming()


def test_program_on_main_long_address():
    station, connection = connect()
    connection.write_cv(3, 10, nce.MAIN, address=1234)
    assert station.sent[-1] == bytes((0xAE, 0xC4, 0xD2, 0x00, 0x03, 0x0A))
    connection.write_cv(3, 10, nce.MAIN, address=3)
    assert station.sent[-1] == bytes((0xAE, 0x00, 0x03, 0x00, 0x03, 0x0A))
    connection.write_cv(3, 10, nce.MAIN, address=3, long=True)
    assert station.sent[-1][1:3] == b"\xc0\x03"


def test_cannot_read_on_main():
    _, connection = connect()
    with pytest.raises(nce.NceError):
        connection.read_cv(1, nce.MAIN)


def test_out_of_range():
    _, connection = connect()
    with pytest.raises(nce.NceError):
        connection.write_cv(0, 1)
    with pytest.raises(nce.NceError):
        connection.write_cv(1, 256)
    with pytest.raises(nce.NceError):
        nce.loco_address_bytes(10240)


class Silent:
    def write(self, data):
        pass

    def read(self, count, timeout):
        return b""

    def reset_input(self):
        pass

    def close(self):
        pass


def test_no_answer():
    connection = nce.NceConnection(Silent())
    with pytest.raises(nce.NoAnswer):
        connection.check()


def test_exit_without_enter_sends_nothing():
    station, connection = connect()
    connection.exit_programming()
    assert station.sent == []


def test_open_error_messages():
    assert "dialout" in nce.describe_open_error("/dev/ttyUSB0", OSError("[Errno 13] Permission denied"))
    assert "plugged in" in nce.describe_open_error("/dev/ttyUSB0", OSError("[Errno 2] No such file"))
