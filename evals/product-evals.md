# Product Evals — Manual Golden Behaviors

Manual checks to run after any vibe-coded change that touches UI, routes, or data pipeline.
Run after starting the server (`./run.sh --serve`). Fail = regression.

---

## Setup

```bash
./run.sh --serve   # starts FastAPI on http://localhost:8000
```

Open http://localhost:8000 in browser, open DevTools console before starting.

---

## Dashboard

### Page loads with content
**Trigger:** Any change to `build_dashboard.py`, `dashboard.html` template, or CSS.
**How to test:**
1. Visit `http://localhost:8000`
2. ✅ Page renders without blank screen
3. ✅ At least one data section is visible (Films, Music, Books, or similar)
4. ✅ No JS errors in console
5. ✅ Sticky search bar appears at top of viewport

### Section navigation scrolls correctly
**Trigger:** Any change to section nav links or section IDs.
**How to test:**
1. Click a section nav link (e.g. "Films" or "Music")
2. ✅ Page scrolls to that section
3. ✅ Sticky nav remains visible after scroll

---

## Search

### Search returns results
**Trigger:** Any change to `api_search.py`, `/api/search` route, or search UI JS.
**How to test:**
1. Type "Inception" in the search bar → press Enter or click search button
2. ✅ Search panel opens with ≥1 result
3. ✅ Each result shows a title (and poster if TMDB key is configured)
4. ✅ No network error in console

### Search type filter works
**Trigger:** Any change to the type dropdown or search filtering logic.
**How to test:**
1. Set type dropdown to "Film" → search "dune"
2. ✅ Results are all films (no books/music mixed in)
3. Set type to "Book" → search "dune"
4. ✅ Results are books

### Invalid search shows graceful state
**Trigger:** Any change to search error handling.
**How to test:**
1. Search for `!@#$%^&*` (unlikely to match anything)
2. ✅ Shows empty state or "no results" message — no crash, no blank panel

---

## Detail Overlay

### Clicking a search result opens detail drawer
**Trigger:** Any change to `openDetailOverlay()`, `/api/detail/{id}`, or `renderDetailHtml()`.
**How to test:**
1. Search "Inception" → click first result
2. ✅ Detail overlay slides in from right
3. ✅ Shows: title, year, overview text, genre tags, links section
4. ✅ No "undefined" or "[object Object]" visible in the drawer

### Escape key closes detail overlay
**Trigger:** Any change to overlay JS or keyboard handlers.
**How to test:**
1. Open any detail overlay
2. Press Esc
3. ✅ Overlay closes, body scroll is restored (not locked)
4. ✅ Clicking the backdrop also closes it

### Watchlist button works from detail overlay
**Trigger:** Any change to `/api/items`, `/api/interactions`, or the watchlist UI.
**How to test:**
1. Open detail for a title not yet in watchlist
2. ✅ Button says "Want to watch" (or equivalent)
3. Click it → ✅ Button changes to "In watchlist" (or saved state)
4. Refresh page → search same title → open detail → ✅ state persists

---

## Watchlist

### Watchlist roundtrip: add and remove
**Trigger:** Any change to `/api/watchlist`, `/api/watchlist/{id}`, or watchlist UI.
**How to test:**
1. Search "Arrival" → open detail → add to watchlist
2. `GET http://localhost:8000/api/watchlist` in a new tab → ✅ Arrival appears in JSON
3. Remove from watchlist (via detail overlay or dedicated UI)
4. Refresh `/api/watchlist` → ✅ Arrival is gone

---

## Brain Map

### Brain page renders SVG
**Trigger:** Any change to `brain.html`, `build_brain.py`, or `/api/brain/zones`.
**How to test:**
1. Visit `http://localhost:8000/brain`
2. ✅ Page title contains "Map of Waldo" (or similar)
3. ✅ `#map-outer` and `#map-svg` are visible
4. ✅ No full-page error — even with no `brain_data.json`, SVG container renders

### Zone labels appear when brain_data.json is built
**Trigger:** After running `python3 scripts/build_brain.py`.
**How to test:**
1. Confirm `data/processed/brain_data.json` exists
2. Visit `/brain`
3. ✅ Zone name labels appear as SVG text elements
4. ✅ Clicking a zone highlights it or shows zone detail

---

## Recommendations

### Rec cards visible on homepage
**Trigger:** Any change to rec seeding, `build_dashboard.py`, or `#sec-recs` section.
**How to test:**
1. Confirm recs have been seeded in DB (run the seed script if not)
2. Visit `http://localhost:8000`
3. ✅ `.rec-card` elements are visible in the `#sec-recs` section
4. ✅ Cards show: title badge, title text, action button (Want to watch / Want to read)
5. Click a rec card title → ✅ Detail overlay opens with enriched data

### Load more works (cards stay styled)
**Trigger:** Any change to `buildRecCard()` or load-more JS.
**How to test:**
1. Visit `http://localhost:8000`
2. Click "Load more" in the recs section
3. ✅ Newly loaded cards look identical to initial cards (same border, font, button styling)
4. ✅ No unstyled raw HTML appears

---

## Collapsibles

### Collapsed sections expand on click
**Trigger:** Any change to collapsible JS or CSS.
**How to test:**
1. Visit `http://localhost:8000`
2. ✅ At least one section shows a "See more" button (collapsed state)
3. Click "See more"
4. ✅ Section expands to show full content; button disappears or changes label

---

## Mobile layout

### Search bar fits within 375px viewport
**Trigger:** Any change to header/search bar CSS.
**How to test:**
1. Open DevTools → set viewport to 375×812 (iPhone SE)
2. ✅ Search button fully visible, not clipped by right edge
3. ✅ Section nav links don't overflow horizontally
