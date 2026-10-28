import { defineConfig, devices } from "@playwright/test";

const DASHBOARD_PORT = 3200;

/**
 * Demo-mode journey: no mock API, no FastAPI, no network backend.
 * `npm run test:e2e:demo` builds with NEXT_PUBLIC_DEMO_MODE=true first.
 */
export default defineConfig({
  testDir: "./e2e/demo",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never", outputFolder: "playwright-report-demo" }]]
    : [["list"], ["html", { open: "never", outputFolder: "playwright-report-demo" }]],
  use: {
    baseURL: `http://127.0.0.1:${DASHBOARD_PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: {
    command: "npm run start",
    url: `http://127.0.0.1:${DASHBOARD_PORT}`,
    env: {
      NEXT_PUBLIC_DEMO_MODE: "true",
      PRGUARD_API_URL: "http://127.0.0.1:9",
      PORT: String(DASHBOARD_PORT),
    },
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
