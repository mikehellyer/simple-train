import io
import subprocess
from unittest.mock import patch

from simple_train.core.self_update import (
    download_asset,
    find_asset_for_this_platform,
    launch_installer,
)


ASSETS = [
    ("Simple-Train-0.2.0-Windows-Setup.exe", "https://dl/win.exe"),
    ("Simple-Train-0.2.0-macOS.dmg", "https://dl/mac.dmg"),
    ("simple-train_0.2.0_amd64.deb", "https://dl/lin.deb"),
]


def test_finds_windows_asset():
    with patch("sys.platform", "win32"):
        assert find_asset_for_this_platform(ASSETS) == "https://dl/win.exe"


def test_finds_macos_asset():
    with patch("sys.platform", "darwin"):
        assert find_asset_for_this_platform(ASSETS) == "https://dl/mac.dmg"


def test_finds_linux_asset():
    # The .deb is picked by processor, so say which: the test machine may be an ARM Mac.
    with patch("sys.platform", "linux"):
        assert find_asset_for_this_platform(ASSETS, arch="amd64") == "https://dl/lin.deb"
        assert find_asset_for_this_platform(ASSETS, arch="arm64") is None


def test_returns_none_when_no_matching_asset():
    with patch("sys.platform", "win32"):
        assert find_asset_for_this_platform(ASSETS[1:]) is None


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_asset_writes_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix="": str(tmp_path))
    with patch("urllib.request.urlopen", return_value=_Response(b"installer bytes")):
        path = download_asset("https://dl/Simple-Train-0.2.0-macOS.dmg")

    assert path is not None
    assert path.name == "Simple-Train-0.2.0-macOS.dmg"
    assert path.read_bytes() == b"installer bytes"


def test_download_asset_returns_none_when_unreachable():
    with patch("urllib.request.urlopen", side_effect=OSError("network down")):
        assert download_asset("https://dl/whatever.exe") is None


def test_launch_installer_linux_prefers_pkexec_apt_over_xdg_open():
    # Handing a local .deb to a desktop "Software" GUI via xdg-open is
    # unreliable across distros (some show "Uninstall" instead of
    # "Install"/"Upgrade" for an already-installed package name and do
    # nothing useful) — installing directly via apt is deterministic and
    # only prompts for a password once.
    def fake_which(name):
        return {"pkexec": "/usr/bin/pkexec", "apt": "/usr/bin/apt"}[name]

    with patch("simple_train.core.self_update.sys.platform", "linux"), patch(
        "simple_train.core.self_update.shutil.which", side_effect=fake_which
    ), patch("simple_train.core.self_update.subprocess.Popen") as mock_popen:
        result = launch_installer("/tmp/simple-train_1.2.3_amd64.deb")

    # Absolute paths, not bare "pkexec"/"apt": pkexec resolves the
    # command it's given using its own restricted environment rather
    # than the invoking shell's $PATH, and a bare "apt" name can fail to
    # resolve there (exit 127) even though `apt` works normally. stderr
    # is piped so a failure can show pkexec/apt's actual error text.
    mock_popen.assert_called_once_with(
        ["/usr/bin/pkexec", "/usr/bin/apt", "install", "-y", "/tmp/simple-train_1.2.3_amd64.deb"],
        stderr=subprocess.PIPE,
        text=True,
    )
    # The caller (main_window.py) waits on this before quitting, on
    # Linux, so quitting can't kill the pkexec password prompt before
    # it's answered.
    assert result is mock_popen.return_value


def test_launch_installer_linux_falls_back_to_xdg_open_without_pkexec_or_apt():
    with patch("simple_train.core.self_update.sys.platform", "linux"), patch(
        "simple_train.core.self_update.shutil.which", return_value=None
    ), patch("simple_train.core.self_update.subprocess.Popen") as mock_popen:
        result = launch_installer("/tmp/simple-train_1.2.3_amd64.deb")

    mock_popen.assert_called_once_with(["xdg-open", "/tmp/simple-train_1.2.3_amd64.deb"])
    assert result is mock_popen.return_value


def test_launch_installer_macos_uses_open():
    with patch("simple_train.core.self_update.sys.platform", "darwin"), patch(
        "simple_train.core.self_update.subprocess.Popen"
    ) as mock_popen:
        result = launch_installer("/tmp/Simple-Train.dmg")

    # `open` mounts the dmg and opens a Finder window for it, but that
    # window doesn't reliably come to the front on its own — right
    # before this app quits, that looks exactly like nothing happened.
    assert mock_popen.call_args_list[0].args[0] == ["open", "/tmp/Simple-Train.dmg"]
    assert mock_popen.call_args_list[1].args[0] == ["open", "-a", "Finder"]
    assert result is mock_popen.return_value


def test_launch_installer_macos_still_returns_the_process_if_raising_finder_fails():
    def fake_popen(args, **kwargs):
        if args == ["open", "-a", "Finder"]:
            raise OSError("no Finder?")
        return "mock-dmg-process"

    with patch("simple_train.core.self_update.sys.platform", "darwin"), patch(
        "simple_train.core.self_update.subprocess.Popen", side_effect=fake_popen
    ):
        result = launch_installer("/tmp/Simple-Train.dmg")

    assert result == "mock-dmg-process"


def test_launch_installer_windows_uses_startfile():
    with patch("simple_train.core.self_update.sys.platform", "win32"), patch(
        "os.startfile", create=True
    ) as mock_startfile:
        result = launch_installer("C:\\temp\\Setup.exe")

    mock_startfile.assert_called_once_with("C:\\temp\\Setup.exe")
    # No process handle for os.startfile — main_window.py falls back to a
    # timed quit instead of waiting on a process.
    assert result is None


def test_linux_picks_the_deb_for_this_processor():
    assets = [
        ("simple-train_0.3.0_amd64.deb", "https://dl/pc.deb"),
        ("simple-train_0.3.0_arm64.deb", "https://dl/pi.deb"),
        ("Simple-Train-0.3.0-macOS.dmg", "https://dl/mac.dmg"),
    ]
    with patch("sys.platform", "linux"):
        assert find_asset_for_this_platform(assets, arch="arm64") == "https://dl/pi.deb"
        assert find_asset_for_this_platform(assets, arch="amd64") == "https://dl/pc.deb"
        assert find_asset_for_this_platform(assets[2:], arch="arm64") is None
