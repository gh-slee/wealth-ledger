import { expect, test, type Page } from "@playwright/test";

const destinations = [
  ["/app", "Home"],
  ["/app/investments", "Stock/Bond"],
  ["/app/investments/exposures", "Exposures"],
  ["/app/crypto", "Crypto"],
  ["/app/total", "Total"],
  ["/app/import", "Import Data"],
  ["/app/sources", "Parser Plugin Store"],
  ["/app/settings", "App Settings"],
  ["/app/profile", "Profile"],
] as const;

async function mockV2(page: Page) {
  await page.route("**/api/v2/auth/csrf", (route) =>
    route.fulfill({
      json: { authenticated: true, csrf_token: "a".repeat(64) },
    }),
  );
}

test("V2 routes preserve the eight destinations and nested Exposures", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await mockV2(page);
  const legacyRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/")) {
      legacyRequests.push(request.url());
    }
  });

  await page.goto("/");
  await expect(page).toHaveURL(/\/app$/);
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.locator(":scope > ul > li")).toHaveCount(8);
  await expect(
    nav.locator(":scope > ul > li > ul").getByRole("link"),
  ).toHaveText("Exposures");

  for (const [path, name] of destinations) {
    const link = nav.getByRole("link", { name, exact: true });
    await link.click();
    expect(new URL(page.url()).pathname).toBe(path);
    await expect(link).toHaveAttribute("aria-current", "page");
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toHaveText(name);
    await expect(heading).toBeFocused();
    await expect(page).toHaveTitle(`${name} · Kurafolio`);
  }
  expect(legacyRequests).toEqual([]);

  for (const path of [
    "/app/investments",
    "/app/investments/exposures",
    "/app/crypto",
  ]) {
    await page.goto(path);
    await page.getByRole("link", { name: "Enable a source" }).click();
    await expect(page).toHaveURL(/\/app\/sources$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Parser Plugin Store",
    );
  }
  for (const path of ["/app", "/app/total", "/app/settings"]) {
    await page.goto(path);
    await expect(
      page.getByRole("link", { name: "Enable a source" }),
    ).toHaveCount(0);
  }

  // WL-P0-011 bans these shipped concepts from the V2 shell and Home.
  // Home content itself is WL-P0-012D, which owns the per-locale check.
  await page.goto("/app");
  const shell = page.locator("body");
  for (const banned of [
    /portfolio/i,
    /edition/i,
    /financial records/i,
    /next steps/i,
    /saved evidence/i,
    /recorded cash flows/i,
    /partial source scope/i,
    /carried forward/i,
    /report edition/i,
  ]) {
    await expect(shell).not.toContainText(banned);
  }

  await page.goto("/app/missing/nested");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Page not found",
  );
  await page.getByRole("link", { name: "Back to Home" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
});

test("the phone menu fits the viewport and manages keyboard focus", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ colorScheme: "dark" });
  await mockV2(page);
  for (const [path, name] of destinations) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
    const main = await page.getByRole("main").boundingBox();
    expect(main?.y).toBeLessThanOrEqual(120);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(375);
  }
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  const menu = page.getByRole("button", { name: "Menu" });
  await menu.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Menu" });
  await expect(dialog).toBeVisible();
  const links = dialog.getByRole("navigation").getByRole("link");
  await expect(links).toHaveCount(9);
  for (const link of await links.all()) {
    const rect = await link.boundingBox();
    expect(rect?.height).toBeGreaterThanOrEqual(42);
  }
  expect(
    await dialog.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);

  const close = dialog.getByRole("button", { name: "Close" });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("combobox")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(menu).toBeFocused();

  await page.keyboard.press("Enter");
  const exposures = dialog.getByRole("link", { name: "Exposures" });
  await exposures.focus();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("heading", { level: 1, name: "Exposures" }),
  ).toBeFocused();
});

test("V2 remembers the interface language across reloads", async ({ page }) => {
  await mockV2(page);
  await page.goto("/app");
  for (const [locale, heading] of [
    ["zh-TW", "首頁"],
    ["zh-CN", "首页"],
    ["en-CA", "Home"],
  ]) {
    await page.getByRole("combobox").selectOption(locale);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
  }
});

test("a failed V2 probe can retry without opening the SQLite shell", async ({
  page,
}) => {
  let attempts = 0;
  await page.route("**/api/v2/auth/csrf", (route) => {
    attempts++;
    return attempts === 1
      ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({
          json: { authenticated: true, csrf_token: "a".repeat(64) },
        });
  });
  await page.goto("/app");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
  expect(attempts).toBe(2);
});

test("the startup probe explains maintenance in the remembered language", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem("kurafolio-v2-locale", "zh-TW"),
  );
  let attempts = 0;
  await page.route("**/api/v2/auth/csrf", (route) => {
    attempts++;
    return attempts === 1
      ? route.fulfill({
          status: 503,
          json: {
            error: { code: "maintenance", message: "", request_id: "x" },
          },
        })
      : route.fulfill({
          json: { authenticated: true, csrf_token: "a".repeat(64) },
        });
  });
  await page.goto("/app");
  await expect(page.getByRole("alert")).toHaveText(
    "系統正在維護，請稍候一分鐘再試。",
  );
  await page.getByRole("button", { name: "重試" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("首頁");
});

test("SQLite session cache clears do not restart shell selection", async ({
  page,
}) => {
  let probes = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v2/auth/csrf") probes++;
  });
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill("example-owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("example-browser-only-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Overview");
  await page
    .getByRole("combobox", { name: "Interface language" })
    .selectOption("zh-TW");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("資產總覽");
  await expect(
    page.getByRole("heading", { name: "CA$1,930.00" }),
  ).toBeVisible();
  expect(probes).toBe(1);
});
