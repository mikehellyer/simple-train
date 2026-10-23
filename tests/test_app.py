import os
import time

import pytest

from simple_train.app import self_test

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_self_test():
    assert self_test() == 0


@pytest.fixture
def window(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from simple_train.core.settings import SettingsStore
    from simple_train.core.roster import Roster
    from simple_train.gui import link, main_window
    from simple_train.gui.roster_store import RosterStore

    monkeypatch.setattr(link, "DEMO_DELAY_SECONDS", 0)
    monkeypatch.setattr(main_window, "check_for_update", lambda *args: None)
    app = QApplication.instance() or QApplication([])
    win = main_window.MainWindow(SettingsStore(tmp_path / "settings.json"),
                                 RosterStore(Roster(tmp_path / "roster.json")), tmp_path / "plan.json")
    yield app, win
    win.close()


def _wait(app, condition, seconds=10):
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def test_program_a_demo_loco(window):
    app, win = window
    bar, panel, link = win.connection_bar, win.programmer, win.link
    bar._ports.setCurrentIndex(bar._ports.findData("demo"))
    bar.connect_now()
    _wait(app, lambda: link.connected and not link.busy)

    panel._read_decoder()
    _wait(app, lambda: not link.busy and 29 in panel._values)
    assert panel._facts["address"].text().startswith("3")

    panel._new_address.setValue(1234)
    panel._write_address()
    _wait(app, lambda: not link.busy and panel._values.get(18) == 1234 & 0xFF)
    panel._read_decoder()
    _wait(app, lambda: not link.busy and panel._facts["address"].text().startswith("1234"))
    assert panel._main_address.value() == 1234


def test_no_programming_track_on_power_pro(window):
    from simple_train.core import nce

    app, win = window
    bar, panel = win.connection_bar, win.programmer
    bar._station.setCurrentIndex(bar._station.findData(nce.POWER_PRO))
    app.processEvents()
    assert panel.mode == nce.MAIN


def test_roster_save_link_and_restore(window, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    app, win = window
    bar, panel, link = win.connection_bar, win.programmer, win.link
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("Class 08", True)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.Yes))
    bar._ports.setCurrentIndex(bar._ports.findData("demo"))
    bar.connect_now()
    _wait(app, lambda: link.connected and not link.busy)
    station = link._connection._transport
    station.cvs.update({17: 192, 18: 144, 29: 38, 3: 12})

    panel._read_decoder()
    _wait(app, lambda: not link.busy and 29 in panel._values)
    panel._read([3])
    _wait(app, lambda: not link.busy and panel._values.get(3) == 12)
    panel._save_to_roster()
    loco = win.roster.roster.locos[0]
    assert (loco.name, loco.address, loco.long_address, loco.cvs[3]) == ("Class 08", 144, True, 12)
    assert win.locos._list.count() == 1

    station.cvs[3] = 99  # someone changes it; reading again finds the roster loco by address
    panel._loco_id = None
    panel._read_decoder()
    _wait(app, lambda: not link.busy and panel.loco is not None)
    win._restore_loco(loco.id)
    _wait(app, lambda: not link.busy and station.cvs[3] == 12)


def test_long_addresses_have_four_digits(window):
    app, win = window
    panel = win.programmer
    panel._values.update({1: 3, 17: 192, 18: 144, 29: 38})
    panel._refresh()
    assert panel._facts["address"].text().startswith("0144")
    panel._new_address.setValue(144)
    assert panel._new_address.text() == "0144"
    panel._new_address.setValue(5)
    panel._new_long.setChecked(False)
    assert panel._new_address.text() == "5"
    panel._new_long.setChecked(True)
    assert panel._new_address.text() == "0005"


def test_throttle_drives_a_roster_loco(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from simple_train.core.roster import Loco

    app, win = window
    bar, link = win.connection_bar, win.link
    loco = win.roster.add(Loco(name="Class 08", address=144, long_address=True,
                               function_names={0: "Lights", 2: "Horn"}, momentary=[2]))
    bar._ports.setCurrentIndex(bar._ports.findData("demo"))
    bar.connect_now()
    _wait(app, lambda: link.connected and not link.busy)
    station = link._connection._transport

    win._drive_loco(loco.id)
    card = win.throttles.card_for(144, True)
    assert card is not None and card._name.text() == "Class 08"
    card._slider.setValue(60)
    card.set_direction(False)
    card.toggle_function(0)
    link.throttle.wait_until_sent()
    word = 0xC000 | 144
    assert station.locos[word][0x03] == 60 and station.locos[word][0x07] == 0x10

    horn = card._function_buttons[2]
    QTest.mousePress(horn, Qt.LeftButton)
    link.throttle.wait_until_sent()
    assert station.locos[word][0x07] == 0x12
    QTest.mouseRelease(horn, Qt.LeftButton)
    link.throttle.wait_until_sent()
    assert station.locos[word][0x07] == 0x10

    win.throttles.stop_all()
    link.throttle.wait_until_sent()
    assert 0x05 in station.locos[word]

    # A programming-track job stops moving locos first, and pauses the throttles.
    card._slider.setValue(30)
    link.throttle.wait_until_sent()
    win.programmer._mode.setCurrentIndex(0)
    win.programmer._read([1])
    assert not card._slider.isEnabled()
    _wait(app, lambda: not link.busy)
    assert station.locos[word][0x03] == 0 and card._slider.isEnabled()

    # Disconnecting stops the loco too.
    card._slider.setValue(40)
    link.throttle.wait_until_sent()
    link.disconnect()
    assert station.locos[word][0x03] == 0


def test_track_plan_edit_and_run(window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from plan_sample import sample_plan
    from simple_train.core import track_plan as tp

    app, win = window
    panel, canvas, link = win.track_plan, win.track_plan.canvas, win.link

    def click(column, row, button=Qt.LeftButton):
        QTest.mouseClick(canvas, button, Qt.NoModifier,
                         QPoint(column * canvas.cell + canvas.cell // 2, row * canvas.cell + canvas.cell // 2))

    panel.set_mode("edit")
    panel.set_tool(tp.STRAIGHT)
    click(3, 3)
    assert canvas.plan.get(3, 3).rotation == 0
    click(3, 3)  # again: turns it
    assert canvas.plan.get(3, 3).rotation == 1
    panel.set_tool(tp.POINT_LEFT)
    click(4, 3)
    canvas.select((4, 3))
    panel._point_address.setValue(9)
    assert canvas.plan.get(4, 3).address == 9
    click(3, 3, Qt.RightButton)
    assert canvas.plan.get(3, 3) is None
    panel.undo()
    assert canvas.plan.get(3, 3) is not None
    panel.save()
    assert tp.load(panel._path).get(4, 3).address == 9

    # Run a real plan against the demo command station.
    panel.plan = sample_plan()
    canvas.set_plan(panel.plan)
    panel.set_mode("run")
    win.connection_bar._ports.setCurrentIndex(win.connection_bar._ports.findData("demo"))
    win.connection_bar.connect_now()
    _wait(app, lambda: link.connected and not link.busy)
    station = link._connection._transport
    click(8, 11)
    link.throttle.wait_until_sent()
    assert station.accessories[1] == tp.THROWN and canvas.plan.get(8, 11).thrown
    click(8, 11)
    link.throttle.wait_until_sent()
    assert station.accessories[1] == tp.CLOSED


def test_phone_drives_a_loco_and_switches_a_point(window):
    from PySide6.QtNetwork import QTcpSocket

    from plan_sample import sample_plan
    from simple_train.core.roster import Loco

    app, win = window
    link = win.link
    win.roster.add(Loco(name="Class 08", address=144, long_address=True,
                        function_names={0: "Lights", 2: "Horn"}, momentary=[2]))
    win.track_plan.plan = sample_plan()
    win.track_plan.canvas.set_plan(win.track_plan.plan)
    win.connection_bar._ports.setCurrentIndex(win.connection_bar._ports.findData("demo"))
    win.connection_bar.connect_now()
    _wait(app, lambda: link.connected and not link.busy)
    station = link._connection._transport

    win.phones.announce = False
    assert win.phones.start(0) is None
    phone = QTcpSocket()
    phone.connectToHost("127.0.0.1", win.phones.port)
    received = []

    def read():
        if phone.bytesAvailable():
            received.extend(bytes(phone.readAll()).decode().splitlines())

    def send(line):
        phone.write((line + "\n").encode())

    _wait(app, lambda: (read(), any(line.startswith("RL1") for line in received))[1])
    assert "RL1]\\[Class 08}|{144}|{L" in received
    assert any(line.startswith("PTL]\\[NT1}|{Loop west}|{2") for line in received)

    send("NTest phone")
    send("M0+L144<;>EClass 08")
    send("M0AL144<;>V60")
    send("M0AL144<;>F10")
    _wait(app, lambda: (read(), "M0AL144<;>F10" in received and win.phones.phones == ["Test phone"])[1])
    link.throttle.wait_until_sent()
    word = 0xC000 | 144
    assert station.locos[word][0x04] == 60 and station.locos[word][0x07] == 0x10

    # The app's own throttle and the phone share the loco.
    win._drive_loco(win.roster.roster.locos[0].id)
    card = win.throttles.card_for(144, True)
    assert card._slider.value() == 60
    card._slider.setValue(20)
    _wait(app, lambda: (read(), "M0AL144<;>V20" in received)[1])

    send("PTATNT1")
    _wait(app, lambda: (read(), "PTA4NT1" in received)[1])
    link.throttle.wait_until_sent()
    assert station.accessories[1] == 4

    # The phone going away stops its moving loco.
    phone.disconnectFromHost()
    _wait(app, lambda: win.phones.phones == [])
    link.throttle.wait_until_sent()
    assert station.locos[word][0x04] == 0
    win.phones.stop()
