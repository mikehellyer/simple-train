"""What a DCC decoder's CVs mean (NMRA S-9.2.2), and the CV writes that
make the common changes — a new address, the CV29 options."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from simple_train.core.manufacturers import manufacturer_name

CV_NAMES = {
    1: "Primary (short) address",
    2: "Start voltage (Vstart)",
    3: "Acceleration rate",
    4: "Deceleration rate",
    5: "Top voltage (Vhigh)",
    6: "Mid voltage (Vmid)",
    7: "Manufacturer version",
    8: "Manufacturer ID (write 8 to reset)",
    9: "Motor PWM period",
    10: "Back-EMF cutout",
    11: "Packet timeout",
    12: "Power source conversion",
    13: "Analogue mode functions F1–F8",
    14: "Analogue mode functions FL, F9–F12",
    15: "Decoder lock (key)",
    16: "Decoder lock (ID)",
    17: "Long address, high byte",
    18: "Long address, low byte",
    19: "Consist address",
    20: "Extended consist address",
    21: "Consist functions F1–F8",
    22: "Consist functions FL, F9–F12",
    23: "Acceleration adjustment",
    24: "Deceleration adjustment",
    25: "Speed table select",
    27: "Automatic stopping",
    28: "RailCom configuration",
    29: "Configuration (CV29)",
    30: "Error information",
    31: "Index high byte",
    32: "Index low byte",
    33: "Function mapping FL forward",
    34: "Function mapping FL reverse",
    **{35 + n: f"Function mapping F{n + 1}" for n in range(12)},
    65: "Kick start",
    66: "Forward trim",
    **{67 + n: f"Speed table step {n + 1}" for n in range(28)},
    95: "Reverse trim",
    105: "User ID 1",
    106: "User ID 2",
}


def cv_name(cv: int) -> str:
    return CV_NAMES.get(cv, "")


# CV29 bits
REVERSED = 0x01
SPEED_STEPS_28 = 0x02  # 28/128 speed steps (clear: 14)
ANALOGUE = 0x04  # may run on DC
RAILCOM = 0x08
SPEED_TABLE = 0x10  # use the speed table in CV67–94 (clear: CV2/5/6)
LONG_ADDRESS = 0x20


@dataclass
class Config:
    """The options in CV29. `other_bits` keeps bits 6 and 7 as they were."""

    reversed: bool = False
    speed_steps_28: bool = True
    analogue: bool = True
    railcom: bool = False
    speed_table: bool = False
    long_address: bool = False
    other_bits: int = 0

    @classmethod
    def from_cv29(cls, value: int) -> "Config":
        return cls(
            reversed=bool(value & REVERSED),
            speed_steps_28=bool(value & SPEED_STEPS_28),
            analogue=bool(value & ANALOGUE),
            railcom=bool(value & RAILCOM),
            speed_table=bool(value & SPEED_TABLE),
            long_address=bool(value & LONG_ADDRESS),
            other_bits=value & 0xC0,
        )

    def cv29(self) -> int:
        value = self.other_bits & 0xC0
        for flag, bit in ((self.reversed, REVERSED), (self.speed_steps_28, SPEED_STEPS_28),
                          (self.analogue, ANALOGUE), (self.railcom, RAILCOM),
                          (self.speed_table, SPEED_TABLE), (self.long_address, LONG_ADDRESS)):
            if flag:
                value |= bit
        return value

    @property
    def is_accessory(self) -> bool:
        return bool(self.other_bits & 0x80)


def long_address_from(cv17: int, cv18: int) -> int:
    return ((cv17 & 0x3F) << 8) | cv18


def long_address_cvs(address: int) -> tuple[int, int]:
    """(CV17, CV18) for a long address."""
    if not 1 <= address <= 10239:
        raise ValueError(f"A long address must be 1–10239 (not {address})")
    return 0xC0 | (address >> 8), address & 0xFF


def active_address(cv1: int, cv17: Optional[int], cv18: Optional[int], cv29: int) -> tuple[Optional[int], bool]:
    """The address the loco answers to, and whether it's a long one. The
    address is None when CV29 says long but CV17/18 couldn't be read."""
    if cv29 & LONG_ADDRESS:
        if cv17 is None or cv18 is None:
            return None, True
        return long_address_from(cv17, cv18), True
    return cv1, False


def address_writes(address: int, long: bool, cv29: int) -> list[tuple[int, int]]:
    """The (CV, value) writes that give a decoder a new address. CV29 is
    written last, so the loco only switches to the new address once it's
    all in place, and its other options are kept."""
    if long:
        cv17, cv18 = long_address_cvs(address)
        return [(17, cv17), (18, cv18), (29, cv29 | LONG_ADDRESS)]
    if not 1 <= address <= 127:
        raise ValueError(f"A short address must be 1–127 (not {address})")
    return [(1, address), (29, cv29 & ~LONG_ADDRESS & 0xFF)]


def should_be_long(address: int) -> bool:
    """NCE (like most systems) treats 1–127 as short and 128+ as long."""
    return address > 127


@dataclass
class DecoderInfo:
    """What "Read decoder" finds out."""

    cv1: int
    cv7: int
    cv8: int
    cv29: int
    cv17: Optional[int] = None
    cv18: Optional[int] = None

    @property
    def manufacturer(self) -> str:
        return manufacturer_name(self.cv8)

    @property
    def config(self) -> Config:
        return Config.from_cv29(self.cv29)

    @property
    def address(self) -> tuple[Optional[int], bool]:
        return active_address(self.cv1, self.cv17, self.cv18, self.cv29)

    @property
    def long_address(self) -> Optional[int]:
        if self.cv17 is None or self.cv18 is None:
            return None
        return long_address_from(self.cv17, self.cv18)


def format_value(value: int) -> tuple[str, str]:
    """A CV value as hex and as bits (bit 7 first), for the CV table."""
    return f"0x{value:02X}", f"{value:08b}"
