// Observatory regression checks — C1-C15 per OBS-041 plan
// Run against live:  OBS_BASE_URL=https://observatory.vanderlore.de OBS_AUTH_USER=waldo OBS_AUTH_PASS=odlaw npx playwright test
// Run against local: npx playwright test
import { test, expect, Page } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";
import { fileURLToPath } from "url";
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ── screenshot helper ──────────────────────────────────────────────────────────
const ITER = process.env.OBS_ITER ?? "0";
const ARTIFACTS = path.join(__dirname, "..", "artifacts", `iter-${ITER}`);
async function snap(page: Page, name: string) {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  await page.screenshot({ path: path.join(ARTIFACTS, `${name}.png`), fullPage: false });
}

// ── C1: No sideways scroll at 375, 768, 1440 ──────────────────────────────────
for (const [pageSlug, route] of [["dashboard", "/"], ["brain", "/brain"], ["ask", "/ask"]] as [string, string][]) {
  for (const width of [375, 768, 1440]) {
    test(`// Regression OBS-041: B1/B10/B11 — C1 no sideways scroll on ${pageSlug} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      await snap(page, `c1-${pageSlug}-${width}`);
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `${pageSlug} at ${width}px scrollWidth=${scrollWidth} > clientWidth=${clientWidth}`).toBeLessThanOrEqual(clientWidth + 1);
    });
  }
}

// ── C2: Logo ≥16px from edge; nav contents within 2px of .wrap at 1440 ─────────
test("// Regression OBS-041: B1/B2 — C2 logo position and nav width at 1440px", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await snap(page, "c2-nav-1440");

  // Logo must be ≥16px from left edge
  const logoBox = await page.locator("#primary-nav .pnav-logo").first().boundingBox();
  expect(logoBox, "pnav-logo not found").not.toBeNull();
  expect(logoBox!.x, `Logo x=${logoBox!.x} < 16`).toBeGreaterThanOrEqual(16);

  // .wrap must exist and nav content area must align with .wrap content area (both have 24px padding)
  const wrapBox = await page.locator(".wrap").first().boundingBox();
  expect(wrapBox, ".wrap not found").not.toBeNull();
  const wrapPaddingLeft = await page.locator(".wrap").first().evaluate(el => parseFloat(getComputedStyle(el).paddingLeft));
  const navLinksLeft = await page.locator("#primary-nav .pnav-logo").first().boundingBox();
  const wrapContentLeft = wrapBox!.x + wrapPaddingLeft;
  expect(Math.abs(navLinksLeft!.x - wrapContentLeft), "nav content left edge differs from .wrap content left by >2px").toBeLessThanOrEqual(2);
});

// ── C3: Exactly one gold line in the header ───────────────────────────────────
test("// Regression OBS-041: B3 — C3 exactly one gold border-bottom in header", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await snap(page, "c3-gold-borders");

  // Count gold border-bottom elements visible in the top 120px of the page
  const goldCount = await page.evaluate(() => {
    const elements = Array.from(document.querySelectorAll("*"));
    let count = 0;
    for (const el of elements) {
      const box = (el as HTMLElement).getBoundingClientRect();
      // skip display:none or zero-size elements
      if (box.width === 0 && box.height === 0) continue;
      if (box.top > 120) continue;
      const style = getComputedStyle(el);
      const bb = style.borderBottomColor;
      // #d4920a = rgb(212, 146, 10) — must also have a visible border (style != none, width > 0)
      if (
        (bb.includes("212, 146, 10") || bb.includes("212,146,10")) &&
        style.borderBottomStyle !== "none" &&
        parseFloat(style.borderBottomWidth) > 0
      ) count++;
    }
    return count;
  });
  expect(goldCount, `Expected 1 gold border-bottom in header, found ${goldCount}`).toBe(1);
});

// ── C4: Nothing highlighted at top; BOOKS highlighted after scroll ─────────────
test("// Regression OBS-041: B4 — C4 no section-nav item active at page load", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await snap(page, "c4-no-active-on-load");

  const activeLinks = await page.locator(".snav-link.active").count();
  expect(activeLinks, `Section nav has ${activeLinks} active links at page load (expected 0)`).toBe(0);
});

test("// Regression OBS-041: B4 — C4 BOOKS highlighted after scroll to #sec-books", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await page.evaluate(() => {
    const el = document.getElementById("sec-books");
    if (el) el.scrollIntoView({ behavior: "instant" });
  });
  await page.waitForTimeout(300);
  await snap(page, "c4-books-active-after-scroll");

  const booksActive = await page.locator('.snav-link[href="#sec-books"].active').count();
  expect(booksActive, "BOOKS snav link not active after scrolling to #sec-books").toBeGreaterThan(0);
});

// ── C5: /api/recs exists, returns total, 15 cards, filters work ──────────────
test("// Regression OBS-041: B5 — C5 /api/recs returns 200 with items", async ({ page }) => {
  const resp = await page.request.get("/api/recs");
  expect(resp.status(), `/api/recs returned ${resp.status()}`).toBe(200);
  const body = await resp.json();
  expect(typeof body.total, "body.total missing").toBe("number");
  expect(body.total, "total is 0").toBeGreaterThan(0);
  expect(Array.isArray(body.items), "body.items is not array").toBe(true);
  expect(body.items.length, "items.length is not 15").toBe(15);
});

test("// Regression OBS-041: B5 — C5 /picks page shows 15 cards", async ({ page }) => {
  await page.goto("/picks");
  await page.waitForLoadState("networkidle");
  await snap(page, "c5-picks-page");
  const cards = await page.locator(".rec-card").count();
  expect(cards, `picks page shows ${cards} cards, expected 15`).toBe(15);
});

// ── C6: No score above 100% ───────────────────────────────────────────────────
// Checks /picks when it exists; falls back to dashboard rec cards (B6 is in build_dashboard.py).
test("// Regression OBS-041: B6 — C6 no rec score above 100%", async ({ page }) => {
  // After P3b: check /picks. Until then: check dashboard rec section.
  const picksResp = await page.request.get("/picks");
  const route = picksResp.status() === 200 ? "/picks" : "/";
  await page.goto(route);
  await page.waitForLoadState("networkidle");
  await snap(page, "c6-scores");

  const badScores = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll(".rec-card"));
    const bad: string[] = [];
    for (const card of cards) {
      const score = card.querySelector(".rec-conf, .rec-score, [data-score], .score");
      if (!score) continue;
      const txt = score.textContent ?? "";
      const m = txt.match(/(\d+)%/);
      if (m && parseInt(m[1]) > 100) bad.push(txt.trim());
    }
    return bad;
  });
  expect(badScores, `Scores over 100%: ${badScores.join(", ")}`).toHaveLength(0);
});

// ── C7: No "None" warnings, no doubled ⚠️ ────────────────────────────────────
// Checks /picks when it exists; falls back to dashboard (B7 is in build_dashboard.py).
test("// Regression OBS-041: B7 — C7 no 'None' warnings in picks", async ({ page }) => {
  const picksResp = await page.request.get("/picks");
  const route = picksResp.status() === 200 ? "/picks" : "/";
  await page.goto(route);
  await page.waitForLoadState("networkidle");

  const noneWarnings = await page.evaluate(() => {
    return document.body.innerText.includes("⚠️ None") || document.body.innerText.includes("⚠ None");
  });
  expect(noneWarnings, "Found '⚠️ None' warning text in picks/dashboard").toBe(false);
});

test("// Regression OBS-041: B7 — C7 no doubled ⚠️ in picks", async ({ page }) => {
  const picksResp = await page.request.get("/picks");
  const route = picksResp.status() === 200 ? "/picks" : "/";
  await page.goto(route);
  await page.waitForLoadState("networkidle");

  const doubled = await page.evaluate(() => {
    return document.body.innerText.includes("⚠️ ⚠️") || document.body.innerText.includes("⚠ ⚠");
  });
  expect(doubled, "Found doubled ⚠️⚠️ warning text in picks/dashboard").toBe(false);
});

// ── C8: Dashboard has no watchlist section ────────────────────────────────────
test("// Regression OBS-041: B8 — C8 dashboard has no watchlist panel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await snap(page, "c8-no-watchlist");

  const watchlistPanel = await page.locator("#watchlist-panel, #sec-recs").count();
  expect(watchlistPanel, `Dashboard still has ${watchlistPanel} watchlist/recs panel(s) — should be 0`).toBe(0);
});

// ── C13: Favicon returns 200 ──────────────────────────────────────────────────
test("// Regression OBS-041: B16 — C13 favicon.ico returns 200", async ({ page }) => {
  const resp = await page.request.get("/favicon.ico");
  expect(resp.status(), `/favicon.ico returned ${resp.status()}`).toBe(200);
});
