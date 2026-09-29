import { defineConfig } from "@playwright/test";

const BASE_URL = process.env.OBS_BASE_URL ?? "http://localhost:8000";
const USER = process.env.OBS_AUTH_USER ?? "";
const PASS = process.env.OBS_AUTH_PASS ?? "";

export default defineConfig({
  testDir: "evals/browser",
  retries: 0,
  use: {
    baseURL: BASE_URL,
    ...(USER ? { httpCredentials: { username: USER, password: PASS } } : {}),
    actionTimeout: 15_000,
  },
  reporter: [
    ["list"],
    ["json", { outputFile: "evals/raw/playwright-results.json" }],
  ],
});
