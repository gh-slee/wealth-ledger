import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

// A stateful fake of the V2 identity API. Every value is synthetic.
const CSRF = "c".repeat(64);
const SETUP_TOKEN = "S".repeat(42) + "_";
const INVITE_TOKEN = "I".repeat(42) + "-";
const ISSUED_TOKEN = "N".repeat(42) + "_";
const EXAMPLE_PASSWORD = "synthetic browser password";

type Role = "instance_admin" | "member";
type Account = { id: string; username: string; role: Role };
type Invitation = {
  id: string;
  issue_request_id: string | null;
  created_at: string;
  expires_at: string;
  status: "issued" | "expired" | "revoked" | "consumed";
  revocation_reason: "manual" | "restore" | null;
};

const admin: Account = {
  id: "00000000-0000-4000-8000-000000000001",
  username: "example-admin",
  role: "instance_admin",
};
const member: Account = {
  id: "00000000-0000-4000-8000-000000000002",
  username: "example-member",
  role: "member",
};

type Fake = {
  signedIn: Account | null;
  requests: string[];
  bodies: Record<string, unknown>[];
  invitations: Invitation[];
  setupCode?: string;
  registerCode?: string;
  issueFailure?: "lost";
  // Simulates another tab replacing the session cookie.
  rejectCsrfFor?: string;
  // Simulates an anonymous session that lapsed before the first submit.
  lapsedAnonymous?: boolean;
};

function error(route: Route, status: number, code: string) {
  return route.fulfill({
    status,
    json: { error: { code, message: "synthetic", request_id: "0".repeat(32) } },
  });
}

async function mockV2(page: Page, fake: Fake) {
  // The SQLite fixture serves the bundle only at / and /login; the V2 server
  // also serves it at /setup and /register.
  await page.route(/\/(setup|register)(\?.*)?$/, async (route) => {
    const response = await route.fetch({
      url: new URL("/login", route.request().url()).href,
    });
    await route.fulfill({ response });
  });
  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v2", "");
    fake.requests.push(`${request.method()} ${path}${url.search}`);
    if (request.method() === "POST") {
      if (request.headers()["x-csrf-token"] !== CSRF)
        return error(route, 403, "csrf_rejected");
      if (fake.rejectCsrfFor === path) {
        fake.rejectCsrfFor = undefined;
        return error(route, 403, "csrf_rejected");
      }
      if (fake.lapsedAnonymous && path === "/auth/login") {
        fake.lapsedAnonymous = false;
        return error(route, 401, "authentication_required");
      }
      fake.bodies.push({ path, ...(request.postDataJSON() ?? {}) });
    }
    const body = request.method() === "POST" ? request.postDataJSON() : null;
    switch (`${request.method()} ${path}`) {
      case "GET /auth/csrf":
        return route.fulfill({
          json: { authenticated: fake.signedIn !== null, csrf_token: CSRF },
        });
      case "GET /me":
        return fake.signedIn
          ? route.fulfill({
              json: {
                authenticated: true,
                user: fake.signedIn,
                portfolio: { id: "00000000-0000-4000-8000-0000000000ff" },
              },
            })
          : error(route, 401, "authentication_required");
      case "POST /auth/login": {
        const account = [admin, member].find(
          (item) => item.username === body.username,
        );
        if (!account || body.password !== EXAMPLE_PASSWORD)
          return error(route, 401, "invalid_credentials");
        fake.signedIn = account;
        return route.fulfill({
          json: { authenticated: true, csrf_token: CSRF },
        });
      }
      case "POST /auth/setup":
        return fake.setupCode
          ? error(
              route,
              fake.setupCode === "setup_closed" ? 409 : 400,
              fake.setupCode,
            )
          : route.fulfill({ status: 201, json: { initialized: true } });
      case "POST /auth/register":
        return fake.registerCode
          ? error(
              route,
              fake.registerCode === "setup_required" ? 409 : 400,
              fake.registerCode,
            )
          : route.fulfill({ status: 201, json: { registered: true } });
      case "POST /auth/logout":
        fake.signedIn = null;
        return route.fulfill({ status: 204 });
      case "POST /auth/activity":
        return route.fulfill({ status: 204 });
    }
    if (path.startsWith("/admin/")) {
      if (!fake.signedIn) return error(route, 401, "authentication_required");
      if (fake.signedIn.role !== "instance_admin")
        return error(route, 403, "admin_required");
      if (request.method() === "GET" && path === "/admin/invitations") {
        const lookup = url.searchParams.get("issue_request_id");
        return route.fulfill({
          json: {
            items: lookup
              ? fake.invitations.filter(
                  (item) => item.issue_request_id === lookup,
                )
              : fake.invitations,
            next_after: null,
          },
        });
      }
      if (request.method() === "POST" && path === "/admin/invitations") {
        const invitation: Invitation = {
          id: `00000000-0000-4000-8000-${String(fake.invitations.length + 100).padStart(12, "0")}`,
          issue_request_id: body.issue_request_id,
          created_at: "2026-11-12T15:00:00.000000Z",
          expires_at: "2026-11-13T15:00:00.000000Z",
          status: "issued",
          revocation_reason: null,
        };
        fake.invitations.push(invitation);
        if (fake.issueFailure === "lost") return route.abort("failed");
        return route.fulfill({
          status: 201,
          json: {
            id: invitation.id,
            issue_request_id: invitation.issue_request_id,
            invite_token: ISSUED_TOKEN,
            expires_at: invitation.expires_at,
          },
        });
      }
      const revoke = path.match(/^\/admin\/invitations\/([^/]+)\/revoke$/);
      if (request.method() === "POST" && revoke) {
        const invitation = fake.invitations.find(
          (item) => item.id === revoke[1],
        );
        if (!invitation || invitation.status !== "issued")
          return error(route, 409, "invite_not_active");
        invitation.status = "revoked";
        invitation.revocation_reason = "manual";
        return route.fulfill({ status: 204 });
      }
    }
    return error(route, 404, "not_found");
  });
}

function newFake(overrides: Partial<Fake> = {}): Fake {
  return {
    signedIn: null,
    requests: [],
    bodies: [],
    invitations: [
      {
        id: "00000000-0000-4000-8000-000000000010",
        issue_request_id: null,
        created_at: "2026-11-01T15:00:00.000000Z",
        expires_at: "2026-11-02T15:00:00.000000Z",
        status: "consumed",
        revocation_reason: null,
      },
      {
        id: "00000000-0000-4000-8000-000000000011",
        issue_request_id: null,
        created_at: "2026-11-03T15:00:00.000000Z",
        expires_at: "2026-11-04T15:00:00.000000Z",
        status: "revoked",
        revocation_reason: "restore",
      },
    ],
    ...overrides,
  };
}

async function expectAccessible(page: Page) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
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
}

async function signIn(page: Page, account: Account) {
  await page.getByLabel("Username").fill(account.username);
  await page.getByLabel("Password", { exact: true }).fill(EXAMPLE_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
}

async function storedText(page: Page) {
  return page.evaluate(() =>
    JSON.stringify([
      { ...localStorage },
      { ...sessionStorage },
      location.href,
      history.state,
    ]),
  );
}

test("first setup validates fields, strips the token and leads to sign-in", async ({
  page,
}) => {
  const fake = newFake();
  await mockV2(page, fake);
  await page.goto(`/setup?token=${SETUP_TOKEN}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Set up Kurafolio",
  );
  await expect(page).toHaveURL(/\/setup$/);
  await expectAccessible(page);

  const username = page.getByLabel("Username");
  const password = page.getByLabel("Password", { exact: true });
  const confirmation = page.getByLabel("Confirm password");
  const submit = page.getByRole("button", { name: "Create administrator" });

  await username.fill("example-admin");
  await password.fill("too short");
  await confirmation.fill("too short");
  await submit.click();
  await expect(password).toBeFocused();
  await expect(password).toHaveAttribute("aria-invalid", "true");
  await expect(password).toHaveAccessibleDescription(
    "At least 15 characters. Spaces are allowed. Use at least 15 characters.",
  );

  await password.fill(EXAMPLE_PASSWORD);
  await confirmation.fill(EXAMPLE_PASSWORD + "!");
  await submit.click();
  await expect(confirmation).toBeFocused();
  await expect(confirmation).toHaveAccessibleDescription(
    "The two passwords do not match.",
  );
  await expect(password).not.toHaveAttribute("aria-invalid");
  expect(fake.requests.filter((item) => item.startsWith("POST"))).toEqual([]);
  await expectAccessible(page);

  await confirmation.fill(EXAMPLE_PASSWORD);
  await submit.click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("status")).toHaveText(
    "Setup is complete. Sign in with the account you just created.",
  );
  await expect(page.getByLabel("Username")).toHaveValue("example-admin");
  expect(fake.bodies).toEqual([
    {
      path: "/auth/setup",
      setup_token: SETUP_TOKEN,
      username: "example-admin",
      password: EXAMPLE_PASSWORD,
    },
  ]);
  expect(await storedText(page)).not.toContain(SETUP_TOKEN);
  expect(await storedText(page)).not.toContain(EXAMPLE_PASSWORD);
});

test("setup without a usable link explains the operator step and shows no form", async ({
  page,
}) => {
  await mockV2(page, newFake());
  for (const path of ["/setup", "/setup?token=short"]) {
    await page.goto(path);
    await expect(
      page.getByText("First setup starts on the server."),
    ).toBeVisible();
    await expect(page.getByRole("textbox")).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Go to sign-in" }),
    ).toBeVisible();
  }
  await expectAccessible(page);

  for (const [code, message] of [
    [
      "setup_rejected",
      "This setup link has expired, was revoked or has already been used.",
    ],
    ["setup_closed", "Kurafolio is already set up on this server."],
  ]) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await mockV2(page, newFake({ setupCode: code }));
    await page.goto(`/setup?token=${SETUP_TOKEN}`);
    await page.getByLabel("Username").fill("example-admin");
    await page.getByLabel("Password", { exact: true }).fill(EXAMPLE_PASSWORD);
    await page.getByLabel("Confirm password").fill(EXAMPLE_PASSWORD);
    await page.getByRole("button", { name: "Create administrator" }).click();
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(page.getByRole("textbox")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(code);
  }
});

test("registration handles missing, rejected and accepted invitations", async ({
  page,
}) => {
  await mockV2(page, newFake());
  await page.goto("/register");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Create your account",
  );
  await expect(
    page.getByText("This invitation link is incomplete"),
  ).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  await mockV2(page, newFake({ registerCode: "setup_required" }));
  await page.goto(`/register?token=${INVITE_TOKEN}`);
  await page.getByLabel("Username").fill("example-member");
  await page.getByLabel("Password", { exact: true }).fill(EXAMPLE_PASSWORD);
  await page.getByLabel("Confirm password").fill(EXAMPLE_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "This server is not set up yet.",
  );
  await expect(page.getByRole("textbox")).toHaveCount(0);

  // The server answers an inactive invitation and a taken username with the
  // same code, so the form stays for another username.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  const rejected = newFake({ registerCode: "registration_rejected" });
  await mockV2(page, rejected);
  await page.goto(`/register?token=${INVITE_TOKEN}`);
  await page.getByLabel("Username").fill("example member");
  await page.getByLabel("Password", { exact: true }).fill(EXAMPLE_PASSWORD);
  await page.getByLabel("Confirm password").fill(EXAMPLE_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByLabel("Username")).toHaveAccessibleDescription(
    /Use only English letters \(A–Z\), numbers, dots, hyphens and underscores/,
  );
  await page.getByLabel("Username").fill("example-member");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "the invitation has expired, was revoked or was already used",
  );
  await expect(page.locator("body")).not.toContainText("registration_rejected");
  await expectAccessible(page);

  await page.unrouteAll({ behavior: "ignoreErrors" });
  const accepted = newFake();
  await mockV2(page, accepted);
  await page.goto(`/register?token=${INVITE_TOKEN}`);
  await expect(page).toHaveURL(/\/register$/);
  await page.getByLabel("Username").fill("example-member");
  await page.getByLabel("Password", { exact: true }).fill(EXAMPLE_PASSWORD);
  await page.getByLabel("Confirm password").fill(EXAMPLE_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Your account is ready. Sign in to continue.",
  );
  expect(accepted.bodies[0]).toMatchObject({
    path: "/auth/register",
    invite_token: INVITE_TOKEN,
  });
  await signIn(page, member);
  expect(await storedText(page)).not.toContain(INVITE_TOKEN);
});

test("a failed sign-in shows one message, clears the password and hides codes", async ({
  page,
}) => {
  const fake = newFake();
  await mockV2(page, fake);
  await page.goto("/app/profile");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in");
  await expect(
    page.getByText(
      "Forgot your password? Ask the person who runs this server.",
    ),
  ).toBeVisible();
  await expectAccessible(page);

  await page.getByLabel("Username").fill(admin.username);
  const password = page.getByLabel("Password", { exact: true });
  await password.fill("wrong synthetic password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Username or password is incorrect.",
  );
  await expect(page.getByRole("alert")).toHaveCount(1);
  await expect(password).toHaveValue("");
  await expect(password).toBeFocused();
  await expect(page.locator("body")).not.toContainText("invalid_credentials");
  await expectAccessible(page);
});

test("an administrator issues, copies and revokes an invitation", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const fake = newFake();
  await mockV2(page, fake);
  await page.goto("/login");
  await signIn(page, admin);
  await expect(
    page.getByText("Signed in as example-admin").first(),
  ).toBeVisible();
  await page.getByRole("link", { name: "Profile" }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: "Invitations" }),
  ).toBeVisible();
  const table = page.getByRole("table");
  await expect(table.getByText("Used")).toBeVisible();
  await expect(table.getByText("Revoked (backup restored)")).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("button", { name: "Create invitation" }).click();
  const link = page.getByLabel("Invitation link");
  await expect(link).toHaveValue(
    new RegExp(`/register\\?token=${ISSUED_TOKEN}$`),
  );
  await expect(
    page.getByRole("heading", { name: "Invitation created" }),
  ).toBeFocused();
  await expect(link).toHaveAccessibleDescription(/^Expires /);
  await page.getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByText("Link copied.")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    await link.inputValue(),
  );
  expect(await storedText(page)).not.toContain(ISSUED_TOKEN);
  const issue = fake.bodies.find((item) => item.path === "/admin/invitations");
  expect(issue?.issue_request_id).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );
  await expectAccessible(page);

  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByLabel("Invitation link")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(ISSUED_TOKEN);
  const active = table.getByRole("row").filter({ hasText: "Active" });
  await expect(active).toHaveCount(1);

  await active.getByRole("button", { name: "Revoke" }).click();
  const dialog = page.getByRole("dialog", { name: "Revoke this invitation?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Keep invitation" }).click();
  await expect(dialog).toBeHidden();
  expect(fake.requests.some((item) => item.endsWith("/revoke"))).toBe(false);

  await active.getByRole("button", { name: "Revoke" }).click();
  await dialog.getByRole("button", { name: "Revoke invitation" }).click();
  await expect(dialog).toBeHidden();
  await expect(
    table.getByRole("row").filter({ hasText: "Active" }),
  ).toHaveCount(0);
  await expect(table.getByText("Revoked", { exact: true })).toBeVisible();
});

test("a lost issue response is found by request ID without showing a link", async ({
  page,
}) => {
  const fake = newFake({ issueFailure: "lost" });
  await mockV2(page, fake);
  await page.goto("/login");
  await signIn(page, admin);
  await page.goto("/app/profile");
  await page.getByRole("button", { name: "Create invitation" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "The invitation was created, but its link could not be shown.",
  );
  await expect(page.getByLabel("Invitation link")).toHaveCount(0);
  const issued = fake.bodies.find((item) => item.path === "/admin/invitations");
  expect(fake.requests).toContain(
    `GET /admin/invitations?issue_request_id=${issued?.issue_request_id}`,
  );
});

test("members never see or request invitation management", async ({ page }) => {
  const fake = newFake();
  await mockV2(page, fake);
  await page.goto("/login");
  await signIn(page, member);
  await page.getByRole("link", { name: "Profile" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Profile");
  await expect(page.getByRole("heading", { name: "Invitations" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Create invitation" }),
  ).toHaveCount(0);
  expect(fake.requests.filter((item) => item.includes("/admin/"))).toEqual([]);
});

test("sign-out, expiry and a different user leave no earlier session data", async ({
  page,
}) => {
  const fake = newFake();
  await mockV2(page, fake);
  await page.goto("/login");
  await signIn(page, admin);
  await page.goto("/app/profile");
  await expect(page.getByRole("table").getByText("Used")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("status")).toHaveText(
    "You signed out. Nothing from your session is kept in this window.",
  );
  expect(fake.requests).toContain("POST /auth/logout");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");

  const before = fake.requests.length;
  await signIn(page, member);
  await page.getByRole("link", { name: "Profile" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Profile");
  await expect(page.locator("body")).not.toContainText("example-admin");
  await expect(page.getByRole("table")).toHaveCount(0);
  expect(
    fake.requests.slice(before).filter((item) => item.includes("/admin/")),
  ).toEqual([]);

  // The server ends the session; the next request reports it.
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, admin);
  await page.getByRole("link", { name: "Profile" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  fake.signedIn = null;
  await page.getByRole("button", { name: "Create invitation" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("status")).toHaveText(
    "Your session ended. Sign in again to continue.",
  );
  await expect(page.getByRole("table")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("example-admin");
});

test("identity pages work in every locale, in dark mode and at phone width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ colorScheme: "dark" });
  await mockV2(page, newFake());
  for (const [locale, signInTitle, setupTitle, registerTitle] of [
    ["zh-TW", "登入", "設定 Kurafolio", "建立帳號"],
    ["zh-CN", "登录", "设置 Kurafolio", "创建账号"],
    ["en-CA", "Sign in", "Set up Kurafolio", "Create your account"],
  ]) {
    await page.goto("/login");
    await page.getByRole("combobox").selectOption(locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      signInTitle,
    );
    await expectAccessible(page);
    await page.goto(`/setup?token=${SETUP_TOKEN}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      setupTitle,
    );
    await expectAccessible(page);
    await page.goto(`/register?token=${INVITE_TOKEN}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      registerTitle,
    );
    await expectAccessible(page);
  }
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  // Keyboard only: sign in and open the menu without a pointer.
  await page.goto("/login");
  await page.getByLabel("Username").focus();
  await page.keyboard.type(member.username);
  await page.keyboard.press("Tab");
  await page.keyboard.type(EXAMPLE_PASSWORD);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
  await page.getByRole("button", { name: "Menu" }).focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Menu" });
  await expect(dialog.getByText("Signed in as example-member")).toBeVisible();
  await dialog.getByRole("button", { name: "Sign out" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sign in");
});

test("a signed-in action never resends as another tab's user", async ({
  page,
}) => {
  const fake = newFake();
  await mockV2(page, fake);
  await page.goto("/login");
  await signIn(page, admin);
  await page.goto("/app/profile");
  const active = page
    .getByRole("table")
    .getByRole("row")
    .filter({ hasText: "Active" });
  await page.getByRole("button", { name: "Create invitation" }).click();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(
    page.getByRole("button", { name: "Create invitation" }),
  ).toBeFocused();

  // Another tab signed in as someone else: the token no longer matches.
  const issued = fake.invitations.find((item) => item.status === "issued");
  fake.rejectCsrfFor = `/admin/invitations/${issued?.id}/revoke`;
  await active.getByRole("button", { name: /^Revoke the invitation/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Revoke invitation" })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("status")).toHaveText(
    "Your session ended. Sign in again to continue.",
  );
  expect(issued?.status).toBe("issued");
  expect(fake.requests.filter((item) => item.endsWith("/revoke"))).toHaveLength(
    1,
  );
});

test("a lapsed anonymous session is renewed once without a message", async ({
  page,
}) => {
  const fake = newFake({ lapsedAnonymous: true });
  await mockV2(page, fake);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/login");
  await signIn(page, admin);
  expect(
    fake.requests.filter((item) => item === "POST /auth/login"),
  ).toHaveLength(2);
  await page.goto("/app/profile");
  await expectAccessible(page);
});

test("a setup link opened while signed in asks to sign out first", async ({
  page,
}) => {
  const fake = newFake();
  await mockV2(page, fake);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/login");
  await signIn(page, admin);
  await page.goto(`/register?token=${INVITE_TOKEN}`);
  await expect(page.getByRole("alert")).toHaveText(
    "You are signed in as example-admin. Sign out before you use this link.",
  );
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expectAccessible(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Confirm password")).toBeVisible();
  expect(fake.requests).toContain("POST /auth/logout");
  await page.getByLabel("Username").fill("example-member");
  await page.getByLabel("Password", { exact: true }).fill(EXAMPLE_PASSWORD);
  await page.getByLabel("Confirm password").fill(EXAMPLE_PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Your account is ready. Sign in to continue.",
  );
  expect(fake.bodies.at(-1)).toMatchObject({ invite_token: INVITE_TOKEN });
});
