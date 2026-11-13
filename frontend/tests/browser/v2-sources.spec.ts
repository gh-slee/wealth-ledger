import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

// A stateful fake of the V2 source lifecycle API (WL-P0-006). Every value is
// synthetic; no real provider, account or installation is represented.
const CSRF = "c".repeat(64);
const OLD = "1".repeat(64);
const NEW = "2".repeat(64);
const API = "3".repeat(64);
const realm = {
  incarnation: "00000000-0000-4000-8000-0000000000aa",
  restore_epoch: "0",
};

type Status = "DISABLED" | "CONFIRMATION_REQUIRED" | "UNAVAILABLE" | "ENABLED";
type Capability = {
  capability: "FILE_IMPORT" | "PULL_API";
  active_installation_id: string | null;
  availability_generation: string | null;
  adapter_id: string | null;
  package_version: string | null;
  format_versions: string[];
  domain_contract_version: 1;
  parser_api_version: 2 | null;
  enablement: {
    enabled: boolean;
    installation_id: string | null;
    revision: string;
    generation: string;
  };
  status: Status;
  reason: string | null;
  connection_count: number;
};
type Source = {
  plugin_id: string;
  provider_id: string;
  display_name: string;
  publisher_label: string;
  docs_url: string | null;
  capabilities: Capability[];
};
type Connection = {
  id: string;
  connection_version: string;
  plugin_id: string;
  provider_id: string;
  capability: "FILE_IMPORT";
  installation_id: string;
  availability_generation: string;
  display_label: string;
  parser_source_alias: string | null;
  enabled: boolean;
  revision: string;
  generation: string;
  status: string;
  reason: string | null;
};
type Sent = { method: string; path: string; body: Record<string, unknown> };
type Fake = {
  sources: Source[];
  connections: Connection[];
  sent: Sent[];
  reads: { catalog: number; connections: number };
  receipts: Map<string, string>;
  // Apply the next write, then drop its response as a network failure would.
  loseNextResponse?: boolean;
  // Another tab changes this capability just before the next write arrives.
  concurrentChange?: boolean;
  // Every read fails, as during a network outage.
  failReads?: boolean;
  refuseCreate?: string;
};

function file(overrides: Partial<Capability> = {}): Capability {
  return {
    capability: "FILE_IMPORT",
    active_installation_id: OLD,
    availability_generation: "1",
    adapter_id: "example.adapter",
    package_version: "1.4.0",
    format_versions: ["holdings-v1", "holdings-v2"],
    domain_contract_version: 1,
    parser_api_version: 2,
    enablement: {
      enabled: false,
      installation_id: null,
      revision: "0",
      generation: "0",
    },
    status: "DISABLED",
    reason: null,
    connection_count: 0,
    ...overrides,
  };
}

function api(): Capability {
  return {
    ...file(),
    capability: "PULL_API",
    active_installation_id: API,
    package_version: "0.1.0",
    format_versions: [],
    status: "UNAVAILABLE",
    reason: "source_capability_unavailable",
  };
}

function brokerage(capability = file()): Source {
  return {
    plugin_id: "example.brokerage",
    provider_id: "example.brokerage",
    display_name: "Example Brokerage",
    publisher_label: "Kurafolio maintainers",
    docs_url: "https://example.com/docs/brokerage",
    capabilities: [capability, api()],
  };
}

function exchange(capability?: Capability): Source {
  return {
    plugin_id: "example.exchange",
    provider_id: "example.exchange",
    display_name: "Example Exchange",
    publisher_label: "Kurafolio maintainers",
    docs_url: null,
    capabilities: [
      capability ??
        file({
          active_installation_id: NEW,
          package_version: "2.0.0",
          format_versions: ["orders-v1"],
          enablement: {
            enabled: true,
            installation_id: NEW,
            revision: "2",
            generation: "1",
          },
          status: "ENABLED",
          connection_count: 1,
        }),
    ],
  };
}

function exchangeConnection(): Connection {
  return {
    id: "00000000-0000-4000-8000-000000000301",
    connection_version: "4".repeat(64),
    plugin_id: "example.exchange",
    provider_id: "example.exchange",
    capability: "FILE_IMPORT",
    installation_id: NEW,
    availability_generation: "1",
    display_label: "Example spot orders",
    parser_source_alias: "spot-main",
    enabled: true,
    revision: "1",
    generation: "1",
    status: "ENABLED",
    reason: null,
  };
}

function newFake(overrides: Partial<Fake> = {}): Fake {
  return {
    sources: [brokerage(), exchange()],
    connections: [exchangeConnection()],
    sent: [],
    reads: { catalog: 0, connections: 0 },
    receipts: new Map(),
    ...overrides,
  };
}

function error(route: Route, status: number, code: string) {
  return route.fulfill({
    status,
    json: { error: { code, message: "synthetic", request_id: "0".repeat(32) } },
  });
}

const bump = (value: string) => String(Number(value) + 1);

function connectionStatus(fake: Fake, item: Connection) {
  const source = fake.sources.find((s) => s.plugin_id === item.plugin_id);
  const capability = source?.capabilities.find(
    (c) => c.capability === "FILE_IMPORT",
  );
  if (!item.enabled) return "DISABLED";
  if (capability?.status !== "ENABLED") return "SOURCE_DISABLED";
  return capability.enablement.installation_id === item.installation_id
    ? "ENABLED"
    : "CONFIRMATION_REQUIRED";
}

function receipt(resource: unknown, operation: string) {
  return {
    operation_id: operation,
    replayed: false,
    representation: "committed",
    changed: true,
    resource,
    catalog_revision: "1",
    state_revision: "1",
    realm,
  };
}

async function mockV2(page: Page, fake: Fake) {
  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v2", "");
    const method = request.method();
    if (method === "GET" && path === "/auth/csrf")
      return route.fulfill({
        json: { authenticated: true, csrf_token: CSRF },
      });
    if (method === "GET" && path === "/me")
      return route.fulfill({
        json: {
          authenticated: true,
          user: {
            id: "00000000-0000-4000-8000-000000000002",
            username: "example-member",
            role: "member",
          },
          portfolio: { id: "00000000-0000-4000-8000-0000000000ff" },
        },
      });
    if (path === "/auth/activity") return route.fulfill({ status: 204 });
    if (fake.failReads && method === "GET")
      return route.abort("internetdisconnected");
    if (method === "GET" && path === "/sources") {
      fake.reads.catalog++;
      return route.fulfill({
        json: {
          items: fake.sources,
          next_after: null,
          catalog_revision: "1",
          state_revision: "1",
          realm,
        },
      });
    }
    if (method === "GET" && path === "/source-connections") {
      fake.reads.connections++;
      return route.fulfill({
        json: {
          items: fake.connections.map((item) => ({
            ...item,
            status: connectionStatus(fake, item),
          })),
          next_after: null,
          catalog_revision: "1",
          state_revision: "1",
          realm,
        },
      });
    }

    if (request.headers()["x-csrf-token"] !== CSRF)
      return error(route, 403, "csrf_rejected");
    const body = request.postDataJSON() as Record<string, unknown>;
    fake.sent.push({ method, path, body });
    const operation = String(body.operation_id);
    const replay = fake.receipts.get(operation);
    if (replay !== undefined) {
      if (replay !== JSON.stringify({ path, body }))
        return error(route, 409, "source_idempotency_conflict");
      // An exact retry gets the stored receipt and changes nothing.
      return route.fulfill({
        json: { ...receipt({}, operation), replayed: true },
      });
    }
    let resource: unknown;
    const capabilityRoute = path.match(
      /^\/sources\/([^/]+)\/capabilities\/(FILE_IMPORT|PULL_API)$/,
    );
    if (method === "PUT" && capabilityRoute) {
      const capability = fake.sources
        .find((item) => item.plugin_id === capabilityRoute[1])
        ?.capabilities.find((item) => item.capability === capabilityRoute[2]);
      if (!capability) return error(route, 404, "not_found");
      if (fake.concurrentChange) {
        fake.concurrentChange = false;
        capability.enablement.revision = bump(capability.enablement.revision);
      }
      if (capability.status === "UNAVAILABLE" && body.enabled === true)
        return error(route, 409, "source_unavailable");
      if (body.expected_revision !== capability.enablement.revision)
        return error(route, 409, "source_revision_conflict");
      capability.enablement = {
        enabled: body.enabled as boolean,
        installation_id: body.installation_id as string | null,
        revision: bump(capability.enablement.revision),
        generation: bump(capability.enablement.generation),
      };
      capability.status = !capability.enablement.enabled
        ? "DISABLED"
        : capability.enablement.installation_id ===
            capability.active_installation_id
          ? "ENABLED"
          : "CONFIRMATION_REQUIRED";
      resource = capability.enablement;
    } else if (method === "POST" && path === "/source-connections") {
      if (fake.refuseCreate) return error(route, 409, fake.refuseCreate);
      const created: Connection = {
        ...exchangeConnection(),
        id: "00000000-0000-4000-8000-000000000302",
        plugin_id: String(body.plugin_id),
        provider_id: String(body.plugin_id),
        installation_id: String(body.installation_id),
        display_label: String(body.display_label),
        parser_source_alias: body.parser_source_alias as string | null,
      };
      fake.connections.push(created);
      resource = created;
    } else if (method === "PUT" && path.startsWith("/source-connections/")) {
      const item = fake.connections.find(
        (connection) => connection.id === path.split("/")[2],
      );
      if (!item) return error(route, 404, "not_found");
      if (body.expected_revision !== item.revision)
        return error(route, 409, "source_revision_conflict");
      // As in source_schema.py: turning a connection on or moving its pin
      // needs the source enabled at exactly that installation.
      const needsAuthorization =
        (!item.enabled && body.enabled === true) ||
        item.installation_id !== body.installation_id;
      const enablement = fake.sources
        .find((source) => source.plugin_id === item.plugin_id)
        ?.capabilities.find((c) => c.capability === "FILE_IMPORT")?.enablement;
      if (
        needsAuthorization &&
        (!enablement?.enabled ||
          enablement.installation_id !== body.installation_id)
      )
        return error(route, 409, "source_context_incompatible");
      Object.assign(item, {
        enabled: body.enabled,
        installation_id: body.installation_id,
        display_label: body.display_label,
        revision: bump(item.revision),
      });
      resource = item;
    } else return error(route, 404, "not_found");
    fake.receipts.set(operation, JSON.stringify({ path, body }));
    if (fake.loseNextResponse) {
      fake.loseNextResponse = false;
      return route.abort("connectionreset");
    }
    return route.fulfill({
      status: method === "POST" ? 201 : 200,
      json: receipt(resource, operation),
    });
  });
}

async function openStore(page: Page, fake: Fake) {
  await mockV2(page, fake);
  await page.goto("/app/sources");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Parser Plugin Store",
  );
  await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
}

function sourceItem(page: Page, name: string) {
  return page
    .getByRole("main")
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { level: 2, name }) });
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

test("lists only the installed sources with versions, formats and status", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  const fake = newFake();
  await openStore(page, fake);

  const list = page.getByRole("main").locator(".v2-source-list > li");
  await expect(list).toHaveCount(2);

  const brokerageItem = sourceItem(page, "Example Brokerage");
  await expect(brokerageItem).toContainText(
    "Published by Kurafolio maintainers",
  );
  await expect(brokerageItem).toContainText("1.4.0");
  await expect(brokerageItem).toContainText("holdings-v1, holdings-v2");
  await expect(
    brokerageItem.getByRole("switch", {
      name: "File import for Example Brokerage",
    }),
  ).toHaveAttribute("aria-checked", "false");
  // API sync is shown as planned, with no control.
  await expect(brokerageItem).toContainText("Automatic sync");
  await expect(brokerageItem).toContainText("Planned");
  await expect(brokerageItem.getByRole("switch")).toHaveCount(1);
  await expect(
    brokerageItem.getByRole("link", { name: /Documentation/ }),
  ).toHaveAttribute("href", "https://example.com/docs/brokerage");

  const exchangeItem = sourceItem(page, "Example Exchange");
  await expect(exchangeItem).toContainText("Enabled");
  await expect(exchangeItem).toContainText("Example spot orders");
  await expect(exchangeItem).toContainText("Alias: spot-main");

  // Official plugins only: a link to the guide, no upload control.
  await expect(
    page.getByRole("link", { name: /parser contribution guide/ }),
  ).toHaveAttribute("href", /docs\/parser-sdk\.md$/);
  await expect(page.locator("input[type=file]")).toHaveCount(0);
  await expectAccessible(page);
});

test("enabling a file capability sends the DTO fields and shows Enabled", async ({
  page,
}) => {
  const fake = newFake();
  await openStore(page, fake);
  const item = sourceItem(page, "Example Brokerage");
  const toggle = item.getByRole("switch", {
    name: "File import for Example Brokerage",
  });
  await toggle.focus();
  await page.keyboard.press("Space");

  await expect(page.getByRole("status")).toHaveText(
    "Source turned on. Add a connection to import its files.",
  );
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(toggle).toBeFocused();
  await expect(item.getByText("Enabled", { exact: true })).toBeVisible();
  expect(fake.sent).toHaveLength(1);
  expect(fake.sent[0]).toMatchObject({
    method: "PUT",
    path: "/sources/example.brokerage/capabilities/FILE_IMPORT",
    body: {
      expected_revision: "0",
      expected_realm: realm,
      enabled: true,
      installation_id: OLD,
    },
  });
  expect(String(fake.sent[0].body.operation_id)).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
  );

  // Connections become available for the enabled source.
  await item.getByRole("button", { name: "Add connection" }).click();
  await item.getByLabel("Name").fill("Example joint account");
  await item.getByRole("button", { name: "Add connection" }).click();
  await expect(page.getByRole("status")).toHaveText("Connection added.");
  await expect(item).toContainText("Example joint account");
  await expect(
    item.getByRole("button", { name: "Add connection" }),
  ).toBeFocused();
  expect(fake.sent[1]).toMatchObject({
    method: "POST",
    path: "/source-connections",
    body: {
      expected_revision: "0",
      expected_realm: realm,
      plugin_id: "example.brokerage",
      capability: "FILE_IMPORT",
      installation_id: OLD,
      display_label: "Example joint account",
      parser_source_alias: null,
    },
  });
});

test("a newer installed version needs explicit confirmation", async ({
  page,
}) => {
  const fake = newFake({
    sources: [
      brokerage(
        file({
          active_installation_id: NEW,
          package_version: "1.5.0",
          enablement: {
            enabled: true,
            installation_id: OLD,
            revision: "3",
            generation: "2",
          },
          status: "CONFIRMATION_REQUIRED",
        }),
      ),
      exchange(),
    ],
  });
  await openStore(page, fake);
  const item = sourceItem(page, "Example Brokerage");
  await expect(item).toContainText("Needs confirmation");
  await expect(item.getByRole("switch")).toHaveCount(0);
  await item.getByRole("button", { name: "Review version 1.5.0" }).click();
  const dialog = page.getByRole("dialog", {
    name: "Use version 1.5.0 of Example Brokerage?",
  });
  await expect(dialog).toContainText(
    "Imports from Example Brokerage will use it after you confirm.",
  );
  expect(fake.sent).toHaveLength(0);
  await dialog.getByRole("button", { name: "Use version 1.5.0" }).click();
  await expect(page.getByRole("status")).toHaveText("Version confirmed.");
  expect(fake.sent[0].body).toMatchObject({
    enabled: true,
    installation_id: NEW,
    expected_revision: "3",
  });
  await expect(
    item.getByRole("switch", { name: "File import for Example Brokerage" }),
  ).toHaveAttribute("aria-checked", "true");
});

test("disabling a source with data says existing data stays visible", async ({
  page,
}) => {
  const fake = newFake();
  await openStore(page, fake);
  const item = sourceItem(page, "Example Exchange");
  const toggle = item.getByRole("switch", {
    name: "File import for Example Exchange",
  });
  await toggle.click();
  const dialog = page.getByRole("dialog", {
    name: "Turn off Example Exchange?",
  });
  await expect(dialog).toContainText(
    "Data you already imported from Example Exchange stays visible. New imports from it stop",
  );
  // Cancelling sends nothing and returns focus to the switch.
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(toggle).toBeFocused();
  expect(fake.sent).toHaveLength(0);

  await toggle.click();
  await dialog.getByRole("button", { name: "Turn off" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Source turned off. Existing data stays visible.",
  );
  expect(fake.sent[0].body).toMatchObject({
    enabled: false,
    installation_id: null,
    expected_revision: "2",
  });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(toggle).toBeFocused();
  // The connection is still listed, now marked as off with its source.
  await expect(item).toContainText("Source off");

  // Once the connection is off too, it cannot be turned on until the source is.
  await item
    .getByRole("button", { name: "Turn off Example spot orders" })
    .click();
  await page
    .getByRole("dialog", { name: "Turn off Example spot orders?" })
    .getByRole("button", { name: "Turn off" })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Connection turned off. Its data stays readable.",
  );
  await expect(item).toContainText(
    "Turn on file import for Example Exchange to use this connection again.",
  );
  await expect(item.getByRole("button", { name: /^Turn on/ })).toHaveCount(0);
});

test("a connection turned off before a version change turns on with the confirmed version", async ({
  page,
}) => {
  const connection = { ...exchangeConnection(), installation_id: OLD };
  connection.enabled = false;
  const fake = newFake({ connections: [connection] });
  await openStore(page, fake);
  const item = sourceItem(page, "Example Exchange");
  const button = item.getByRole("button", {
    name: "Turn on Example spot orders",
  });
  await expect(button).toHaveText("Turn on with version 2.0.0");
  await button.click();
  await expect(page.getByRole("status")).toHaveText("Connection turned on.");
  expect(fake.sent[0].body).toMatchObject({
    enabled: true,
    installation_id: NEW,
  });
  await expect(item.locator(".v2-connection")).toContainText("Enabled");
});

test("a refused connection keeps the form and what was typed", async ({
  page,
}) => {
  const fake = newFake({ refuseCreate: "source_capacity_reached" });
  await openStore(page, fake);
  const item = sourceItem(page, "Example Exchange");
  await item.getByRole("button", { name: "Add connection" }).click();
  await item.getByLabel("Name", { exact: true }).fill("Example second stream");
  await item.getByLabel("Alias (optional)").fill("second");
  await item.getByRole("button", { name: "Add connection" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "You have reached the limit of 256 connections.",
  );
  await expect(item.getByLabel("Name", { exact: true })).toHaveValue(
    "Example second stream",
  );
  await expect(item.getByLabel("Alias (optional)")).toHaveValue("second");
});

test("an enabled source that became unavailable can still be turned off", async ({
  page,
}) => {
  const fake = newFake({
    sources: [
      brokerage(),
      exchange(
        file({
          active_installation_id: NEW,
          package_version: "2.0.0",
          enablement: {
            enabled: true,
            installation_id: NEW,
            revision: "2",
            generation: "1",
          },
          status: "UNAVAILABLE",
          reason: "source_unavailable",
        }),
      ),
    ],
  });
  await openStore(page, fake);
  const item = sourceItem(page, "Example Exchange");
  await expect(item.getByRole("switch")).toHaveCount(0);
  await item.getByRole("button", { name: "Turn off" }).first().click();
  await page
    .getByRole("dialog", { name: "Turn off Example Exchange?" })
    .getByRole("button", { name: "Turn off" })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Source turned off. Existing data stays visible.",
  );
  expect(fake.sent[0].body).toMatchObject({
    enabled: false,
    installation_id: null,
  });
});

test("during an outage the list and the same-request retry stay available", async ({
  page,
}) => {
  const fake = newFake({ loseNextResponse: true });
  await openStore(page, fake);
  fake.failReads = true;
  await sourceItem(page, "Example Brokerage").getByRole("switch").click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText(
    "We could not confirm whether your change was saved.",
  );
  await expect(page.getByText("We could not refresh this list")).toBeVisible();
  await expect(sourceItem(page, "Example Brokerage")).toBeVisible();
  fake.failReads = false;
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Source turned on. Add a connection to import its files.",
  );
  expect(fake.sent).toHaveLength(2);
  expect(fake.sent[1]).toEqual(fake.sent[0]);
});

test("a stale revision reloads the list and says nothing was applied", async ({
  page,
}) => {
  const fake = newFake({ concurrentChange: true });
  await openStore(page, fake);
  const before = fake.reads.catalog;
  await sourceItem(page, "Example Brokerage")
    .getByRole("switch", { name: "File import for Example Brokerage" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Your change was not applied because this list changed",
  );
  await expect.poll(() => fake.reads.catalog).toBeGreaterThan(before);
  await expect(
    sourceItem(page, "Example Brokerage").getByRole("switch"),
  ).toHaveAttribute("aria-checked", "false");
  // Trying again uses the reloaded revision and succeeds.
  await sourceItem(page, "Example Brokerage").getByRole("switch").click();
  await expect(page.getByRole("status")).toHaveText(
    "Source turned on. Add a connection to import its files.",
  );
  expect(fake.sent.at(-1)?.body.expected_revision).toBe("1");
});

test("an unavailable capability offers no control and states why", async ({
  page,
}) => {
  const fake = newFake({
    sources: [
      brokerage(file({ status: "UNAVAILABLE", reason: "source_unavailable" })),
      exchange(),
    ],
  });
  await openStore(page, fake);
  const item = sourceItem(page, "Example Brokerage");
  await expect(item.getByRole("switch")).toHaveCount(0);
  await expect(item).toContainText("Unavailable");
  await expect(item).toContainText(
    "Ask your operator to install or repair it.",
  );
  await expect(
    item.getByRole("button", { name: "Add connection" }),
  ).toHaveCount(0);
});

test("a retry after a lost response sends the same operation ID", async ({
  page,
}) => {
  const fake = newFake({ loseNextResponse: true });
  await openStore(page, fake);
  const toggle = sourceItem(page, "Example Brokerage").getByRole("switch");
  await toggle.click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText(
    "We could not confirm whether your change was saved.",
  );
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Source turned on. Add a connection to import its files.",
  );
  expect(fake.sent).toHaveLength(2);
  expect(fake.sent[1]).toEqual(fake.sent[0]);
  await expect(toggle).toHaveAttribute("aria-checked", "true");
});

test("connections can be renamed, turned off and turned on", async ({
  page,
}) => {
  const fake = newFake();
  await openStore(page, fake);
  const item = sourceItem(page, "Example Exchange");

  const rename = item.getByRole("button", {
    name: "Rename Example spot orders",
  });
  await rename.click();
  const dialog = page.getByRole("dialog", { name: "Rename connection" });
  const field = dialog.getByLabel("Name");
  await expect(field).toHaveValue("Example spot orders");
  await field.fill(" ");
  await dialog.getByRole("button", { name: "Save name" }).click();
  await expect(dialog.getByText("Enter a name.")).toBeVisible();
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await field.fill("Example margin orders");
  await dialog.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("status")).toHaveText("Connection renamed.");
  expect(fake.sent[0]).toMatchObject({
    method: "PUT",
    path: "/source-connections/00000000-0000-4000-8000-000000000301",
    body: {
      expected_revision: "1",
      expected_realm: realm,
      enabled: true,
      installation_id: NEW,
      display_label: "Example margin orders",
    },
  });

  await item
    .getByRole("button", { name: "Turn off Example margin orders" })
    .click();
  const confirm = page.getByRole("dialog", {
    name: "Turn off Example margin orders?",
  });
  await expect(confirm).toContainText(
    "Data imported through this connection stays readable.",
  );
  await confirm.getByRole("button", { name: "Turn off" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Connection turned off. Its data stays readable.",
  );
  expect(fake.sent[1].body).toMatchObject({
    enabled: false,
    expected_revision: "2",
  });
  await expect(item.locator(".v2-connection")).toContainText("Disabled");

  await item
    .getByRole("button", { name: "Turn on Example margin orders" })
    .click();
  await expect(page.getByRole("status")).toHaveText("Connection turned on.");
  expect(fake.sent[2].body).toMatchObject({
    enabled: true,
    expected_revision: "3",
  });
});

for (const [locale, heading, enabled] of [
  ["zh-TW", "Parser Plugin Store", "已啟用"],
  ["zh-CN", "Parser Plugin Store", "已启用"],
] as const) {
  test(`renders in ${locale} at phone width in dark mode`, async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.addInitScript(
      (value) => localStorage.setItem("kurafolio-v2-locale", value),
      locale,
    );
    const fake = newFake();
    await mockV2(page, fake);
    await page.goto("/app/sources");
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).not.toHaveText(heading);
    await expect(
      sourceItem(page, "Example Exchange")
        .getByText(enabled, { exact: true })
        .first(),
    ).toBeVisible();
    await expectAccessible(page);
  });
}

test("is keyboard reachable with visible focus in light mode at 1024 px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await page.emulateMedia({ colorScheme: "light" });
  await openStore(page, newFake());
  const toggle = sourceItem(page, "Example Brokerage").getByRole("switch");
  for (let step = 0; step < 40; step++) {
    await page.keyboard.press("Tab");
    if (await toggle.evaluate((element) => element === document.activeElement))
      break;
  }
  await expect(toggle).toBeFocused();
  const outline = await toggle.evaluate(
    (element) => getComputedStyle(element).outlineStyle,
  );
  expect(outline).not.toBe("none");
  await expectAccessible(page);
});
