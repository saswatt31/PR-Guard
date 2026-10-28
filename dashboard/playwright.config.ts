import { defineConfig, devices } from "@playwright/test";

const DASHBOARD_PORT = 3100;
const MOCK_API_PORT = 4100;

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["**/demo/**"],
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${DASHBOARD_PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "node e2e/mock-api.mjs",
      url: `http://127.0.0.1:${MOCK_API_PORT}/api/stats`,
      env: { MOCK_API_PORT: String(MOCK_API_PORT) },
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: "npm run start",
      url: `http://127.0.0.1:${DASHBOARD_PORT}`,
      env: {
        PRGUARD_API_URL: `http://127.0.0.1:${MOCK_API_PORT}`,
        PORT: String(DASHBOARD_PORT),
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
