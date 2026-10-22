import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import en from "../../src/locales/en-CA.json" with { type: "json" };
import tw from "../../src/locales/zh-TW.json" with { type: "json" };
import cn from "../../src/locales/zh-CN.json" with { type: "json" };

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(en.expired, { exact: true })).toHaveCount(0);
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("first-use guidance distinguishes loading, empty metadata and a new financial ledger", async ({
  page,
}) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() !== "GET" &&
      /\/(uploads|previews|source-import-previews|financial|declarations)/.test(
        request.url(),
      )
    )
      writes.push(request.url());
  });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/portfolios", async (route) => {
    await gate;
    await route.fulfill({ json: { portfolios: [] } });
  });
  await signIn(page);
  await expect(page.getByRole("status")).toHaveText(en.loading);
  await expect(
    page.getByRole("heading", { name: en.noPortfolios }),
  ).toHaveCount(0);
  release();
  await expect(
    page.getByRole("heading", { name: en.noPortfolios }),
  ).toBeVisible();
  await expect(page.getByText(en.createPortfolioHint)).toBeVisible();
  await page.unroute("**/api/v1/portfolios");
  await page
    .locator("main")
    .getByLabel("Name", { exact: true })
    .fill("First-use synthetic portfolio");
  await page
    .locator("main")
    .getByRole("button", { name: "Create portfolio", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: en.noReport })).toBeVisible();
  await expect(page.locator(".portfolio-value")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: en.startAction }),
  ).toHaveAttribute("href", /\/imports$/);
  for (const [locale, messages] of [
    ["en-CA", en],
    ["zh-TW", tw],
    ["zh-CN", cn],
  ] as const) {
    await page
      .getByRole("combobox", {
        name:
          locale === "en-CA"
            ? en.language
            : locale === "zh-TW"
              ? en.language
              : tw.language,
        exact: true,
      })
      .selectOption(locale);
    await expect(
      page.getByRole("heading", { name: messages.noReport }),
    ).toBeVisible();
    await expect(
      page.getByText(messages.startFlowsBody, { exact: true }),
    ).toBeVisible();
    await page.getByText(messages.startPrepare, { exact: true }).click();
    await expect(
      page.getByText(messages.startReferencesBody, { exact: true }),
    ).toBeVisible();
    await page.getByText(messages.startPrepare, { exact: true }).click();
  }
  await page
    .getByRole("combobox", { name: cn.language, exact: true })
    .selectOption("en-CA");
  for (const appearance of ["light", "dark"]) {
    await page
      .getByRole("combobox", { name: "Appearance", exact: true })
      .selectOption(appearance);
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: en.noReport })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: en.startRecordsAction }).click();
  await expect(
    page.getByRole("heading", { name: "Financial records", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.getByRole("link", { name: en.startSettingsAction }).click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true, level: 1 }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.getByRole("link", { name: en.startAction }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Import & jobs", exact: true }),
  ).toBeVisible();
  expect(writes).toEqual([]);
});

test("portfolio load failure offers retry instead of claiming an empty portfolio", async ({
  page,
}) => {
  await page.route("**/api/v1/portfolios", (route) =>
    route.fulfill({ status: 503, json: { error: { code: "request_failed" } } }),
  );
  await signIn(page);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: en.noPortfolios }),
  ).toHaveCount(0);
  await page.unroute("**/api/v1/portfolios");
  await page.getByRole("button", { name: en.retry, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "CA$1,930.00", exact: true }),
  ).toBeVisible();
});
