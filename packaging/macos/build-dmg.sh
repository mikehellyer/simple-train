#!/usr/bin/env bash
# Packages dist/Simple-Train.app (already built by PyInstaller) into a
# .dmg where dragging the app onto an Applications shortcut is the install
# step. Uses hdiutil directly — it ships with macOS, so no extra tool to
# install in CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/dist/Simple-Train.app"
VERSION="$(grep -o '__version__ = "[^"]*"' "$ROOT/src/simple_train/__init__.py" | cut -d'"' -f2)"
OUT="$ROOT/dist/Simple-Train-$VERSION-macOS.dmg"
STAGING="$ROOT/dist/dmg-staging"

if [ ! -d "$APP" ]; then
  echo "error: $APP not found — run PyInstaller first" >&2
  exit 1
fi

rm -rf "$STAGING" "$OUT"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create -volname "Simple-Train" -srcfolder "$STAGING" -ov -format UDZO "$OUT"
rm -rf "$STAGING"

echo "wrote $OUT"
