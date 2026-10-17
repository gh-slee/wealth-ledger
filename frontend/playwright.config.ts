import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  fullyParallel: false,
  timeout: 90000,
  use: {
    reducedMotion: "reduce",
    ...(process.env.WEALTH_LEDGER_BROWSER_CHANNEL
      ? { channel: process.env.WEALTH_LEDGER_BROWSER_CHANNEL }
      : {}),
    baseURL: "http://localhost:8765",
    trace: "off",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `${JSON.stringify(process.env.WEALTH_LEDGER_TEST_PYTHON ?? "python3")} ../scripts/web_browser_fixture.py`,
    url: "http://localhost:8765/healthz",
    reuseExistingServer: false,
    timeout: 120000,
  },
});
