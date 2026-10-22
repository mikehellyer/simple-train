"""The loco roster: every loco you've got, with its address, decoder and a
copy of its CVs.

Kept as one JSON file in the user's data folder. Each save first keeps the
previous file as roster.json.bak, then writes a temporary file and swaps
it in, so a crash mid-save can't lose the roster.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir

from simple_train.core.decoder import address_text
from simple_train.core.manufacturers import manufacturer_name

FORMAT = 1

# CVs never written back when restoring a loco: CV7 can't be written, and
# writing CV8 resets the decoder.
NOT_RESTORED = {7, 8}
# Written last when restoring, in this order, so the loco only changes
# address once everything else is in place.
RESTORED_LAST = (17, 18, 1, 29)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


@dataclass
class Loco:
    name: str
    address: int = 3
    long_address: bool = False
    road_number: str = ""
    decoder_model: str = ""  # whatever the user calls it, e.g. "Gaugemaster DCC22"
    manufacturer_id: Optional[int] = None  # CV8
    decoder_version: Optional[int] = None  # CV7
    notes: str = ""
    cvs: dict[int, int] = field(default_factory=dict)
    cvs_saved_at: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def manufacturer(self) -> str:
        return manufacturer_name(self.manufacturer_id) if self.manufacturer_id is not None else ""

    @property
    def label(self) -> str:
        return f"{self.name}  ·  {self.address_text}"

    @property
    def address_text(self) -> str:
        return address_text(self.address, self.long_address)

    def take_cvs(self, values: dict[int, int]) -> None:
        """Store CVs read from (or written to) the decoder, and what they
        say about it."""
        self.cvs.update(values)
        self.cvs_saved_at = _now()
        if 8 in values:
            self.manufacturer_id = values[8]
        if 7 in values:
            self.decoder_version = values[7]
        cv29 = self.cvs.get(29)
        if cv29 is not None:
            if cv29 & 0x20 and 17 in self.cvs and 18 in self.cvs:
                self.address, self.long_address = ((self.cvs[17] & 0x3F) << 8) | self.cvs[18], True
            elif not cv29 & 0x20 and 1 in self.cvs:
                self.address, self.long_address = self.cvs[1], False

    def restore_writes(self) -> list[tuple[int, int]]:
        """The (CV, value) writes that put this loco's saved CVs back."""
        writes = [(cv, value) for cv, value in sorted(self.cvs.items())
                  if cv not in NOT_RESTORED and cv not in RESTORED_LAST]
        writes += [(cv, self.cvs[cv]) for cv in RESTORED_LAST if cv in self.cvs]
        return writes

    def to_json(self) -> dict:
        data = asdict(self)
        data["cvs"] = {str(cv): value for cv, value in sorted(self.cvs.items())}
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Loco":
        loco = cls(name=str(data.get("name") or "Unnamed loco"))
        for key in ("address", "manufacturer_id", "decoder_version"):
            value = data.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(loco, key, value)
        for key in ("road_number", "decoder_model", "notes", "cvs_saved_at", "id"):
            if isinstance(data.get(key), str) and data[key]:
                setattr(loco, key, data[key])
        loco.long_address = bool(data.get("long_address", loco.address > 127))
        cvs = data.get("cvs") or {}
        if isinstance(cvs, dict):
            for cv, value in cvs.items():
                try:
                    cv, value = int(cv), int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= cv <= 1024 and 0 <= value <= 255:
                    loco.cvs[cv] = value
        return loco


def default_path() -> Path:
    return Path(user_data_dir("Simple-Train")) / "roster.json"


class Roster:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_path()
        self.locos: list[Loco] = self._load()

    def _load(self) -> list[Loco]:
        for path in (self.path, self.path.with_suffix(".json.bak")):
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            return [Loco.from_json(item) for item in data.get("locos", []) if isinstance(item, dict)]
        return []

    def save(self) -> None:
        data = {"format": FORMAT, "locos": [loco.to_json() for loco in self.locos]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        if self.path.exists():
            os.replace(self.path, self.path.with_suffix(".json.bak"))
        os.replace(temp, self.path)

    def sorted(self) -> list[Loco]:
        return sorted(self.locos, key=lambda loco: (loco.name.lower(), loco.address))

    def get(self, loco_id: Optional[str]) -> Optional[Loco]:
        return next((loco for loco in self.locos if loco.id == loco_id), None)

    def find_by_address(self, address: int, long: bool) -> Optional[Loco]:
        return next((loco for loco in self.sorted() if loco.address == address and loco.long_address == long), None)

    def add(self, loco: Loco) -> Loco:
        self.locos.append(loco)
        self.save()
        return loco

    def remove(self, loco_id: str) -> None:
        self.locos = [loco for loco in self.locos if loco.id != loco_id]
        self.save()


def export_loco(loco: Loco, path: Path) -> None:
    """One loco on its own, to keep or share (e.g. a known-good CV sheet)."""
    path.write_text(json.dumps({"format": FORMAT, "loco": loco.to_json()}, indent=2, ensure_ascii=False))


def import_loco(path: Path) -> Loco:
    """Read a file written by export_loco. The loco gets a new id, so the
    same file can be imported more than once. Raises ValueError if it isn't
    a loco file."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"Couldn't read {path.name}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("loco"), dict):
        raise ValueError(f"{path.name} isn't a Simple-Train loco file")
    loco = Loco.from_json(data["loco"])
    loco.id = uuid.uuid4().hex
    return loco
