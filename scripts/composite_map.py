"""
Composite 12 zone images into a single world-map.png.

Algorithm:
  1. Load config/layout.json for zone seed points (0-100 coordinate space)
  2. Compute Voronoi cells for the output canvas
  3. For each zone:
     a. Load static/map-pieces/{ZONE_ID}.png
     b. Resize/center-crop to fill the zone's bounding box (with padding)
     c. Create a feathered Voronoi mask (Gaussian-blurred polygon)
     d. Blend zone image onto the composite canvas using the mask as alpha
  4. Apply a final ocean-color fill where no zone image reaches (failsafe)
  5. Save to static/map-pieces/world-map.png

Usage:
    python3 scripts/composite_map.py [--size 2400] [--feather 80]

Requirements:
    pip install Pillow scipy
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).parent.parent
LAYOUT_PATH    = ROOT / "config" / "layout.json"
IMAGES_DIR     = ROOT / "static" / "map-pieces"
OUT_PATH       = ROOT / "static" / "map-pieces" / "world-map.png"

OCEAN_COLOR = (9, 27, 40)      # #091b28
ZONE_ORDER  = [                # render order — less important zones first
    "HISTORY", "ARTHOUSE", "CRIME_THRILLER", "DRAMA",
    "ANIMATION", "FANTASY_COMEDY", "ACTION_ADV",
    "INDIE_WORLD", "FOLK_SINGER", "ELECTRONIC_HIP",
    "SOUL_JAZZ", "SCI_FI",
]


def load_layout() -> list[dict]:
    data = json.loads(LAYOUT_PATH.read_text())
    return data["nodes"]


def scale_points(nodes: list[dict], W: int, H: int) -> dict[str, tuple[float, float]]:
    """Convert 0-100 layout coords to canvas pixels. Y is inverted (y=100 → top)."""
    return {
        n["id"]: (n["x"] / 100 * W, (1 - n["y"] / 100) * H)
        for n in nodes
    }


def compute_voronoi_masks(
    centers: dict[str, tuple[float, float]],
    W: int,
    H: int,
    feather_radius: int,
) -> dict[str, np.ndarray]:
    """
    For each zone, produce a float32 mask (H, W) in [0,1] via:
      1. Nearest-seed-point classification (Voronoi)
      2. Gaussian blur for feathered borders
    """
    # Build a pixel-level zone index map (nearest centroid)
    ids = list(centers.keys())
    pts = np.array([centers[z] for z in ids], dtype=np.float32)  # (N, 2)

    ys, xs = np.mgrid[0:H, 0:W]  # (H, W) grids
    px = xs.astype(np.float32)
    py = ys.astype(np.float32)

    # Distance from every pixel to every seed point
    dx = px[:, :, np.newaxis] - pts[:, 0]   # (H, W, N)
    dy = py[:, :, np.newaxis] - pts[:, 1]
    dists = dx * dx + dy * dy                # squared distance

    nearest = np.argmin(dists, axis=2)       # (H, W) index into ids

    masks: dict[str, np.ndarray] = {}
    for i, zone_id in enumerate(ids):
        binary = (nearest == i).astype(np.float32)  # 1 inside cell, 0 outside
        # Blur the binary mask → soft feathered edge
        img = Image.fromarray((binary * 255).astype(np.uint8), mode="L")
        img = img.filter(ImageFilter.GaussianBlur(radius=feather_radius))
        masks[zone_id] = np.array(img, dtype=np.float32) / 255.0
    return masks


def fit_image_to_region(
    img: Image.Image,
    cx: float,
    cy: float,
    W: int,
    H: int,
    size_fraction: float = 0.85,
) -> Image.Image:
    """
    Resize the zone image so its longer side covers `size_fraction` of the
    shorter canvas dimension, then position it centered on (cx, cy).
    Returns an RGBA image the same size as the canvas (W, H).
    """
    target_px = int(min(W, H) * size_fraction)
    scale = target_px / max(img.width, img.height)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img_resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Convert to RGBA
    if img_resized.mode != "RGBA":
        img_resized = img_resized.convert("RGBA")

    # Paste onto a transparent canvas at the center position
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    paste_x = int(cx - new_w / 2)
    paste_y = int(cy - new_h / 2)
    canvas.paste(img_resized, (paste_x, paste_y))
    return canvas


def composite(
    output_size: int = 2400,
    feather_radius: int = 80,
    zone_size_fraction: float = 0.82,
) -> None:
    W, H = output_size, int(output_size * 0.72)   # 4:2.88 landscape ratio
    print(f"Canvas: {W}×{H}px  |  feather: {feather_radius}px")

    nodes = load_layout()
    centers = scale_points(nodes, W, H)

    # Voronoi masks
    print("Computing Voronoi masks …")
    masks = compute_voronoi_masks(centers, W, H, feather_radius)

    # Start with ocean base
    composite_rgb = np.full((H, W, 3), OCEAN_COLOR, dtype=np.float32)
    composite_alpha = np.zeros((H, W), dtype=np.float32)

    # Render order — back-to-front doesn't really matter for non-overlapping Voronoi,
    # but process all zones regardless of whether their image exists
    zone_ids = [n["id"] for n in nodes]
    missing: list[str] = []

    for zone_id in zone_ids:
        img_path = IMAGES_DIR / f"{zone_id}.png"
        mask = masks.get(zone_id)
        if mask is None:
            continue

        if not img_path.exists():
            missing.append(zone_id)
            # Placeholder: solid zone-color tinted region
            color_map = {
                "SOUL_JAZZ":      (156,  82, 24),
                "FOLK_SINGER":    ( 58, 104, 32),
                "ELECTRONIC_HIP": ( 20,  64, 104),
                "INDIE_WORLD":    ( 72,  34, 104),
                "DRAMA":          (124,  24, 24),
                "CRIME_THRILLER": ( 20,  40, 40),
                "ARTHOUSE":       ( 56,  72, 24),
                "SCI_FI":         ( 12,  64,  96),
                "FANTASY_COMEDY": (104,  72, 24),
                "ACTION_ADV":     (120,  32, 16),
                "ANIMATION":      ( 20,  88,  64),
                "HISTORY":        ( 72,  48, 24),
            }
            color = np.array(color_map.get(zone_id, (80, 80, 80)), dtype=np.float32)
            m3 = mask[:, :, np.newaxis]
            composite_rgb = composite_rgb * (1 - m3) + color * m3
            composite_alpha = np.maximum(composite_alpha, mask * 0.7)
            continue

        print(f"  Compositing {zone_id} …")
        img = Image.open(img_path)
        cx, cy = centers[zone_id]
        zone_canvas = fit_image_to_region(img, cx, cy, W, H, zone_size_fraction)

        zone_rgb  = np.array(zone_canvas, dtype=np.float32)[:, :, :3]
        zone_a    = np.array(zone_canvas, dtype=np.float32)[:, :, 3] / 255.0

        # Combined alpha: Voronoi mask × image alpha
        combined = mask * zone_a
        m3 = combined[:, :, np.newaxis]

        composite_rgb   = composite_rgb * (1 - m3) + zone_rgb * m3
        composite_alpha = np.maximum(composite_alpha, combined)

    # Post-process: apply a canvas-level edge vignette so any image whose own
    # fade is uneven (e.g. bright on one side) still blends cleanly into the ocean.
    # Uses a radial gradient: transparent at the landmass center, opaque-ocean at borders.
    ys, xs = np.mgrid[0:H, 0:W]
    # Normalised distance from canvas center, slightly stretched horizontally
    nx = (xs / W - 0.5) * 2        # -1 … +1
    ny = (ys / H - 0.5) * 2
    dist = np.sqrt(nx * nx + ny * ny)   # 0 at center, ~1.4 at corners
    # Fade starts at r=0.60 (well inside the landmass) and reaches full at r=1.10
    vignette = np.clip((dist - 0.60) / (1.10 - 0.60), 0, 1).astype(np.float32)
    # Darken composite_rgb toward OCEAN_COLOR based on vignette strength
    ocean = np.array(OCEAN_COLOR, dtype=np.float32)
    v3 = vignette[:, :, np.newaxis]
    composite_rgb = composite_rgb * (1 - v3) + ocean * v3
    # Also suppress alpha at the very edges so they dissolve into background
    composite_alpha = composite_alpha * (1 - np.clip((dist - 0.75) / 0.35, 0, 1))

    # Convert to uint8
    result_rgb   = np.clip(composite_rgb, 0, 255).astype(np.uint8)
    result_alpha = np.clip(composite_alpha * 255, 0, 255).astype(np.uint8)

    result = Image.fromarray(
        np.dstack([result_rgb, result_alpha[:, :, np.newaxis]]),
        mode="RGBA",
    )

    # Final output: flatten onto ocean background (no transparency in output)
    bg = Image.new("RGB", (W, H), OCEAN_COLOR)
    bg.paste(result, mask=result.split()[3])
    bg.save(OUT_PATH, "PNG", optimize=True)
    print(f"\nSaved → {OUT_PATH}  ({W}×{H})")

    if missing:
        print(f"\nMissing images (used placeholder colors): {', '.join(missing)}")
        print("Generate them with the prompts in static/map-pieces/prompts.md")
    else:
        print("\nAll 12 zone images composited successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Composite taste map zones into world-map.png")
    parser.add_argument("--size",    type=int,   default=2400,
                        help="Output width in pixels (default 2400)")
    parser.add_argument("--feather", type=int,   default=80,
                        help="Gaussian feather radius at zone borders (default 80px)")
    parser.add_argument("--fraction", type=float, default=0.82,
                        help="Zone image size as fraction of canvas short side (default 0.82)")
    args = parser.parse_args()
    composite(args.size, args.feather, args.fraction)
