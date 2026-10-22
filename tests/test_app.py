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
    from simple_train.gui import link, main_window

    monkeypatch.setattr(link, "DEMO_DELAY_SECONDS", 0)
    monkeypatch.setattr(main_window, "check_for_update", lambda *args: None)
    app = QApplication.instance() or QApplication([])
    win = main_window.MainWindow(SettingsStore(tmp_path / "settings.json"))
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
