import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { isLocalResource } from "./request-origin";
import en from "../../src/locales/en-CA.json" with { type: "json" };
import tw from "../../src/locales/zh-TW.json" with { type: "json" };
import cn from "../../src/locales/zh-CN.json" with { type: "json" };

// Invented amounts and country coverage; no broker export or real portfolio data.
const countries = [
  ["US", "United States"],
  ["GB", "United Kingdom"],
  ["FR", "France"],
  ["IN", "India"],
  ["CN", "China"],
  ["ZA", "South Africa"],
  ["FI", "Finland"],
  ["TH", "Thailand"],
  ["TR", "Türkiye"],
  ["KW", "Kuwait"],
  ["PT", "Portugal"],
  ["CZ", "Czechia"],
  ["CA", "Canada"],
  ["DE", "Germany"],
  ["JP", "Japan"],
  ["AU", "Australia"],
  ["CH", "Switzerland"],
  ["NL", "Netherlands"],
  ["SE", "Sweden"],
  ["DK", "Denmark"],
  ["NO", "Norway"],
  ["BE", "Belgium"],
  ["ES", "Spain"],
  ["IT", "Italy"],
  ["SG", "Singapore"],
  ["KR", "South Korea"],
  ["HK", "Hong Kong"],
  ["NZ", "New Zealand"],
  ["BR", "Brazil"],
  ["MX", "Mexico"],
  ["TW", "Taiwan"],
] as const;
const rows = [
  ...countries.map(([key, name], index) => ({
    key,
    name: `${name} (${key})`,
    market_cad: `${(31 - index) * 10}.10`,
    investment_weight: "0.01",
  })),
  {
    key: "unknown",
    name: "Unknown classification",
    market_cad: "12.34",
    investment_weight: null,
  },
  {
    key: "adjustment",
    name: "Unallocated adjustment",
    market_cad: "-0.15",
    investment_weight: null,
  },
];
async function enterCountry(page: Page, selected = rows) {
  const writes: string[] = [];
  const external: string[] = [];
  page.on("request", (request) => {
    if (!isLocalResource(request.url(), "http://localhost:8765"))
      external.push(request.url());
    if (
      request.method() !== "GET" &&
      !new URL(request.url()).pathname.includes("/auth/")
    )
      writes.push(request.url());
  });
  await page.route(
    /\/api\/v1\/portfolios\/[^/]+\/reports\/[^/?]+(?:\?[^/]*)?$/,
    async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.dimensions.country = {
        ...data.dimensions.country,
        rows: selected,
      };
      await route.fulfill({ json: data });
    },
  );
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Exposure", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Exposure", exact: true })
    .selectOption("country");
  return { writes, external };
}

for (const viewport of [
  { width: 1440, height: 1000 },
  { width: 390, height: 844 },
]) {
  for (const theme of ["light", "dark"] as const) {
    test(`all 31 countries and exact table values at ${viewport.width}px in ${theme}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      const { writes, external } = await enterCountry(page);
      await page
        .getByRole("combobox", { name: "Appearance", exact: true })
        .selectOption(theme);
      const chart = page.getByRole("img", {
        name: "Country · CAD",
        exact: true,
      });
      await expect(chart.locator("svg")).toBeVisible();
      const expectedLabelColor = await page.evaluate(() =>
        getComputedStyle(document.documentElement)
          .getPropertyValue("--muted")
          .trim(),
      );
      await expect
        .poll(() => chart.locator("svg text").first().getAttribute("fill"))
        .toBe(expectedLabelColor);
      // ECharts auto-skipped axis labels in the original fixed-height chart.
      await expect
        .poll(async () =>
          (await chart.locator("svg text").allTextContents())
            .join("")
            .replace(/\s/g, ""),
        )
        .toContain("Taiwan(TW)");
      const text = (await chart.locator("svg text").allTextContents())
        .join("")
        .replace(/\s/g, "");
      let previous = -1;
      for (const row of rows) {
        const position = text.indexOf(row.name.replace(/\s/g, ""));
        expect(position).toBeGreaterThan(previous);
        previous = position;
      }
      const scroll = page.getByRole("region", {
        name: "Country · CAD",
        exact: true,
      });
      await expect(scroll).toHaveAttribute("tabindex", "0");
      expect(
        await scroll.evaluate(
          (element) => element.scrollHeight > element.clientHeight,
        ),
      ).toBeTruthy();
      await scroll.focus();
      await page.keyboard.press("End");
      await expect
        .poll(() => scroll.evaluate((element) => element.scrollTop))
        .toBeGreaterThan(0);
      await expect(
        chart.getByText("Taiwan (TW)", { exact: true }),
      ).toBeInViewport();
      await scroll.focus();
      await page.keyboard.press("Home");
      await expect
        .poll(() => scroll.evaluate((element) => element.scrollTop))
        .toBe(0);
      await expect(
        chart.getByText("United States (US)", { exact: true }),
      ).toBeInViewport();
      await page.getByText("View chart data", { exact: true }).click();
      const table = page.getByRole("table", { name: "Country", exact: true });
      const checkTable = async (expected: typeof rows) => {
        expect(
          await table.locator("tbody tr td:first-child").allTextContents(),
        ).toEqual(expected.map((row) => row.name));
        for (const row of expected) {
          const exact = row.market_cad.startsWith("-")
            ? `−CA$${row.market_cad.slice(1)}`
            : `CA$${row.market_cad}`;
          await expect(
            table.getByRole("row").filter({ hasText: row.name }),
          ).toContainText(exact);
        }
      };
      await checkTable(rows.slice(0, 20));
      await table
        .locator("..")
        .locator("..")
        .getByRole("button", { name: "Next", exact: true })
        .click();
      await checkTable(rows.slice(20));
      await expect(
        table.getByRole("row").filter({ hasText: "Unallocated adjustment" }),
      ).toContainText("−CA$0.15");
      await expect(
        table.getByRole("row").filter({ hasText: "Unknown classification" }),
      ).toContainText("CA$12.34");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBeTruthy();
      expect(
        (
          await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
            .analyze()
        ).violations,
      ).toEqual([]);
      await page.screenshot({
        path: `test-results/country-${viewport.width}-${theme}.png`,
        fullPage: true,
      });
      expect(writes).toEqual([]);
      expect(external).toEqual([]);
    });
  }
}

test("country chart supports locale, narrow labels and zoom", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 900 });
  const { writes, external } = await enterCountry(page);
  for (const [locale, catalog] of [
    ["en-CA", en],
    ["zh-TW", tw],
    ["zh-CN", cn],
  ] as const) {
    await page.locator(".language select").selectOption(locale);
    await page
      .getByRole("combobox", { name: catalog.exposure, exact: true })
      .selectOption("country");
    const scroll = page.getByRole("region", {
      name: `${catalog.country} · CAD`,
      exact: true,
    });
    await expect(scroll).toHaveAttribute("aria-describedby");
    await expect(
      page.getByText(catalog.chartScrollHint, { exact: true }),
    ).toBeVisible();
    await scroll.focus();
    await page.keyboard.press("End");
    await expect
      .poll(() => scroll.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(0);
  }
  await page.locator(".language select").selectOption("en-CA");
  await page
    .getByRole("combobox", { name: en.exposure, exact: true })
    .selectOption("country");
  // A 200% browser zoom halves the effective CSS viewport. CSS zoom alone
  // leaves media queries unchanged and does not model responsive browser zoom.
  await page.setViewportSize({ width: 360, height: 450 });
  const scroll = page.getByRole("region", {
    name: "Country · CAD",
    exact: true,
  });
  await expect(scroll).toBeVisible();
  await scroll.focus();
  await page.keyboard.press("Home");
  await expect
    .poll(() => scroll.evaluate((element) => element.scrollTop))
    .toBe(0);
  await page.keyboard.press("ArrowDown");
  await expect
    .poll(() => scroll.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);
  await page.keyboard.press("PageDown");
  await page.keyboard.press("End");
  const chart = scroll.getByRole("img", { name: "Country · CAD", exact: true });
  await expect(
    chart.getByText("Taiwan (TW)", { exact: true }),
  ).toBeInViewport();
  const text = (await chart.locator("svg text").allTextContents())
    .join("")
    .replace(/\s/g, "");
  for (const row of rows) expect(text).toContain(row.name.replace(/\s/g, ""));
  const ticks = await chart.locator("svg text").evaluateAll((elements) =>
    elements
      .filter((element) => /^-?[\d,]+$/.test(element.textContent ?? ""))
      .map((element) => {
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, width: box.width };
      })
      .filter((box) => box.width > 0)
      .sort((a, b) => a.left - b.left),
  );
  expect(ticks.length).toBeGreaterThan(1);
  for (let index = 1; index < ticks.length; index++)
    expect(ticks[index - 1].right).toBeLessThanOrEqual(ticks[index].left);

  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/country-zoom-reflow.png",
    fullPage: true,
  });

  expect(writes).toEqual([]);
  expect(external).toEqual([]);
});

test("empty country data keeps an explicit state and usable table", async ({
  page,
}) => {
  await enterCountry(page, []);
  await expect(
    page.getByRole("region", { name: "Country · CAD", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText(en.emptyRows, { exact: true }).first(),
  ).toBeVisible();
  await page.getByText("View chart data", { exact: true }).click();
  await expect(
    page.getByRole("table", { name: "Country", exact: true }),
  ).toContainText(en.emptyRows);
});

test("failed chart module keeps the complete country table available", async ({
  page,
}) => {
  let rejectChart: (() => void) | undefined;
  await page.route(/\/assets\/chart-view-[^/]+\.js$/, async (route) => {
    await new Promise<void>((resolve) => {
      rejectChart = resolve;
    });
    await route.abort();
  });
  const { writes, external } = await enterCountry(page);
  await expect.poll(() => !!rejectChart).toBeTruthy();
  rejectChart?.();
  await expect(
    page.getByText(en.chartUnavailable, { exact: true }),
  ).toBeVisible();
  await page.getByText("View chart data", { exact: true }).click();
  const table = page.getByRole("table", { name: "Country", exact: true });
  await expect(table).toContainText("United States (US)");
  await table
    .locator("..")
    .locator("..")
    .getByRole("button", { name: "Next", exact: true })
    .click();
  await expect(table).toContainText("Taiwan (TW)");
  expect(writes).toEqual([]);
  expect(external).toEqual([]);
});
