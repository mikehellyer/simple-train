# -*- mode: python ; coding: utf-8 -*-
"""Shared PyInstaller spec for all three platforms.

Built with: pyinstaller packaging/pyinstaller/simple-train.spec
(run from the repo root, with the venv's PySide6 etc. on the path).
"""
import re
import sys
from pathlib import Path

# PySide6 6.12 drops a reference to None on every call to a method that
# returns nothing (QSlider.setValue, QLabel.setText, …). Before Python
# 3.12 None can actually be freed, so a few minutes of playback-progress
# updates used them all up and the app died with "Fatal Python error:
# none_dealloc". From 3.12 None is immortal and the bug is harmless —
# refuse to build a frozen app on anything older.
if sys.version_info < (3, 12):
    raise SystemExit(
        f"Simple-Train must be built with Python 3.12+ (this is {sys.version.split()[0]}) "
        "— see the comment in simple-train.spec"
    )

root = Path(SPECPATH).resolve().parent.parent
src = root / "src"
icons = root / "packaging" / "icons"

version = re.search(
    r'__version__ = "([^"]+)"', (src / "simple_train" / "__init__.py").read_text()
).group(1)

if sys.platform == "win32":
    icon_path = str(icons / "icon.ico")
elif sys.platform == "darwin":
    icon_path = str(icons / "icon.icns")
else:
    icon_path = None

a = Analysis(
    [str(src / "simple_train" / "app.py")],
    pathex=[str(src)],
    binaries=[],
    datas=[
        (str(src / "simple_train" / "gui" / "resources" / "icon.png"), "simple_train/gui/resources"),
    ],
    hiddenimports=["serial.tools.list_ports"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Simple-Train",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Simple-Train",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Simple-Train.app",
        icon=icon_path,
        bundle_identifier="uk.hellyer.simpletrain",
        version=version,
        info_plist={
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "NSHighResolutionCapable": True,
        },
    )
