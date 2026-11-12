import { defineConfig } from "@playwright/test";

const rawPort = process.env.KURAFOLIO_E2E_PORT ?? "8765";
const port = Number(rawPort);
if (/[^0-9]/.test(rawPort) || port < 1 || port > 65535) {
  throw new Error("KURAFOLIO_E2E_PORT must be an integer from 1 to 65535");
}
const origin = new URL(`http://localhost:${port}`).origin;

export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  fullyParallel: false,
  timeout: 90000,
  use: {
    reducedMotion: "reduce",
    ...(process.env.KURAFOLIO_BROWSER_CHANNEL
      ? { channel: process.env.KURAFOLIO_BROWSER_CHANNEL }
      : {}),
    baseURL: origin,
    trace: "off",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `${JSON.stringify(process.env.KURAFOLIO_TEST_PYTHON ?? "python3")} ../scripts/web_browser_fixture.py`,
    env: { KURAFOLIO_E2E_PORT: String(port) },
    url: `${origin}/healthz`,
    reuseExistingServer: false,
    timeout: 120000,
  },
});
