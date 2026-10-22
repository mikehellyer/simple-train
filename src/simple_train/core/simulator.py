"""A pretend NCE command station with a decoder on its programming track.

It speaks the same binary commands as the real USB interface, so the whole
app can be tried (and tested) without any hardware: pick "Demo (no
hardware)" as the port.
"""
from __future__ import annotations

import time

from simple_train.core import nce

FACTORY_CVS = {
    1: 3,  # short address
    2: 1,  # start voltage
    3: 8,  # acceleration
    4: 6,  # deceleration
    5: 0,  # top voltage (0 = full)
    6: 0,  # mid voltage
    7: 21,  # version
    8: 151,  # manufacturer: ESU
    17: 192,  # long address, high byte
    18: 3,  # long address, low byte
    19: 0,  # consist address
    29: 0b00000110,  # 28/128 speed steps, analogue running allowed
}


class SimulatedCommandStation:
    """A Transport: write() a command and its answer is ready to read()."""

    def __init__(self, command_station: str = nce.POWER_CAB, delay: float = 0.0, loco_on_track: bool = True):
        self.command_station = command_station
        self.delay = delay  # seconds per programming-track operation, to feel real in the demo
        self.loco_on_track = loco_on_track
        self.cvs = dict(FACTORY_CVS)
        self.in_programming_mode = False
        self.main_writes: list[tuple[int, int, int]] = []  # (address word, cv, value)
        # What each loco on the main has been told: address word -> {op: data}
        self.locos: dict[int, dict[int, int]] = {}
        self.sent: list[bytes] = []
        self._reply = b""

    # --- Transport

    def write(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        self._reply += self._answer(bytes(data))

    def read(self, count: int, timeout: float) -> bytes:
        reply, self._reply = self._reply[:count], self._reply[count:]
        return reply

    def reset_input(self) -> None:
        self._reply = b""

    def close(self) -> None:
        pass

    # --- the command station

    def _answer(self, command: bytes) -> bytes:
        op, args = command[0], command[1:]
        ok = bytes((nce.OK,))
        if op == nce.NOP:
            return ok
        if op == nce.VERSION:
            return bytes((7, 3, 7)) if self.command_station != nce.POWER_CAB else bytes((6, 3, 9))
        if op == nce.LOCO_COMMAND:
            address, sub, data = (args[0] << 8) | args[1], args[2], args[3]
            if sub > 0x17 or (sub in (0x01, 0x02, 0x03, 0x04) and data > 126):
                return b"2"
            state = self.locos.setdefault(address, {})
            if sub in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06):  # speed and direction replace each other
                for old in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06):
                    state.pop(old, None)
            state[sub] = data
            return ok
        if op == nce.OPS_PROGRAM_LOCO:
            address, cv, value = (args[0] << 8) | args[1], (args[2] << 8) | args[3], args[4]
            self.main_writes.append((address, cv, value))
            if self.loco_on_track and address == self.address_word():
                self._store(cv, value)
            return ok
        if op in (nce.ENTER_PROGRAMMING, nce.EXIT_PROGRAMMING):
            if not nce.has_programming_track(self.command_station):
                return b"0"
            self.in_programming_mode = op == nce.ENTER_PROGRAMMING
            return ok
        programming = {nce.DIRECT_READ, nce.DIRECT_WRITE, nce.PAGED_READ, nce.PAGED_WRITE,
                       nce.REGISTER_READ, nce.REGISTER_WRITE}
        if op not in programming:
            return b"0"
        reading = op in (nce.DIRECT_READ, nce.PAGED_READ, nce.REGISTER_READ)
        if not nce.has_programming_track(self.command_station):
            return b"\x000" if reading else b"0"
        time.sleep(self.delay)
        if op in (nce.REGISTER_READ, nce.REGISTER_WRITE):
            cv = {register: cv for cv, register in nce.REGISTER_FOR_CV.items()}.get(args[0], 0)
            value = args[1] if op == nce.REGISTER_WRITE else 0
        else:
            cv = (args[0] << 8) | args[1]
            value = args[2] if not reading else 0
        if reading:
            if not self.loco_on_track:
                return b"\x003"
            return bytes((self.cvs.get(cv, 0), nce.OK))
        if self.loco_on_track:
            self._store(cv, value)
        return ok  # NCE can't tell whether a write was heard

    def _store(self, cv: int, value: int) -> None:
        if cv == 8:
            if value == 8:  # the usual "reset to factory settings"
                self.cvs = dict(FACTORY_CVS)
            return
        if cv == 7:
            return  # the version can't be written
        self.cvs[cv] = value

    def address_word(self) -> int:
        """The address the decoder answers to on the main, as NCE sends it."""
        if self.cvs.get(29, 0) & 0x20:
            return (((self.cvs.get(17, 192) - 192) << 8) | self.cvs.get(18, 0)) | 0xC000
        return self.cvs.get(1, 3)
