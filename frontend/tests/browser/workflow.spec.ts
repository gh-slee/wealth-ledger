import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import path from "node:path";
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
}) => {
  const external: string[] = [];
  page.on("request", (request) => {
    if (
      !request.url().startsWith("http://localhost:8765") &&
      !request.url().startsWith("data:")
    )
      external.push(request.url());
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
  await page.getByRole("link", { name: "Report library", exact: true }).click();
  const saved = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "portfolio.ods", exact: true })
    .click();
  expect((await saved).suggestedFilename()).toBe("portfolio.ods");
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
  await page.getByRole("link", { name: "Report library", exact: true }).click();
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
