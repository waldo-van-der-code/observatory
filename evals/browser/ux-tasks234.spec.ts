import { test, chromium } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE = process.env.OBS_BASE_URL!;
const USER = process.env.OBS_AUTH_USER!;
const PASS = process.env.OBS_AUTH_PASS!;
const OUT = path.join(__dirname, '..', 'artifacts', 'ux-screenshots');

test('task walkthroughs 2-4', async ({ browser }) => {
  fs.mkdirSync(OUT, { recursive: true });
  const ctx = await browser.newContext({
    httpCredentials: { username: USER, password: PASS },
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();
  // Task 2: dismiss
  await page.goto(BASE + '/picks', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const dismissBtn = page.locator('.action-btn.dismiss').first();
  await dismissBtn.click();
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/task2-after-dismiss.png`, fullPage: false });
  // Task 3: book filter
  await page.goto(BASE + '/picks', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.click('button[data-media="book"]');
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/task3-book-filter.png`, fullPage: false });
  // Task 4: search
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const searchInput = page.locator('#search-input');
  await searchInput.fill('Dune');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/task4-search-dune.png`, fullPage: false });
  await ctx.close();
});
