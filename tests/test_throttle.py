from simple_train.core import nce, throttle
from simple_train.core.roster import Loco
from simple_train.core.simulator import SimulatedCommandStation


def test_command_bytes():
    assert throttle.speed_command(144, True, 63, True) == bytes((0xA2, 0xC0, 0x90, 0x04, 63))
    assert throttle.speed_command(3, False, 200, False) == bytes((0xA2, 0x00, 0x03, 0x03, 126))
    assert throttle.emergency_stop_command(3, False, True) == bytes((0xA2, 0x00, 0x03, 0x06, 0))
    functions = [False] * throttle.FUNCTION_COUNT
    functions[0] = functions[1] = functions[4] = True
    assert throttle.function_command(3, False, 0, functions)[3:] == bytes((0x07, 0x19))
    functions[13] = functions[20] = True
    assert throttle.function_command(3, False, 3, functions)[3:] == bytes((0x15, 0x81))
    functions[28] = True
    assert throttle.function_command(3, False, 4, functions)[3:] == bytes((0x16, 0x80))
    assert [throttle.group_of(n) for n in (0, 4, 5, 9, 12, 13, 28)] == [0, 0, 1, 2, 2, 3, 4]


def test_sender_sends_latest_state():
    station = SimulatedCommandStation()
    sender = throttle.ThrottleSender(nce.NceConnection(station))
    state = throttle.LocoState(144, True)
    for speed in range(0, 100, 5):
        state.speed = speed
        sender.drive(state)
    state.functions[0] = True
    sender.functions(state, 0)
    assert sender.wait_until_sent()
    word = 0xC000 | 144
    assert station.locos[word][0x04] == 95
    assert station.locos[word][0x07] == 0x10
    state.forward = False
    state.emergency = True
    sender.drive(state)
    sender.stop()
    assert station.locos[word] == {0x05: 0, 0x07: 0x10}


def test_sender_reports_errors():
    class Broken:
        def write(self, data): pass
        def read(self, count, timeout): return b"1"
        def reset_input(self): pass
        def close(self): pass

    errors = []
    sender = throttle.ThrottleSender(nce.NceConnection(Broken()), errors.append)
    sender.drive(throttle.LocoState(3, False, speed=10))
    sender.stop()
    assert errors and errors[0].startswith("Loco 3:")


def test_roster_functions_round_trip():
    loco = Loco(name="x", function_names={0: "Lights", 2: "Horn"}, momentary=[2])
    copy = Loco.from_json(loco.to_json())
    assert copy.function_name(2) == "Horn" and copy.is_momentary(2) and not copy.is_momentary(0)
    assert Loco(name="new").function_name(0) == "Lights"
