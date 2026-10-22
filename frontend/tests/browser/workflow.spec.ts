import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import path from "node:path";
import { isLocalResource } from "./request-origin";
const root = path.resolve(import.meta.dirname, "../../..");
async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
}
test("frozen reports, charts, three locales, mobile, downloads and cache isolation", async ({
  page,
  baseURL,
}) => {
  const origin = new URL(baseURL!).origin;
  const external: string[] = [];
  page.on("request", (request) => {
    if (!isLocalResource(request.url(), origin)) external.push(request.url());
  });
  await login(page);
  await expect(
    page.getByRole("heading", { name: "CA$1,930.00", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Display currency", exact: true })
    .selectOption("USD");
  await expect(
    page.getByRole("heading", { name: "US$1,286.67", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Display currency", exact: true })
    .selectOption("TWD");
  await expect(
    page.getByRole("heading", { name: "NT$38,600.00", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Display currency", exact: true })
    .selectOption("CAD");
  await expect(
    page.getByRole("img", { name: "Value over recorded observations" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/overview-desktop.png",
    fullPage: true,
  });
  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  await page.getByRole("link", { name: "Holdings", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("table", { name: "Holdings", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Exposure", exact: true }).click();
  await expect(
    page.getByText("Synthetic Alpha Corporation", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Rank" })).toBeVisible();
  await page.screenshot({
    path: "test-results/exposure-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("combobox", { name: "Interface language", exact: true })
    .selectOption("zh-TW");
  await expect(
    page.getByRole("heading", { name: "組合曝險", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "介面語言", exact: true })
    .selectOption("zh-CN");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await page
    .getByRole("combobox", { name: "界面语言", exact: true })
    .selectOption("en-CA");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.screenshot({
    path: "test-results/overview-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page
    .getByRole("link", { name: "Analysis reports", exact: true })
    .click();
  const saved = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "portfolio.ods", exact: true })
    .click();
  expect((await saved).suggestedFilename()).toBe("portfolio.ods");
  const zipDownload = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download report ZIP", exact: true })
    .click();
  const bundle = await zipDownload;
  expect(bundle.suggestedFilename()).toMatch(/^report-[a-f0-9]{32}\.zip$/);
  expect(
    readFileSync((await bundle.path())!)
      .subarray(0, 2)
      .toString(),
  ).toBe("PK");
  await page.getByText("Export report data", { exact: true }).click();
  const csvDownload = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download data", exact: true })
    .click();
  const csv = await csvDownload;
  expect(readFileSync((await csv.path())!, "utf8")).toContain("market_cad");
  await page
    .getByRole("combobox", { name: "Dataset", exact: true })
    .selectOption("history");
  await page
    .getByRole("combobox", { name: "Format", exact: true })
    .selectOption("json");
  await page
    .getByLabel("From date (optional)", { exact: true })
    .fill("2099-01-01");
  const jsonDownload = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download data", exact: true })
    .click();
  const exported = JSON.parse(
    readFileSync((await (await jsonDownload).path())!, "utf8"),
  );
  expect(exported.rows).toEqual([]);
  expect(exported.dataset).toBe("history");
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
  });
  await page.screenshot({
    path: "test-results/report-exports-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .selectOption({ label: "Empty synthetic portfolio" });
  await expect(
    page.getByRole("heading", { name: "Start with your first observation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "CA$1,930.00", exact: true }),
  ).toHaveCount(0);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("table")).toHaveCount(0);
  expect(external).toEqual([]);
});
test("real CSV preview, explicit confirmation and worker report publication", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .selectOption({ label: "Empty synthetic portfolio" });
  await page.getByRole("link", { name: "Import & jobs", exact: true }).click();
  await page.getByLabel("Use parser plugins", { exact: true }).uncheck();
  // Invented unrecognized ETF/stock names avoid production issuer network calls.
  const csv = readFileSync(
    path.join(root, "examples/data/wealthsimple-holdings.csv"),
    "utf8",
  )
    .replaceAll("VEQT", "DEMO-ETF")
    .replaceAll("QQQ", "DEMO-ETF-US");
  await page.getByLabel("CSV exports", { exact: true }).setInputFiles({
    name: "synthetic.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await page.getByText("Optional reference JSON", { exact: true }).click();
  await page
    .getByLabel("Verified FX", { exact: true })
    .setInputFiles(path.join(root, "examples/data/fx.json"));
  await page
    .getByRole("button", { name: "Upload & preview", exact: true })
    .click();
  const confirm = page.getByRole("button", {
    name: "Confirm import & generate reports",
    exact: true,
  });
  await expect(confirm).toBeVisible({ timeout: 30000 });
  await confirm.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", {
      name: "Confirm import & generate reports",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.locator(".job-list").getByText("Published", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await page
    .getByRole("link", { name: "Analysis reports", exact: true })
    .click();
  for (const name of ["portfolio.ods", "report.md", "report.pdf"])
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
});
test("untrusted labels stay text and authentication expiry removes financial views", async ({
  page,
}) => {
  const view = /\/reports\/[a-f0-9]{32}\?/;
  const hostile = '<img src=x onerror="window.syntheticXss=true">';
  await page.route(view, async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.companies[0].name = hostile;
    data.dimensions.sector.rows[0].name = hostile;
    await route.fulfill({ json: data });
  });
  await login(page);
  await page.getByRole("link", { name: "Exposure", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: hostile, exact: true }),
  ).toBeVisible();
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  await page.locator(".chart").hover({ position: { x: 250, y: 45 } });
  expect(
    await page.evaluate(() => Reflect.get(window, "syntheticXss")),
  ).toBeUndefined();
  await page.unroute(view);
  await page.route(view, (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "authentication_required" } },
    }),
  );
  await page
    .getByRole("combobox", { name: "Interface language", exact: true })
    .selectOption("zh-TW");
  await expect(
    page.getByRole("heading", { name: "登入", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("table")).toHaveCount(0);
});
test("a dated BTC total can be submitted without either CSV", async ({
  page,
}) => {
  await login(page);
  await page.getByText("New portfolio", { exact: true }).click();
  await page
    .getByLabel("Name", { exact: true })
    .fill("BTC-only synthetic portfolio");
  await page
    .getByRole("button", { name: "Create portfolio", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Start with your first observation" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Import & jobs", exact: true }).click();
  await page.getByLabel("Use parser plugins", { exact: true }).uncheck();
  await page.getByLabel("BTC total (optional)", { exact: true }).fill("0.01");
  await page
    .getByLabel("Balance observed at (with UTC offset)", { exact: true })
    .fill("2024-02-01T10:00:00-05:00");
  await page
    .getByLabel("Valuation time (optional, with UTC offset)", { exact: true })
    .fill("2024-02-01T10:00:00-05:00");
  await page.getByText("Optional reference JSON", { exact: true }).click();
  await page
    .getByLabel("Verified FX", { exact: true })
    .setInputFiles(path.join(root, "examples/data/fx.json"));
  await page
    .getByLabel("Verified BTC price", { exact: true })
    .setInputFiles(path.join(root, "examples/data/btc-price.json"));
  await page
    .getByRole("button", { name: "Upload & preview", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Confirm import & generate reports",
      exact: true,
    })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", {
      name: "Confirm import & generate reports",
      exact: true,
    })
    .click();
  await expect(
    page.locator(".job-list").getByText("Published", { exact: true }),
  ).toBeVisible({ timeout: 60000 });
  await page
    .getByRole("link", { name: "Bitcoin & flows", exact: true })
    .click();
  await expect(
    page.getByText("Quantity basis: User-reported wallet total", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.locator(".source-date").getByText("Bull Bitcoin", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.locator(".source-date").getByText("Wealthsimple", { exact: true }),
  ).toHaveCount(0);
});

test("financial declarations preview, save, revise and remain isolated from frozen reports", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("navigation", { name: "Portfolio navigation", exact: true })
    .getByRole("link", { name: "Financial records", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Declarations and corrections" }),
  ).toBeVisible();
  await page
    .getByLabel("What would you like to record?")
    .selectOption("balance");
  await page
    .getByLabel("BTC equivalent quantity", { exact: true })
    .fill("0.02000000");
  await page
    .getByLabel("Balance observed at (with UTC offset)", { exact: true })
    .fill("2024-01-15T12:00:00-05:00");
  await page
    .getByLabel("Evidence source", { exact: true })
    .fill("Synthetic browser wallet");
  await page
    .getByRole("button", { name: "Preview declaration", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Confirm and save declaration",
      exact: true,
    }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page
      .getByText("Expected BTC at observation", { exact: true })
      .locator("..")
      .getByText("Unknown", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByText("Unexplained difference (BTC)", { exact: true })
      .locator("..")
      .getByText("Unknown", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Confirm and save declaration", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm and save declaration", exact: true })
    .click();
  await expect(
    page.getByText(
      "Data saved. Review current records, then prepare a new report to include these changes.",
    ),
  ).toBeVisible({ timeout: 30000 });
  await page
    .getByRole("button", { name: "Refresh records", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("cell", { name: "B000001", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "What would you like to record?" })
    .selectOption("revision");
  await page
    .getByRole("combobox", { name: "Record ID", exact: true })
    .selectOption("B000001");
  await page
    .getByLabel("BTC equivalent quantity", { exact: true })
    .fill("0.01990000");
  await page
    .getByLabel("Reason for this correction")
    .fill("Synthetic corrected wallet total");
  await page
    .getByRole("button", { name: "Preview declaration", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Confirm and save declaration",
      exact: true,
    }),
  ).toBeVisible({ timeout: 30000 });
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(axe.violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/financial-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Confirm and save declaration", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm and save declaration", exact: true })
    .click();
  await expect(
    page.getByText(
      "Data saved. Review current records, then prepare a new report to include these changes.",
    ),
  ).toBeVisible({ timeout: 30000 });
  await page
    .getByRole("button", { name: "Refresh records", exact: true })
    .first()
    .click();
  await page
    .getByRole("button", {
      name: "Details and revision history B000001",
      exact: true,
    })
    .click();
  await expect(page.getByText("Revision 2", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Expected quantity unknown", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "CA$1,930.00", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .selectOption({ label: "Empty synthetic portfolio" });
  await page
    .getByRole("navigation", { name: "Portfolio navigation", exact: true })
    .getByRole("link", { name: "Financial records", exact: true })
    .click();
  await expect(
    page
      .getByText("No records yet. Add evidence above when available.")
      .first(),
  ).toBeVisible();
  await expect(page.getByText("B000001", { exact: true })).toHaveCount(0);
});

test("legacy migration basis is visible in three locales and retained downloads work", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .selectOption({ label: "Legacy synthetic portfolio" });
  await expect(
    page.getByText("Verified at migration.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "CA$1,930.00", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Interface language", exact: true })
    .selectOption("zh-TW");
  await expect(page.getByText("於遷移時核對", { exact: false })).toBeVisible();
  await page
    .getByRole("combobox", { name: "介面語言", exact: true })
    .selectOption("zh-CN");
  await expect(page.getByText("于迁移时核对", { exact: false })).toBeVisible();
  await page
    .getByRole("combobox", { name: "界面语言", exact: true })
    .selectOption("en-CA");
  await page
    .getByRole("link", { name: "Analysis reports", exact: true })
    .click();
  await expect(
    page.getByText("Verified at migration.", { exact: false }),
  ).toBeVisible();
  const saved = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download report ZIP", exact: true })
    .click();
  const file = await saved;
  expect(
    readFileSync((await file.path())!)
      .subarray(0, 2)
      .toString(),
  ).toBe("PK");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
});

test("frozen source publications preserve partial scope, generic providers and exports", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .selectOption({ label: "Source synthetic portfolio" });
  await expect(
    page.getByText(
      "These values cover valued observed holdings, not complete wealth. Missing contributions and full portfolio returns remain unknown.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByText("Holdings observation", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".evidence-rail").getByText("Bull Bitcoin", { exact: true }),
  ).toHaveCount(0);
  await page.route(/\/reports\/[a-f0-9]{32}\?/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.source_dates = [
      {
        provider: "SYNTHETIC-THIRD",
        as_of: body.as_of,
        usage: "holdings_observation",
      },
    ];
    await route.fulfill({ response, json: body });
  });
  await page
    .getByRole("combobox", { name: "Interface language", exact: true })
    .selectOption("zh-TW");
  await expect(
    page
      .locator(".evidence-rail")
      .getByText("SYNTHETIC-THIRD", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "這些金額僅涵蓋已觀測且可估值的持倉，不代表完整資產。缺少的供款及完整組合報酬仍屬未知。",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "介面語言", exact: true })
    .selectOption("en-CA");
  await page.getByRole("link", { name: "Holdings", exact: true }).click();
  await expect(
    page.getByRole("table", { name: "Holdings", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Analysis reports", exact: true })
    .click();
  for (const name of ["portfolio.ods", "report.md", "report.pdf"])
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "portfolio.ods", exact: true })
    .click();
  expect((await download).suggestedFilename()).toBe("portfolio.ods");
  // Prepare the advanced explicit request; review/confirm through ordinary jobs UI.
  const portfolio = await page
    .getByRole("combobox", { name: "Portfolio", exact: true })
    .inputValue();
  const csrf = await (await page.request.get("/api/v1/auth/csrf")).json();
  const headers = {
    Origin: "http://localhost:8765",
    "X-CSRF-Token": csrf.csrf_token,
  };
  const raw = readFileSync(
    path.join(root, "examples/data/wealthsimple-holdings.csv"),
    "utf8",
  )
    .replaceAll("VEQT", "DEMO-ETF")
    .replaceAll("QQQ", "DEMO-ETF-US");
  const uploaded = await page.request.post(
    `/api/v1/portfolios/${portfolio}/uploads?kind=source_csv&filename=synthetic.csv`,
    {
      headers: { ...headers, "Content-Type": "text/csv" },
      data: raw,
    },
  );
  expect(uploaded.status()).toBe(201);
  const evidence = await uploaded.json();
  const prepared = await page.request.post(
    `/api/v1/portfolios/${portfolio}/source-report-previews`,
    {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: {
        upload_ids: [evidence.id],
        contexts: [
          {
            evidence_at: "2024-02-01T12:00:00-05:00",
            source_reference: "synthetic-browser-source",
            source_timezone: "America/Toronto",
          },
        ],
        valuation: {
          as_of: "2024-03-01T00:00:00Z",
          period_start: "2023-12-31T00:00:00Z",
          generated_at: "2024-03-01T00:00:00Z",
          report_locale: "en-CA",
          fx: {
            usd_cad: "1.5",
            usd_twd: "30",
            usd_cad_date: "2024-01-30",
            usd_twd_date: "2024-01-30",
            usd_cad_source: "synthetic-fixed",
            usd_twd_source: "synthetic-fixed",
          },
        },
      },
    },
  );
  expect(prepared.status()).toBe(202);
  await page.getByRole("link", { name: "Import & jobs", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Source account mappings", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await page
    .getByRole("button", {
      name: "Confirm import & generate reports",
      exact: true,
    })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", {
      name: "Confirm import & generate reports",
      exact: true,
    })
    .click();
  await expect(
    page.locator(".job-list").getByText("Published", { exact: true }),
  ).toHaveCount(2, { timeout: 60000 });
});

test("regular parser upload reviews mappings and publishes without hand-written contexts", async ({
  page,
}) => {
  // This case executes several isolated Python jobs and two real report builds.
  // Bound asynchronous work separately from ordinary browser interactions.
  test.setTimeout(300000);
  const jobTimeout = 90000;
  await login(page);
  await page.getByText("New portfolio", { exact: true }).click();
  await page
    .getByLabel("Name", { exact: true })
    .fill("Automatic parser synthetic portfolio");
  await page
    .getByRole("button", { name: "Create portfolio", exact: true })
    .click();
  await page.getByRole("link", { name: "Import & jobs", exact: true }).click();
  await expect(
    page.getByLabel("Use parser plugins", { exact: true }),
  ).toBeChecked();
  const raw = readFileSync(
    path.join(root, "examples/data/wealthsimple-holdings.csv"),
    "utf8",
  )
    .replaceAll("VEQT", "DEMO-ETF")
    .replaceAll("QQQ", "DEMO-ETF-US");
  await page.getByLabel("CSV exports", { exact: true }).setInputFiles({
    name: "synthetic-parser.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(raw),
  });
  await page.getByText("Optional reference JSON", { exact: true }).click();
  await page
    .getByLabel("Verified FX", { exact: true })
    .setInputFiles(path.join(root, "examples/data/fx.json"));
  let interrupted = false;
  let firstRequest = "";
  let firstKey = "";
  await page.route("**/source-import-previews", async (route) => {
    if (!interrupted) {
      firstRequest = route.request().postData() ?? "";
      firstKey = route.request().headers()["idempotency-key"];
      const response = await route.fetch();
      expect(response.status()).toBe(202);
      interrupted = true;
      await route.abort("failed");
    } else {
      await route.continue();
    }
  });
  await page
    .getByRole("button", { name: "Upload & preview", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("request_failed");
  // The worker may finish and populate suggested mappings before the retry.
  await expect(
    page.getByRole("heading", { name: "Source account mappings", exact: true }),
  ).toBeVisible({ timeout: jobTimeout });
  const retry = page.waitForRequest("**/source-import-previews");
  await page
    .getByRole("button", { name: "Upload & preview", exact: true })
    .click();
  const retried = await retry;
  expect(retried.postData()).toBe(firstRequest);
  expect(retried.headers()["idempotency-key"]).toBe(firstKey);
  await page.unroute("**/source-import-previews");
  await expect(
    page.getByRole("heading", { name: "Source account mappings", exact: true }),
  ).toBeVisible({ timeout: jobTimeout });
  const confirmation = page.getByRole("button", {
    name: "Confirm import & generate reports",
    exact: true,
  });
  await expect(confirmation).toHaveCount(0);
  await expect(
    page.getByRole("combobox", { name: "Mapping destination 1", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Preview reviewed mappings", exact: true })
    .click();
  await expect(confirmation).toBeVisible({ timeout: jobTimeout });
  await confirmation.click();
  await page
    .getByRole("dialog")
    .getByRole("button", {
      name: "Confirm import & generate reports",
      exact: true,
    })
    .click();
  await expect(
    page.locator(".job-list").getByText("Published", { exact: true }),
  ).toBeVisible({ timeout: jobTimeout });
  // A second preparation in the same form gets its own exact approval key.
  await page.getByLabel("CSV exports", { exact: true }).setInputFiles({
    name: "synthetic-parser.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(raw),
  });
  const savedContext = page.getByRole("combobox", {
    name: "Saved source context",
    exact: true,
  });
  await expect(savedContext.locator("option")).toHaveCount(2);
  await savedContext.selectOption({ index: 1 });
  await expect(
    page.getByLabel("Stable source account alias (if required)", {
      exact: true,
    }),
  ).toBeDisabled();
  await page
    .getByLabel("Valuation time (optional, with UTC offset)", { exact: true })
    .fill("2024-02-01T15:00:00+00:00");
  await page
    .getByRole("button", { name: "Upload & preview", exact: true })
    .click();
  await expect(confirmation).toBeVisible({ timeout: jobTimeout });
  await confirmation.click();
  await page
    .getByRole("dialog")
    .getByRole("button", {
      name: "Confirm import & generate reports",
      exact: true,
    })
    .click();
  await expect(
    page.locator(".job-list").getByText("Published", { exact: true }),
  ).toHaveCount(2, { timeout: jobTimeout });
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(
    page.getByText(
      "These values cover valued observed holdings, not complete wealth. Missing contributions and full portfolio returns remain unknown.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Analysis reports", exact: true })
    .click();
  for (const name of ["portfolio.ods", "report.md", "report.pdf"])
    await expect(page.getByRole("button", { name, exact: true })).toHaveCount(
      1,
    );
});
