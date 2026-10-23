import sys

from simple_train import __version__


def self_test() -> int:
    """`Simple-Train --self-test`: checks a built app has everything it
    needs bundled (the release workflow runs this on each OS). Exit code
    0 if so."""
    checks = {}
    try:
        from simple_train.core import nce
        from simple_train.core.programmer import Programmer
        from simple_train.core.simulator import SimulatedCommandStation

        programmer = Programmer(nce.NceConnection(SimulatedCommandStation()))
        checks["programmer"] = programmer.identify(nce.DIRECT).address == (3, False)
    except Exception:
        checks["programmer"] = False
    try:
        import serial  # noqa: F401
        from serial.tools import list_ports  # noqa: F401

        checks["serial ports"] = True
    except Exception:
        checks["serial ports"] = False
    try:
        from zeroconf import ServiceInfo, Zeroconf  # noqa: F401  (phones find us with it)

        from simple_train.core import withrottle

        checks["phone throttles"] = withrottle.parse_key("L144") == (144, True)
    except Exception:
        checks["phone throttles"] = False
    try:
        import certifi  # noqa: F401

        checks["certificates"] = True
    except Exception:
        checks["certificates"] = False
    report = ", ".join(f"{name}: {'ok' if ok else 'MISSING'}" for name, ok in checks.items())
    try:
        print(f"Simple-Train {__version__} self-test — {report}", flush=True)
    except (AttributeError, OSError):  # no console (Windows GUI build)
        pass
    return 0 if all(checks.values()) else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    # Qt is imported only now, so --self-test runs even where there's no
    # display or graphics libraries (the release workflow's build machines).
    from PySide6.QtWidgets import QApplication

    from simple_train.core.diagnostics import enable_app_log, enable_crash_log, log_event
    from simple_train.gui.main_window import MainWindow

    enable_app_log(__version__)
    enable_crash_log()
    app = QApplication(sys.argv)
    app.setApplicationName("Simple-Train")
    app.setDesktopFileName("simple-train")
    window = MainWindow()
    window.show()
    code = app.exec()
    log_event(f"event loop finished (code {code})")
    return code


if __name__ == "__main__":
    sys.exit(main())
