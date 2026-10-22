import pytest

from simple_train.core import nce
from simple_train.core.programmer import Programmer, Progress, Stopped
from simple_train.core.simulator import SimulatedCommandStation


def make(**kwargs):
    station = SimulatedCommandStation(**kwargs)
    return station, Programmer(nce.NceConnection(station), kwargs.get("command_station", nce.POWER_CAB))


def test_identify():
    station, programmer = make()
    info = programmer.identify(nce.DIRECT)
    assert info.manufacturer == "Electronic Solutions Ulm GmbH"
    assert info.address == (3, False)
    assert not station.in_programming_mode  # left programming mode again


def test_write_long_address_then_identify():
    from simple_train.core.decoder import address_writes

    station, programmer = make()
    programmer.write_cvs(address_writes(4472, True, station.cvs[29]), nce.DIRECT, verify=True)
    assert programmer.identify(nce.DIRECT).address == (4472, True)


def test_programming_mode_left_after_an_error():
    station, programmer = make(loco_on_track=False)
    with pytest.raises(nce.NoDecoder):
        programmer.read_cvs([1, 2], nce.DIRECT)
    assert not station.in_programming_mode


def test_read_range_keeps_going():
    station, programmer = make()
    results = programmer.read_cvs(range(1, 6), nce.DIRECT, keep_going=True)
    assert results == {1: 3, 2: 1, 3: 8, 4: 6, 5: 0}


def test_stop():
    _, programmer = make()
    progress = Progress()
    progress.stop()
    with pytest.raises(Stopped):
        programmer.read_cvs([1], nce.DIRECT, progress)


def test_power_pro_only_programs_on_main():
    station, programmer = make(command_station=nce.POWER_PRO)
    with pytest.raises(nce.NotSupported, match="On the main"):
        programmer.read_cvs([1], nce.DIRECT)
    programmer.write_cvs([(3, 20)], nce.MAIN, address=3)
    assert station.cvs[3] == 20


def test_reset_restores_factory_values():
    station, programmer = make()
    programmer.write_cvs([(3, 99), (8, 8)], nce.DIRECT)
    assert station.cvs[3] == 8
