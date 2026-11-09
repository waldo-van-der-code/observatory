import { test, expect, Page } from '@playwright/test';

// These scenarios write data and must only target the disposable local server.
test.skip(process.env.OBS_ORACLE_LOCAL !== '1', 'Requires OBS_ORACLE_LOCAL=1 and oracle_local_server.py');
test.use({ baseURL: process.env.OBS_BASE_URL ?? 'http://127.0.0.1:8011' });

async function openDrawer(page: Page, width: number) {
  if (width <= 700) await page.getByRole('button', { name: 'Conversations', exact: true }).click();
}

for (const width of [1280, 390]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 844 } });
    test(`Regression OBS-051: sessions continue, rename, confirm and undo at ${width}px`, async ({ page }) => {
      await page.goto('/ask?new=1');
      await expect(page.locator('#input')).toBeFocused();
      await openDrawer(page, width);
      await expect(page.locator('#sb-list')).toContainText('Recent films conversation');
      await expect(page.locator('#sb-list')).toContainText('Older books conversation');
      await page.getByRole('button', { name: '+ New', exact: true }).click();
      await expect(page.locator('#suggestions')).toBeVisible();
      await page.locator('#input').fill('rate pantheon 4 stars');
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      await expect(page.locator('.bubble.bot').last()).toContainText('Pantheon');
      await expect(page).toHaveURL(/\?s=\d+$/);
      const sid = new URL(page.url()).searchParams.get('s');
      await expect(page.locator('#session-title')).toHaveText('Pantheon praise', { timeout: 15_000 });
      await expect(page.locator('.bubble.bot img')).toHaveCount(0);
      await page.reload();
      await expect(page.locator('.bubble.user')).toContainText('rate pantheon 4 stars');
      await expect(page.locator('.bubble.bot')).toContainText('Pantheon');
      await expect(page.locator('#main-head')).toBeHidden();
      await expect(page.locator('#suggestions')).toBeHidden();
      const request = page.waitForRequest(r => r.url().endsWith('/api/ask') && r.method() === 'POST');
      await page.locator('#input').fill('What should I try next?');
      await page.locator('#input').press('Enter');
      expect((await request).postDataJSON()).toEqual({ question: 'What should I try next?', session_id: Number(sid) });
      await expect(page.locator('.bubble.user')).toHaveCount(2);
      await expect(page.locator('#send-btn')).toBeEnabled();
      await page.getByRole('button', { name: 'Rename conversation' }).click();
      const title = `My Pantheon notes ${width}`;
      await page.getByRole('textbox', { name: 'Conversation title' }).fill(title);
      await page.getByRole('textbox', { name: 'Conversation title' }).press('Enter');
      await expect(page.locator('#session-title')).toHaveText(title);
      await page.reload();
      await expect(page.locator('#session-title')).toHaveText(title);
      const card = page.locator('.action-card').first();
      await expect(card).toContainText('Not saved', { timeout: 20_000 });
      await expect(card).not.toContainText('security review:');
      await card.getByRole('button', { name: 'Save anyway' }).click();
      await expect(card).toContainText('Saved');
      await card.getByRole('button', { name: 'Undo', exact: true }).click();
      await expect(card).toContainText('Undone');
      await openDrawer(page, width);
      await page.locator('.sb-item').filter({ hasText: 'Older books conversation' }).click();
      await expect(page.locator('.bubble.user')).toHaveText('Older books conversation');
      if (width <= 700) {
        await expect(page.locator('#sidebar')).toBeHidden();
        await openDrawer(page, width);
        await page.keyboard.press('Escape');
        await expect(page.locator('#sidebar')).toBeHidden();
      }
      await page.goBack();
      await expect(page.locator('#session-title')).toHaveText(title);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: `/tmp/obs-051-${width}.png`, fullPage: true });
    });
  });
}

test('Regression OBS-051: home entry opens a focused new conversation', async ({ page, request }) => {
  const home = await request.get('/');
  test.skip(home.status() === 404, 'No generated dashboard is available');
  expect(home.ok()).toBeTruthy();
  await page.goto('/');
  await page.locator('a.oracle-entry').click();
  await expect(page).toHaveURL(/\/ask\?new=1$/);
  await expect(page.locator('#input')).toBeFocused();
});

test('Regression OBS-051: late answers and slow loads stay in their conversation', async ({ page }) => {
  await page.goto('/ask?new=1');
  await expect(page.locator('#sb-list')).toContainText('Older books conversation');
  const initialCount = await page.locator('.sb-item').count();
  let releaseAnswer!: () => void;
  let answerReady!: () => void;
  const answerGate = new Promise<void>(resolve => { releaseAnswer = resolve; });
  const ready = new Promise<void>(resolve => { answerReady = resolve; });
  await page.route('**/api/ask', async route => {
    const response = await route.fetch();
    answerReady();
    await answerGate;
    await route.fulfill({ response });
  }, { times: 1 });
  await page.locator('#input').fill('A delayed answer');
  await page.locator('#input').press('Enter');
  await ready;
  await expect(page.locator('#send-btn')).toBeDisabled();
  await page.getByRole('button', { name: '+ New', exact: true }).click();
  await expect(page.locator('#send-btn')).toBeEnabled();
  releaseAnswer();
  await expect(page.locator('.sb-item')).toHaveCount(initialCount + 1);
  await expect(page.locator('.bubble.user')).toHaveCount(0);
  await expect(page.locator('#suggestions')).toBeVisible();
  await expect(page).toHaveURL(/\/ask\?new=1$/);

  let releaseLoad!: () => void;
  let loadReady!: () => void;
  const loadGate = new Promise<void>(resolve => { releaseLoad = resolve; });
  const loading = new Promise<void>(resolve => { loadReady = resolve; });
  await page.route('**/api/oracle/sessions/*', async route => {
    const response = await route.fetch();
    loadReady();
    await loadGate;
    await route.fulfill({ response });
  }, { times: 1 });
  await page.locator('.sb-item').filter({ hasText: 'Older books conversation' }).click();
  await loading;
  await page.locator('.sb-item').filter({ hasText: 'Recent films conversation' }).click();
  await expect(page.locator('.bubble.user')).toHaveText('Recent films conversation');
  const lateLoad = page.waitForResponse(response => /\/api\/oracle\/sessions\/\d+$/.test(new URL(response.url()).pathname));
  releaseLoad();
  await (await lateLoad).finished();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await expect(page.locator('.bubble.user')).toHaveText('Recent films conversation');
  await expect(page.locator('#session-title')).toHaveText('Recent films conversation');
});

test('Regression OBS-051: unknown sessions, rename errors and narrow keyboard space', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await page.goto('/ask?s=99999999');
  await expect(page.locator('#session-note')).toContainText('could not be found');
  await expect(page).toHaveURL(/\/ask$/);
  await expect(page.locator('#suggestions')).toBeVisible();
  await page.setViewportSize({ width: 360, height: 350 });
  await page.locator('#input').focus();
  const inputBox = await page.locator('#input').boundingBox();
  expect(inputBox).not.toBeNull();
  expect(inputBox!.y).toBeGreaterThanOrEqual(0);
  expect(inputBox!.y + inputBox!.height).toBeLessThanOrEqual(350);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.setViewportSize({ width: 360, height: 640 });
  await openDrawer(page, 360);
  await page.locator('.sb-item').filter({ hasText: 'Older books conversation' }).click();
  await page.getByRole('button', { name: 'Rename conversation' }).click();
  await page.getByRole('textbox', { name: 'Conversation title' }).fill('Cancelled title');
  await page.getByRole('textbox', { name: 'Conversation title' }).press('Escape');
  await expect(page.locator('#session-title')).toHaveText('Older books conversation');
  await page.route('**/api/oracle/sessions/*', route => route.request().method() === 'PATCH'
    ? route.fulfill({ status: 409, json: { detail: 'Rename refused by test server' } })
    : route.continue());
  await page.getByRole('button', { name: 'Rename conversation' }).click();
  await page.getByRole('textbox', { name: 'Conversation title' }).fill('Refused title');
  await page.getByRole('textbox', { name: 'Conversation title' }).press('Enter');
  await expect(page.locator('#rename-error')).toHaveText('Rename refused by test server');
  await expect(page.getByRole('textbox', { name: 'Conversation title' })).toBeEnabled();
});
