"""
Phase 3: Render the A3 taste landscape map.
Reads: data/processed/map_data.json + config/{layout,exemplars,weights}.json
Outputs: data/processed/map_light.pdf + map_preview.png
"""
import json, math, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle, Wedge
from pathlib import Path

ROOT = Path(__file__).parent.parent

MAP_DATA   = ROOT / "data/processed/map_data.json"
LAYOUT     = ROOT / "config/layout.json"
EXEMPLARS  = ROOT / "config/exemplars.json"
WEIGHTS    = ROOT / "config/weights.json"
OUT_PDF    = ROOT / "data/processed/map_light.pdf"
OUT_PNG    = ROOT / "data/processed/map_preview.png"

# --- colors ---
C_MUSIC = "#c8860a"   # warm amber
C_FILM  = "#2563eb"   # deep blue
C_BOOK  = "#7c3aed"   # purple
C_BG    = "#f8f5f0"   # off-white
C_AXIS  = "#9e9e9e"   # muted grey for axis labels
C_TEXT  = "#1a1a1a"


def load_all():
    data      = json.loads(MAP_DATA.read_text())["nodes"]
    layout    = {n["id"]: n for n in json.loads(LAYOUT.read_text())["nodes"]}
    axes_cfg  = json.loads(LAYOUT.read_text())["axes"]
    exemplars = json.loads(EXEMPLARS.read_text())
    weights   = json.loads(WEIGHTS.read_text())
    return data, layout, axes_cfg, exemplars, weights


def normalize(nodes: list[dict], weights: dict) -> list[dict]:
    """Add normalized 'total' and per-medium shares to each node."""
    max_music = max((n["music_raw"] for n in nodes), default=1) or 1
    max_film  = max((n["film_raw"]  for n in nodes), default=1) or 1
    max_book  = max((n["book_raw"]  for n in nodes), default=1) or 1

    for n in nodes:
        mn = (n["music_raw"] / max_music) * weights["music"]
        fn = (n["film_raw"]  / max_film)  * weights["film"]
        bn = (n["book_raw"]  / max_book)  * weights["book"]
        total = mn + fn + bn
        n["total_norm"] = total
        n["music_share"] = mn / total if total else 0
        n["film_share"]  = fn / total if total else 0
        n["book_share"]  = bn / total if total else 0
    return nodes


def repel(positions: list, radii: list, iterations: int = 80, strength: float = 0.6):
    """Push overlapping circles apart."""
    pos = [list(p) for p in positions]
    for _ in range(iterations):
        moved = False
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                dx = pos[j][0] - pos[i][0]
                dy = pos[j][1] - pos[i][1]
                dist = math.hypot(dx, dy)
                min_d = radii[i] + radii[j] + 2.0
                if dist < min_d and dist > 0.01:
                    overlap = (min_d - dist) * strength
                    nx, ny = dx / dist, dy / dist
                    pos[i][0] -= nx * overlap * 0.5
                    pos[i][1] -= ny * overlap * 0.5
                    pos[j][0] += nx * overlap * 0.5
                    pos[j][1] += ny * overlap * 0.5
                    moved = True
        if not moved:
            break
    return pos


def draw_pie_circle(ax, cx, cy, radius, music_s, film_s, book_s, alpha=0.88):
    """Draw a tri-sector pie circle (Wedge patches)."""
    shares = [music_s, film_s, book_s]
    colors = [C_MUSIC, C_FILM, C_BOOK]
    start = 90  # start at top
    for share, color in zip(shares, colors):
        if share < 0.005:
            continue
        angle = share * 360
        w = Wedge((cx, cy), radius, start, start + angle,
                  facecolor=color, edgecolor="white", linewidth=0.8, alpha=alpha,
                  zorder=3)
        ax.add_patch(w)
        start += angle
    # Thin white rim
    rim = Circle((cx, cy), radius, fill=False,
                 edgecolor="white", linewidth=1.5, zorder=4)
    ax.add_patch(rim)


def draw_label(ax, cx, cy, radius, label: str, exemplars: list[str]):
    """Draw node name + exemplar sub-label, positioned below circle center."""
    label_y = cy - radius - 0.8
    ax.text(cx, label_y, label,
            ha="center", va="top", fontsize=7.5, fontweight="bold",
            color=C_TEXT, zorder=5,
            bbox=dict(boxstyle="round,pad=0.1", fc=C_BG, ec="none", alpha=0.7))
    if exemplars:
        sub = " · ".join(exemplars[:3])
        ax.text(cx, label_y - 2.5, sub,
                ha="center", va="top", fontsize=5.5,
                color="#555555", zorder=5, style="italic")


def main():
    for path in [MAP_DATA, LAYOUT, EXEMPLARS, WEIGHTS]:
        if not path.exists():
            sys.exit(f"Missing: {path}")

    data, layout, axes_cfg, exemplars, weights = load_all()
    data = normalize(data, weights)

    # --- scale factor: largest bubble radius ≈ 13 units (of 100-unit space) ---
    max_total = max(n["total_norm"] for n in data)
    SCALE = 13.0 / math.sqrt(max_total) if max_total else 1

    radii  = [math.sqrt(n["total_norm"]) * SCALE for n in data]
    coords = [[layout[n["id"]]["x"], layout[n["id"]]["y"]] for n in data]

    # Repulsion pass
    coords = repel(coords, radii)

    # --- figure setup ---
    # A3 landscape: 420 × 297 mm → 16.54 × 11.69 in
    fig, ax = plt.subplots(figsize=(16.54, 11.69))
    fig.patch.set_facecolor(C_BG)
    ax.set_facecolor(C_BG)
    ax.set_xlim(-5, 105)
    ax.set_ylim(-12, 108)
    ax.set_aspect("equal")
    ax.axis("off")

    # --- subtle grid backdrop ---
    for v in range(0, 101, 25):
        ax.axhline(v, color="#e0dbd4", linewidth=0.5, zorder=0)
        ax.axvline(v, color="#e0dbd4", linewidth=0.5, zorder=0)

    # --- axis arrows + labels ---
    arrow_kw = dict(arrowstyle="-|>", color=C_AXIS,
                    mutation_scale=8, lw=1.0, zorder=1)
    ax.annotate("", xy=(103, 0), xytext=(-3, 0),
                arrowprops=arrow_kw)
    ax.annotate("", xy=(0, 106), xytext=(0, -3),
                arrowprops=arrow_kw)

    ax.text(50, -8, f"← {axes_cfg['x_left']}  ·  {axes_cfg['x_right']} →",
            ha="center", va="center", fontsize=8, color=C_AXIS, style="italic")
    ax.text(-4, 50, f"↑ {axes_cfg['y_top']}\n\n{axes_cfg['y_bottom']} ↓",
            ha="center", va="center", fontsize=8, color=C_AXIS, style="italic",
            rotation=90)

    # --- title ---
    ax.text(50, 104, "My Cultural Taste Space",
            ha="center", va="center", fontsize=18, fontweight="bold",
            color=C_TEXT, zorder=6)
    ax.text(50, 101, "Music · Film · Books  ·  2014 – 2026",
            ha="center", va="center", fontsize=8, color="#777777", zorder=6)

    # --- draw nodes ---
    for i, node in enumerate(data):
        nid = node["id"]
        cx, cy = coords[i]
        r = radii[i]
        lbl = layout[nid]["label"]
        exs = exemplars.get(nid, [])

        draw_pie_circle(ax, cx, cy, r,
                        node["music_share"], node["film_share"], node["book_share"])
        draw_label(ax, cx, cy, r, lbl, exs)

    # --- legend ---
    legend_elements = [
        mpatches.Patch(facecolor=C_MUSIC, label="Music (Spotify)"),
        mpatches.Patch(facecolor=C_FILM,  label="Film & TV (IMDb · Netflix · JustWatch)"),
        mpatches.Patch(facecolor=C_BOOK,  label="Books (Goodreads · Audible)"),
    ]
    ax.legend(handles=legend_elements, loc="lower right",
              bbox_to_anchor=(1.0, 0.0), framealpha=0.85,
              fontsize=7, title="Medium", title_fontsize=7.5,
              edgecolor="#cccccc")

    # --- weight annotation ---
    ax.text(0, -11,
            f"Bubble area ∝ engagement intensity  ·  weights: "
            f"music {int(weights['music']*100)}%  film {int(weights['film']*100)}%  book {int(weights['book']*100)}%",
            ha="left", va="center", fontsize=5.5, color="#aaaaaa")

    plt.tight_layout(pad=0.3)

    # --- save ---
    print("Saving preview PNG (150 dpi)...")
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight", facecolor=C_BG)
    print(f"Saved: {OUT_PNG}")

    print("Saving print PDF (300 dpi)...")
    fig.savefig(OUT_PDF, dpi=300, bbox_inches="tight", facecolor=C_BG, format="pdf")
    print(f"Saved: {OUT_PDF}")
    plt.close()


if __name__ == "__main__":
    main()
