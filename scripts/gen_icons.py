"""Generate PWA home-screen icons for the entertainment dashboard."""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent.parent / "static"
OUT.mkdir(exist_ok=True)

BG      = (13,  17,  23,  255)   # #0d1117
AMBER   = (240, 136,  62,  255)  # #f0883e
GOLD    = (255, 200,  80,  255)  # highlight
RING    = (240, 136,  62,   70)  # faint ring


def _play_triangle(cx: int, cy: int, size: int) -> list[tuple[int, int]]:
    """Right-pointing play triangle, visually centred."""
    w = int(size * 0.28)
    h = int(size * 0.34)
    ox = int(size * 0.04)  # nudge right so optical centre looks right
    return [
        (cx - w // 2 + ox, cy - h // 2),
        (cx + w // 2 + ox, cy),
        (cx - w // 2 + ox, cy + h // 2),
    ]


def create_icon(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # ── Background fill ──────────────────────────────────────────────────────
    base = Image.new("RGBA", (size, size), BG)
    img = Image.alpha_composite(img, base)

    # ── Warm centre radial glow ───────────────────────────────────────────────
    cx = cy = size // 2
    radial = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rd = ImageDraw.Draw(radial)
    steps = 40
    for i in range(steps, 0, -1):
        r = int(cx * 0.75 * i / steps)
        a = int(35 * (1 - i / steps))
        rd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(180, 70, 10, a))
    radial = radial.filter(ImageFilter.GaussianBlur(size // 14))
    img = Image.alpha_composite(img, radial)

    # ── Outer decorative ring ─────────────────────────────────────────────────
    draw = ImageDraw.Draw(img)
    m = int(size * 0.07)
    lw = max(2, int(size * 0.012))
    draw.ellipse([m, m, size - m, size - m], outline=RING, width=lw)

    # ── Play-button glow (blurred amber blob) ─────────────────────────────────
    tri = _play_triangle(cx, cy, size)

    glow1 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow1).polygon(tri, fill=(240, 136, 62, 220))
    glow1 = glow1.filter(ImageFilter.GaussianBlur(size // 8))
    img = Image.alpha_composite(img, glow1)

    glow2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow2).polygon(tri, fill=(255, 180, 60, 160))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(size // 20))
    img = Image.alpha_composite(img, glow2)

    # ── Play triangle (sharp, bright gradient illusion via two draws) ─────────
    draw = ImageDraw.Draw(img)
    draw.polygon(tri, fill=AMBER)   # base amber
    # Highlight: a slightly smaller inset triangle shifted up-left → illusion of sheen
    hi_tri = [(x - int(size * 0.01), y - int(size * 0.01)) for x, y in tri]
    draw.polygon(hi_tri, fill=GOLD)

    # ── Tiny top sparkle dots ─────────────────────────────────────────────────
    for angle, dist, dot_r in [(45, 0.36, 0.012), (315, 0.38, 0.009)]:
        rad = math.radians(angle)
        sx = int(cx + dist * size * math.cos(rad))
        sy = int(cy + dist * size * math.sin(rad))
        dr = max(2, int(dot_r * size))
        draw.ellipse([sx - dr, sy - dr, sx + dr, sy + dr], fill=GOLD)

    return img


if __name__ == "__main__":
    for sz in (512, 192, 180):
        path = OUT / f"icon-{sz}.png"
        create_icon(sz).save(path, "PNG")
        print(f"  wrote {path}")
    print("Done.")
