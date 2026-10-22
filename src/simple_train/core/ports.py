"""Finding the NCE USB interface among the computer's serial ports."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

DEMO_PORT = "demo"

# The NCE USB interface is built on a Silicon Labs CP210x USB-to-serial chip.
SILICON_LABS_VID = 0x10C4
CP210X_PIDS = {0xEA60, 0xEA70, 0xEA71}


@dataclass
class Port:
    device: str
    description: str
    likely_nce: bool = False

    @property
    def label(self) -> str:
        if self.device == DEMO_PORT:
            return "Demo (no hardware)"
        hint = " — looks like the NCE USB" if self.likely_nce else ""
        return f"{self.device} ({self.description}){hint}" if self.description else f"{self.device}{hint}"


def list_ports() -> list[Port]:
    """Serial ports, the likely NCE ones first, then the demo."""
    found: list[Port] = []
    try:
        from serial.tools import list_ports as serial_ports

        for info in serial_ports.comports():
            likely = info.vid == SILICON_LABS_VID and info.pid in CP210X_PIDS
            if sys.platform == "darwin" and info.device.startswith("/dev/tty."):
                continue  # the /dev/cu. twin is the one to open on a Mac
            description = info.description if info.description and info.description != "n/a" else ""
            found.append(Port(info.device, description, likely))
    except Exception:
        pass
    found.sort(key=lambda port: (not port.likely_nce, port.device))
    found.append(Port(DEMO_PORT, ""))
    return found


def permission_problem(device: str) -> str:
    """On Linux, a serial port you can't open needs the dialout group."""
    if not sys.platform.startswith("linux") or device == DEMO_PORT or not os.path.exists(device):
        return ""
    if os.access(device, os.R_OK | os.W_OK):
        return ""
    return ("You don't have permission to use the USB interface yet. Run "
            "“sudo usermod -aG dialout $USER” in a terminal, then log out and back in.")
