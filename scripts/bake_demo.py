#!/usr/bin/env python3
"""Bake fixture brain data into brain.html for the GitHub Pages static demo.

Reads data/processed/brain_data.json (built by build_brain.py),
inlines it as window.BRAIN_ZONES, fixes asset paths for static hosting,
adds the demo banner, and writes docs/brain.html.

build_brain.py also patches brain.html via _patch_brain_html() when the
placeholder is present. bake_demo.py restores the placeholder in the source
file after writing docs/brain.html, keeping the repo copy clean.
"""
import json
import re
from pathlib import Path

ROOT       = Path(__file__).parent.parent
BRAIN_DATA = ROOT / "data" / "processed" / "brain_data.json"
BRAIN_SRC  = ROOT / "brain.html"
DOCS_DIR   = ROOT / "docs"
OUT        = DOCS_DIR / "brain.html"

PLACEHOLDER = "/* BRAIN_DATA_PLACEHOLDER */"


def main():
    if not BRAIN_DATA.exists():
        raise FileNotFoundError(
            f"{BRAIN_DATA} not found. Run: python3 scripts/build_brain.py"
        )

    zones = json.loads(BRAIN_DATA.read_text())
    html  = BRAIN_SRC.read_text()

    # ── Inline zone data ──────────────────────────────────────────────────────
    inline = f"window.BRAIN_ZONES = {json.dumps(zones, separators=(',', ':'))};"
    if PLACEHOLDER in html:
        html = html.replace(PLACEHOLDER, inline)
    else:
        # Fallback: inject before the main <script> block
        html = html.replace("<script>\n// ── Dimensions", f"<script>{inline}</script>\n<script>\n// ── Dimensions", 1)

    # ── Fix asset paths for static hosting (no leading slash) ─────────────────
    html = html.replace('src="/static/', 'src="static/')
    html = html.replace('href="/static/', 'href="static/')

    # ── Atlas image: hide gracefully if absent (it's gitignored) ─────────────
    html = html.replace(
        'src="static/map-pieces/world-atlas.png" alt="Taste Map Atlas"',
        'src="static/map-pieces/world-atlas.png" alt="Taste Map Atlas" '
        'onerror="this.style.opacity=\'0\'"',
    )

    # ── Demo banner ───────────────────────────────────────────────────────────
    banner = (
        '<div id="demo-banner" style="position:fixed;top:0;left:0;right:0;z-index:200;'
        'background:rgba(15,22,12,0.93);border-bottom:1px solid rgba(232,218,184,0.18);'
        'padding:5px 18px;display:flex;align-items:center;justify-content:space-between;'
        'font-family:\'Cinzel\',serif;font-size:0.68rem;color:rgba(232,218,184,0.65);'
        'letter-spacing:0.08em;">'
        '<span>DEMO &mdash; fixture data &middot; '
        '<a href="https://github.com/waldo-van-der-code/observatory" '
        'style="color:rgba(232,218,184,0.85);text-decoration:underline;" target="_blank">'
        'clone the repo</a> to use your own</span>'
        '<a href="index.html" style="color:rgba(232,218,184,0.55);text-decoration:none;">'
        '&larr; back</a></div>\n'
    )
    html = html.replace("<body>", f"<body>\n{banner}")

    DOCS_DIR.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"Wrote {OUT}  ({len(zones)} zones, {len(inline):,} chars inline)")

    # ── Restore placeholder in source brain.html ──────────────────────────────
    # build_brain.py replaces the placeholder with inline data in the source file.
    # We always restore it so the repo copy stays clean (no personal data baked in).
    src = BRAIN_SRC.read_text()
    restored = re.sub(
        r'<script>window\.BRAIN_ZONES = \[.*?\];</script>',
        f'<script>{PLACEHOLDER}</script>',
        src,
        flags=re.DOTALL,
    )
    if restored != src:
        BRAIN_SRC.write_text(restored)
        print(f"Restored placeholder in {BRAIN_SRC.name}")


if __name__ == "__main__":
    main()
