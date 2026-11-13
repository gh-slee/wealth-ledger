import { describe, expect, it } from "vitest";
import { catalogs } from "../src/lib/i18n";
import { V2Error } from "../src/v2/api";
import {
  capabilityView,
  connectionLabel,
  failureMessage,
  importableSources,
  pagePath,
  retryable,
  textProblem,
  type Capability,
  type CatalogItem,
  type SourceConnection,
} from "../src/v2/sources-model";

const HASH = "a".repeat(64);
const realm = {
  incarnation: "00000000-0000-4000-8000-0000000000aa",
  restore_epoch: "0",
};

function capability(overrides: Partial<Capability> = {}): Capability {
  return {
    capability: "FILE_IMPORT",
    active_installation_id: HASH,
    availability_generation: "1",
    adapter_id: "example.adapter",
    package_version: "1.0.0",
    format_versions: ["v1"],
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

function source(id: string, capabilities: Capability[]): CatalogItem {
  return {
    plugin_id: id,
    provider_id: id,
    display_name: id,
    publisher_label: "Example",
    docs_url: null,
    capabilities,
  };
}

function connection(
  plugin: string,
  status: SourceConnection["status"],
): SourceConnection {
  return {
    id: "00000000-0000-4000-8000-000000000101",
    connection_version: HASH,
    plugin_id: plugin,
    provider_id: plugin,
    capability: "FILE_IMPORT",
    installation_id: HASH,
    availability_generation: "1",
    display_label: "Example",
    parser_source_alias: null,
    enabled: status !== "DISABLED",
    revision: "1",
    generation: "1",
    status,
    reason: null,
  };
}

describe("source capability view", () => {
  it("offers a switch only for a file capability that can change", () => {
    expect(capabilityView(capability()).switchable).toBe(true);
    expect(capabilityView(capability({ status: "ENABLED" })).switchable).toBe(
      true,
    );
    expect(
      capabilityView(capability({ status: "UNAVAILABLE" })).switchable,
    ).toBe(false);
    expect(
      capabilityView(capability({ capability: "PULL_API", status: "ENABLED" })),
    ).toMatchObject({
      label: "wlP0011c.status.planned",
      switchable: false,
    });
  });

  it("explains why an unavailable capability cannot be enabled", () => {
    expect(
      capabilityView(
        capability({ status: "UNAVAILABLE", reason: "source_unavailable" }),
      ).explanation,
    ).toBe("wlP0011c.unavailableExplain");
    expect(
      capabilityView(
        capability({
          status: "UNAVAILABLE",
          reason: "source_counter_exhausted",
        }),
      ).explanation,
    ).toBe("wlP0011c.counterExhausted");
    // Nothing installed means nothing to enable.
    expect(
      capabilityView(capability({ active_installation_id: null })).switchable,
    ).toBe(false);
  });

  it("names the version a confirmation is for", () => {
    expect(
      capabilityView(
        capability({ status: "CONFIRMATION_REQUIRED", package_version: "2.1" }),
      ).confirmVersion,
    ).toBe("2.1");
  });

  it("labels every connection state", () => {
    for (const status of [
      "ENABLED",
      "DISABLED",
      "SOURCE_DISABLED",
      "CONFIRMATION_REQUIRED",
      "UNAVAILABLE",
    ] as const)
      expect(connectionLabel(status)).not.toBe("wlP0011c.status.unknown");
  });
});

describe("Import Data offer", () => {
  it("lists only enabled file sources with an enabled connection", () => {
    const enabled = source("enabled", [capability({ status: "ENABLED" })]);
    const off = source("off", [capability()]);
    const found = importableSources(
      [enabled, off],
      [
        connection("enabled", "ENABLED"),
        connection("enabled", "DISABLED"),
        connection("off", "SOURCE_DISABLED"),
      ],
    );
    expect(found.map((item) => item.source.plugin_id)).toEqual(["enabled"]);
    expect(found[0].connections).toHaveLength(1);
  });
});

describe("source requests", () => {
  it("carries the revisions and realm with a cursor", () => {
    expect(pagePath("/sources", null)).toBe("/sources?limit=100");
    const next = new URLSearchParams(
      pagePath("/sources", {
        items: [],
        next_after: "example.next",
        catalog_revision: "3",
        state_revision: "4",
        realm,
      }).split("?")[1],
    );
    expect(Object.fromEntries(next)).toEqual({
      limit: "100",
      after: "example.next",
      catalog_revision: "3",
      state_revision: "4",
      incarnation: realm.incarnation,
      restore_epoch: "0",
    });
  });

  it("retries only when the outcome is unknown", () => {
    expect(retryable(new TypeError("Failed to fetch"))).toBe(true);
    expect(retryable(new V2Error(503, "source_commit_uncertain"))).toBe(true);
    expect(retryable(new V2Error(500, "internal_error"))).toBe(true);
    expect(retryable(new V2Error(409, "source_revision_conflict"))).toBe(false);
    expect(retryable(new V2Error(422, "invalid_input"))).toBe(false);
    expect(retryable(new DOMException("gone", "AbortError"))).toBe(false);
  });

  it("maps refusals to a message", () => {
    expect(failureMessage("source_capacity_reached")).toBe(
      "wlP0011c.error.capacity",
    );
    expect(failureMessage("source_context_incompatible")).toBe(
      "wlP0011c.error.alias",
    );
    expect(failureMessage("anything_else")).toBe("wlP0011c.error.failed");
  });

  it("checks labels the way the server does", () => {
    expect(textProblem("", 100)).toBe("required");
    expect(textProblem("Joint account", 100)).toBeNull();
    expect(textProblem(" padded", 100)).toBe("invalid");
    expect(textProblem("tab\there", 100)).toBe("invalid");
    expect(textProblem("x".repeat(101), 100)).toBe("long");
    // Code points, not UTF-16 units.
    expect(textProblem("😀".repeat(100), 100)).toBeNull();
  });
});

describe("source locale catalogs", () => {
  it("have the same keys and placeholders in every locale", () => {
    const keys = (catalog: Record<string, string>) =>
      Object.keys(catalog).filter((key) => key.startsWith("wlP0011c."));
    const english = keys(catalogs["en-CA"]);
    expect(english.length).toBeGreaterThan(50);
    for (const locale of ["zh-TW", "zh-CN"] as const) {
      expect(keys(catalogs[locale]).sort()).toEqual([...english].sort());
      for (const key of english) {
        const tokens = (text: string) =>
          (text.match(/\{[a-z]+\}/g) ?? []).sort();
        expect(tokens(catalogs[locale][key]), `${locale} ${key}`).toEqual(
          tokens(catalogs["en-CA"][key]),
        );
      }
    }
  });
});
