/** Capture only the disposable synthetic browser fixture, never an external instance. */
import { chromium, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

if (
  process.argv
    .slice(2)
    .some(
      (argument) => !["--first-run-only", "--overview-only"].includes(argument),
    )
)
  throw new Error(
    "Only --first-run-only or --overview-only is supported; external inputs are forbidden",
  );
const firstRunOnly = process.argv.includes("--first-run-only");
const overviewOnly = process.argv.includes("--overview-only");
if (firstRunOnly && overviewOnly)
  throw new Error("Capture modes are mutually exclusive");
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
    viewport: { width: 1440, height: 1200 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    colorScheme: "light",
    timezoneId: "America/Toronto",
  });
  const failures = [];
  const external = [];
  const files = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.protocol === "data:" || url.origin === origin)
      return route.continue();
    external.push(url.origin);
    return route.abort();
  });
  await mkdir(output, { recursive: true });
  async function capture(
    filename,
    signedIn = true,
    scrollTop = true,
    expectedPortfolio = "SYNTHETIC demonstration",
  ) {
    if (new URL(page.url()).origin !== origin)
      throw new Error("Unexpected capture origin");
    if (signedIn) {
      const selected = await page
        .getByRole("combobox", { name: "Portfolio", exact: true })
        .locator("option:checked")
        .textContent();
      if (
        selected !== expectedPortfolio ||
        !["SYNTHETIC demonstration", "Empty synthetic portfolio"].includes(
          expectedPortfolio,
        )
      )
        throw new Error("Unexpected portfolio; refusing to capture");
    }
    // Login and password-change screenshots must contain no entered credentials.
    for (const field of await page.locator('input[type="password"]').all())
      if (await field.inputValue())
        throw new Error("Entered credential present; refusing to capture");
    await page.evaluate(async (top) => {
      await document.fonts.ready;
      if (top) window.scrollTo(0, 0);
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }, scrollTop);
    await page.screenshot({
      path: path.join(output, filename),
      fullPage:
        filename === "web-overview.png" || filename === "web-overview-dark.png",
      animations: "disabled",
    });
    files.push(filename);
  }
  await page.goto(origin);
  await page.getByRole("heading", { name: "Sign in", exact: true }).waitFor();
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page
    .getByRole("heading", { name: "CA$1,930.00", exact: true })
    .waitFor();
  await page
    .getByRole("combobox", { name: "Appearance", exact: true })
    .selectOption("light");
  await page
    .getByRole("img", { name: "Value over recorded observations", exact: true })
    .waitFor();
  if (!firstRunOnly) {
    await expect(page.locator(".evidence-status")).toBeVisible();
    await expect(page.locator(".processing-status")).toHaveCount(0);
    await capture("web-overview.png");
    await page
      .getByRole("combobox", { name: "Appearance", exact: true })
      .selectOption("dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await capture("web-overview-dark.png");
    await page
      .getByRole("combobox", { name: "Appearance", exact: true })
      .selectOption("light");
    const pages = overviewOnly
      ? []
      : [
          ["Holdings", "web-holdings.png"],
          ["Exposure", "web-exposure.png"],
          ["History", "web-history.png"],
          ["Bitcoin & flows", "web-bitcoin.png"],
          ["Import & jobs", "web-imports.png"],
          ["Financial records", "web-records.png"],
          ["Analysis reports", "web-reports.png"],
          ["Settings", "web-settings.png"],
        ];
    for (const [title, filename] of pages) {
      await page.getByRole("link", { name: title, exact: true }).click();
      await page.getByRole("heading", { name: title, level: 1 }).waitFor();
      if (title === "Holdings") {
        await page.getByRole("table").first().waitFor();
        await page.getByText("VEQT", { exact: true }).first().waitFor();
      } else if (title === "Exposure") {
        await page
          .getByRole("cell", {
            name: "Synthetic Alpha Corporation",
            exact: true,
          })
          .waitFor();
        await page
          .getByRole("img", { name: "Sector · CAD", exact: true })
          .waitFor();
      } else if (title === "History") {
        await page
          .getByRole("img", {
            name: "Value over recorded observations",
            exact: true,
          })
          .waitFor();
      } else if (title === "Bitcoin & flows") {
        await page.getByRole("table").first().waitFor();
      } else if (title === "Import & jobs") {
        await page
          .locator('input[name="csv"]')
          .setInputFiles([
            path.join(root, "examples/data/wealthsimple-holdings.csv"),
            path.join(root, "examples/data/bull-orders.csv"),
          ]);
        await page
          .getByRole("button", { name: "Upload & preview", exact: true })
          .waitFor();
      } else if (title === "Financial records") {
        await page
          .getByLabel("BTC equivalent quantity", { exact: true })
          .fill("0.00950000");
        await page
          .getByLabel("Balance observed at (with UTC offset)", { exact: true })
          .fill("2024-02-02T12:00:00-05:00");
        await page
          .getByLabel("Evidence source", { exact: true })
          .fill("Synthetic wallet declaration");
      } else if (title === "Analysis reports") {
        await page.getByRole("article", { name: "Read the report" }).waitFor();
        await expect(
          page
            .getByRole("navigation", { name: "Contents", exact: true })
            .getByRole("link")
            .first(),
        ).toBeVisible();
      } else if (title === "Settings") {
        await page.locator('select[name="locale"]').waitFor();
      }
      await capture(filename);
      if (title === "Analysis reports") {
        await page
          .getByRole("article", { name: "Read the report" })
          .evaluate((element) => element.scrollIntoView({ block: "start" }));
        await capture("web-report-reader.png", true, false);
      }
    }
  }
  if (!overviewOnly) {
    await page
      .getByRole("combobox", { name: "Appearance", exact: true })
      .selectOption("light");
    await page
      .getByRole("combobox", { name: "Portfolio", exact: true })
      .selectOption({ label: "Empty synthetic portfolio" });
    await page
      .getByRole("heading", {
        name: "Start with your first observation",
        exact: true,
      })
      .waitFor();
    await capture(
      "web-getting-started.png",
      true,
      true,
      "Empty synthetic portfolio",
    );
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page.getByRole("heading", { name: "Sign in", exact: true }).waitFor();
    if (!firstRunOnly) await capture("web-login.png", false);
  }
  if (failures.length || external.length)
    throw new Error(
      "Browser errors or external requests occurred during capture",
    );
  const evidence = {
    fixture: "scripts/web_browser_fixture.py",
    source: "examples/demo.py and examples/data only",
    portfolios: firstRunOnly
      ? ["Empty synthetic portfolio"]
      : overviewOnly
        ? ["SYNTHETIC demonstration"]
        : ["SYNTHETIC demonstration", "Empty synthetic portfolio"],
    valuation: firstRunOnly ? null : "2024-02-01T10:00:00-05:00",
    synthetic: true,
    browser: browser.version(),
    viewport: { width: 1440, height: 1200 },
    files,
    input_examples: firstRunOnly
      ? "Empty portfolio guidance only; no uploads or declarations"
      : overviewOnly
        ? "Read-only synthetic overview; no uploads or declarations"
        : "Public example CSVs and an unsaved invented wallet declaration; no import or record confirmation",
    external_requests: external.length,
    browser_errors: failures.length,
  };
  const review = path.join(root, "work/readme-capture");
  await mkdir(review, { recursive: true });
  await writeFile(
    path.join(
      review,
      firstRunOnly
        ? "first-run-provenance.json"
        : overviewOnly
          ? "overview-provenance.json"
          : "provenance.json",
    ),
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
