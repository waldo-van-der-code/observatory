#!/usr/bin/env python3
"""Bake fixture data into static files for the GitHub Pages demo.

Produces two files in docs/:
  docs/index.html  — dashboard.html with path fixes + demo banner
  docs/brain.html  — brain.html with inline zone data, path fixes + demo banner

build_brain.py patches brain.html in place via _patch_brain_html(). This script
restores the placeholder after writing docs/brain.html so the repo copy stays clean.
"""
import json
import re
from pathlib import Path

ROOT       = Path(__file__).parent.parent
BRAIN_DATA = ROOT / "data" / "processed" / "brain_data.json"
BRAIN_SRC  = ROOT / "brain.html"
DASH_SRC   = ROOT / "dashboard.html"
DOCS_DIR   = ROOT / "docs"

PLACEHOLDER = "/* BRAIN_DATA_PLACEHOLDER */"

DEMO_BANNER = (
    '<div id="demo-banner" style="position:fixed;top:0;left:0;right:0;z-index:9999;'
    'background:rgba(10,14,10,0.95);border-bottom:1px solid rgba(255,255,255,0.1);'
    'padding:6px 18px;display:flex;align-items:center;justify-content:space-between;'
    'font-size:0.72rem;color:rgba(255,255,255,0.55);font-family:sans-serif;">'
    '<span>Demo &mdash; synthetic fixture data &middot; '
    '<a href="https://github.com/waldo-van-der-code/observatory" '
    'style="color:rgba(255,255,255,0.75);text-decoration:underline;" target="_blank">'
    'clone the repo</a> to use your own data</span>'
    '</div>\n'
    '<div style="height:32px"></div>\n'  # push content below fixed banner
)


def bake_dashboard():
    """Copy dashboard.html → docs/index.html with static-hosting fixes."""
    if not DASH_SRC.exists():
        raise FileNotFoundError(
            f"{DASH_SRC} not found. Run: python3 scripts/build_dashboard.py"
        )

    html = DASH_SRC.read_text()

    # Fix /culture/map → brain.html
    html = html.replace('href="/culture/map"', 'href="brain.html"')

    # Fix /culture/img/ absolute paths → relative (GitHub Pages serves from /observatory/)
    html = html.replace('src="/culture/img/', 'src="culture/img/')

    # Add demo banner
    html = html.replace("<body>", f"<body>\n{DEMO_BANNER}", 1)

    out = DOCS_DIR / "index.html"
    out.write_text(html)
    print(f"Wrote {out}  ({len(html):,} bytes)")


def bake_brain():
    """Inline zone data into brain.html → docs/brain.html with static-hosting fixes."""
    if not BRAIN_DATA.exists():
        raise FileNotFoundError(
            f"{BRAIN_DATA} not found. Run: python3 scripts/build_brain.py"
        )

    zones = json.loads(BRAIN_DATA.read_text())
    html  = BRAIN_SRC.read_text()

    # Inline zone data
    inline = f"window.BRAIN_ZONES = {json.dumps(zones, separators=(',', ':'))};"
    if PLACEHOLDER in html:
        html = html.replace(PLACEHOLDER, inline)
    else:
        html = html.replace(
            "<script>\n// ── Dimensions",
            f"<script>{inline}</script>\n<script>\n// ── Dimensions",
            1,
        )

    # Fix asset paths for static hosting (no leading slash — GitHub Pages serves from /observatory/)
    html = html.replace('src="/static/', 'src="static/')
    html = html.replace('href="/static/', 'href="static/')
    # Also fix JS template literals that reference /static/ (zone island images)
    html = html.replace('`/static/map-pieces/', '`static/map-pieces/')

    # Add demo banner
    html = html.replace("<body>", f"<body>\n{DEMO_BANNER}", 1)

    out = DOCS_DIR / "brain.html"
    out.write_text(html)
    print(f"Wrote {out}  ({len(zones)} zones, {len(inline):,} chars inline)")

    # Restore placeholder in source brain.html
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


def main():
    DOCS_DIR.mkdir(exist_ok=True)
    bake_dashboard()
    bake_brain()


if __name__ == "__main__":
    main()
