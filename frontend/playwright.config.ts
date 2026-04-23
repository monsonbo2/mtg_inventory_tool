import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:4173";
const shouldStartDevServer =
  process.env.PLAYWRIGHT_START_DEV_SERVER !== "0" && !process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./playwright",
  outputDir: "./test-results/playwright",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1080 },
      },
    },
    {
      name: "mobile-chromium",
      use: {
        ...devices["Pixel 7"],
      },
    },
  ],
  webServer: shouldStartDevServer
    ? {
        command: "npm run dev -- --host 127.0.0.1 --port 4173",
        url: baseURL,
        cwd: process.cwd(),
        reuseExistingServer: true,
        stdout: "ignore",
        stderr: "pipe",
        timeout: 120_000,
      }
    : undefined,
});
