import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import en from "../../src/locales/en-CA.json" with { type: "json" };
import tw from "../../src/locales/zh-TW.json" with { type: "json" };
import cn from "../../src/locales/zh-CN.json" with { type: "json" };
async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".evidence-status")).toBeVisible();
}
const pendingJob = {
  id: "f".repeat(32),
  kind: "update",
  status: "report_failed",
  created_at: 1700000000,
  updated_at: 1700000010,
  execution_at: "2024-02-01T12:00:00Z",
  preview_id: null,
  core_operation_id: null,
  error_code: "report_generation_failed",
  result: null,
};
test("saved status keeps historical evidence separate from current jobs and links to the exact job without mutations", async ({
  page,
}) => {
  const writes: string[] = [];
  let currentJob = { ...pendingJob };
  page.on("request", (request) => {
    if (request.method() !== "GET" && !request.url().includes("/auth/"))
      writes.push(request.url());
  });
  await page.route("**/api/v1/portfolios/*/jobs", (route) =>
    route.fulfill({ json: { jobs: [currentJob] } }),
  );
  await page.route(
    /\/api\/v1\/portfolios\/[^/]+\/reports\/[^/?]+(?:\?[^/]*)?$/,
    async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.issues = [
        ...data.issues,
        ...["a", "b", "c", "d"].map((account_id) => ({
          severity: "warning",
          code: "synthetic_cash_check",
          message: "Invented scoped cash check",
          account_id,
        })),
      ];
      await route.fulfill({ json: data });
    },
  );
  await signIn(page);
  const status = page.locator(".evidence-status");
  await expect(
    status.getByText(en.evidenceLatest, { exact: true }),
  ).toBeVisible();
  await expect(status.locator("#evidence-actions > li")).toHaveCount(3);
  await status.getByRole("button", { name: /Show all next steps/ }).click();
  expect(
    await status.locator("#evidence-actions > li").count(),
  ).toBeGreaterThan(3);
  await status
    .getByRole("link", { name: en.evidenceViewDetails, exact: true })
    .first()
    .click();
  await expect(status.locator("#saved-status-evidence")).toHaveAttribute(
    "open",
    "",
  );
  await status.getByText("Saved evidence and checks", { exact: true }).click();
  const editions = page.getByRole("combobox", {
    name: "Report edition",
    exact: true,
  });
  const old = await editions.locator("option").last().getAttribute("value");
  await editions.selectOption(old!);
  await expect(
    status.getByText(en.evidenceHistorical, { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".processing-status")
      .getByText(en.processingUnpublished, { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".portfolio-value")).toHaveText("CA$1,930.00");
  await page
    .getByRole("link", { name: en.processingViewJob, exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`imports\\?job=${pendingJob.id}`));
  await expect(page.locator(".job-list button.selected")).toContainText(
    "Report needs retry",
  );
  currentJob = { ...pendingJob, kind: "record", status: "interrupted" };
  await page.goto(new URL(page.url()).pathname.replace(/imports$/, "overview"));
  await page
    .getByRole("link", { name: en.processingViewJob, exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`records\\?job=${pendingJob.id}`));
  await expect(page.locator(".job-list button")).toContainText("Interrupted");
  expect(writes).toEqual([]);
});
test("unavailable current jobs do not hide saved figures, and retry does not publish", async ({
  page,
}) => {
  let failing = true;
  await page.route("**/api/v1/portfolios/*/jobs", (route) =>
    route.fulfill(
      failing
        ? { status: 503, json: { error: { code: "request_failed" } } }
        : { json: { jobs: [] } },
    ),
  );
  await signIn(page);
  await expect(
    page
      .locator(".processing-status")
      .getByText(en.processingUnavailable, { exact: true })
      .last(),
  ).toBeVisible();
  await expect(page.locator(".portfolio-value")).toHaveText("CA$1,930.00");
  failing = false;
  await page
    .locator(".processing-status")
    .getByRole("button", { name: en.retry, exact: true })
    .click();
  await expect(page.locator(".processing-status")).toHaveCount(0);
  const saved = await page
    .getByRole("combobox", { name: "Report edition", exact: true })
    .inputValue();
  await page.route("**/api/v1/portfolios/*/reports", (route) =>
    route.fulfill({ status: 503, json: { error: { code: "request_failed" } } }),
  );
  await page.goto(new URL(page.url()).pathname + "?report=" + saved);
  await expect(
    page
      .locator(".evidence-status")
      .getByText(en.evidenceLatestUnknown, { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".portfolio-value")).toHaveText("CA$1,930.00");
});
test("status supports three locales, keyboard expansion, dark/light mobile layouts and unknown-job links", async ({
  page,
}) => {
  await page.route("**/api/v1/portfolios/*/jobs", (route) =>
    route.fulfill({ json: { jobs: [] } }),
  );
  await signIn(page);
  await page
    .locator(".evidence-status")
    .getByRole("button", { name: /Show all next steps/ })
    .click();
  for (const [locale, messages] of [
    ["en-CA", en],
    ["zh-TW", tw],
    ["zh-CN", cn],
  ] as const) {
    await page.locator(".language select").selectOption(locale);
    await expect(
      page.getByRole("region", {
        name: messages.evidenceStatusTitle,
        exact: true,
      }),
    ).toBeVisible();
    const toggle = page.locator(
      ".evidence-status button[aria-controls='evidence-actions']",
    );
    if ((await toggle.getAttribute("aria-expanded")) === "false")
      await toggle.click();
    await expect(
      page
        .locator(".evidence-status")
        .getByText(messages.evidenceFlowsUnknown, { exact: true })
        .first(),
    ).toBeVisible();
  }
  await page.locator(".language select").selectOption("en-CA");
  const details = page.locator("#saved-status-evidence > summary");
  await details.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText(en.evidenceGapUnavailable, { exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Enter");
  for (const theme of ["light", "dark"]) {
    await page
      .getByRole("combobox", { name: "Appearance", exact: true })
      .selectOption(theme);
    await page.setViewportSize({
      width: theme === "dark" ? 1440 : 390,
      height: theme === "dark" ? 1200 : 844,
    });
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/evidence-status-${theme}.png`,
      fullPage: true,
    });
  }
  const path = new URL(page.url()).pathname.replace(/overview$/, "imports");
  await page.goto(path + "?job=" + "e".repeat(32));
  await expect(
    page.getByText(en.processingJobMissing, { exact: true }),
  ).toBeVisible();
  await page.goto(
    path.replace(/imports$/, "records") + "?job=" + "e".repeat(32),
  );
  await expect(
    page.getByText(en.processingJobMissing, { exact: true }),
  ).toBeVisible();
});
