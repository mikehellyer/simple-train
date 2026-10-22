"""One-off script: draws the Simple-Train app icon and exports every
size/format the platform installers need. Not part of the app itself and
not run automatically — re-run manually if the icon design ever changes.

Usage: venv/bin/python packaging/icons/generate_icon.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = Path(__file__).parent
APP_RESOURCES = OUT_DIR.parent.parent / "src" / "simple_train" / "gui" / "resources"
SIZE = 1024

# A loco coming head-on down the track, on a deep railway-green tile: a
# rounded cab front with two windows and a bright headlight, buffers, and
# rails with sleepers running away to the horizon.
TILE_TOP = (40, 120, 84, 255)
TILE_BOTTOM = (14, 52, 36, 255)
BALLAST = (70, 66, 60, 255)
SLEEPER = (118, 84, 52, 255)
RAIL = (205, 210, 218, 255)
BODY = (196, 40, 40, 255)
BODY_DARK = (140, 24, 28, 255)
WINDOW = (30, 36, 48, 255)
LAMP = (255, 230, 140, 255)
BUFFER = (40, 40, 44, 255)


def draw_icon() -> Image.Image:
    tile = Image.new("RGBA", (SIZE, SIZE))
    td = ImageDraw.Draw(tile)
    for y in range(SIZE):
        t = y / SIZE
        td.line([(0, y), (SIZE, y)], fill=tuple(int(TILE_TOP[i] + (TILE_BOTTOM[i] - TILE_TOP[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (SIZE, SIZE), 0)
    margin = SIZE * 0.06
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, SIZE - margin, SIZE - margin], radius=SIZE * 0.22, fill=255)
    img = tile
    s = SIZE / 100
    d = ImageDraw.Draw(img)

    # the track bed, narrowing towards the horizon
    d.polygon([(44 * s, 30 * s), (56 * s, 30 * s), (96 * s, 100 * s), (4 * s, 100 * s)], fill=BALLAST)
    for i in range(9):
        t = (i / 8) ** 1.6
        y = 32 + t * 66
        half = 7 + t * 36
        h = 0.8 + t * 3.2
        d.rectangle([(50 - half) * s, y * s, (50 + half) * s, (y + h) * s], fill=SLEEPER)
    for side in (-1, 1):
        d.polygon([((50 + side * 3.5) * s, 30 * s), ((50 + side * 4.3) * s, 30 * s),
                   ((50 + side * 30) * s, 100 * s), ((50 + side * 26) * s, 100 * s)], fill=RAIL)

    # the loco's soft shadow, then its front
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([24 * s, 22 * s, 78 * s, 84 * s], radius=10 * s, fill=(0, 0, 0, 150))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(SIZE * 0.025)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([24 * s, 16 * s, 76 * s, 76 * s], radius=11 * s, fill=BODY)
    d.rounded_rectangle([24 * s, 60 * s, 76 * s, 76 * s], radius=6 * s, fill=BODY_DARK)
    d.rectangle([24 * s, 60 * s, 76 * s, 66 * s], fill=BODY_DARK)
    for x0 in (30, 52):
        d.rounded_rectangle([x0 * s, 24 * s, (x0 + 18) * s, 40 * s], radius=3 * s, fill=WINDOW)
    # headlight with a glow
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([38 * s, 42 * s, 62 * s, 66 * s], fill=(255, 220, 120, 170))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(SIZE * 0.03)))
    d = ImageDraw.Draw(img)
    d.ellipse([44 * s, 48 * s, 56 * s, 60 * s], fill=LAMP)
    # buffers
    for x0 in (22, 68):
        d.rectangle([(x0 + 3) * s, 72 * s, (x0 + 7) * s, 78 * s], fill=BUFFER)
        d.ellipse([x0 * s, 76 * s, (x0 + 10) * s, 84 * s], fill=BUFFER)

    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    icon = draw_icon()
    master_png = OUT_DIR / "icon.png"
    icon.save(master_png)
    print(f"wrote {master_png}")

    APP_RESOURCES.mkdir(parents=True, exist_ok=True)
    icon.resize((256, 256), Image.LANCZOS).save(APP_RESOURCES / "icon.png")
    print(f"wrote {APP_RESOURCES / 'icon.png'}")

    # Windows .ico (multi-resolution)
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    ico_path = OUT_DIR / "icon.ico"
    icon.save(ico_path, sizes=[(s, s) for s in ico_sizes])
    print(f"wrote {ico_path}")

    # Linux: a few common hicolor sizes as plain PNGs.
    for s in (16, 32, 48, 64, 128, 256, 512):
        icon.resize((s, s), Image.LANCZOS).save(OUT_DIR / f"icon_{s}.png")
    print("wrote icon_16..512.png")

    # macOS .icns: iconutil on a Mac; elsewhere Pillow's own ICNS writer is
    # good enough to commit, so CI on macOS always has a file to use.
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = OUT_DIR / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            icon.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            icon.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(OUT_DIR / "icon.icns")],
            check=True,
        )
        for f in iconset.iterdir():
            f.unlink()
        iconset.rmdir()
    else:
        icon.save(OUT_DIR / "icon.icns")
    print(f"wrote {OUT_DIR / 'icon.icns'}")


if __name__ == "__main__":
    main()
