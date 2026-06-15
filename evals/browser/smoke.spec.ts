// @readonly — safe to run against production
import { test, expect } from "@playwright/test";

// ── Layout / load ──────────────────────────────────────────────────────────

test("homepage loads and has a title", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/.+/);
});

test("analytics tab: dashboard is scrollable", async ({ page }) => {
  await page.goto("/");
  const scrollHeight = await page.evaluate(
    () => document.documentElement.scrollHeight
  );
  const viewportHeight = await page.evaluate(() => window.innerHeight);
  expect(scrollHeight).toBeGreaterThan(viewportHeight);

  await page.evaluate(() => window.scrollTo({ top: 500, behavior: "instant" }));
  const scrollTop = await page.evaluate(() => window.scrollY);
  expect(scrollTop).toBeGreaterThan(0);
});

test("search button fits within viewport on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");

  const btn = page.locator("#search-btn");
  await expect(btn).toBeVisible();

  const box = await btn.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x + box!.width).toBeLessThanOrEqual(375 + 1);
});

test("taste map link points to /culture/map not /culture/brain", async ({
  page,
}) => {
  await page.goto("/");
  const tasteMapLink = page.locator('a.snav-link.external:has-text("Taste Map")');
  await expect(tasteMapLink).toHaveAttribute("href", "/culture/map");
});

// ── Section nav ────────────────────────────────────────────────────────────

test("section nav contains all expected anchor links", async ({ page }) => {
  await page.goto("/");
  const expectedAnchors = [
    "#sec-overview", "#sec-films", "#sec-series", "#sec-music-wrap",
    "#sec-books", "#sec-podcasts", "#sec-comics", "#sec-youtube",
    "#sec-tiktok", "#sec-patterns", "#sec-recs",
  ];
  for (const anchor of expectedAnchors) {
    await expect(page.locator(`a.snav-link[href="${anchor}"]`)).toBeVisible();
  }
});

test("all section anchor targets exist in DOM", async ({ page }) => {
  await page.goto("/");
  const sectionIds = [
    "sec-overview", "sec-films", "sec-series", "sec-music-wrap",
    "sec-books", "sec-podcasts", "sec-comics", "sec-youtube",
    "sec-tiktok", "sec-patterns", "sec-recs",
  ];
  for (const id of sectionIds) {
    const count = await page.locator(`#${id}`).count();
    expect(count, `#${id} missing from DOM`).toBeGreaterThan(0);
  }
});

test("sticky search bar stays visible after scrolling 800px", async ({
  page,
}) => {
  await page.goto("/");
  await page.evaluate(() => window.scrollTo({ top: 800, behavior: "instant" }));
  const bar = page.locator("#search-bar");
  await expect(bar).toBeVisible();
  const box = await bar.boundingBox();
  expect(box!.y).toBeLessThanOrEqual(5); // within 5px of viewport top
});

// ── Search ─────────────────────────────────────────────────────────────────

test("search input accepts text and search panel appears", async ({ page }) => {
  await page.goto("/");
  await page.fill("#search-input", "Inception");
  await expect(page.locator("#search-input")).toHaveValue("Inception");
  await page.click("#search-btn");
  await expect(page.locator("#search-panel")).toBeVisible();
});

test("search type dropdown has all expected media type options", async ({
  page,
}) => {
  await page.goto("/");
  const values = await page.locator("#search-type option").evaluateAll(
    (opts) => opts.map((o) => (o as HTMLOptionElement).value)
  );
  for (const v of ["all", "book", "film", "tv", "music", "podcast"]) {
    expect(values, `missing option: ${v}`).toContain(v);
  }
});

// ── Detail panel ───────────────────────────────────────────────────────────

test("detail overlay starts hidden", async ({ page }) => {
  await page.goto("/");
  const overlay = page.locator("#detail-overlay");
  await expect(overlay).not.toHaveClass(/open/);
});

test("Esc key closes detail overlay when open", async ({ page }) => {
  await page.goto("/");
  // Open programmatically (the function is global)
  await page.evaluate(() => (window as any).openDetailOverlay("Test"));
  await expect(page.locator("#detail-overlay")).toHaveClass(/open/);
  await page.keyboard.press("Escape");
  await expect(page.locator("#detail-overlay")).not.toHaveClass(/open/);
});

test("detail panel closes and body scroll is restored", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => (window as any).openDetailOverlay("Test"));
  await expect(page.locator("#detail-overlay")).toHaveClass(/open/);
  await page.keyboard.press("Escape");
  const overflow = await page.evaluate(() => document.body.style.overflow);
  expect(overflow).not.toBe("hidden");
});

// ── Collapsibles ───────────────────────────────────────────────────────────

test("collapsible panels are initialised collapsed when content is long", async ({
  page,
}) => {
  await page.goto("/");
  // At least one collapsible should be in collapsed state after init
  const collapsed = await page.locator(".collapsible.collapsed").count();
  expect(collapsed).toBeGreaterThan(0);
});

test("collapsible See-more button expands a panel", async ({ page }) => {
  await page.goto("/");
  const btn = page.locator(".collapsible-btn").first();
  // Only interact if the button is visible (collapsed panel)
  const visible = await btn.isVisible();
  if (!visible) test.skip();
  await btn.click();
  // After expanding, the collapsed class should be removed from its parent
  const parent = btn.locator("..");
  await expect(parent).not.toHaveClass(/collapsed/);
});

// ── Recommendations — product health evals ────────────────────────────────
//
// These evals define the minimum viable recommendation catalogue.
// They will FAIL if the Supabase recs table is not sufficiently seeded.
// Target: ≥ 50 total, ≥ 20 per primary medium.
// Current state: 80 total but only books (38) meet the per-medium floor.
// Failing mediums: film (11), music (15), podcast (10), tv_show (6).

test("recommendations: total count ≥ 50", async ({ page }) => {
  await page.goto("/");
  const total = await page.locator(".rec-card").count();
  expect(
    total,
    `Only ${total} rec cards found — need at least 50. Seed more recommendations.`
  ).toBeGreaterThanOrEqual(50);
});

test("recommendations: books ≥ 20", async ({ page }) => {
  await page.goto("/");
  const count = await page.locator('.rec-card[data-type="book"]').count();
  expect(
    count,
    `Book recs: ${count} — need at least 20`
  ).toBeGreaterThanOrEqual(20);
});

test("recommendations: films ≥ 20", async ({ page }) => {
  await page.goto("/");
  const count = await page.locator('.rec-card[data-type="film"]').count();
  expect(
    count,
    `Film recs: ${count} — need at least 20. Currently ${count}. Regenerate profile with more film picks.`
  ).toBeGreaterThanOrEqual(20);
});

test("recommendations: music ≥ 20", async ({ page }) => {
  await page.goto("/");
  const count = await page.locator('.rec-card[data-type="music"]').count();
  expect(
    count,
    `Music recs: ${count} — need at least 20`
  ).toBeGreaterThanOrEqual(20);
});

test("recommendations: TV shows ≥ 20", async ({ page }) => {
  await page.goto("/");
  const count = await page.locator('.rec-card[data-type="tv"]').count();
  expect(
    count,
    `TV recs: ${count} — need at least 20`
  ).toBeGreaterThanOrEqual(20);
});

test("recommendations: podcasts ≥ 20", async ({ page }) => {
  await page.goto("/");
  const count = await page.locator('.rec-card[data-type="podcast"]').count();
  expect(
    count,
    `Podcast recs: ${count} — need at least 20`
  ).toBeGreaterThanOrEqual(20);
});

test("recommendations: no duplicate titles", async ({ page }) => {
  await page.goto("/");
  const titles = await page.locator(".rec-card strong").evaluateAll(
    (els) => els.map((el) => el.textContent?.trim().toLowerCase() ?? "")
  );
  const seen = new Set<string>();
  const dupes: string[] = [];
  for (const t of titles) {
    if (seen.has(t)) dupes.push(t);
    seen.add(t);
  }
  expect(dupes, `Duplicate rec titles: ${dupes.join(", ")}`).toHaveLength(0);
});

test("to-read queue: no duplicate titles", async ({ page }) => {
  await page.goto("/");
  const rows = page.locator("#sec-books table tr td:first-child");
  const count = await rows.count();
  const titles: string[] = [];
  for (let i = 0; i < count; i++) {
    const text = await rows.nth(i).textContent();
    titles.push(text?.trim().toLowerCase() ?? "");
  }
  const seen = new Set<string>();
  const dupes: string[] = [];
  for (const t of titles.filter(Boolean)) {
    if (seen.has(t)) dupes.push(t);
    seen.add(t);
  }
  expect(dupes, `Duplicate to-read titles: ${dupes.join(", ")}`).toHaveLength(0);
});

// ── brain.html ────────────────────────────────────────────────────────────

test("brain page loads with correct title and map container", async ({
  page,
}) => {
  await page.goto("/brain");
  await expect(page).toHaveTitle(/Map of Waldo/);
  await expect(page.locator("#map-outer")).toBeVisible();
  await expect(page.locator("#map-svg")).toBeVisible();
});

test("brain page zone names are rendered in SVG", async ({ page }) => {
  await page.goto("/brain");
  // Zone names are injected by build_brain.py — skip if brain_data.json not built
  const hasData = await page.locator(".zone-name").count();
  if (hasData === 0) {
    test.skip(true, "brain_data.json not built — run build_brain.py first");
  }
  expect(hasData).toBeGreaterThan(0);
});
