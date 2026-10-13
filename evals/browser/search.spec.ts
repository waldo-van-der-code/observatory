import { test, expect } from "@playwright/test";

// Regression OBS: Open Library latency spikes made "flybot" return no results.
test("searching a book title returns results in the UI", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await page.fill("#nav-search-input", "flybot");
  await page.selectOption("#nav-search-type", "book");
  await page.click("#nav-search-btn");
  await expect(page.locator("#search-status")).toContainText(/\d+ results? for "flybot"/, { timeout: 40_000 });
  await expect(page.locator("#search-results-list")).toContainText(/Flybot/i);
  await page.screenshot({ path: "test-results/flybot-search.png" });
});
