"""Programming jobs: a run of CV reads or writes, done as one piece.

Each job puts the command station into programming track mode first and
takes it out again at the end (on a Power Cab the one track is the
programming track meanwhile, so the main is unpowered). Jobs block, so the
GUI runs them in the background and watches a Progress for how far along
they are and whether the user has asked to stop.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable, Optional, Union

from simple_train.core import nce
from simple_train.core.decoder import DecoderInfo


@dataclass
class Progress:
    """Shared between a job (on its thread) and the GUI (polling it)."""

    total: int = 0
    done: int = 0
    current: str = ""
    _stop: threading.Event = field(default_factory=threading.Event)

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()


class Stopped(nce.NceError):
    def __init__(self):
        super().__init__("Stopped")


Result = Union[int, nce.NceError]


class Programmer:
    def __init__(self, connection: nce.NceConnection, command_station: str = nce.POWER_CAB):
        self.connection = connection
        self.command_station = command_station

    def check_mode(self, mode: str) -> None:
        if nce.uses_programming_track(mode) and not nce.has_programming_track(self.command_station):
            name = nce.COMMAND_STATIONS.get(self.command_station, self.command_station)
            raise nce.NotSupported(
                f"Through the USB interface a {name} has no programming track (only a Power Cab "
                "or Twin does) — use “On the main” instead")

    @contextmanager
    def _session(self, mode: str):
        """Programming track mode for the length of a job."""
        self.check_mode(mode)
        track = nce.uses_programming_track(mode)
        if track:
            self.connection.enter_programming()
        try:
            yield
        except BaseException:
            if track:
                try:
                    self.connection.exit_programming()
                except nce.NceError:
                    pass  # the first error is the one worth reporting
            raise
        if track:
            self.connection.exit_programming()

    def read_cvs(self, cvs: Iterable[int], mode: str, progress: Optional[Progress] = None,
                 keep_going: bool = False) -> dict[int, Result]:
        """Read each CV in turn. A CV the decoder doesn't answer for stops
        the job (it's most likely not on the track), unless keep_going —
        when reading a range, some CVs just aren't there."""
        if not nce.can_read(mode):
            raise nce.NceError("NCE can't read CVs on the main — use the programming track")
        cvs = list(cvs)
        progress = progress or Progress()
        progress.total, progress.done = len(cvs), 0
        results: dict[int, Result] = {}
        with self._session(mode):
            for cv in cvs:
                if progress.stopping:
                    raise Stopped()
                progress.current = f"Reading CV {cv}"
                try:
                    results[cv] = self.connection.read_cv(cv, mode)
                except nce.NoDecoder as error:
                    if not keep_going:
                        raise
                    results[cv] = error
                except nce.NceError as error:
                    if isinstance(error, nce.NoAnswer) or not keep_going:
                        raise
                    results[cv] = error
                progress.done += 1
        return results

    def write_cvs(self, writes: Iterable[tuple[int, int]], mode: str, address: int = 3,
                  long: Optional[bool] = None, verify: bool = False,
                  progress: Optional[Progress] = None) -> None:
        """Write each (CV, value) in turn; with verify (programming track
        only), read each one back to make sure the decoder took it."""
        writes = list(writes)
        verify = verify and nce.can_read(mode)
        progress = progress or Progress()
        progress.total, progress.done = len(writes), 0
        with self._session(mode):
            for cv, value in writes:
                if progress.stopping:
                    raise Stopped()
                progress.current = f"Writing CV {cv} = {value}"
                self.connection.write_cv(cv, value, mode, address, long)
                if verify:
                    progress.current = f"Checking CV {cv}"
                    found = self.connection.read_cv(cv, mode)
                    if found != value:
                        raise nce.NceError(f"CV {cv} reads back as {found}, not {value} — "
                                           "the decoder didn't take the new value")
                progress.done += 1

    def identify(self, mode: str, progress: Optional[Progress] = None) -> DecoderInfo:
        """Read what's needed to say who made the decoder and what address it's on."""
        wanted = [8, 7, 1, 29]
        if mode != nce.REGISTER:  # register mode can't reach CV17/18
            wanted += [17, 18]
        progress = progress or Progress()
        progress.total, progress.done = len(wanted), 0
        values: dict[int, int] = {}
        with self._session(mode):
            for cv in wanted:
                if progress.stopping:
                    raise Stopped()
                progress.current = f"Reading CV {cv}"
                try:
                    values[cv] = self.connection.read_cv(cv, mode)
                except nce.NoDecoder:
                    if cv in (17, 18):  # some short-address-only decoders lack them
                        continue
                    raise
                progress.done += 1
        return DecoderInfo(cv1=values[1], cv7=values[7], cv8=values[8], cv29=values[29],
                           cv17=values.get(17), cv18=values.get(18))
