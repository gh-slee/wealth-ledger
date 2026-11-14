import type { Message } from "../lib/i18n";

// Client mirrors of the source lifecycle DTOs in
// src/kurafolio/web_v2/schemas.py (SourceCatalogPage and friends). The server
// stays authoritative for every rule; these types only shape the page.

export type SourceRealm = { incarnation: string; restore_epoch: string };
export type CapabilityName = "FILE_IMPORT" | "PULL_API";
export type CapabilityStatus =
  "DISABLED" | "CONFIRMATION_REQUIRED" | "UNAVAILABLE" | "ENABLED";

export type SourceEnablement = {
  enabled: boolean;
  installation_id: string | null;
  revision: string;
  generation: string;
};

export type Capability = {
  capability: CapabilityName;
  active_installation_id: string | null;
  availability_generation: string | null;
  adapter_id: string | null;
  package_version: string | null;
  format_versions: string[];
  domain_contract_version: number;
  parser_api_version: number | null;
  enablement: SourceEnablement;
  status: CapabilityStatus;
  reason:
    | "source_unavailable"
    | "source_capability_unavailable"
    | "source_counter_exhausted"
    | null;
  connection_count: number;
};

export type CatalogItem = {
  plugin_id: string;
  provider_id: string;
  display_name: string;
  publisher_label: string;
  docs_url: string | null;
  capabilities: Capability[];
};

type Page<T, Cursor> = {
  items: T[];
  next_after: Cursor | null;
  catalog_revision: string;
  state_revision: string;
  realm: SourceRealm;
};
export type SourceCatalogPage = Page<CatalogItem, string>;

export type ConnectionStatus =
  | "DISABLED"
  | "SOURCE_DISABLED"
  | "CONFIRMATION_REQUIRED"
  | "UNAVAILABLE"
  | "ENABLED";

export type SourceConnection = {
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
  status: ConnectionStatus;
  reason:
    | "source_unavailable"
    | "source_context_incompatible"
    | "source_counter_exhausted"
    | null;
};
export type SourceConnectionPage = Page<SourceConnection, string>;

/** A merged view of every page; the realm comes from the last page read. */
export type Listing<T> = { items: T[]; realm: SourceRealm };

/**
 * The path of the next page. A cursor must carry the revisions and realm of
 * the page that returned it, or the server rejects it.
 */
export function pagePath(
  base: "/sources" | "/source-connections",
  previous: Page<unknown, string> | null,
): string {
  const params = new URLSearchParams({ limit: "100" });
  if (previous?.next_after) {
    params.set("after", previous.next_after);
    params.set("catalog_revision", previous.catalog_revision);
    params.set("state_revision", previous.state_revision);
    params.set("incarnation", previous.realm.incarnation);
    params.set("restore_epoch", previous.realm.restore_epoch);
  }
  return `${base}?${params}`;
}

export type CapabilityView = {
  label: Message;
  tone: "good" | "review" | "neutral";
  /** The switch is offered only for a file capability that can change. */
  switchable: boolean;
  /** The newer installed version the user must confirm, when there is one. */
  confirmVersion: string | null;
  explanation: Message | null;
};

export function capabilityView(capability: Capability): CapabilityView {
  if (capability.capability !== "FILE_IMPORT")
    return {
      label: "wlP0011c.status.planned",
      tone: "neutral",
      switchable: false,
      confirmVersion: null,
      explanation: "wlP0011c.apiPlanned",
    };
  switch (capability.status) {
    case "ENABLED":
      return {
        label: "wlP0011c.status.enabled",
        tone: "good",
        switchable: true,
        confirmVersion: null,
        explanation: null,
      };
    case "DISABLED":
      // Enabling pins the active installation; without one there is
      // nothing to enable.
      return capability.active_installation_id
        ? {
            label: "wlP0011c.status.disabled",
            tone: "neutral",
            switchable: true,
            confirmVersion: null,
            explanation: null,
          }
        : unavailable();
    case "CONFIRMATION_REQUIRED":
      return capability.active_installation_id
        ? {
            label: "wlP0011c.status.confirm",
            tone: "review",
            switchable: true,
            confirmVersion:
              capability.package_version ?? capability.active_installation_id,
            explanation: "wlP0011c.confirmExplain",
          }
        : unavailable();
    case "UNAVAILABLE":
      return unavailable(capability.reason);
    default:
      return {
        label: "wlP0011c.status.unknown",
        tone: "review",
        switchable: false,
        confirmVersion: null,
        explanation: null,
      };
  }
}

function unavailable(reason?: Capability["reason"]): CapabilityView {
  return {
    label: "wlP0011c.status.unavailable",
    tone: "review",
    switchable: false,
    confirmVersion: null,
    explanation:
      reason === "source_counter_exhausted"
        ? "wlP0011c.counterExhausted"
        : "wlP0011c.unavailableExplain",
  };
}

export function connectionLabel(status: ConnectionStatus): Message {
  switch (status) {
    case "ENABLED":
      return "wlP0011c.status.enabled";
    case "DISABLED":
      return "wlP0011c.status.disabled";
    case "SOURCE_DISABLED":
      return "wlP0011c.status.sourceDisabled";
    case "CONFIRMATION_REQUIRED":
      return "wlP0011c.status.confirm";
    case "UNAVAILABLE":
      return "wlP0011c.status.unavailable";
    default:
      return "wlP0011c.status.unknown";
  }
}

/**
 * Sources that Import Data may offer: an enabled file capability with an
 * enabled connection. WL-P0-011D reads the same catalog and connections.
 */
export function importableSources(
  catalog: CatalogItem[],
  connections: SourceConnection[],
): { source: CatalogItem; connections: SourceConnection[] }[] {
  return catalog.flatMap((source) => {
    const file = source.capabilities.find(
      (item) => item.capability === "FILE_IMPORT" && item.status === "ENABLED",
    );
    if (!file) return [];
    const usable = connections.filter(
      (connection) =>
        connection.plugin_id === source.plugin_id &&
        connection.status === "ENABLED",
    );
    return usable.length ? [{ source, connections: usable }] : [];
  });
}

/** Errors after which the list is stale and must be read again. */
export const STALE_CODES = new Set([
  "source_revision_conflict",
  "source_repreview_required",
  "source_connection_conflict",
]);

/**
 * True when the request may not have reached the server or its answer was
 * lost. Only then may the same operation be resent unchanged.
 */
export function retryable(error: unknown): boolean {
  if (error instanceof DOMException && error.name === "AbortError")
    return false;
  const value = error as { status?: unknown; code?: unknown };
  if (typeof value?.status !== "number") return true;
  return (
    value.status >= 500 ||
    value.code === "request_timeout" ||
    value.code === "source_commit_uncertain"
  );
}

export function failureMessage(code: string): Message {
  switch (code) {
    case "source_capacity_reached":
      return "wlP0011c.error.capacity";
    case "source_context_incompatible":
      return "wlP0011c.error.alias";
    case "source_capability_unavailable":
    case "source_unavailable":
    case "source_catalog_unavailable":
      return "wlP0011c.error.unavailable";
    case "source_idempotency_conflict":
      return "wlP0011c.error.duplicate";
    case "rate_limited":
      return "wlP0011c.error.rateLimited";
    case "invalid_input":
      return "wlP0011c.error.invalid";
    default:
      return "wlP0011c.error.failed";
  }
}

/** Mirrors SourceLabel and SourceAlias: trimmed, no control characters. */
export function textProblem(
  value: string,
  maximum: number,
): "required" | "long" | "invalid" | null {
  if (!value) return "required";
  if ([...value].length > maximum) return "long";
  if (
    value !== value.trim() ||
    // eslint-disable-next-line no-control-regex
    /[\u0000-\u001f\u007f-\u009f]/.test(value) ||
    /[\ud800-\udfff]/.test(value.replace(/[\ud800-\udbff][\udc00-\udfff]/g, ""))
  )
    return "invalid";
  return null;
}
