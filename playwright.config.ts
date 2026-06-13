import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./evals/browser",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ["list"],
    ["json", { outputFile: "evals/raw/playwright-results.json" }],
  ],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8000",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  // webServer is skipped when BASE_URL is set (running against live/preview URL)
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: "./run.sh --serve",
        url: "http://localhost:8000",
        reuseExistingServer: !process.env.CI,
      },
});
