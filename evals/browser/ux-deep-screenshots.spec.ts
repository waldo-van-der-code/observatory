import { test, chromium } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE = process.env.OBS_BASE_URL || 'https://observatory.vanderlore.de';
const USER = process.env.OBS_AUTH_USER || 'waldo';
const PASS = process.env.OBS_AUTH_PASS!;
const OUT = path.join(__dirname, '..', 'artifacts', 'ux-screenshots');

test('capture all pages at 375 and 1440', async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();

  const pages = [
    { path: '/', name: 'dashboard' },
    { path: '/picks', name: 'picks' },
    { path: '/brain', name: 'brain' },
    { path: '/ask', name: 'ask' },
  ];

  for (const vp of [{ w: 375, h: 812 }, { w: 1440, h: 900 }]) {
    const ctx = await browser.newContext({
      httpCredentials: { username: USER, password: PASS },
      viewport: { width: vp.w, height: vp.h },
    });
    const page = await ctx.newPage();

    for (const pg of pages) {
      await page.goto(BASE + pg.path, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${OUT}/${pg.name}-${vp.w}.png`, fullPage: true });
      console.log(`captured ${pg.name} @ ${vp.w}px`);
    }
    await ctx.close();
  }

  // Task walkthrough screenshots
  const ctx2 = await browser.newContext({
    httpCredentials: { username: USER, password: PASS },
    viewport: { width: 1440, height: 900 },
  });
  const page2 = await ctx2.newPage();

  // Task 1: picks → filter Film → click first card → detail panel
  await page2.goto(BASE + '/picks', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(800);
  await page2.click('button[data-media="film"]');
  await page2.waitForTimeout(600);
  await page2.screenshot({ path: `${OUT}/task1-picks-film-filter.png`, fullPage: false });
  const firstCard = page2.locator('.rec-card').first();
  await firstCard.click();
  await page2.waitForTimeout(1000);
  await page2.screenshot({ path: `${OUT}/task1-detail-open.png`, fullPage: false });

  // Task 2: dismiss first card
  await page2.goto(BASE + '/picks', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(800);
  const dismissBtn = page2.locator('.action-btn.dismiss').first();
  await dismissBtn.click();
  await page2.waitForTimeout(500);
  await page2.screenshot({ path: `${OUT}/task2-after-dismiss.png`, fullPage: false });

  // Task 3: filter by Book
  await page2.goto(BASE + '/picks', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(800);
  await page2.click('button[data-media="book"]');
  await page2.waitForTimeout(600);
  await page2.screenshot({ path: `${OUT}/task3-book-filter.png`, fullPage: false });

  // Task 4: dashboard search
  await page2.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page2.waitForTimeout(800);
  await page2.fill('#search-input', 'Dune');
  await page2.waitForTimeout(1200);
  await page2.screenshot({ path: `${OUT}/task4-search-dune.png`, fullPage: false });

  await ctx2.close();
  await browser.close();
});
