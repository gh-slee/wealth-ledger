import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function openReports(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page
    .getByRole("link", { name: "Analysis reports", exact: true })
    .click();
  await expect(
    page.getByRole("article", { name: "Read the report" }),
  ).toBeVisible();
}

test("complete report reading, grouped editions, deep links and dark/system themes", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  await openReports(page);
  const contents = page.getByRole("navigation", {
    name: "Contents",
    exact: true,
  });
  expect(await contents.getByRole("link").count()).toBeGreaterThanOrEqual(12);
  await page.locator(".report-chart").first().scrollIntoViewIfNeeded();
  await expect(page.locator(".saved-report-chart img").first()).toBeVisible();
  expect(
    await page
      .locator(".saved-report-chart img")
      .first()
      .evaluate((image) => (image as HTMLImageElement).naturalWidth),
  ).toBeGreaterThan(0);
  await expect(
    page.getByRole("button", { name: "report.pdf", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "portfolio.ods", exact: true }),
  ).toBeVisible();
  await page.locator(".report-history > summary").click();
  await expect(page.locator(".report-history-group")).toHaveCount(1);
  await page.getByText("Earlier editions (1)", { exact: true }).click();
  const older = page.locator(".report-history-group details a").first();
  const target = await older.getAttribute("href");
  await older.click();
  await expect(page).toHaveURL(
    new RegExp(`report=${target!.split("report=")[1]}`),
  );
  await page.reload();
  await expect(
    page.getByRole("article", { name: "Read the report" }),
  ).toBeVisible();
  await expect(page).toHaveURL(
    new RegExp(`report=${target!.split("report=")[1]}`),
  );
  await page
    .getByRole("combobox", { name: "Appearance", exact: true })
    .selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("article", { name: "Read the report" }),
  ).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: "test-results/report-reader-dark-desktop.png",
  });
  await page
    .getByRole("button", { name: "Interactive view · CAD", exact: true })
    .first()
    .click();
  await expect(page.locator(".report-chart .chart svg").first()).toBeVisible();
  await page
    .locator(".report-chart .chart svg")
    .first()
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: "test-results/report-reader-dark-chart.png" });
  await page
    .getByRole("combobox", { name: "Appearance", exact: true })
    .selectOption("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page
    .getByRole("combobox", { name: "Appearance", exact: true })
    .selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/report-reader-light-mobile.png",
  });
  await page
    .getByRole("combobox", { name: "Interface language", exact: true })
    .selectOption("zh-TW");
  await expect(
    page.getByRole("heading", { name: "分析報告", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "外觀", exact: true })
    .selectOption("dark");
  await page
    .getByRole("combobox", { name: "介面語言", exact: true })
    .selectOption("zh-CN");
  await expect(
    page.getByRole("heading", { name: "分析报告", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([
    "wealth-ledger-theme",
  ]);
  await page.screenshot({ path: "test-results/report-reader-dark-mobile.png" });
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
});

test("report text stays escaped and a document authentication failure clears the page", async ({
  page,
}) => {
  const hostile = '<img src=x onerror="window.syntheticXss=true">';
  await page.route("**/reports/*/document", async (route) => {
    const response = await route.fetch();
    const document = await response.json();
    document.sections[0].blocks.unshift({
      kind: "paragraph",
      text: hostile,
      headers: [],
      rows: [],
      artifact_id: null,
      filename: null,
    });
    await route.fulfill({ json: document });
  });
  await openReports(page);
  await expect(page.getByText(hostile, { exact: true })).toBeVisible();
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  expect(
    await page.evaluate(() => Reflect.get(window, "syntheticXss")),
  ).toBeUndefined();
  await page.unroute("**/reports/*/document");
  await page.route("**/reports/*/document", (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "authentication_required" } },
    }),
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".report-document")).toHaveCount(0);
});
