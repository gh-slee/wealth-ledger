import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import en from "../../src/locales/en-CA.json" with { type: "json" };
import tw from "../../src/locales/zh-TW.json" with { type: "json" };
import cn from "../../src/locales/zh-CN.json" with { type: "json" };
import type { Job } from "../../src/lib/api";
const ready = (digit = "a"): Job => ({
  id: digit.repeat(32),
  kind: "preview",
  status: "ready",
  created_at: 1800000000,
  updated_at: 1800000000,
  execution_at: "2024-02-01T12:00:00Z",
  preview_id: null,
  core_operation_id: null,
  error_code: null,
  result: {
    status: "awaiting_confirmation",
    approval_sha256: "a".repeat(64),
    blockers: [],
    sources: {
      "synthetic-provider": {
        status: "provided",
        as_of: "2024-02-01T12:00:00Z",
      },
    },
    source_usage: { "synthetic-provider": "provided" },
  },
});
async function openImports(page: Page) {
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".portfolio-value")).toBeVisible();
  const report = await page
    .getByRole("combobox", { name: en.edition, exact: true })
    .inputValue();
  await page.getByRole("link", { name: en.imports, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: en.uploadTitle, exact: true }),
  ).toBeVisible();
  return report;
}
test("unchanged retries preserve identity, edits invalidate old approval and exact confirmation survives a lost response", async ({
  page,
}) => {
  let jobs: Job[] = [];
  const previews: { key: string; body: unknown }[] = [];
  const confirmations: { key: string; body: unknown }[] = [];
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/portfolios/*/jobs", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { jobs } })
      : route.continue(),
  );
  await page.route("**/source-import-previews", async (route) => {
    previews.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
    });
    if (previews.length === 1) await gate;
    const prepared = ready(previews.length === 1 ? "a" : "b");
    jobs = [prepared, ...jobs];
    await route.fulfill({ status: 202, json: prepared });
  });
  const report = await openImports(page);
  await expect(page.getByLabel(en.parserMode, { exact: true })).toBeHidden();
  await expect(
    page.locator(".import-stages [aria-current='step']"),
  ).toContainText(en.importPrepareStep);
  await page.locator("form.import-form").evaluate((form) => {
    (form as HTMLFormElement).requestSubmit();
    (form as HTMLFormElement).requestSubmit();
  });
  await expect.poll(() => previews.length).toBe(1);
  release();
  await expect(page.locator("#import-review")).toBeFocused();
  const confirmation = page
    .locator("#import-review")
    .getByRole("button", { name: en.confirm, exact: true });
  await expect(confirmation).toBeVisible();
  expect(previews[0].body).toMatchObject({
    reference_policy: "saved_only",
    upload_ids: [],
  });
  await expect(
    page.getByText("synthetic-provider", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("synthetic-provider: Provided", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel(en.valuationAt, { exact: true })
    .fill("2024-02-01T12:00:00Z");
  await expect(confirmation).toHaveCount(0);
  await expect(
    page.getByText(en.importDraftChanged, { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: en.preview, exact: true }).click();
  await expect(confirmation).toBeVisible();
  expect(previews[1].key).not.toBe(previews[0].key);
  await page.locator(".job-list button").nth(1).click();
  await expect(confirmation).toHaveCount(0);
  await page.locator(".job-list button").first().click();
  await expect(confirmation).toBeVisible();
  await page.route("**/source-reports", async (route) => {
    confirmations.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
    });
    if (confirmations.length === 1) {
      await route.abort("failed");
      return;
    }
    const published: Job = {
      ...ready("c"),
      kind: "update",
      status: "published",
      preview_id: "b".repeat(32),
      result: { report_id: report },
    };
    jobs = [published, ...jobs];
    await route.fulfill({ status: 202, json: published });
  });
  await confirmation.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: en.confirm, exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("request_failed");
  await dialog.getByRole("button", { name: en.confirm, exact: true }).click();
  await expect(
    page.getByText(en.importPublished, { exact: true }),
  ).toBeVisible();
  expect(confirmations).toHaveLength(2);
  expect(confirmations[1]).toEqual(confirmations[0]);
  expect(confirmations[0].body).toEqual({
    preview_id: "b".repeat(32),
    approval_sha256: "a".repeat(64),
  });
  await expect(
    page.getByRole("link", { name: en.importOpenReport, exact: true }),
  ).toHaveAttribute("href", new RegExp(`report=${report}`));
  await page.locator(".job-list button").nth(1).click();
  await expect(
    page.getByText(en.importLinkedJob, { exact: false }),
  ).toBeVisible();
  await expect(confirmation).toHaveCount(0);
});
test("missing references, stale approval and uncertain commits offer only their relevant recovery", async ({
  page,
}) => {
  const base = ready();
  let jobs: Job[] = [
    {
      ...base,
      result: { status: "reference_required", missing_references: ["fx"] },
    },
  ];
  const resumes: string[] = [];
  await page.route("**/api/v1/portfolios/*/jobs", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: { jobs } })
      : route.fulfill({
          status: 409,
          json: { error: { code: "stale_preview" } },
        }),
  );
  await openImports(page);
  await expect(
    page.getByText(en.importReferencesNext, { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: en.importReviewReferences, exact: true })
    .click();
  await expect(page.locator("#import-references")).toHaveAttribute("open", "");
  await expect(
    page.getByLabel(en.fetchPublicReferences, { exact: true }),
  ).not.toBeChecked();
  jobs = [{ ...base, result: { status: "checked", blockers: [] } }];
  await page.reload();
  await page
    .locator("#import-review")
    .getByRole("button", { name: en.confirm, exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: en.confirm, exact: true })
    .click();
  await expect(
    page.getByText(en.importStaleHint, { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page
      .locator("#import-review")
      .getByRole("button", { name: en.confirm, exact: true }),
  ).toHaveCount(0);
  const states = [
    "data_committed",
    "report_failed",
    "interrupted",
    "needs_review",
    "cancelled",
    "failed",
    "future_state",
  ];
  for (const [index, status] of states.entries()) {
    const id = String(index + 1).repeat(32);
    jobs = [{ ...base, id, kind: "update", status, result: null }];
    await page.goto(new URL(page.url()).pathname + "?job=" + id);
    const panel = page.locator("#import-review");
    await expect(panel).toBeVisible();
    if (status === "report_failed") {
      await expect(
        panel.getByText(en.importReportFailed, { exact: true }),
      ).toBeVisible();
      await page.route(`**/jobs/${id}/resume`, (route) => {
        resumes.push(route.request().url());
        jobs = [{ ...jobs[0], status: "data_committed" }];
        return route.fulfill({ status: 202, json: jobs[0] });
      });
      await panel.getByRole("button", { name: en.resume, exact: true }).click();
      await expect(
        panel.getByText(en.importCommitted, { exact: true }),
      ).toBeVisible();
    } else {
      await expect(
        panel.getByRole("button", { name: en.resume, exact: true }),
      ).toHaveCount(0);
    }
    await expect(
      panel.getByRole("button", { name: en.confirm, exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", { name: en.cancel, exact: true }),
    ).toHaveCount(0);
  }
  expect(resumes).toHaveLength(1);
});
test("staged form stays accessible in three locales, light/dark and narrow layouts without financial submission", async ({
  page,
}) => {
  const writes: string[] = [];
  await openImports(page);
  await page
    .getByLabel(en.valuationAt, { exact: true })
    .fill("2024-02-01T12:00:00Z");
  await expect(
    page.locator(".import-stages [aria-current='step']"),
  ).toContainText(en.importPrepareStep);
  await expect(
    page.locator("#import-review").getByText(en.previewHint, { exact: true }),
  ).toHaveCount(0);
  page.on("request", (request) => {
    if (request.method() !== "GET" && !request.url().includes("/auth/"))
      writes.push(request.url());
  });
  for (const [locale, messages] of [
    ["en-CA", en],
    ["zh-TW", tw],
    ["zh-CN", cn],
  ] as const) {
    await page.locator(".language select").selectOption(locale);
    await expect(
      page.getByRole("list", { name: messages.importStages, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(messages.importInputOptions, { exact: true }),
    ).toBeVisible();
  }
  await page.locator(".language select").selectOption("en-CA");
  const disclosure = page.getByText(en.importAdvanced, { exact: true });
  await disclosure.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel(en.parserMode, { exact: true })).toBeVisible();
  await page.keyboard.press("Enter");
  for (const theme of ["light", "dark"]) {
    await page
      .getByRole("combobox", { name: en.appearance, exact: true })
      .selectOption(theme);
    await page.setViewportSize({
      width: theme === "light" ? 390 : 1440,
      height: 900,
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
      path: `test-results/import-review-${theme}.png`,
      fullPage: true,
    });
  }
  expect(writes).toEqual([]);
});
