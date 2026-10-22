"""Persisted user preferences."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir

from simple_train.core import nce


@dataclass
class Settings:
    # The NCE USB interface: its serial port ("demo" for the built-in
    # pretend command station), speed, and what it's plugged into.
    port: str = ""
    baud: int = nce.DEFAULT_BAUD
    command_station: str = nce.POWER_CAB
    connect_at_start: bool = True

    # The programmer.
    programming_mode: str = nce.DIRECT
    main_address: int = 3  # the loco programmed on the main
    verify_writes: bool = False


_CHOICES = {
    "baud": nce.BAUD_RATES,
    "command_station": tuple(nce.COMMAND_STATIONS),
    "programming_mode": nce.MODES,
}


def default_path() -> Path:
    return Path(user_config_dir("Simple-Train")) / "settings.json"


class SettingsStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_path()
        self.settings = self._load()

    def _load(self) -> Settings:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return Settings()
        settings = Settings()
        for f in fields(Settings):
            if f.name not in raw:
                continue
            value = raw[f.name]
            default = getattr(settings, f.name)
            if type(value) is not type(default):
                continue
            if f.name in _CHOICES and value not in _CHOICES[f.name]:
                continue
            setattr(settings, f.name, value)
        return settings

    def update(self, **changes) -> None:
        for name, value in changes.items():
            setattr(self.settings, name, value)
        self.save()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(asdict(self.settings), indent=2))
        except OSError:
            pass
