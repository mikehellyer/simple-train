from simple_train.core import withrottle as wt
from simple_train.core.throttle import LocoState


class FakeRailway:
    def __init__(self):
        self.states = {}
        self.driven = []
        self.function_calls = []
        self.point_calls = []
        self.refuse = None

    def roster(self):
        return [wt.RosterEntry("Class 08", 144, True), wt.RosterEntry("Pug", 3, False)]

    def function_labels(self, address, long):
        return ["Lights", "Sound", "Horn"] if address == 144 else []

    def is_momentary(self, address, long, number):
        return address == 144 and number == 2

    def loco(self, address, long):
        return self.states.setdefault((address, long), LocoState(address, long))

    def drive(self, state, session):
        self.driven.append((state.speed, state.forward, state.emergency))
        return self.refuse

    def functions(self, state, number, session):
        self.function_calls.append((number, state.functions[number]))
        return self.refuse

    def points(self):
        return [wt.PointEntry("NT1", "Loop west", False), wt.PointEntry("NT3", "Siding", None)]

    def set_point(self, name, action):
        self.point_calls.append((name, action))
        return None if name in ("NT1", "1") else f"No point called {name}"


def make():
    railway = FakeRailway()
    sent = []
    return railway, sent, wt.Session(railway, sent.append)


def test_greeting():
    _, sent, session = make()
    session.greet()
    assert sent[0] == "VN2.0"
    assert sent[1] == "RL2]\\[Class 08}|{144}|{L]\\[Pug}|{3}|{S"
    assert "PTL]\\[NT1}|{Loop west}|{2]\\[NT3}|{Siding}|{1" in sent
    assert "*10" in sent


def test_acquire_by_roster_name_and_drive():
    railway, sent, session = make()
    session.handle("NMike's phone")
    session.handle("M0+L144<;>EClass 08")
    assert "M0+L144<;>" in sent
    labels = ["Lights", "Sound", "Horn"] + [""] * 26
    assert "M0LL144<;>]\\[" + "]\\[".join(labels) + "]\\[" in sent
    assert "M0AL144<;>s1" in sent
    sent.clear()
    session.handle("M0AL144<;>V50")
    session.handle("M0A*<;>R0")
    assert railway.states[(144, True)].speed == 50 and not railway.states[(144, True)].forward
    assert "M0AL144<;>V50" in sent and "M0AL144<;>R0" in sent
    session.handle("M0AL144<;>X")
    assert railway.driven[-1] == (0, False, True)


def test_function_keys():
    railway, sent, session = make()
    session.handle("M0+L144<;>L144")
    state = railway.states[(144, True)]
    session.handle("M0AL144<;>F10")  # lights: latching, toggles on key down
    session.handle("M0AL144<;>F00")
    assert state.functions[0] is True
    session.handle("M0AL144<;>F10")
    assert state.functions[0] is False
    session.handle("M0AL144<;>F12")  # horn: momentary from the roster
    assert state.functions[2] is True
    session.handle("M0AL144<;>F02")
    assert state.functions[2] is False
    session.handle("M0AL144<;>m15")  # the phone makes F5 momentary
    session.handle("M0AL144<;>F15")
    session.handle("M0AL144<;>F05")
    assert state.functions[5] is False and (5, True) in railway.function_calls
    session.handle("M0AL144<;>f17")
    assert state.functions[7] is True


def test_bad_address_and_release():
    railway, sent, session = make()
    session.handle("M0+S300<;>S300")
    assert sent[-1].startswith("HM")
    session.handle("M1+S3<;>S3")
    session.handle("M1-*<;>r")
    assert "M1-S3<;>" in sent and session.locos == []


def test_points_and_power():
    railway, sent, session = make()
    session.handle("PTA2NT1")
    session.handle("PTACNT9")
    assert railway.point_calls == [("NT1", "2"), ("NT9", "C")]
    assert sent[-1] == "HMNo point called NT9"
    session.handle("PPA0")
    assert sent[-1].startswith("HM") and "track power" in sent[-1]
    assert wt.point_change_line("NT1", True) == "PTA4NT1"


def test_refusal_is_shown_and_quit():
    railway, sent, session = make()
    session.handle("M0+S3<;>S3")
    railway.refuse = "The programming track is in use"
    session.handle("M0AS3<;>V20")
    assert "HMThe programming track is in use" in sent
    session.handle("Q")
    assert session.closed


def test_sync_sends_only_changes():
    railway, sent, session = make()
    session.handle("M0+S3<;>S3")
    state = railway.states[(3, False)]
    sent.clear()
    session.sync(state)
    assert sent == []
    state.speed = 40  # changed from the app
    state.functions[1] = True
    session.sync(state)
    assert sent == ["M0AS3<;>V40", "M0AS3<;>F11"]
