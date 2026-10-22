"""Talking to an NCE command station through the NCE USB interface.

The USB interface is a serial port (a Silicon Labs CP210x chip: /dev/ttyUSB0
on Linux, COMn on Windows, /dev/cu.SLAB_USBtoUART on a Mac) that speaks NCE's
binary command set at 9600 baud, 8N1, no flow control. Every command is a
command byte plus a few argument bytes, and the command station answers with
a fixed number of bytes — usually just "!" for success, or an error digit.

Programming track commands (see JMRI's jmrix/nce for the same set):
  0x9E / 0x9F          enter / leave programming track mode
  0xA8 cvH cvL data    direct mode write      -> status
  0xA9 cvH cvL         direct mode read       -> value, status
  0xA0 / 0xA1          the same in paged mode
  0xA6 reg data        register mode write    -> status
  0xA7 reg             register mode read     -> value, status
And on the main track:
  0xAE adH adL cvH cvL data   program a loco's CV on the main ("POM", write only)
  0xAA                        the interface's version: 3 bytes

Through the USB interface only a Power Cab or a Twin offers the programming
track; with an SB3, SB5 or Power Pro the USB interface can only program on
the main.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional, Protocol

BAUD_RATES = (9600, 19200)
DEFAULT_BAUD = 9600

NOP = 0x80
ENTER_PROGRAMMING = 0x9E
EXIT_PROGRAMMING = 0x9F
PAGED_WRITE = 0xA0
PAGED_READ = 0xA1
LOCO_COMMAND = 0xA2
REGISTER_WRITE = 0xA6
REGISTER_READ = 0xA7
DIRECT_WRITE = 0xA8
DIRECT_READ = 0xA9
VERSION = 0xAA
OPS_PROGRAM_LOCO = 0xAE

OK = ord("!")

# How long to wait for an answer. A paged-mode read tries each value in
# turn on some decoders, so JMRI allows 20 s; direct mode is quicker.
QUICK_TIMEOUT = 2.0
PROGRAMMING_TIMEOUT = 10.0
DIRECT_TIMEOUT = 15.0
PAGED_TIMEOUT = 25.0

# Programming modes. The first three use the programming track.
DIRECT = "direct"
PAGED = "paged"
REGISTER = "register"
MAIN = "main"  # programming on the main (POM)
MODES = (DIRECT, PAGED, REGISTER, MAIN)
MODE_NAMES = {
    DIRECT: "Direct mode",
    PAGED: "Paged mode",
    REGISTER: "Register mode",
    MAIN: "On the main (POM)",
}

# Command stations the USB interface can be plugged into.
POWER_CAB = "powercab"
TWIN = "twin"
SB3 = "sb3"
SB5 = "sb5"
POWER_PRO = "powerpro"
COMMAND_STATIONS = {
    POWER_CAB: "Power Cab",
    TWIN: "Twin",
    SB3: "Smart Booster SB3",
    SB5: "Smart Booster SB5",
    POWER_PRO: "Power Pro",
}

# In register mode only these CVs can be reached directly, each in its own
# register (register 6 is the page register, used by paged mode).
REGISTER_FOR_CV = {1: 1, 2: 2, 3: 3, 4: 4, 29: 5, 7: 7, 8: 8}

MAX_CV = 1024
MAX_LONG_ADDRESS = 10239
MAX_SHORT_ADDRESS = 127


def has_programming_track(command_station: str) -> bool:
    return command_station in (POWER_CAB, TWIN)


def uses_programming_track(mode: str) -> bool:
    return mode != MAIN


def can_read(mode: str) -> bool:
    """Only the programming track can read a decoder back: on the main,
    the NCE system can't hear the decoder's answer."""
    return uses_programming_track(mode)


class NceError(Exception):
    """Something went wrong talking to the command station. The message is
    written to be shown to the user as it is."""


class NoAnswer(NceError):
    """The command station didn't answer at all."""


class NoDecoder(NceError):
    """The command station answered, but heard nothing from the decoder."""


class NotSupported(NceError):
    """The command station doesn't offer this command over USB."""


_ERRORS = {
    ord("0"): "The command station doesn't support that command over the USB interface",
    ord("1"): "That loco address is out of range",
    ord("2"): "That cab address or command is out of range",
    ord("3"): "That CV number or value is out of range",
    ord("4"): "The command was the wrong length",
}


def _status_error(status: int, reading: bool) -> NceError:
    if reading and status == ord("3"):
        # For a read, "3" is how the command station says nothing answered.
        return NoDecoder("No answer from the decoder — is the loco on the programming track, "
                         "with clean wheels and track?")
    if status == ord("0"):
        return NotSupported(_ERRORS[status])
    text = _ERRORS.get(status, f"The command station answered with an unexpected code ({status:#04x})")
    return NceError(text)


class Transport(Protocol):
    """A byte pipe to the command station: a serial port, or the simulator."""

    def write(self, data: bytes) -> None: ...

    def read(self, count: int, timeout: float) -> bytes:
        """Up to `count` bytes, waiting at most `timeout` seconds in all."""
        ...

    def reset_input(self) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    """The NCE USB interface, through pyserial."""

    def __init__(self, port: str, baud: int = DEFAULT_BAUD):
        import serial  # imported here so the core (and its tests) don't need it

        try:
            self._serial = serial.Serial(port, baudrate=baud, bytesize=8, parity="N", stopbits=1,
                                         timeout=0.1, write_timeout=2, rtscts=False, xonxoff=False)
        except serial.SerialException as error:
            raise NceError(describe_open_error(port, error)) from error

    def write(self, data: bytes) -> None:
        import serial

        try:
            self._serial.write(data)
            self._serial.flush()
        except serial.SerialException as error:
            raise NceError(f"Couldn't send to the USB interface: {error}") from error

    def read(self, count: int, timeout: float) -> bytes:
        import serial

        deadline = time.monotonic() + timeout
        data = b""
        try:
            while len(data) < count and time.monotonic() < deadline:
                data += self._serial.read(count - len(data))
        except serial.SerialException as error:
            raise NceError(f"The USB interface stopped answering: {error}") from error
        return data

    def reset_input(self) -> None:
        try:
            self._serial.reset_input_buffer()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass


def describe_open_error(port: str, error: Exception) -> str:
    text = str(error)
    if "Permission denied" in text or "Errno 13" in text:
        return (f"Not allowed to open {port}. On Linux, add yourself to the dialout group "
                "(sudo usermod -aG dialout $USER), then log out and back in.")
    if "No such file" in text or "Errno 2" in text or "FileNotFoundError" in text:
        return f"{port} isn't there any more — is the USB interface plugged in?"
    if "busy" in text.lower() or "Errno 16" in text:
        return f"{port} is in use by another program (JMRI, another Simple-Train?)"
    return f"Couldn't open {port}: {text}"


@dataclass
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def _cv_bytes(cv: int) -> bytes:
    if not 1 <= cv <= MAX_CV:
        raise NceError(f"CV {cv} is out of range (1–{MAX_CV})")
    return bytes((cv >> 8, cv & 0xFF))


def _check_value(value: int) -> None:
    if not 0 <= value <= 255:
        raise NceError(f"A CV value must be 0–255 (not {value})")


def loco_address_bytes(address: int, long: Optional[bool] = None) -> bytes:
    """A loco address as NCE sends it: long addresses have the top two bits
    of the high byte set. Addresses over 127 are always long; 1–127 are
    short unless `long` says otherwise."""
    if long is None:
        long = address > MAX_SHORT_ADDRESS
    if long:
        if not 1 <= address <= MAX_LONG_ADDRESS:
            raise NceError(f"A long address must be 1–{MAX_LONG_ADDRESS} (not {address})")
        address |= 0xC000
    elif not 1 <= address <= MAX_SHORT_ADDRESS:
        raise NceError(f"A short address must be 1–{MAX_SHORT_ADDRESS} (not {address})")
    return bytes((address >> 8, address & 0xFF))


class NceConnection:
    """One open connection to the command station. Every method blocks
    until the command station has answered, so call them off the GUI
    thread; a lock keeps commands from different threads apart."""

    def __init__(self, transport: Transport):
        self._transport = transport
        self._lock = threading.Lock()
        self.in_programming_mode = False

    def close(self) -> None:
        with self._lock:
            if self.in_programming_mode:
                try:
                    self._send(bytes((EXIT_PROGRAMMING,)), 1, PROGRAMMING_TIMEOUT)
                except NceError:
                    pass
                self.in_programming_mode = False
            self._transport.close()

    def _send(self, command: bytes, reply_length: int, timeout: float) -> bytes:
        self._transport.reset_input()  # drop anything left over from a timed-out command
        self._transport.write(command)
        reply = self._transport.read(reply_length, timeout)
        if len(reply) < reply_length:
            raise NoAnswer("No answer from the command station — check the USB interface is "
                           "plugged in to the cab bus and the command station is switched on")
        return reply

    def _command(self, command: bytes, reply_length: int = 1, timeout: float = QUICK_TIMEOUT) -> bytes:
        with self._lock:
            return self._send(command, reply_length, timeout)

    # --- the connection itself

    def check(self) -> None:
        """Raise NceError unless the command station answers a no-op."""
        reply = self._command(bytes((NOP,)))
        if reply[0] != OK:
            raise NceError(f"Something answered, but not like an NCE command station ({reply[0]:#04x})")

    def version(self) -> Version:
        reply = self._command(bytes((VERSION,)), 3)
        return Version(*reply)

    # --- the programming track

    def enter_programming(self) -> None:
        reply = self._command(bytes((ENTER_PROGRAMMING,)), 1, PROGRAMMING_TIMEOUT)
        if reply[0] != OK:
            raise _status_error(reply[0], reading=False)
        self.in_programming_mode = True

    def exit_programming(self) -> None:
        # Old NCE firmware can crash on an exit without an enter (JMRI notes this).
        if not self.in_programming_mode:
            return
        self.in_programming_mode = False
        reply = self._command(bytes((EXIT_PROGRAMMING,)), 1, PROGRAMMING_TIMEOUT)
        if reply[0] != OK:
            raise _status_error(reply[0], reading=False)

    def read_cv(self, cv: int, mode: str = DIRECT) -> int:
        if mode == DIRECT:
            command = bytes((DIRECT_READ,)) + _cv_bytes(cv)
            timeout = DIRECT_TIMEOUT
        elif mode == PAGED:
            command = bytes((PAGED_READ,)) + _cv_bytes(cv)
            timeout = PAGED_TIMEOUT
        elif mode == REGISTER:
            command = bytes((REGISTER_READ, _register(cv)))
            timeout = PAGED_TIMEOUT
        else:
            raise NceError("Reading CVs needs the programming track: on the main, NCE can only write")
        value, status = self._command(command, 2, timeout)
        if status != OK:
            raise _status_error(status, reading=True)
        return value

    def write_cv(self, cv: int, value: int, mode: str = DIRECT, address: int = 3, long: Optional[bool] = None) -> None:
        """Write one CV. On the main, `address` (and `long`) say which loco."""
        _check_value(value)
        if mode == DIRECT:
            command = bytes((DIRECT_WRITE,)) + _cv_bytes(cv) + bytes((value,))
            timeout = DIRECT_TIMEOUT
        elif mode == PAGED:
            command = bytes((PAGED_WRITE,)) + _cv_bytes(cv) + bytes((value,))
            timeout = PAGED_TIMEOUT
        elif mode == REGISTER:
            command = bytes((REGISTER_WRITE, _register(cv), value))
            timeout = PAGED_TIMEOUT
        elif mode == MAIN:
            command = bytes((OPS_PROGRAM_LOCO,)) + loco_address_bytes(address, long) + _cv_bytes(cv) + bytes((value,))
            timeout = QUICK_TIMEOUT
        else:
            raise NceError(f"Unknown programming mode {mode!r}")
        (status,) = self._command(command, 1, timeout)
        if status != OK:
            raise _status_error(status, reading=False)


def _register(cv: int) -> int:
    try:
        return REGISTER_FOR_CV[cv]
    except KeyError:
        raise NceError(f"Register mode can only reach CVs 1–4, 7, 8 and 29 (not CV {cv}) — "
                       "use direct or paged mode") from None
