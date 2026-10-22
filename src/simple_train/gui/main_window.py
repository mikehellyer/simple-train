"""The main window: the connection bar, the update banner, and a tab for
each part of the app (just the programmer, so far)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import QFrame, QMainWindow, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from simple_train import __version__
from simple_train.core.diagnostics import log_dir
from simple_train.core.self_update import download_asset, find_asset_for_this_platform, launch_installer
from simple_train.core.settings import SettingsStore
from simple_train.core.updater import API_TIMEOUT_SECONDS, check_for_update
from simple_train.gui.connection_bar import ConnectionBar
from simple_train.gui.link import Link
from simple_train.gui.programmer_panel import ProgrammerPanel
from simple_train.gui.roster_panel import RosterPanel
from simple_train.gui.roster_store import RosterStore
from simple_train.gui.throttle_panel import ThrottlePanel
from simple_train.gui.update_banner import UpdateBanner
from simple_train.gui.workers import BackgroundRunner

UPDATE_OWNER = "mikehellyer"
UPDATE_REPO = "simple-train"
BACKGROUND_JOIN_TIMEOUT_MS = (API_TIMEOUT_SECONDS + 1) * 1000
ICON_PATH = Path(__file__).parent / "resources" / "icon.png"


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore | None = None, roster: RosterStore | None = None):
        super().__init__()
        self.setWindowTitle("Simple-Train")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1180, 780)

        self._store = store or SettingsStore()
        self._runner = BackgroundRunner(self)
        self._pending_update = None
        self.link = Link(self)
        self.roster = roster or RosterStore(parent=self)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._update_banner = UpdateBanner()
        self._update_banner.update_clicked.connect(self._start_update)
        layout.addWidget(self._update_banner)
        self.connection_bar = ConnectionBar(self.link, self._store)
        layout.addWidget(self.connection_bar)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self.programmer = ProgrammerPanel(self.link, self._store, self.roster)
        self._tabs.addTab(self.programmer, "Programmer")
        self.throttles = ThrottlePanel(self.link, self._store, self.roster)
        self._tabs.addTab(self.throttles, "Throttles")
        self.locos = RosterPanel(self.roster)
        self._tabs.addTab(self.locos, "Locos")
        self.locos.drive_requested.connect(self._drive_loco)
        self.locos.open_in_programmer.connect(self._open_in_programmer)
        self.locos.restore_requested.connect(self._restore_loco)
        layout.addWidget(self._tabs, stretch=1)
        self.setCentralWidget(central)

        self._build_menus()
        self.programmer.log(f"Simple-Train {__version__}. Pick the NCE USB interface's port above and press "
                            "Connect — or choose “Demo (no hardware)” to try it out.")
        if self._store.settings.connect_at_start and self._store.settings.port:
            QTimer.singleShot(0, self.connection_bar.connect_now)
        QTimer.singleShot(1500, self._check_for_updates)

    def _open_in_programmer(self, loco_id: str) -> None:
        self.programmer.link_loco(loco_id)
        self._tabs.setCurrentWidget(self.programmer)

    def _drive_loco(self, loco_id: str) -> None:
        loco = self.roster.roster.get(loco_id)
        if loco is not None:
            self._tabs.setCurrentWidget(self.throttles)
            self.throttles.drive(loco)

    def _restore_loco(self, loco_id: str) -> None:
        if not self.link.connected:
            QMessageBox.information(self, "Write saved CVs", "Connect to the NCE USB interface first.")
            return
        self._tabs.setCurrentWidget(self.programmer)
        self.programmer.restore(self.roster.roster.get(loco_id))

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        updates = QAction("Check for &updates", self)
        updates.triggered.connect(lambda: self._check_for_updates(tell_if_none=True))
        help_menu.addAction(updates)
        logs = QAction("Open the &log folder", self)
        logs.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir()))))
        help_menu.addAction(logs)
        help_menu.addSeparator()
        about = QAction("&About Simple-Train", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    # --- about & updates

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About Simple-Train",
            f"<b>Simple-Train</b> v{__version__}<br><br>"
            "Model railway control for DCC, with a decoder programmer, throttles and a loco roster, "
            "for NCE systems through the NCE USB interface.<br><br>"
            "Decoder manufacturer names from the NMRA list, as kept by "
            "<a href='https://www.jmri.org/'>JMRI</a>.<br><br>"
            "By Mike Hellyer, built with Claude Code.",
        )

    def _check_for_updates(self, tell_if_none: bool = False) -> None:
        def checked(info):
            self._on_update_checked(info)
            if info is None and tell_if_none:
                QMessageBox.information(self, "Simple-Train", f"You have the latest version ({__version__}).")

        self._runner.run(lambda: check_for_update(__version__, UPDATE_OWNER, UPDATE_REPO), checked,
                         lambda error: None)

    def _on_update_checked(self, info) -> None:
        if info:
            self._pending_update = info
            self._update_banner.announce(info.version)

    def _start_update(self) -> None:
        if self._pending_update is None:
            return
        asset_url = find_asset_for_this_platform(self._pending_update.assets)
        if asset_url is None:
            self._update_banner.set_status(f"No installer for this platform — see {self._pending_update.url}")
            return
        self._update_banner.set_busy(True, "Downloading…")
        self._runner.run(lambda: download_asset(asset_url), self._on_update_downloaded,
                         lambda error: self._on_update_downloaded(None))

    def _on_update_downloaded(self, path) -> None:
        if path is None:
            self._update_banner.set_status("Couldn't download the update — try again")
            self._update_banner.set_busy(False)
            return
        try:
            process = launch_installer(path)
        except OSError:
            self._update_banner.set_status(f"Downloaded to {path} — open it manually")
            self._update_banner.set_busy(False)
            return

        self._update_banner.set_status("Installer launched — closing to finish…")
        if sys.platform not in ("win32", "darwin") and process is not None:
            # Linux: wait for pkexec/apt to finish before quitting — quitting
            # immediately can kill its password prompt before it's answered.
            self._runner.run(lambda: (path, self._wait_for_installer(process)), self._on_installer_finished)
        else:
            QTimer.singleShot(1500, self.close)

    @staticmethod
    def _wait_for_installer(process) -> tuple[int, str]:
        returncode = process.wait()
        stderr_text = process.stderr.read().strip() if process.stderr is not None else ""
        return returncode, stderr_text

    def _on_installer_finished(self, result) -> None:
        path, (returncode, stderr_text) = result
        if returncode == 0:
            self.close()
            return
        detail = f": {stderr_text}" if stderr_text else f" (exit code {returncode})"
        self._update_banner.set_status(f"Update didn't install{detail} — installer is at {path}")
        self._update_banner.set_busy(False)

    def closeEvent(self, event) -> None:
        self.locos.shutdown()  # saves any edit still waiting
        self.throttles.shutdown()  # brings moving locos to a stop
        self.link.shutdown()  # leaves programming track mode, so the Power Cab's track is the main again
        self._store.save()
        self._runner.shutdown(BACKGROUND_JOIN_TIMEOUT_MS)
        super().closeEvent(event)
