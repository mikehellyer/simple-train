from types import SimpleNamespace

from simple_train.core import ports


def test_ch340_and_cp210x_are_likely_nce(monkeypatch):
    from serial.tools import list_ports

    found = [SimpleNamespace(device="/dev/ttyS0", vid=None, pid=None, description="n/a"),
             SimpleNamespace(device="/dev/ttyUSB0", vid=0x1A86, pid=0x7523, description="USB Serial"),
             SimpleNamespace(device="/dev/ttyUSB1", vid=0x10C4, pid=0xEA60, description="CP2102")]
    monkeypatch.setattr(list_ports, "comports", lambda: found)
    listed = ports.list_ports()
    assert [port.device for port in listed] == ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyS0", ports.DEMO_PORT]
    assert listed[0].likely_nce and listed[1].likely_nce and not listed[2].likely_nce
