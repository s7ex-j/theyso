#!/usr/bin/env python3
"""Generates every Theyso brand asset from one geometry (needs Pillow).

The mark: a "T" built from a cable. Three connector rings — your phone, your
PC and the agent — joined by a line that bends like a real cable. The
violet → cyan gradient is the connection itself.

    python docs/brand/make_brand.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
OUT_APP = ROOT / "app/assets/brand"
OUT_DOCS = ROOT / "docs/brand"

VIOLET = (124, 92, 255)
CYAN = (34, 211, 238)
INK = (11, 15, 26)
SS = 4  # supersampling

# Geometry on a 1024 grid
BAR_Y, LEFT_X, RIGHT_X, CX = 330, 262, 762, 512
BOTTOM_Y = 770
STROKE = 78
NODE_R, HOLE_R = 74, 30
STEM = [(CX, BAR_Y), (CX, 470), (CX + 120, 560), (CX, BOTTOM_Y)]  # cubic Bézier: the cable bend


def bezier(p: list[tuple[float, float]], n: int = 200) -> list[tuple[float, float]]:
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 3 * p[0][0] + 3 * (1 - t) ** 2 * t * p[1][0] + 3 * (1 - t) * t**2 * p[2][0] + t**3 * p[3][0]
        y = (1 - t) ** 3 * p[0][1] + 3 * (1 - t) ** 2 * t * p[1][1] + 3 * (1 - t) * t**2 * p[2][1] + t**3 * p[3][1]
        pts.append((x, y))
    return pts


def glyph_mask(size: int, scale: float = 1.0) -> Image.Image:
    """White glyph on black, `size` px, glyph scaled around the centre."""
    big = size * SS
    k = big / 1024 * scale
    off = big / 2 - 512 * k

    def tr(x: float, y: float) -> tuple[float, float]:
        return (off + x * k, off + y * k)

    m = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(m)
    w = STROKE * k
    d.line([tr(LEFT_X, BAR_Y), tr(RIGHT_X, BAR_Y)], fill=255, width=round(w))
    stem = [tr(*p) for p in bezier(STEM)]
    d.line(stem, fill=255, width=round(w), joint="curve")
    for x, y in stem[:: max(1, len(stem) // 60)]:  # round the stroke evenly
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)
    for nx, ny in [(LEFT_X, BAR_Y), (RIGHT_X, BAR_Y), (CX, BOTTOM_Y)]:
        x, y = tr(nx, ny)
        r = NODE_R * k
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    # connector holes are real holes (transparent), not painted dots
    holes = Image.new("L", (big, big), 0)
    hd = ImageDraw.Draw(holes)
    for nx, ny in [(LEFT_X, BAR_Y), (RIGHT_X, BAR_Y), (CX, BOTTOM_Y)]:
        x, y = tr(nx, ny)
        r = HOLE_R * k
        hd.ellipse([x - r, y - r, x + r, y + r], fill=255)
    m = ImageChops.subtract(m, holes)
    return m.resize((size, size), Image.LANCZOS)


def gradient(size: int) -> Image.Image:
    """Diagonal violet (top-left) → cyan (bottom-right)."""
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = min(1.0, max(0.0, (x * 0.45 + y * 0.9) / (size * 1.15)))
            t = t * t * (3 - 2 * t)  # smoothstep
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(VIOLET, CYAN))
    return g


def rounded_square(size: int, radius_ratio: float = 0.225) -> Image.Image:
    big = size * SS
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, big - 1, big - 1], radius=round(big * radius_ratio), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def glyph_rgba(size: int, scale: float = 1.0) -> Image.Image:
    img = gradient(size).convert("RGBA")
    img.putalpha(glyph_mask(size, scale))
    return img


def full_icon(size: int, rounded: bool) -> Image.Image:
    bg = Image.new("RGBA", (size, size), INK + (255,))
    # soft glow behind the mark
    glow = glyph_mask(size, 1.0).filter(ImageFilter.GaussianBlur(size / 18))
    glow_col = Image.new("RGBA", (size, size), VIOLET + (0,))
    glow_col.putalpha(glow.point(lambda v: int(v * 0.45)))
    bg = Image.alpha_composite(bg, glow_col)
    bg = Image.alpha_composite(bg, glyph_rgba(size, 0.92))
    if rounded:
        bg.putalpha(rounded_square(size))
    return bg


def main() -> None:
    OUT_APP.mkdir(parents=True, exist_ok=True)
    OUT_DOCS.mkdir(parents=True, exist_ok=True)
    full_icon(1024, rounded=False).convert("RGB").save(OUT_APP / "icon.png")  # store icons apply their own mask
    glyph_rgba(1024, 0.72).save(OUT_APP / "icon_foreground.png")  # Android adaptive safe zone
    glyph_rgba(1152, 0.55).save(OUT_APP / "splash.png")  # Android 12 splash: inside the 768 px circle
    glyph_rgba(512, 1.0).save(OUT_APP / "logo.png")  # in-app mark
    full_icon(512, rounded=True).save(OUT_DOCS / "icon-rounded.png")  # README
    # Wide banner for the README / social preview (1280×640)
    w, h = 1280, 640
    banner = Image.new("RGBA", (w, h), INK + (255,))
    mark = full_icon(360, rounded=True)
    banner.alpha_composite(mark, (140, (h - 360) // 2))
    banner.convert("RGB").save(OUT_DOCS / "banner-mark.png")
    print("brand assets written to", OUT_APP, "and", OUT_DOCS)
    _ = math  # keep import for readers tweaking the geometry


if __name__ == "__main__":
    main()
