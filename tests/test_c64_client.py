"""The C64 throttle's protocol code (c64/src/wt.c), compiled for this PC and
run against a real Simple-Train phone server: the same conversation the
Commodore 64 Ultimate will have, minus its network chip."""
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from test_app import _wait, window  # noqa: F401  (the fixture)

C64 = Path(__file__).resolve().parent.parent / "c64"

pytestmark = pytest.mark.skipif(sys.platform == "win32" or shutil.which("cc") is None,
                                reason="needs a C compiler and POSIX sockets")


def test_c64_throttle_talks_to_simple_train(window, tmp_path):  # noqa: F811
    from plan_sample import sample_plan
    from simple_train.core.roster import Loco

    client = tmp_path / "net_client"
    subprocess.run(["cc", "-std=gnu99", "-Wno-unknown-pragmas", "-o", str(client),
                    str(C64 / "tests" / "net_client.c"), str(C64 / "src" / "wt.c")], check=True)

    app, win = window
    link = win.link
    win.roster.add(Loco(name="Class 08 Shunter", address=144, long_address=True,
                        function_names={0: "Lights", 1: "Sound", 2: "Horn"}))
    win.track_plan.plan = sample_plan()
    win.track_plan.canvas.set_plan(win.track_plan.plan)
    win.connection_bar._ports.setCurrentIndex(win.connection_bar._ports.findData("demo"))
    win.connection_bar.connect_now()
    _wait(app, lambda: link.connected and not link.busy)
    station = link._connection._transport
    win.phones.announce = False
    assert win.phones.start(0) is None

    process = subprocess.Popen([str(client), str(win.phones.port)], stdout=subprocess.PIPE, text=True)
    output: list[str] = []
    reader = threading.Thread(target=lambda: output.extend(process.stdout), daemon=True)
    reader.start()

    _wait(app, lambda: "READY\n" in output, seconds=10)
    assert win.phones.phones == ["C64 Ultimate"]
    link.throttle.wait_until_sent()
    word = 0xC000 | 144
    assert station.locos[word][0x03] == 50  # reverse at 50
    assert station.locos[word][0x07] == 0x10  # F0
    assert station.accessories[1] == 4  # Loop west thrown

    # Change the speed from the app: the C64 should see it.
    win._drive_loco(win.roster.roster.locos[0].id)
    win.throttles.card_for(144, True)._slider.setValue(33)
    deadline = time.monotonic() + 10
    while process.poll() is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    reader.join(2)
    print("".join(output))
    assert process.returncode == 0, "".join(output)
    win.phones.stop()
