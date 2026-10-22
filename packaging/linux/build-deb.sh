#!/usr/bin/env bash
# Packages dist/Simple-Train/ (already built by PyInstaller, onedir mode)
# into a .deb that installs to /opt/simple-train and adds a proper menu
# entry + icon, so it behaves like a native app rather than a dropped
# binary. Uses dpkg-deb directly, which ships with Debian-based distros
# (Pop!_OS included) — no extra tool to install in CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE="$ROOT/dist/Simple-Train"
VERSION="$(grep -o '__version__ = "[^"]*"' "$ROOT/src/simple_train/__init__.py" | cut -d'"' -f2)"
ARCH="$(dpkg --print-architecture)"
PKG_ROOT="$ROOT/dist/deb-staging"
OUT="$ROOT/dist/simple-train_${VERSION}_${ARCH}.deb"

if [ ! -d "$BUNDLE" ]; then
  echo "error: $BUNDLE not found — run PyInstaller first" >&2
  exit 1
fi

rm -rf "$PKG_ROOT" "$OUT"
mkdir -p "$PKG_ROOT/DEBIAN"
mkdir -p "$PKG_ROOT/opt/simple-train"
mkdir -p "$PKG_ROOT/usr/bin"
mkdir -p "$PKG_ROOT/usr/share/applications"

cp -R "$BUNDLE"/. "$PKG_ROOT/opt/simple-train/"
ln -s /opt/simple-train/Simple-Train "$PKG_ROOT/usr/bin/simple-train"
cp "$ROOT/packaging/linux/simple-train.desktop" "$PKG_ROOT/usr/share/applications/"
mkdir -p "$PKG_ROOT/usr/lib/udev/rules.d"
cp "$ROOT/packaging/linux/71-simple-train-nce.rules" "$PKG_ROOT/usr/lib/udev/rules.d/"

for size in 16 32 48 64 128 256 512; do
  dir="$PKG_ROOT/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$dir"
  cp "$ROOT/packaging/icons/icon_${size}.png" "$dir/simple-train.png"
done

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: simple-train
Version: $VERSION
Section: misc
Priority: optional
Architecture: $ARCH
Depends: libegl1, libxkbcommon0, libxcb-cursor0, libfontconfig1, libdbus-1-3
Maintainer: Mike Hellyer
Description: Model railway control for DCC, starting with an NCE decoder programmer
 Read and write DCC decoder CVs through the NCE USB interface: the
 address, the CV29 options, speed and motor settings, or any CV, on the
 programming track or on the main.
EOF

# Pick up the udev rule at once, so the USB interface works without a re-plug.
cat > "$PKG_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules || true
  udevadm trigger --subsystem-match=tty --action=change || true
fi
EOF
chmod 755 "$PKG_ROOT/DEBIAN/postinst"

dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUT"
rm -rf "$PKG_ROOT"

echo "wrote $OUT"
