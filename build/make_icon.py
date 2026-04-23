"""Generate the app icon set from a single SVG source.

Produces:
- ``build/icon/icon.icns`` (macOS app bundle icon)
- ``build/icon/icon.ico`` (Windows exe icon)
- ``build/icon/icon.png`` (1024x1024 PNG for README / GitHub)

Uses only the stdlib + Pillow. On macOS we prefer ``iconutil`` for the .icns
because it produces smaller, Apple-preferred files; we fall back to Pillow
if iconutil is not available (e.g. on CI).
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    print("Pillow is required. pip3 install pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "build" / "icon"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Brand colors — match web/index.html palette
NAVY = (5, 8, 15)
NAVY_EDGE = (13, 21, 48)
AMBER = (245, 158, 11)
CREAM = (240, 244, 255)


def draw_master(size: int) -> Image.Image:
    """Draw a 1024px master icon.

    Design: rounded-square navy tile, amber film-reel mark in the middle,
    subtle diagonal highlight top-left, Syne-like monogram "PK".
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded square background — macOS guidance is ~22% corner radius at the edge,
    # PyWebView uses the raw image as-is so we pre-round.
    radius = int(size * 0.22)
    d.rounded_rectangle((0, 0, size, size), radius=radius, fill=NAVY)

    # Subtle inner ring for depth
    inset = int(size * 0.03)
    d.rounded_rectangle(
        (inset, inset, size - inset, size - inset),
        radius=radius - inset, outline=NAVY_EDGE, width=max(2, size // 180),
    )

    # Diagonal highlight (top-left) — fake light source
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    for i in range(0, size, 2):
        alpha = max(0, 30 - i // 10)
        hd.line([(0, i), (i, 0)], fill=(255, 255, 255, alpha), width=1)
    img = Image.alpha_composite(img, highlight)
    d = ImageDraw.Draw(img)

    # Film-reel mark — amber circle with 6 holes
    cx, cy = size // 2, int(size * 0.54)
    reel_r = int(size * 0.32)
    d.ellipse((cx - reel_r, cy - reel_r, cx + reel_r, cy + reel_r), fill=AMBER)
    d.ellipse((cx - reel_r // 3, cy - reel_r // 3, cx + reel_r // 3, cy + reel_r // 3), fill=NAVY)

    # 6 reel holes around the hub
    import math
    hole_r = int(reel_r * 0.12)
    orbit = int(reel_r * 0.62)
    for i in range(6):
        ang = math.radians(i * 60 - 90)
        hx = cx + int(math.cos(ang) * orbit)
        hy = cy + int(math.sin(ang) * orbit)
        d.ellipse((hx - hole_r, hy - hole_r, hx + hole_r, hy + hole_r), fill=NAVY)

    # Monogram "PK" across the top
    try:
        font_size = int(size * 0.16)
        # Try a system bold font first, fall back to default
        for candidate in (
            "/System/Library/Fonts/Supplemental/Futura.ttc",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf",
        ):
            if os.path.exists(candidate):
                font = ImageFont.truetype(candidate, font_size)
                break
        else:
            font = ImageFont.load_default()
        text = "PK"
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        d.text(((size - tw) // 2, int(size * 0.12) - bbox[1]), text,
               fill=CREAM, font=font)
    except Exception:
        pass  # Monogram is decorative

    return img


def make_png(master: Image.Image) -> Path:
    out = OUT_DIR / "icon.png"
    master.save(out, "PNG")
    return out


def make_ico(master: Image.Image) -> Path:
    out = OUT_DIR / "icon.ico"
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(out, "ICO", sizes=sizes)
    return out


def make_icns(master: Image.Image) -> Path:
    out = OUT_DIR / "icon.icns"
    iconset = OUT_DIR / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()
    layers = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, size in layers:
        master.resize((size, size), Image.LANCZOS).save(iconset / name, "PNG")

    if shutil.which("iconutil"):
        subprocess.check_call(["iconutil", "-c", "icns", str(iconset), "-o", str(out)])
        shutil.rmtree(iconset)
    else:
        # Fallback: write a 1024x1024 icns via PIL (lower quality but portable)
        master.save(out, "ICNS")
    return out


def make_pwa_icons(master: Image.Image) -> list[Path]:
    """Produce PNG icons used by the PWA manifest (web/icons/)."""
    pwa_dir = ROOT / "web" / "icons"
    pwa_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for size in (192, 512):
        p = pwa_dir / f"icon-{size}.png"
        master.resize((size, size), Image.LANCZOS).save(p, "PNG")
        out.append(p)
    # Maskable variant: inset the design 15% so the OS-chosen mask has safe area.
    mask_size = 512
    maskable = Image.new("RGBA", (mask_size, mask_size), NAVY)
    inset = int(mask_size * 0.1)
    inner = master.resize((mask_size - 2 * inset, mask_size - 2 * inset), Image.LANCZOS)
    maskable.paste(inner, (inset, inset), inner)
    p = pwa_dir / "icon-512-maskable.png"
    maskable.save(p, "PNG")
    out.append(p)
    return out


def main() -> int:
    master = draw_master(1024)
    png = make_png(master)
    ico = make_ico(master)
    icns = make_icns(master)
    pwa = make_pwa_icons(master)
    print(f"✓ {png}")
    print(f"✓ {ico}")
    print(f"✓ {icns}")
    for p in pwa:
        print(f"✓ {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
