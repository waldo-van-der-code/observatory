#!/usr/bin/env python3
"""Bake fixture data into a multi-page static demo for GitHub Pages.

docs/
  index.html      — Observatory hub (6 cards, mirrors culture.astro)
  analytics.html  — Full dashboard (mirrors analytics.astro / dashboard.html)
  chapters.html   — Life Chapters game board (mirrors chapters.astro, mocked data)
  brain.html      — Taste Map (brain.html with inline zone data)
  demo_results.json
  culture/img/    — Section images (copied by build_demo.sh)
  static/         — Icons, manifest, map-pieces
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

# ── Shared shell ───────────────────────────────────────────────────────────────

def culture_page(title: str, page: str, body: str) -> str:
    """Wrap body in the full CultureLayout shell (header, nav, fonts, CSS vars)."""
    nav_pages = [
        ("chat",      "Ask Claude",      "ask-claude.html"),
        ("picks",     "Recommendations", "picks.html"),
        ("analytics", "Analytics",       "analytics.html"),
        ("find",      "Find & Add",      "find.html"),
        ("chapters",  "Life Chapters",   "chapters.html"),
        ("map",       "Taste Map",       "brain.html"),
    ]
    nav_links = "\n        ".join(
        f'<a href="{href}" class="{"active" if p == page else ""}">{label}</a>'
        for p, label, href in nav_pages
    )
    drawer_links = "\n      ".join(
        f'<a href="{href}" class="{"active" if p == page else ""}">{label}</a>'
        for p, label, href in nav_pages
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="apple-touch-icon" sizes="180x180" href="static/icon-180.png">
  <link rel="manifest" href="static/manifest.json">
  <style>
    *, *::before, *::after {{ box-sizing:border-box; margin:0; padding:0; }}
    :root {{
      --cream:#f5f0e8; --cream-dark:#ede6d8; --paper:#faf7f2;
      --ink:#1a1612; --ink-mid:#3d3530; --ink-dim:#7a6e64;
      --border:rgba(26,22,18,.12); --rust:#c94c1a; --cobalt:#1a4fa0;
      --gold:#d4920a; --teal:#0d7e6b;
    }}
    body {{ font-family:'Inter',sans-serif; background:var(--cream); color:var(--ink); min-height:100vh; }}

    /* ── Demo banner ── */
    #demo-banner {{
      position:fixed; top:0; left:0; right:0; z-index:9999;
      background:rgba(26,79,160,.97); border-bottom:2px solid var(--gold);
      padding:5px 18px; display:flex; align-items:center; justify-content:space-between;
      font-size:.7rem; color:rgba(255,255,255,.7); font-family:'Inter',sans-serif;
    }}
    #demo-banner a {{ color:rgba(255,255,255,.9); text-decoration:underline; }}
    .demo-push {{ height:30px; }}

    /* ── Header ── */
    .c-header {{
      display:flex; align-items:center; gap:1rem; padding:0 1.5rem;
      background:var(--cobalt); border-bottom:4px solid var(--gold);
      min-height:64px; position:sticky; top:30px; z-index:100;
    }}
    .c-header-logo {{ font-family:'Lora',serif; font-size:1.15rem; font-weight:700; color:#fff; text-decoration:none; letter-spacing:.04em; flex:1; }}
    .c-header-logo span {{ color:var(--gold); }}
    .c-nav {{ display:flex; gap:.25rem; }}
    .c-nav a {{
      padding:.4rem .9rem; border:2px solid rgba(255,255,255,.25); border-radius:2px;
      font-size:.72rem; font-weight:700; color:rgba(255,255,255,.65); text-decoration:none;
      letter-spacing:.07em; text-transform:uppercase; transition:all .15s;
    }}
    .c-nav a:hover {{ color:#fff; border-color:rgba(255,255,255,.6); }}
    .c-nav a.active {{ background:var(--gold); color:var(--ink); border-color:var(--gold); }}
    .c-hamburger {{
      display:none; background:transparent; border:2px solid rgba(255,255,255,.4);
      border-radius:2px; color:#fff; padding:.5rem .75rem; cursor:pointer; font-size:1.2rem;
    }}
    .c-drawer {{
      display:none; position:fixed; inset:0; background:var(--cobalt); z-index:300; padding:1.5rem;
    }}
    .c-drawer.open {{ display:block; }}
    .c-drawer-head {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:2rem; }}
    .c-drawer-logo {{ font-family:'Lora',serif; font-size:1.15rem; font-weight:700; color:#fff; letter-spacing:.04em; }}
    .c-drawer-logo span {{ color:var(--gold); }}
    .c-drawer-close {{ background:transparent; border:2px solid rgba(255,255,255,.4); border-radius:2px; color:#fff; padding:.5rem .75rem; cursor:pointer; font-size:1rem; }}
    .c-drawer a {{ display:block; padding:1.1rem 0; border-bottom:1px solid rgba(255,255,255,.12); font-size:.95rem; font-weight:700; color:rgba(255,255,255,.75); text-decoration:none; letter-spacing:.07em; text-transform:uppercase; }}
    .c-drawer a:last-child {{ border-bottom:none; }}
    .c-drawer a.active {{ color:var(--gold); }}
    @media (max-width:700px) {{ .c-nav {{ display:none; }} .c-hamburger {{ display:flex; align-items:center; justify-content:center; }} }}
  </style>
</head>
<body>

<div id="demo-banner">
  <span>Demo &mdash; synthetic fixture data &middot;
    <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">clone the repo</a> to use your own data</span>
</div>
<div class="demo-push"></div>

<header class="c-header">
  <a href="index.html" class="c-header-logo">Culture <span>✦</span></a>
  <nav class="c-nav">
    {nav_links}
  </nav>
  <button class="c-hamburger" id="cHam" aria-label="Open menu">&#9776;</button>
</header>
<div class="c-drawer" id="cDrawer">
  <div class="c-drawer-head">
    <span class="c-drawer-logo">Culture <span>✦</span></span>
    <button class="c-drawer-close" id="cDrawerClose" aria-label="Close">&#10005;</button>
  </div>
  <a href="index.html">Dashboard</a>
  {drawer_links}
</div>
<script>
  const ham=document.getElementById('cHam'),drawer=document.getElementById('cDrawer'),close=document.getElementById('cDrawerClose');
  ham?.addEventListener('click',()=>drawer?.classList.add('open'));
  close?.addEventListener('click',()=>drawer?.classList.remove('open'));
</script>

{body}
</body>
</html>"""


# ── Hub page ───────────────────────────────────────────────────────────────────

def bake_hub():
    body = """
<style>
  .hub { min-height:calc(100vh - 94px); background:var(--cream); display:flex; flex-direction:column; align-items:center; justify-content:center; padding:3rem 1.5rem; }
  .hub-eyebrow { font-size:.7rem; font-weight:700; letter-spacing:.2em; text-transform:uppercase; color:var(--ink-dim); margin-bottom:.75rem; text-align:center; }
  .hub-title { font-family:'Lora',serif; font-size:clamp(2rem,6vw,3.5rem); font-weight:700; text-align:center; color:var(--ink); letter-spacing:-.02em; line-height:1.1; margin-bottom:.75rem; }
  .hub-sub { font-size:.9rem; color:var(--ink-dim); text-align:center; margin-bottom:3rem; max-width:420px; line-height:1.6; }
  .hub-intro { font-size:.72rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-dim); background:rgba(201,76,26,.07); border:1.5px solid rgba(201,76,26,.15); border-radius:2px; padding:.35rem .75rem; display:inline-block; margin-bottom:2rem; }
  .hub-intro a { color:var(--rust); font-weight:700; text-decoration:underline; }
  .hub-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:1.25rem; width:100%; max-width:960px; }
  @media (max-width:720px) { .hub-grid { grid-template-columns:repeat(2,1fr); } }
  @media (max-width:480px) { .hub-grid { grid-template-columns:1fr; } }
  .hub-card { background:var(--paper); border:2px solid var(--ink); border-radius:4px; padding:1.75rem 1.5rem; box-shadow:4px 4px 0 var(--ink); text-decoration:none; color:var(--ink); display:flex; flex-direction:column; gap:.5rem; transition:transform .1s,box-shadow .1s; position:relative; overflow:hidden; }
  .hub-card:hover { transform:translate(-2px,-2px); box-shadow:6px 6px 0 var(--ink); }
  .hub-card-icon { font-size:1.75rem; margin-bottom:.25rem; }
  .hub-card-label { font-size:.65rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; color:var(--ink-dim); }
  .hub-card-title { font-family:'Lora',serif; font-size:1.35rem; font-weight:700; color:var(--ink); line-height:1.2; }
  .hub-card-desc { font-size:.82rem; color:var(--ink-dim); line-height:1.5; }
  .hub-card-accent { position:absolute; bottom:0; left:0; right:0; height:4px; }
  .hub-card.chat      .hub-card-accent { background:var(--cobalt); }
  .hub-card.picks     .hub-card-accent { background:var(--gold); }
  .hub-card.analytics .hub-card-accent { background:var(--rust); }
  .hub-card.map       .hub-card-accent { background:var(--teal); }
  .hub-card.find      .hub-card-accent { background:#6b3fa0; }
  .hub-card.chapters  .hub-card-accent { background:#8b5a2b; }
  .hub-cta { margin-top:2.5rem; display:flex; align-items:center; gap:1rem; flex-wrap:wrap; justify-content:center; }
  .hub-cta a { font-size:.78rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--ink); background:var(--paper); border:2px solid var(--ink); border-radius:3px; padding:.5rem 1.2rem; text-decoration:none; box-shadow:2px 2px 0 var(--ink); transition:transform .1s,box-shadow .1s; }
  .hub-cta a:hover { transform:translate(-1px,-1px); box-shadow:3px 3px 0 var(--ink); }
  .hub-cta .hint { font-size:.72rem; color:var(--ink-dim); }
</style>

<div class="hub">
  <div class="hub-eyebrow">Personal Observatory</div>
  <h1 class="hub-title">Your cultural life,<br>quantified.</h1>
  <p class="hub-sub">Track every film, book, album, and series. Build your taste profile. Let Claude analyse the patterns.</p>
  <div class="hub-grid">
    <a href="ask-claude.html" class="hub-card chat">
      <div class="hub-card-icon">✦</div>
      <div class="hub-card-label">AI</div>
      <div class="hub-card-title">Ask Claude</div>
      <div class="hub-card-desc">Chat with Claude about your taste, get recommendations, explore connections.</div>
      <div class="hub-card-accent"></div>
    </a>
    <a href="picks.html" class="hub-card picks">
      <div class="hub-card-icon">→</div>
      <div class="hub-card-label">Recommendations</div>
      <div class="hub-card-title">What's next.</div>
      <div class="hub-card-desc">Curated picks by medium — films, series, books, music, comics, podcasts.</div>
      <div class="hub-card-accent"></div>
    </a>
    <a href="analytics.html" class="hub-card analytics">
      <div class="hub-card-icon">◈</div>
      <div class="hub-card-label">Data</div>
      <div class="hub-card-title">Analytics</div>
      <div class="hub-card-desc">Your full taste dashboard — genres, directors, reading patterns, listening history.</div>
      <div class="hub-card-accent"></div>
    </a>
    <a href="brain.html" class="hub-card map">
      <div class="hub-card-icon">◎</div>
      <div class="hub-card-label">Visualisation</div>
      <div class="hub-card-title">Taste Map</div>
      <div class="hub-card-desc">An interactive map of how your cultural taste clusters and connects.</div>
      <div class="hub-card-accent"></div>
    </a>
    <a href="find.html" class="hub-card find">
      <div class="hub-card-icon">⊕</div>
      <div class="hub-card-label">Discover</div>
      <div class="hub-card-title">Find &amp; Add</div>
      <div class="hub-card-desc">Search for films, books, albums, and series to add to your collection.</div>
      <div class="hub-card-accent"></div>
    </a>
    <a href="chapters.html" class="hub-card chapters">
      <div class="hub-card-icon">◫</div>
      <div class="hub-card-label">Timeline</div>
      <div class="hub-card-title">Life Chapters</div>
      <div class="hub-card-desc">Your cultural autobiography — what you watched, read, and heard in each era.</div>
      <div class="hub-card-accent"></div>
    </a>
  </div>
  <div class="hub-cta">
    <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">&#8599; Run it with your own data</a>
    <span class="hint">Open source &middot; Python + FastAPI &middot; SQLite &middot; Runs locally</span>
  </div>
</div>"""
    out = DOCS_DIR / "index.html"
    out.write_text(culture_page("Observatory — Culture ✦", "hub", body))
    print(f"Wrote {out}")


# ── Analytics dashboard ────────────────────────────────────────────────────────

# Culture nav injected into dashboard.html's own <head> / <body>
# --culture-nav-offset = demo banner (30px) + culture header (~60px)
_CULTURE_HEAD_INJECT = """
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Lora:wght@400;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root{--cream:#f5f0e8;--cream-dark:#ede6d8;--paper:#faf7f2;--ink:#1a1612;--ink-mid:#3d3530;--ink-dim:#7a6e64;--c-border-light:rgba(26,22,18,.12);--rust:#c94c1a;--cobalt:#1a4fa0;--gold:#d4920a;--teal:#0d7e6b;--culture-nav-offset:90px;}
    #demo-banner{position:fixed;top:0;left:0;right:0;z-index:9999;background:rgba(26,79,160,.97);border-bottom:2px solid var(--gold);padding:5px 18px;display:flex;align-items:center;justify-content:space-between;font-size:.7rem;color:rgba(255,255,255,.7);font-family:'Inter',sans-serif;}
    #demo-banner a{color:rgba(255,255,255,.9);text-decoration:underline;}
    .c-header{display:flex;align-items:center;gap:1rem;padding:0 1.5rem;background:var(--cobalt);border-bottom:4px solid var(--gold);min-height:60px;position:sticky;top:30px;z-index:150;}
    .c-header-logo{font-family:'Lora',serif;font-size:1.1rem;font-weight:700;color:#fff;text-decoration:none;letter-spacing:.04em;flex:1;}
    .c-header-logo span{color:var(--gold);}
    .c-nav{display:flex;gap:.25rem;}
    .c-nav a{padding:.35rem .85rem;border:2px solid rgba(255,255,255,.25);border-radius:2px;font-size:.68rem;font-weight:700;color:rgba(255,255,255,.65);text-decoration:none;letter-spacing:.07em;text-transform:uppercase;transition:all .15s;}
    .c-nav a:hover{color:#fff;border-color:rgba(255,255,255,.6);}
    .c-nav a.active{background:var(--gold);color:var(--ink);border-color:var(--gold);}
    .c-hamburger{display:none;background:transparent;border:2px solid rgba(255,255,255,.4);border-radius:2px;color:#fff;padding:.5rem .75rem;cursor:pointer;font-size:1.1rem;}
    .c-drawer{display:none;position:fixed;inset:0;background:var(--cobalt);z-index:300;padding:1.5rem;}
    .c-drawer.open{display:block;}
    .c-drawer-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;}
    .c-drawer-logo{font-family:'Lora',serif;font-size:1.1rem;font-weight:700;color:#fff;letter-spacing:.04em;}
    .c-drawer-logo span{color:var(--gold);}
    .c-drawer-close{background:transparent;border:2px solid rgba(255,255,255,.4);border-radius:2px;color:#fff;padding:.5rem .75rem;cursor:pointer;font-size:1rem;}
    .c-drawer a{display:block;padding:1rem 0;border-bottom:1px solid rgba(255,255,255,.12);font-size:.9rem;font-weight:700;color:rgba(255,255,255,.75);text-decoration:none;letter-spacing:.07em;text-transform:uppercase;}
    .c-drawer a:last-child{border-bottom:none;}
    .c-drawer a.active{color:var(--gold);}
    @media(max-width:700px){.c-nav{display:none;}.c-hamburger{display:flex;align-items:center;justify-content:center;}}
    /* Hide dashboard's own search bar — non-functional in demo, and visually conflicts with culture header */
    #search-bar{display:none!important;}
    /* Section nav sticks directly below the culture header */
    #section-nav{top:var(--culture-nav-offset)!important;z-index:99!important;}
    #sec-overview,#sec-films,#sec-series,#sec-music-wrap,#sec-books,#sec-podcasts,#sec-comics,#sec-youtube,#sec-tiktok,#sec-patterns,#sec-recs{scroll-margin-top:calc(var(--culture-nav-offset) + 52px)!important;}
    /* Demo-locked search notice */
    #demo-search-lock{display:flex;align-items:center;gap:8px;margin-left:8px;padding:6px 12px;background:rgba(212,146,10,.15);border:1px solid rgba(212,146,10,.4);border-radius:2px;font-size:.7rem;color:rgba(255,255,255,.8);white-space:nowrap;}
    #demo-search-lock a{color:var(--gold);text-decoration:underline;cursor:pointer;}
    #demo-api-toast{display:none;position:fixed;bottom:1.5rem;right:1.5rem;z-index:9998;background:#1a1612;border:1px solid var(--gold);border-radius:4px;padding:.75rem 1.1rem;font-size:.78rem;color:#f5f0e8;max-width:320px;box-shadow:0 4px 20px rgba(0,0,0,.4);}
    #demo-api-toast.show{display:block;animation:toastIn .2s ease;}
    @keyframes toastIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
  </style>"""

_CULTURE_BODY_INJECT = """<div id="demo-banner">
  <span>Demo &mdash; synthetic fixture data &middot;
    <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">clone the repo</a> to use your own data</span>
</div>
<div style="height:30px"></div>
<header class="c-header">
  <a href="index.html" class="c-header-logo">Culture <span>&#10022;</span></a>
  <nav class="c-nav">
    <a href="ask-claude.html">Ask Claude</a>
    <a href="picks.html">Recommendations</a>
    <a href="analytics.html" class="active">Analytics</a>
    <a href="find.html">Find &amp; Add</a>
    <a href="chapters.html">Life Chapters</a>
    <a href="brain.html">Taste Map</a>
  </nav>
  <button class="c-hamburger" id="cHam2" aria-label="Open menu">&#9776;</button>
</header>
<div class="c-drawer" id="cDrawer2">
  <div class="c-drawer-head">
    <span class="c-drawer-logo">Culture <span>&#10022;</span></span>
    <button class="c-drawer-close" id="cDrawerClose2">&#10005;</button>
  </div>
  <a href="index.html">Dashboard</a>
  <a href="ask-claude.html">Ask Claude</a>
  <a href="picks.html">Recommendations</a>
  <a href="analytics.html" class="active">Analytics</a>
  <a href="find.html">Find &amp; Add</a>
  <a href="chapters.html">Life Chapters</a>
  <a href="brain.html">Taste Map</a>
</div>
<!-- Demo API toast notification -->
<div id="demo-api-toast">
  &#128274; This action requires a live server.<br>
  <a href="https://github.com/waldo-van-der-code/observatory" target="_blank" style="color:var(--gold)">Clone the repo</a> and run <code style="background:rgba(255,255,255,.1);padding:1px 5px;border-radius:2px">./run.sh --serve</code> to use it with your own data.
</div>
<script>
  const h2=document.getElementById('cHam2'),d2=document.getElementById('cDrawer2'),c2=document.getElementById('cDrawerClose2');
  h2?.addEventListener('click',()=>d2?.classList.add('open'));
  c2?.addEventListener('click',()=>d2?.classList.remove('open'));

  // Intercept search and watchlist API calls — show demo toast instead
  (function() {
    const TOAST = document.getElementById('demo-api-toast');
    let toastTimer;
    function showToast() {
      TOAST.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => TOAST.classList.remove('show'), 4500);
    }
    // Inject demo lock badge into search bar when it appears
    function lockSearchBar() {
      const sb = document.getElementById('search-bar');
      if (!sb || sb.dataset.demoLocked) return;
      sb.dataset.demoLocked = '1';
      const lock = document.createElement('div');
      lock.id = 'demo-search-lock';
      lock.innerHTML = '&#128274; Demo &mdash; search requires a live server. <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">Clone repo</a> to try it.';
      const row = sb.querySelector('.search-row');
      if (row) row.appendChild(lock);
    }
    // Prevent search form submit
    document.addEventListener('click', function(e) {
      const btn = e.target.closest('#search-btn');
      if (btn) { e.preventDefault(); e.stopImmediatePropagation(); showToast(); }
    }, true);
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && document.activeElement?.id === 'search-input') {
        e.preventDefault(); e.stopImmediatePropagation(); showToast();
      }
    }, true);
    // Intercept watchlist / rate / related clicks
    document.addEventListener('click', function(e) {
      const t = e.target.closest('.action-btn,.detail-btn,.watchlist-btn,[data-action]');
      if (t) { e.preventDefault(); e.stopImmediatePropagation(); showToast(); }
    }, true);
    // Run lock after DOM ready
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', lockSearchBar);
    else lockSearchBar();
    setTimeout(lockSearchBar, 500);
  })();
</script>
"""

def bake_analytics():
    if not DASH_SRC.exists():
        raise FileNotFoundError(f"{DASH_SRC} not found. Run: python3 scripts/build_dashboard.py")

    html = DASH_SRC.read_text()
    # Fix /culture/map → brain.html
    html = html.replace('href="/culture/map"', 'href="brain.html"')
    # Fix /culture/img/ absolute paths → relative
    html = html.replace('src="/culture/img/', 'src="culture/img/')
    # Remove any pre-existing demo banner injections
    html = re.sub(
        r'<div id="demo-banner".*?</div>\s*<div[^>]*style="height:\d+px"[^>]*></div>',
        '', html, flags=re.DOTALL
    )
    # Inject culture CSS into </head>
    html = html.replace('</head>', f'{_CULTURE_HEAD_INJECT}\n</head>', 1)
    # Inject culture nav header at start of <body>
    html = re.sub(r'<body([^>]*)>', rf'<body\1>\n{_CULTURE_BODY_INJECT}', html, count=1)

    out = DOCS_DIR / "analytics.html"
    out.write_text(html)
    print(f"Wrote {out}")


# ── Life Chapters ──────────────────────────────────────────────────────────────

WALDO_SVG_FACE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="114" height="114" role="img" aria-label="Where is Waldo cartoon">
  <circle cx="60" cy="60" r="58" fill="#f9c9a0"/>
  <ellipse cx="17" cy="56" rx="12" ry="22" fill="#7a4a18"/>
  <ellipse cx="103" cy="56" rx="12" ry="22" fill="#7a4a18"/>
  <clipPath id="hc"><rect x="12" y="4" width="96" height="42" rx="48"/></clipPath>
  <rect x="12" y="4" width="96" height="42" rx="18" fill="#f0f0f0" clip-path="url(#hc)"/>
  <rect x="12" y="4"  width="96" height="10" fill="#dd1111" clip-path="url(#hc)"/>
  <rect x="12" y="22" width="96" height="10" fill="#dd1111" clip-path="url(#hc)"/>
  <rect x="12" y="40" width="96" height="6"  fill="#dd1111" clip-path="url(#hc)"/>
  <rect x="6" y="41" width="108" height="12" rx="6" fill="#dd1111"/>
  <ellipse cx="60" cy="53" rx="50" ry="10" fill="#8b5520" opacity=".55"/>
  <circle cx="38" cy="70" r="16" fill="rgba(210,235,255,.35)" stroke="#222" stroke-width="3.5"/>
  <circle cx="82" cy="70" r="16" fill="rgba(210,235,255,.35)" stroke="#222" stroke-width="3.5"/>
  <line x1="54" y1="70" x2="66" y2="70" stroke="#222" stroke-width="3"/>
  <line x1="6"  y1="67" x2="22" y2="69" stroke="#222" stroke-width="3"/>
  <line x1="98" y1="69" x2="114" y2="67" stroke="#222" stroke-width="3"/>
  <circle cx="38" cy="71" r="5.5" fill="#1a2888"/>
  <circle cx="82" cy="71" r="5.5" fill="#1a2888"/>
  <circle cx="40" cy="69" r="2" fill="#fff"/>
  <circle cx="84" cy="69" r="2" fill="#fff"/>
  <ellipse cx="60" cy="83" rx="5" ry="4" fill="#e8a87c"/>
  <path d="M 36 91 Q 60 112 84 91" stroke="#55332a" stroke-width="3" fill="none" stroke-linecap="round"/>
  <ellipse cx="108" cy="28" rx="13" ry="13" fill="#f9c9a0" stroke="#e0a870" stroke-width="1.5"/>
  <ellipse cx="100" cy="16" rx="4.5" ry="7" fill="#f9c9a0" transform="rotate(-25 100 16)"/>
  <ellipse cx="109" cy="13" rx="4.5" ry="7" fill="#f9c9a0" transform="rotate(0 109 13)"/>
  <ellipse cx="118" cy="17" rx="4.5" ry="7" fill="#f9c9a0" transform="rotate(20 118 17)"/>
</svg>"""

CHAPTERS_BODY = f"""
<style>
  .board-page {{ padding:1.5rem 1.25rem 4rem; max-width:1340px; margin:0 auto; }}
  .board-page > h1 {{ font-family:'Lora',serif; font-size:2rem; font-weight:700; color:var(--ink); margin-bottom:.25rem; }}
  .board-page > .subtitle {{ color:var(--ink-dim); font-size:.875rem; margin-bottom:1.5rem; }}
  .goose-board {{ position:relative; border-radius:6px; overflow:hidden; box-shadow:0 12px 40px rgba(0,0,0,.45),10px 10px 0 #2a1806; }}
  .board-border {{ background:repeating-linear-gradient(90deg,#a83808 0px,#c94c1a 4px,#e07828 4px,#e07828 8px,#c94c1a 8px,#c94c1a 14px,#f0a040 14px,#f0a040 18px,#c94c1a 18px,#c94c1a 24px,#8b2e0a 24px,#8b2e0a 28px,#c94c1a 28px,#c94c1a 36px); height:13px; }}
  .board-border.bottom {{ transform:scaleY(-1); }}
  .board-inner {{ background:radial-gradient(ellipse 80% 60% at 50% 50%,#3d7828 0%,#2c5c1e 55%,#1e4414 100%); border-left:7px solid #6b4010; border-right:7px solid #6b4010; padding:1rem 1.1rem 1.1rem; position:relative; }}
  .board-inner::before {{ content:''; position:absolute; inset:0; border-left:2px solid rgba(212,146,10,.3); border-right:2px solid rgba(212,146,10,.3); pointer-events:none; z-index:0; }}
  .board-title {{ text-align:center; font-family:'Lora',serif; font-size:.78rem; font-weight:700; letter-spacing:.22em; text-transform:uppercase; color:#f0c040; margin-bottom:.85rem; text-shadow:0 1px 5px rgba(0,0,0,.6); position:relative; z-index:1; }}
  .goose-grid {{ display:grid; grid-template-columns:repeat(4,1fr); grid-template-rows:auto auto auto; grid-template-areas:"c1 c2 c3 c4" "c10 cw cw c5" "c9 c8 c7 c6"; gap:.6rem; position:relative; z-index:1; }}
  .c1  {{ grid-area:c1; }} .c2  {{ grid-area:c2; }} .c3  {{ grid-area:c3; }} .c4  {{ grid-area:c4; }}
  .c5  {{ grid-area:c5; }} .c6  {{ grid-area:c6; }} .c7  {{ grid-area:c7; }} .c8  {{ grid-area:c8; }}
  .c9  {{ grid-area:c9; }} .c10 {{ grid-area:c10; }} .cw  {{ grid-area:cw; }}
  .ch-sq {{ background:linear-gradient(155deg,#faf5e4 0%,#f0e6c0 100%); border:2.5px solid #9b7820; border-radius:5px; padding:.8rem .7rem .9rem; position:relative; display:flex; flex-direction:column; gap:.33rem; box-shadow:inset 0 1px 3px rgba(255,255,255,.55),0 2px 5px rgba(0,0,0,.22),2px 3px 0 rgba(0,0,0,.18); transition:transform .15s,box-shadow .15s; cursor:default; }}
  .ch-sq:hover {{ transform:translateY(-2px); box-shadow:inset 0 1px 3px rgba(255,255,255,.55),0 4px 10px rgba(0,0,0,.28),3px 5px 0 rgba(0,0,0,.18); }}
  .ch-num {{ position:absolute; top:-.82rem; left:50%; transform:translateX(-50%); width:1.65rem; height:1.65rem; border-radius:50%; background:linear-gradient(135deg,#9b7820,#6b4e10); color:#f5e090; font-size:.68rem; font-weight:700; display:flex; align-items:center; justify-content:center; font-family:'Lora',serif; border:2.5px solid #f0e6c0; box-shadow:0 2px 5px rgba(0,0,0,.35),inset 0 1px 2px rgba(255,255,255,.2); z-index:1; }}
  .turn-badge {{ position:absolute; width:1.35rem; height:1.35rem; border-radius:50%; background:rgba(212,146,10,.22); border:1.5px solid rgba(212,146,10,.55); display:flex; align-items:center; justify-content:center; color:#f0c040; font-size:.75rem; line-height:1; z-index:2; }}
  .c4  .turn-badge {{ bottom:.4rem; right:.4rem; }}
  .c6  .turn-badge {{ bottom:.4rem; left:.4rem; }}
  .c9  .turn-badge {{ top:.4rem; left:.4rem; }}
  .c10 .turn-badge {{ top:50%; right:.35rem; transform:translateY(-50%); }}
  .ch-yr {{ font-family:'Lora',serif; font-size:.95rem; font-weight:700; color:#5c3a10; margin-top:.45rem; line-height:1.1; }}
  .ch-name {{ font-size:.72rem; font-weight:700; color:#3a2408; line-height:1.3; }}
  .ch-div {{ border:none; border-top:1px solid rgba(155,120,32,.28); margin:.15rem 0; }}
  .ch-summary {{ font-size:.67rem; color:#4a3428; line-height:1.55; }}
  .ch-media-label {{ font-size:.54rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase; color:#7a5a28; margin-top:.3rem; }}
  .ch-media-val {{ font-size:.65rem; color:#4a3428; line-height:1.5; }}
  .ch-pill {{ display:inline-block; background:rgba(155,120,32,.11); border:1px solid rgba(155,120,32,.22); border-radius:2px; padding:1px 5px; font-size:.6rem; margin:1px 2px 1px 0; color:#3a2408; }}
  .cw {{ background:linear-gradient(145deg,#2d6022 0%,#1e4a16 100%); border:2.5px solid #6b8a20; border-radius:5px; padding:.8rem 1rem; display:flex; align-items:center; justify-content:center; gap:1rem; box-shadow:inset 0 2px 8px rgba(0,0,0,.25),2px 3px 0 rgba(0,0,0,.2); position:relative; }}
  .cw::before {{ content:''; position:absolute; inset:4px; border:1px solid rgba(212,146,10,.2); border-radius:3px; pointer-events:none; }}
  .goose-wrap {{ flex-shrink:0; filter:drop-shadow(1px 4px 6px rgba(0,0,0,.4)); align-self:flex-end; }}
  .waldo-portrait {{ flex-shrink:0; display:flex; flex-direction:column; align-items:center; gap:.45rem; text-align:center; }}
  .waldo-ring {{ width:130px; height:130px; border-radius:50%; background:conic-gradient(from 0deg,#d4920a 0deg,#f5d060 45deg,#d4920a 90deg,#8b5a00 135deg,#d4920a 180deg,#f5d060 225deg,#d4920a 270deg,#8b5a00 315deg,#d4920a 360deg); padding:5px; box-shadow:0 0 18px rgba(212,146,10,.4),0 4px 8px rgba(0,0,0,.4); }}
  .waldo-ring-inner {{ width:100%; height:100%; border-radius:50%; background:#245018; padding:3px; }}
  .waldo-photo {{ width:100%; height:100%; border-radius:50%; overflow:hidden; border:2px solid rgba(212,146,10,.35); display:flex; align-items:center; justify-content:center; background:#1e4016; }}
  .waldo-name {{ font-family:'Lora',serif; font-size:1rem; font-weight:700; color:#f0c040; text-shadow:0 1px 5px rgba(0,0,0,.65); }}
  .waldo-tagline {{ font-size:.6rem; color:rgba(255,255,255,.68); max-width:155px; line-height:1.55; }}
  .waldo-stats {{ border-top:1px solid rgba(212,146,10,.22); padding-top:.4rem; font-size:.57rem; color:rgba(255,255,255,.5); line-height:1.8; }}
  .waldo-stats em {{ color:#f0c040; font-style:normal; font-weight:600; }}
  @media (max-width:780px) {{ .goose-grid {{ grid-template-columns:1fr 1fr; grid-template-areas:"c1 c2" "c3 c4" "c5 c6" "c7 c8" "c9 c10" "cw cw"; }} }}
  @media (max-width:480px) {{ .goose-grid {{ grid-template-columns:1fr; grid-template-areas:"c1""c2""c3""c4""c5""c6""c7""c8""c9""c10""cw"; }} .cw {{ flex-direction:column; }} }}
</style>

<div class="board-page">
  <h1>Life Chapters</h1>
  <p class="subtitle">A decade of life, traced through what was being watched, read, and listened to — arranged as a game board.</p>

  <div class="goose-board">
    <div class="board-border"></div>
    <div class="board-inner">
      <div class="board-title">&#9753; The Game of Cultural Life &mdash; Roll &amp; Discover &#10023;</div>

      <div class="goose-grid">

        <!-- ① -->
        <div class="ch-sq c1">
          <div class="ch-num">&#9312;</div>
          <div class="ch-yr">2012–13</div>
          <div class="ch-name">First Apartment &amp; Late-Night Cinema</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Moved into a studio with a projector and no furniture. Watched films on the wall every night. Criterion Collection rabbit hole — Tati, Kubrick, Kurosawa. Music taste crystallising around blues, soul, and Django Reinhardt. Renting DVDs from the video store two streets over still felt normal.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Robert Johnson · Django Reinhardt · Billie Holiday · Tom Waits</div>
        </div>

        <!-- ② -->
        <div class="ch-sq c2">
          <div class="ch-num">&#9313;</div>
          <div class="ch-yr">2014–15</div>
          <div class="ch-name">The Series Awakening</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Breaking Bad in five days. Then The Wire. Then a subscription to everything. Streaming finally arrived and the projector became a TV. Started keeping a spreadsheet — later migrated to IMDb ratings. A Spotify account appeared alongside the record collection. Bob Dylan every Sunday morning, always.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Bob Dylan · Paul Simon · Sam Cooke · Eels</div>
        </div>

        <!-- ③ -->
        <div class="ch-sq c3">
          <div class="ch-num">&#9314;</div>
          <div class="ch-yr">2016–17</div>
          <div class="ch-name">The Reading Comeback</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Discworld enters the picture — 38 novels in 14 months. Rediscovered that books are better than screens at 1am. Goodreads account created mostly to log what was already finished. The Pratchett streak instilled a permanent preference for wit over spectacle that now shows up in every rating.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Bonobo · DJ Shadow · Nick Drake · Portishead</div>
          <div class="ch-media-label">&#128218; Reading</div>
          <div class="ch-media-val">
            <span class="ch-pill">Guards! Guards! 5&#9733;</span>
            <span class="ch-pill">Mort 5&#9733;</span>
            <span class="ch-pill">Hogfather 5&#9733;</span>
          </div>
        </div>

        <!-- ④ top-right corner, turns DOWN -->
        <div class="ch-sq c4">
          <div class="ch-num">&#9315;</div>
          <div class="ch-yr">2018</div>
          <div class="ch-name">Arthouse Deep Dive</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Stalker on a Tuesday. Took three watches and a Wikipedia binge. Bergman retrospective at the local cinema — eleven films in a month. Started logging not just what was watched but notes on why. The ARTHOUSE zone was forming, though it didn't have a name yet.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Nina Simone · Chet Baker · Miles Davis · Bill Evans</div>
          <div class="ch-media-label">&#127916; Watching</div>
          <div class="ch-media-val">Stalker · The Seventh Seal · Persona · Mirror</div>
          <div class="turn-badge">&#8595;</div>
        </div>

        <!-- ⑤ right column top -->
        <div class="ch-sq c5">
          <div class="ch-num">&#9316;</div>
          <div class="ch-yr">2019</div>
          <div class="ch-name">Sci-Fi Renaissance</div>
          <hr class="ch-div"/>
          <div class="ch-summary">The Three-Body Problem in six weeks. Then Dark Forest and Death's End. Hard sci-fi colonised the reading list. Arrival, Annihilation, and Blade Runner 2049 all in the same month. The SCI_FI zone lit up and never stopped. Began listening to ambient and electronic music during long reading sessions.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Boards of Canada · Brian Eno · Aphex Twin · Massive Attack</div>
          <div class="ch-media-label">&#128218; Reading</div>
          <div class="ch-media-val">
            <span class="ch-pill">Three-Body Problem 5&#9733;</span>
            <span class="ch-pill">Children of Time 5&#9733;</span>
            <span class="ch-pill">Hyperion 5&#9733;</span>
          </div>
        </div>

        <!-- CENTER: Waldo + Goose -->
        <div class="cw">
          <!-- Canada Goose SVG -->
          <div class="goose-wrap">
            <svg viewBox="0 0 210 250" xmlns="http://www.w3.org/2000/svg" width="140" height="167">
              <ellipse cx="105" cy="240" rx="95" ry="11" fill="#1e5a18" opacity=".5"/>
              <path d="M20 240 Q45 231 70 238 Q95 245 118 239 Q142 233 168 239 Q188 244 205 238" stroke="#2d6a1e" stroke-width="3.5" fill="none" opacity=".6"/>
              <ellipse cx="108" cy="178" rx="85" ry="56" fill="#8b6520"/>
              <ellipse cx="103" cy="168" rx="77" ry="48" fill="#9b7530"/>
              <ellipse cx="93" cy="198" rx="55" ry="32" fill="#c4a058"/>
              <ellipse cx="82" cy="188" rx="36" ry="28" fill="#d4b068" opacity=".7"/>
              <path d="M36 170 Q65 184 100 175 Q130 166 160 173 Q180 178 198 167" stroke="#6b4e18" stroke-width="1.5" fill="none" opacity=".65"/>
              <path d="M34 186 Q65 202 104 192 Q136 183 168 190 Q188 195 198 184" stroke="#6b4e18" stroke-width="1.5" fill="none" opacity=".6"/>
              <path d="M38 202 Q68 215 106 206 Q138 199 166 205" stroke="#6b4e18" stroke-width="1" fill="none" opacity=".45"/>
              <path d="M196 165 Q222 150 220 177 Q218 200 202 194Z" fill="#7a5a16"/>
              <path d="M103 133 Q92 104 97 72 Q101 50 110 40" stroke="#161616" stroke-width="25" fill="none" stroke-linecap="round"/>
              <path d="M106 129 Q97 104 100 75 Q103 55 112 46" stroke="#2a2a2a" stroke-width="8" fill="none" stroke-linecap="round" opacity=".4"/>
              <ellipse cx="118" cy="36" rx="27" ry="23" fill="#161616"/>
              <path d="M99 42 Q102 57 117 63 Q130 66 139 57 Q132 69 118 70 Q100 70 95 52Z" fill="#e0e0e0"/>
              <circle cx="128" cy="31" r="5.5" fill="#fff" opacity=".92"/>
              <circle cx="129" cy="31" r="3.5" fill="#0a0a0a"/>
              <circle cx="130" cy="30" r="1.2" fill="#fff"/>
              <path d="M141 32 L163 38 Q165 41 163 44 L141 44Z" fill="#909090"/>
              <line x1="141" y1="38" x2="163" y2="39" stroke="#666" stroke-width="1" opacity=".7"/>
              <line x1="88" y1="224" x2="88" y2="238" stroke="#9b7828" stroke-width="4"/>
              <path d="M88 238 L74 250 M88 238 L82 253 M88 238 L91 252 M88 238 L100 250" stroke="#9b7828" stroke-width="2.5" fill="none" stroke-linecap="round"/>
              <line x1="126" y1="224" x2="126" y2="238" stroke="#9b7828" stroke-width="4"/>
              <path d="M126 238 L112 250 M126 238 L120 253 M126 238 L129 252 M126 238 L138 250" stroke="#9b7828" stroke-width="2.5" fill="none" stroke-linecap="round"/>
            </svg>
          </div>
          <!-- Waldo portrait with SVG cartoon -->
          <div class="waldo-portrait">
            <div class="waldo-ring">
              <div class="waldo-ring-inner">
                <div class="waldo-photo">
                  {WALDO_SVG_FACE}
                </div>
              </div>
            </div>
            <div class="waldo-name">Where is Waldo?</div>
            <div class="waldo-tagline">Right here — at the end of a decade of music, films, reading binges, and a slow drift toward building things with code.</div>
            <div class="waldo-stats">
              <em>150k+</em> Spotify streams &middot; <em>38</em> Pratchett novels<br/>
              <em>647</em> IMDb ratings &middot; <em>12</em> taste zones mapped
            </div>
          </div>
        </div>

        <!-- ⑥ bottom-right corner, turns LEFT -->
        <div class="ch-sq c6">
          <div class="ch-num">&#9317;</div>
          <div class="ch-yr">2020</div>
          <div class="ch-name">COVID Lockdown — Comfort &amp; Craft</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Stuck indoors with a streaming subscription and suddenly infinite time. Watched Wes Anderson's entire filmography in a week. Discovered Cartoon Saloon animation. Penn &amp; Teller: Fool Us — six episodes in a single sitting. Also: baking, plant-based everything, Avicii tribute concerts, and way too much YouTube.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">The Beatles · David Bowie · Avicii · Nina Simone</div>
          <div class="ch-media-label">&#128218; Reading</div>
          <div class="ch-media-val"><span class="ch-pill">One Hundred Years of Solitude</span></div>
          <div class="turn-badge">&#8592;</div>
        </div>

        <!-- ⑦ bottom row, going left -->
        <div class="ch-sq c7">
          <div class="ch-num">&#9318;</div>
          <div class="ch-yr">2021</div>
          <div class="ch-name">One Piece &amp; Board Games</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Fell into One Piece lore via YouTube analysis channels — a year of theory videos and symbolism deep dives. Legends of Andor arrives as the first board game hobby. Spotify habits split between children's music and the occasional late-night soul session. A quieter year, closer to home, slower pace.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Bill Withers · Otis Redding · The Rolling Stones · B.B. King</div>
          <div class="ch-media-label">&#128218; Reading</div>
          <div class="ch-media-val">
            <span class="ch-pill">We Are Legion 4&#9733;</span>
            <span class="ch-pill">Ender's Game 5&#9733;</span>
          </div>
        </div>

        <!-- ⑧ bottom row, going left -->
        <div class="ch-sq c8">
          <div class="ch-num">&#9319;</div>
          <div class="ch-yr">2022–23</div>
          <div class="ch-name">Hard SF Era &amp; AI Discovery</div>
          <hr class="ch-div"/>
          <div class="ch-summary">The Will of the Many. Children of Time again. Hyperion twice. A hard SF reading streak that didn't stop for 18 months. In March 2023, a single YouTube explainer video: the first ChatGPT overview. Something shifted. National Geographic documentaries gave way to AI content. The Observatory began as a side project.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">ALA.NI · The Beach Boys · Aretha Franklin · Vulfpeck</div>
          <div class="ch-media-label">&#128218; Reading</div>
          <div class="ch-media-val">
            <span class="ch-pill">The Will of the Many 5&#9733;</span>
            <span class="ch-pill">Hyperion 5&#9733;</span>
            <span class="ch-pill">Red Rising 5&#9733;</span>
          </div>
        </div>

        <!-- ⑨ bottom-left corner, turns UP -->
        <div class="ch-sq c9">
          <div class="ch-num">&#9320;</div>
          <div class="ch-yr">2024</div>
          <div class="ch-name">Anime Awakening &amp; New Hobbies</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Solo Leveling and Pantheon land as serious contenders alongside live-action. Flock Together and Caverna board games multiply. Tom Scott architecture and craft YouTube. The Taste Map starts to look like an accurate mirror of identity rather than just data. Cari Cari on heavy rotation.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Cari Cari · Rodriguez · Bob Dylan · Angèle</div>
          <div class="ch-media-label">&#128218; Reading</div>
          <div class="ch-media-val">
            <span class="ch-pill">The Creative Act 4&#9733;</span>
            <span class="ch-pill">Nexus 5&#9733;</span>
          </div>
          <div class="turn-badge">&#8593;</div>
        </div>

        <!-- ⑩ left column, turns RIGHT → to Waldo -->
        <div class="ch-sq c10">
          <div class="ch-num">&#9321;</div>
          <div class="ch-yr">2025–26</div>
          <div class="ch-name">Long Reads &amp; Slow Sundays</div>
          <hr class="ch-div"/>
          <div class="ch-summary">Everything slowed down. One long novel a month, no bingeing. Sunday mornings with vinyl and strong coffee — a deliberate antidote to algorithmic urgency. Children of Time re-read. Good Omens for the third time. Slow Horses somehow better on second watch. A growing preference for things that don't ask you to hurry.</div>
          <div class="ch-media-label">&#127925; Listening to</div>
          <div class="ch-media-val">Nina Simone · Miles Davis · Billie Holiday · Nick Drake</div>
          <div class="ch-media-label">&#128218; Reading</div>
          <div class="ch-media-val">
            <span class="ch-pill">Children of Time 5&#9733;</span>
            <span class="ch-pill">Good Omens 5&#9733;</span>
            <span class="ch-pill">Project Hail Mary 5&#9733;</span>
          </div>
          <div class="ch-media-label">&#127916; Films</div>
          <div class="ch-media-val">Stalker 5&#9733; &middot; Mulholland Drive 5&#9733;</div>
          <div class="turn-badge">&#8594;</div>
        </div>

      </div>
    </div>
    <div class="board-border bottom"></div>
  </div>
</div>"""


def bake_chapters():
    out = DOCS_DIR / "chapters.html"
    out.write_text(culture_page("Life Chapters — Culture ✦", "chapters", CHAPTERS_BODY))
    print(f"Wrote {out}")


# ── Rich stub pages (Ask Claude, Find & Add, Picks) ─────────────────────────

_STUB_SHARED_CSS = """
<style>
  .demo-section { max-width:820px; margin:0 auto; padding:2rem 1.5rem 4rem; }
  .demo-section-head { margin-bottom:2rem; }
  .demo-section-head h1 { font-family:'Lora',serif; font-size:1.75rem; font-weight:700; color:var(--ink); margin-bottom:.35rem; }
  .demo-section-head p { font-size:.875rem; color:var(--ink-dim); line-height:1.6; max-width:520px; }
  .demo-live-note { display:inline-flex; align-items:center; gap:.5rem; margin-top:1rem; padding:.45rem .85rem; background:rgba(201,76,26,.08); border:1.5px solid rgba(201,76,26,.22); border-radius:3px; font-size:.72rem; color:var(--rust); }
  .demo-live-note a { color:var(--rust); font-weight:700; }
  .demo-preview { background:var(--paper); border:2px solid var(--ink); border-radius:4px; box-shadow:4px 4px 0 var(--ink); overflow:hidden; }
  .demo-preview-label { font-size:.6rem; font-weight:700; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-dim); background:var(--cream-dark); padding:.35rem .75rem; border-bottom:1.5px solid var(--ink); }
</style>"""

def bake_ask_claude():
    body = _STUB_SHARED_CSS + """
<style>
  .chat-wrap { padding:1.25rem; display:flex; flex-direction:column; gap:1rem; }
  .chat-msg { display:flex; gap:.75rem; align-items:flex-start; }
  .chat-msg.user { flex-direction:row-reverse; }
  .chat-avatar { width:28px; height:28px; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:.65rem; font-weight:700; }
  .chat-avatar.bot  { background:var(--cobalt); color:#fff; }
  .chat-avatar.user { background:var(--gold); color:var(--ink); }
  .chat-bubble { max-width:78%; padding:.65rem .9rem; border-radius:4px; font-size:.82rem; line-height:1.6; color:var(--ink); }
  .chat-bubble.bot  { background:#fff; border:1.5px solid var(--border,rgba(26,22,18,.12)); }
  .chat-bubble.user { background:var(--cobalt); color:#fff; }
  .chat-input-row { display:flex; gap:.5rem; padding:.75rem 1.25rem; border-top:1.5px solid rgba(26,22,18,.1); background:var(--cream-dark); }
  .chat-input-mock { flex:1; background:#fff; border:1.5px solid rgba(26,22,18,.18); border-radius:3px; padding:.5rem .75rem; font-size:.8rem; color:var(--ink-dim); cursor:not-allowed; }
  .chat-send-mock { background:var(--cobalt); color:#fff; border:none; border-radius:3px; padding:.5rem 1rem; font-size:.75rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; cursor:not-allowed; opacity:.6; }
  .chat-note { font-size:.68rem; color:var(--ink-dim); text-align:center; padding:.5rem .75rem 0; }
</style>
<div class="demo-section">
  <div class="demo-section-head">
    <h1>Ask Claude</h1>
    <p>Chat with Claude about your taste — get recommendations, explore themes, understand why you love what you love.</p>
    <span class="demo-live-note">&#128274; Requires a live server. <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">Clone the repo</a> to use with your own data.</span>
  </div>
  <div class="demo-preview">
    <div class="demo-preview-label">Preview — what a real conversation looks like</div>
    <div class="chat-wrap">
      <div class="chat-msg user">
        <div class="chat-avatar user">Me</div>
        <div class="chat-bubble user">Why do I keep giving sci-fi books 5 stars but sci-fi films only 4?</div>
      </div>
      <div class="chat-msg">
        <div class="chat-avatar bot">✦</div>
        <div class="chat-bubble bot">Looking at your ratings: you've given 5 stars to 7 sci-fi books (Hyperion, Children of Time, The Three-Body Problem…) but only 4 stars to most sci-fi films.<br><br>The pattern suggests you value ideas over spectacle. Your top-rated books are all hard sci-fi — civilisational scale, rigorous world-building, slow philosophical payoff. Films like Blade Runner 2049 and Arrival score well because they have that restraint, but most sci-fi cinema trades depth for action.<br><br>You also rate Tarkovsky (Stalker, 5★) highest of all — pure idea, no compromise. That's your north star.</div>
      </div>
      <div class="chat-msg user">
        <div class="chat-avatar user">Me</div>
        <div class="chat-bubble user">What should I read next given that pattern?</div>
      </div>
      <div class="chat-msg">
        <div class="chat-avatar bot">✦</div>
        <div class="chat-bubble bot">Given your love of hard SF at civilisational scale, three strong candidates:<br><br>
          <strong>A Fire Upon the Deep</strong> — Vernor Vinge. Zones of thought concept = your kind of rigorous world-building. You'll finish it in four days.<br><br>
          <strong>Blindsight</strong> — Peter Watts. Radical hard SF about consciousness. Darker than your usual taste (you flag bleak as a mild dislike) but intellectually exactly your register.<br><br>
          <strong>Exhalation</strong> — Ted Chiang. Short stories, but each one is a philosophical proposition disguised as fiction. Matches your 5★ threshold better than a novel might.</div>
      </div>
    </div>
    <div class="chat-input-row">
      <div class="chat-input-mock">Ask about your taste…</div>
      <button class="chat-send-mock">Send</button>
    </div>
    <div class="chat-note">Input disabled in demo. Clone the repo and add your Anthropic API key to try it live.</div>
  </div>
</div>"""
    out = DOCS_DIR / "ask-claude.html"
    out.write_text(culture_page("Ask Claude — Culture ✦", "chat", body))
    print(f"Wrote {out}")


def bake_picks():
    body = _STUB_SHARED_CSS + """
<style>
  .picks-grid { display:grid; grid-template-columns:1fr 1fr; gap:1rem; padding:1.25rem; }
  @media(max-width:560px) { .picks-grid { grid-template-columns:1fr; } }
  .pick-card { background:#fff; border:1.5px solid rgba(26,22,18,.12); border-radius:4px; padding:1rem; display:flex; flex-direction:column; gap:.4rem; }
  .pick-type { font-size:.58rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-dim); }
  .pick-type.film   { color:var(--rust); }
  .pick-type.book   { color:var(--cobalt); }
  .pick-type.music  { color:var(--teal); }
  .pick-type.series { color:#6b3fa0; }
  .pick-title { font-family:'Lora',serif; font-size:.95rem; font-weight:700; color:var(--ink); }
  .pick-creator { font-size:.75rem; color:var(--ink-dim); }
  .pick-reason { font-size:.74rem; color:var(--ink-mid); line-height:1.55; }
  .pick-conf { display:flex; align-items:center; gap:.35rem; margin-top:.2rem; font-size:.64rem; color:var(--ink-dim); }
  .pick-conf-bar { flex:1; height:3px; background:rgba(26,22,18,.1); border-radius:2px; overflow:hidden; }
  .pick-conf-fill { height:100%; background:var(--gold); }
</style>
<div class="demo-section">
  <div class="demo-section-head">
    <h1>What's next.</h1>
    <p>Curated recommendations across every medium — grounded in your taste profile, generated by Claude, filtered by things you haven't consumed yet.</p>
    <span class="demo-live-note">&#128274; Requires a live server. <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">Clone the repo</a> to generate your personal picks.</span>
  </div>
  <div class="demo-preview">
    <div class="demo-preview-label">Preview — sample recommendations based on fixture taste profile</div>
    <div class="picks-grid">
      <div class="pick-card">
        <span class="pick-type book">&#128218; Book</span>
        <div class="pick-title">A Fire Upon the Deep</div>
        <div class="pick-creator">Vernor Vinge &middot; 1992</div>
        <div class="pick-reason">Hard SF at civilisational scale — zones of thought is exactly the kind of rigorous world-building concept you rate 5&#9733;. Vinge matches your Hyperion/Children of Time register.</div>
        <div class="pick-conf">
          <span>Confidence</span>
          <div class="pick-conf-bar"><div class="pick-conf-fill" style="width:94%"></div></div>
          <span>94%</span>
        </div>
      </div>
      <div class="pick-card">
        <span class="pick-type film">&#127916; Film</span>
        <div class="pick-title">Annihilation</div>
        <div class="pick-creator">Alex Garland &middot; 2018</div>
        <div class="pick-reason">Tarkovsky-adjacent sci-fi: slow, ambiguous, idea-first. Your 5&#9733; on Stalker and Arrival signals appetite for this. Pairs thematically with Blade Runner 2049.</div>
        <div class="pick-conf">
          <div class="pick-conf-bar"><div class="pick-conf-fill" style="width:91%"></div></div>
          <span>91%</span>
        </div>
      </div>
      <div class="pick-card">
        <span class="pick-type series">&#127902; Series</span>
        <div class="pick-title">Station Eleven</div>
        <div class="pick-creator">HBO Max &middot; 2021</div>
        <div class="pick-reason">Literary post-apocalyptic drama — not bleak but meditative. Your 5&#9733; on The Leftovers and Never Let Me Go suggests this exact register.</div>
        <div class="pick-conf">
          <div class="pick-conf-bar"><div class="pick-conf-fill" style="width:88%"></div></div>
          <span>88%</span>
        </div>
      </div>
      <div class="pick-card">
        <span class="pick-type music">&#127925; Music</span>
        <div class="pick-title">Vashti Bunyan</div>
        <div class="pick-creator">Just Another Diamond Day &middot; 1970</div>
        <div class="pick-reason">Shares the stillness of Nick Drake and Billie Holiday in your top streams. Fragile, pastoral, unhurried — well within your listening register.</div>
        <div class="pick-conf">
          <div class="pick-conf-bar"><div class="pick-conf-fill" style="width:85%"></div></div>
          <span>85%</span>
        </div>
      </div>
    </div>
  </div>
</div>"""
    out = DOCS_DIR / "picks.html"
    out.write_text(culture_page("Recommendations — Culture ✦", "picks", body))
    print(f"Wrote {out}")


def bake_find():
    body = _STUB_SHARED_CSS + """
<style>
  .find-bar { display:flex; gap:.5rem; padding:1rem 1.25rem; background:var(--cream-dark); border-bottom:1.5px solid rgba(26,22,18,.1); }
  .find-input-mock { flex:1; background:#fff; border:1.5px solid rgba(26,22,18,.2); border-radius:3px; padding:.55rem .85rem; font-size:.82rem; color:var(--ink); pointer-events:none; }
  .find-type-mock { background:#fff; border:1.5px solid rgba(26,22,18,.2); border-radius:3px; padding:.55rem .65rem; font-size:.8rem; color:var(--ink-dim); pointer-events:none; }
  .find-btn-mock { background:var(--cobalt); color:#fff; border:none; border-radius:3px; padding:.55rem 1.1rem; font-size:.75rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; cursor:not-allowed; opacity:.55; }
  .find-results { padding:.75rem 1.25rem; display:flex; flex-direction:column; gap:.65rem; }
  .find-result { display:flex; gap:.85rem; padding:.65rem .75rem; background:#fff; border:1.5px solid rgba(26,22,18,.1); border-radius:4px; align-items:center; }
  .find-result-thumb { width:40px; height:58px; background:linear-gradient(135deg,var(--ink),#5a4a3a); border-radius:3px; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:1.2rem; color:rgba(255,255,255,.5); }
  .find-result-info { flex:1; }
  .find-result-title { font-family:'Lora',serif; font-size:.9rem; font-weight:700; color:var(--ink); }
  .find-result-sub { font-size:.72rem; color:var(--ink-dim); }
  .find-result-year { font-size:.65rem; background:rgba(26,22,18,.07); color:var(--ink-dim); padding:1px 6px; border-radius:2px; display:inline-block; margin-top:.2rem; }
  .find-add-mock { font-size:.7rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--cobalt); border:1.5px solid var(--cobalt); border-radius:3px; padding:.35rem .7rem; cursor:not-allowed; opacity:.55; white-space:nowrap; }
  .find-note { font-size:.68rem; color:var(--ink-dim); text-align:center; padding:.5rem .75rem; }
</style>
<div class="demo-section">
  <div class="demo-section-head">
    <h1>Find &amp; Add</h1>
    <p>Search TMDB, OpenLibrary, and MusicBrainz to add films, books, albums, and series to your watchlist and reading list.</p>
    <span class="demo-live-note">&#128274; Requires a live server. <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">Clone the repo</a> to search and add your own media.</span>
  </div>
  <div class="demo-preview">
    <div class="demo-preview-label">Preview — mock search for "Foundation"</div>
    <div class="find-bar">
      <input class="find-input-mock" value="Foundation" readonly/>
      <select class="find-type-mock"><option>Book</option></select>
      <button class="find-btn-mock">Search</button>
    </div>
    <div class="find-results">
      <div class="find-result">
        <div class="find-result-thumb">&#128218;</div>
        <div class="find-result-info">
          <div class="find-result-title">Foundation</div>
          <div class="find-result-sub">Isaac Asimov &middot; Science Fiction</div>
          <span class="find-result-year">1951</span>
        </div>
        <button class="find-add-mock">+ Add</button>
      </div>
      <div class="find-result">
        <div class="find-result-thumb">&#128218;</div>
        <div class="find-result-info">
          <div class="find-result-title">Foundation and Empire</div>
          <div class="find-result-sub">Isaac Asimov &middot; Science Fiction</div>
          <span class="find-result-year">1952</span>
        </div>
        <button class="find-add-mock">+ Add</button>
      </div>
      <div class="find-result">
        <div class="find-result-thumb">&#128218;</div>
        <div class="find-result-info">
          <div class="find-result-title">Second Foundation</div>
          <div class="find-result-sub">Isaac Asimov &middot; Science Fiction</div>
          <span class="find-result-year">1953</span>
        </div>
        <button class="find-add-mock">+ Add</button>
      </div>
    </div>
    <div class="find-note">Buttons disabled in demo. Clone the repo to search TMDB &amp; OpenLibrary with your own API keys.</div>
  </div>
</div>"""
    out = DOCS_DIR / "find.html"
    out.write_text(culture_page("Find & Add — Culture ✦", "find", body))
    print(f"Wrote {out}")


# ── Brain map ─────────────────────────────────────────────────────────────────

_BRAIN_BODY_INJECT = """<div id="demo-banner">
  <span>Demo &mdash; synthetic fixture data &middot;
    <a href="https://github.com/waldo-van-der-code/observatory" target="_blank">clone the repo</a> to use your own data</span>
</div>
<div style="height:30px"></div>
<header class="c-header">
  <a href="index.html" class="c-header-logo">Culture <span>&#10022;</span></a>
  <nav class="c-nav">
    <a href="ask-claude.html">Ask Claude</a>
    <a href="picks.html">Recommendations</a>
    <a href="analytics.html">Analytics</a>
    <a href="find.html">Find &amp; Add</a>
    <a href="chapters.html">Life Chapters</a>
    <a href="brain.html" class="active">Taste Map</a>
  </nav>
  <button class="c-hamburger" id="cHam3" aria-label="Open menu">&#9776;</button>
</header>
<div class="c-drawer" id="cDrawer3">
  <div class="c-drawer-head">
    <span class="c-drawer-logo">Culture <span>&#10022;</span></span>
    <button class="c-drawer-close" id="cDrawerClose3">&#10005;</button>
  </div>
  <a href="index.html">Dashboard</a>
  <a href="ask-claude.html">Ask Claude</a>
  <a href="picks.html">Recommendations</a>
  <a href="analytics.html">Analytics</a>
  <a href="find.html">Find &amp; Add</a>
  <a href="chapters.html">Life Chapters</a>
  <a href="brain.html" class="active">Taste Map</a>
</div>
<script>
  const h3=document.getElementById('cHam3'),d3=document.getElementById('cDrawer3'),c3=document.getElementById('cDrawerClose3');
  h3?.addEventListener('click',()=>d3?.classList.add('open'));
  c3?.addEventListener('click',()=>d3?.classList.remove('open'));
</script>
"""

def bake_brain():
    if not BRAIN_DATA.exists():
        raise FileNotFoundError(f"{BRAIN_DATA} not found. Run: python3 scripts/build_brain.py")

    zones = json.loads(BRAIN_DATA.read_text())
    html  = BRAIN_SRC.read_text()

    inline = f"window.BRAIN_ZONES = {json.dumps(zones, separators=(',', ':'))};"
    if PLACEHOLDER in html:
        html = html.replace(PLACEHOLDER, inline)
    else:
        html = html.replace(
            "<script>\n// ── Dimensions",
            f"<script>{inline}</script>\n<script>\n// ── Dimensions", 1,
        )

    html = html.replace('src="/static/', 'src="static/')
    html = html.replace('href="/static/', 'href="static/')
    html = html.replace('`/static/map-pieces/', '`static/map-pieces/')

    # Inject culture nav header (brain.html has own <head>, so inject CSS + nav)
    html = html.replace('</head>', f'{_CULTURE_HEAD_INJECT}\n</head>', 1)
    html = re.sub(r'<body([^>]*)>', rf'<body\1>\n{_BRAIN_BODY_INJECT}', html, count=1)

    out = DOCS_DIR / "brain.html"
    out.write_text(html)
    print(f"Wrote {out}  ({len(zones)} zones, {len(inline):,} chars inline)")

    src = BRAIN_SRC.read_text()
    restored = re.sub(
        r'<script>window\.BRAIN_ZONES = \[.*?\];</script>',
        f'<script>{PLACEHOLDER}</script>',
        src, flags=re.DOTALL,
    )
    if restored != src:
        BRAIN_SRC.write_text(restored)
        print(f"Restored placeholder in {BRAIN_SRC.name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    DOCS_DIR.mkdir(exist_ok=True)
    bake_hub()
    bake_analytics()
    bake_chapters()
    bake_ask_claude()
    bake_picks()
    bake_find()
    bake_brain()


if __name__ == "__main__":
    main()
