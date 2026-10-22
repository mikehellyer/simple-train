"""Facts about the machine Simple-Train is running on."""
from __future__ import annotations

import platform
from pathlib import Path

_MODEL = Path("/proc/device-tree/model")


def is_raspberry_pi(model_file: Path = _MODEL) -> bool:
    try:
        return "raspberry pi" in model_file.read_text(errors="ignore").lower()
    except OSError:
        return False


def debian_arch(machine: str | None = None) -> str:
    """This machine's architecture as Debian names it (amd64, arm64…)."""
    machine = (machine or platform.machine()).lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
            "armv7l": "armhf", "i686": "i386", "i386": "i386"}.get(machine, machine)
