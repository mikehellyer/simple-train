"""The track plan: the layout drawn as tiles on a grid, iTrain style.

Each tile sits in one grid square and joins some of the square's eight
"ends": the middles of its four sides and its four corners. Ends are
numbered anticlockwise from the right, 45° apart:

        3   2   1
        4   ·   0
        5   6   7

A tile's rotation (0–7) turns it in 45° steps. Its kind says what it
joins, relative to that rotation r:
  straight       r ↔ r+4
  curve          r ↔ r+3      a gentle 45° bend
  curve90        r ↔ r+2      a sharp 90° bend
  point_left     r ↔ r+4 when closed, r ↔ r+5 when thrown
  point_right    r ↔ r+4 when closed, r ↔ r+3 when thrown
  crossing       r ↔ r+4 and r+2 ↔ r+6 (square)
  crossing45     r ↔ r+4 and r+1 ↔ r+5 (diamond)
  buffer         r only: the end of the line
  label          nothing: just text on the plan

Points are switched with NCE's accessory command:
  0xAD adH adL 3 0   closed (normal, straight on)
  0xAD adH adL 4 0   thrown (reverse, the diverging route)
for accessory addresses 1–2044. The command station can't tell us how a
point is set, so the plan remembers the last command it sent.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from platformdirs import user_data_dir

FORMAT = 1
ACCESSORY_COMMAND = 0xAD
CLOSED = 0x03
THROWN = 0x04
MAX_ACCESSORY = 2044

STRAIGHT = "straight"
CURVE = "curve"
CURVE90 = "curve90"
POINT_LEFT = "point_left"
POINT_RIGHT = "point_right"
CROSSING = "crossing"
CROSSING45 = "crossing45"
BUFFER = "buffer"
LABEL = "label"
KINDS = (STRAIGHT, CURVE, CURVE90, POINT_LEFT, POINT_RIGHT, CROSSING, CROSSING45, BUFFER, LABEL)
KIND_NAMES = {
    STRAIGHT: "Straight",
    CURVE: "Curve",
    CURVE90: "Sharp curve",
    POINT_LEFT: "Left-hand point",
    POINT_RIGHT: "Right-hand point",
    CROSSING: "Crossing",
    CROSSING45: "Diamond crossing",
    BUFFER: "Buffer stop",
    LABEL: "Label",
}
POINTS = (POINT_LEFT, POINT_RIGHT)

# Screen offsets (x right, y down) from a square's middle to each end, in half squares.
END_OFFSETS = [(1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1)]

DEFAULT_COLUMNS = 80
DEFAULT_ROWS = 45


def opposite(end: int) -> int:
    return (end + 4) % 8


def accessory_command(address: int, closed: bool) -> bytes:
    if not 1 <= address <= MAX_ACCESSORY:
        raise ValueError(f"An accessory address must be 1–{MAX_ACCESSORY} (not {address})")
    return bytes((ACCESSORY_COMMAND, address >> 8, address & 0xFF, CLOSED if closed else THROWN, 0))


@dataclass
class Tile:
    column: int
    row: int
    kind: str
    rotation: int = 0
    # Points only:
    address: int = 0  # the NCE accessory address; 0 = none yet
    name: str = ""
    inverted: bool = False  # wired the other way round: "closed" sends thrown and vice versa
    thrown: bool = False  # as last set
    # Labels only:
    text: str = ""

    @property
    def place(self) -> tuple[int, int]:
        return self.column, self.row

    @property
    def is_point(self) -> bool:
        return self.kind in POINTS

    def _turn(self, *ends: int) -> tuple[int, ...]:
        return tuple((self.rotation + end) % 8 for end in ends)

    def routes(self, all_routes: bool = False) -> list[tuple[int, ...]]:
        """The pairs of ends joined by track: for a point, only the route
        it's set to, unless all_routes. A buffer stop gives one end alone."""
        if self.kind == STRAIGHT:
            return [self._turn(0, 4)]
        if self.kind == CURVE:
            return [self._turn(0, 3)]
        if self.kind == CURVE90:
            return [self._turn(0, 2)]
        if self.kind in POINTS:
            diverging = self._turn(0, 5 if self.kind == POINT_LEFT else 3)
            straight = self._turn(0, 4)
            if all_routes:
                return [straight, diverging]
            return [diverging if self.thrown else straight]
        if self.kind == CROSSING:
            return [self._turn(0, 4), self._turn(2, 6)]
        if self.kind == CROSSING45:
            return [self._turn(0, 4), self._turn(1, 5)]
        if self.kind == BUFFER:
            return [self._turn(0)]
        return []

    def ends(self) -> set[int]:
        return {end for route in self.routes(all_routes=True) for end in route}

    def command(self, thrown: bool) -> bytes:
        """The accessory command that sets this point."""
        closed = not thrown
        if self.inverted:
            closed = not closed
        return accessory_command(self.address, closed)

    @property
    def label(self) -> str:
        if self.is_point:
            title = self.name or "Point"
            return f"{title} ({self.address})" if self.address else f"{title} (no address)"
        return KIND_NAMES.get(self.kind, self.kind)

    def to_json(self) -> dict:
        data = asdict(self)
        # Keep the file small and readable: only what this kind of tile uses.
        if not self.is_point:
            for key in ("address", "name", "inverted", "thrown"):
                data.pop(key)
        if self.kind != LABEL:
            data.pop("text")
        return data

    @classmethod
    def from_json(cls, data: dict) -> Optional["Tile"]:
        try:
            tile = cls(column=int(data["column"]), row=int(data["row"]), kind=str(data["kind"]))
        except (KeyError, TypeError, ValueError):
            return None
        if tile.kind not in KINDS or tile.column < 0 or tile.row < 0:
            return None
        rotation = data.get("rotation", 0)
        tile.rotation = rotation % 8 if isinstance(rotation, int) else 0
        address = data.get("address", 0)
        if isinstance(address, int) and 0 <= address <= MAX_ACCESSORY:
            tile.address = address
        for key in ("name", "text"):
            if isinstance(data.get(key), str):
                setattr(tile, key, data[key])
        for key in ("inverted", "thrown"):
            if isinstance(data.get(key), bool):
                setattr(tile, key, data[key])
        return tile


def _neighbour(column: int, row: int, end: int) -> tuple[int, int]:
    dx, dy = END_OFFSETS[end]
    return column + dx, row + dy


@dataclass
class Plan:
    name: str = "My layout"
    columns: int = DEFAULT_COLUMNS
    rows: int = DEFAULT_ROWS
    tiles: dict[tuple[int, int], Tile] = field(default_factory=dict)

    def get(self, column: int, row: int) -> Optional[Tile]:
        return self.tiles.get((column, row))

    def put(self, tile: Tile) -> None:
        self.tiles[tile.place] = tile
        # Room to keep drawing past the furthest tile.
        self.columns = max(self.columns, tile.column + 10)
        self.rows = max(self.rows, tile.row + 10)

    def remove(self, column: int, row: int) -> Optional[Tile]:
        return self.tiles.pop((column, row), None)

    def points(self) -> list[Tile]:
        return sorted((tile for tile in self.tiles.values() if tile.is_point),
                      key=lambda tile: (tile.address or 99999, tile.name, tile.row, tile.column))

    def joined(self, tile: Tile, end: int) -> bool:
        """Whether the tile's end meets track in the next square."""
        other = self.get(*_neighbour(tile.column, tile.row, end))
        return other is not None and opposite(end) in other.ends()

    def loose_ends(self, tile: Tile) -> list[int]:
        """Ends of the tile with no track to meet them (a buffer's own end
        is meant to be one, but only on its far side)."""
        return [end for end in sorted(tile.ends()) if not self.joined(tile, end)]

    def duplicate_addresses(self) -> dict[int, list[Tile]]:
        """Accessory addresses used by more than one point."""
        seen: dict[int, list[Tile]] = {}
        for tile in self.points():
            if tile.address:
                seen.setdefault(tile.address, []).append(tile)
        return {address: tiles for address, tiles in seen.items() if len(tiles) > 1}

    def to_json(self) -> dict:
        tiles = sorted(self.tiles.values(), key=lambda tile: (tile.row, tile.column))
        return {"format": FORMAT, "name": self.name, "columns": self.columns, "rows": self.rows,
                "tiles": [tile.to_json() for tile in tiles]}

    @classmethod
    def from_json(cls, data: dict) -> "Plan":
        plan = cls()
        if isinstance(data.get("name"), str) and data["name"].strip():
            plan.name = data["name"].strip()
        for key in ("columns", "rows"):
            value = data.get(key)
            if isinstance(value, int) and 10 <= value <= 1000:
                setattr(plan, key, value)
        for item in data.get("tiles", []):
            if isinstance(item, dict):
                tile = Tile.from_json(item)
                if tile is not None:
                    plan.put(tile)
        return plan

    def copy(self) -> "Plan":
        return Plan.from_json(self.to_json())


def default_path() -> Path:
    return Path(user_data_dir("Simple-Train")) / "track_plan.json"


def load(path: Optional[Path] = None) -> Plan:
    path = path or default_path()
    for candidate in (path, path.with_suffix(".json.bak")):
        try:
            return Plan.from_json(json.loads(candidate.read_text()))
        except (OSError, ValueError, AttributeError):
            continue
    return Plan()


def save(plan: Plan, path: Optional[Path] = None) -> None:
    """Like the roster: keep the last file as .bak, write a temp file, swap it in."""
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(plan.to_json(), indent=1, ensure_ascii=False))
    if path.exists():
        os.replace(path, path.with_suffix(".json.bak"))
    os.replace(temp, path)


def export_plan(plan: Plan, path: Path) -> None:
    path.write_text(json.dumps(plan.to_json(), indent=1, ensure_ascii=False))


def import_plan(path: Path) -> Plan:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"Couldn't read {path.name}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("tiles"), list):
        raise ValueError(f"{path.name} isn't a Simple-Train track plan")
    return Plan.from_json(data)


def tiles_between(start: tuple[int, int], end: tuple[int, int]) -> Iterable[tuple[int, int]]:
    """The squares on a straight run from start to end, for dragging out
    a line of track: across, down, or 45° diagonal (whichever is nearest)."""
    (c0, r0), (c1, r1) = start, end
    dc, dr = c1 - c0, r1 - r0
    steps = max(abs(dc), abs(dr))
    if steps == 0:
        return [start]
    if abs(dc) >= 2 * abs(dr):
        dr = 0
    elif abs(dr) >= 2 * abs(dc):
        dc = 0
    else:
        steps = max(abs(dc), abs(dr))
        dc = steps if dc > 0 else -steps
        dr = steps if dr > 0 else -steps
    step_c = (dc > 0) - (dc < 0)
    step_r = (dr > 0) - (dr < 0)
    count = max(abs(dc), abs(dr))
    return [(c0 + step_c * i, r0 + step_r * i) for i in range(count + 1)]


def direction_of(step_c: int, step_r: int) -> int:
    """The end number pointing along a one-square step."""
    return END_OFFSETS.index((step_c, step_r))
