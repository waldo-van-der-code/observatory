import { defineConfig } from "@playwright/test";

const port = process.env.OBS_PORT ?? "8000";

export default defineConfig({
  testDir: "evals/browser",
  retries: 1,
  use: {
    baseURL: `http://localhost:${port}`,
    actionTimeout: 10_000,
  },
  reporter: [
    ["list"],
    ["json", { outputFile: "evals/raw/playwright-results.json" }],
  ],
});
