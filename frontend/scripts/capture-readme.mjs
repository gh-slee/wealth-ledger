/** Capture only the disposable synthetic browser fixture, never an external instance. */
import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const origin = "http://localhost:8765";
const output = path.join(root, "assets/readme");
const pause = (delay) => new Promise((resolve) => setTimeout(resolve, delay));
const listener = createServer();
// Refuse to reuse a process that could contain somebody's real portfolio.
await new Promise((resolve, reject) => {
  listener.once("error", reject);
  listener.listen(8765, "127.0.0.1", resolve);
});
await new Promise((resolve) => listener.close(resolve));
const server = spawn(
  process.env.WEALTH_LEDGER_TEST_PYTHON ?? "python3",
  [path.join(root, "scripts/web_browser_fixture.py")],
  {
    cwd: root,
    stdio: "ignore",
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  },
);
let launchError;
server.once("error", (error) => {
  launchError = error;
});
let browser;
try {
  let ready = false;
  for (let attempt = 0; attempt < 120; attempt++) {
    if (launchError) throw launchError;
    if (server.exitCode !== null)
      throw new Error("Synthetic fixture exited before readiness");
    try {
      const response = await fetch(origin + "/healthz");
      if (response.ok) {
        ready = true;
        break;
      }
    } catch {
      /* The isolated fixture is still preparing its invented reports. */
    }
    await pause(1000);
  }
  if (!ready) throw new Error("Synthetic fixture did not become ready");
  browser = await chromium.launch(
    process.env.WEALTH_LEDGER_BROWSER_CHANNEL
      ? { channel: process.env.WEALTH_LEDGER_BROWSER_CHANNEL }
      : {},
  );
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1028 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    timezoneId: "America/Toronto",
  });
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto(origin);
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page
    .getByRole("heading", { name: "CA$1,930.00", exact: true })
    .waitFor();
  const portfolio = await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .locator("option:checked")
    .textContent();
  if (portfolio !== "SYNTHETIC demonstration")
    throw new Error("Unexpected portfolio; refusing to capture");
  await page
    .getByRole("img", { name: "Value over recorded observations", exact: true })
    .waitFor();
  await page.evaluate(() => document.fonts.ready);
  await mkdir(output, { recursive: true });
  await page.screenshot({
    path: path.join(output, "web-overview.png"),
    fullPage: false,
  });
  await page.getByRole("link", { name: "Exposure", exact: true }).click();
  await page
    .getByRole("cell", { name: "Synthetic Alpha Corporation", exact: true })
    .waitFor();
  await page.getByRole("img", { name: "Sector · CAD", exact: true }).waitFor();
  await page.setViewportSize({ width: 1440, height: 1200 });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({
    path: path.join(output, "web-exposure.png"),
    fullPage: false,
  });
  if (failures.length)
    throw new Error("Browser errors occurred during capture");
  const evidence = {
    fixture: "scripts/web_browser_fixture.py",
    source: "examples/demo.py and examples/data only",
    portfolio,
    valuation: "2024-02-01T10:00:00-05:00",
    synthetic: true,
    browser: browser.version(),
    files: ["web-overview.png", "web-exposure.png"],
  };
  const review = path.join(root, "work/readme-capture");
  await mkdir(review, { recursive: true });
  await writeFile(
    path.join(review, "provenance.json"),
    JSON.stringify(evidence, null, 2) + "\n",
  );
  console.log(JSON.stringify(evidence));
} finally {
  await browser?.close();
  if (server.pid && server.exitCode === null && server.signalCode === null) {
    server.kill("SIGTERM");
    for (
      let attempt = 0;
      attempt < 100 && server.exitCode === null && server.signalCode === null;
      attempt++
    )
      await pause(100);
    if (server.exitCode === null && server.signalCode === null)
      server.kill("SIGKILL");
  }
}
