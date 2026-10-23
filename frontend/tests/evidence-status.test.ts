import { describe, expect, it } from "vitest";
import {
  evidenceItems,
  jobDestination,
  jobMessage,
  unresolvedJobs,
} from "../src/lib/evidence-status";
import type { Job, Report } from "../src/lib/api";
const report = (): Report => ({
  schema_version: 1,
  report: {
    id: "saved",
    valuation_as_of: "2024-02-01T12:00:00Z",
    published_at: 1,
    verification_basis: "publication_manifest",
    artifacts: [],
  },
  locale: "en-CA",
  as_of: "2024-02-01T12:00:00Z",
  kind: "baseline",
  is_complete: true,
  data_status: null,
  source_dates: [
    { provider: "synthetic", as_of: "2024-02-01T12:00:00Z", usage: "snapshot" },
  ],
  totals: {},
  fx: {},
  accounts: [],
  holdings: [],
  history: [],
  findings: [],
  issues: [],
  companies: [],
  dimensions: {},
  exposure_status: null,
  exposure_sources: [],
  btc: null,
  cash_flows: [],
  missing_official_months: [],
});
const ids = (r: Report) => evidenceItems(r).map((i) => i.id);
describe("Frozen evidence status", () => {
  it("does not infer freshness, contributions or returns from completeness, elapsed time, flows or purchase spending", () => {
    const r = report();
    r.as_of = "2030-01-01T12:00:00Z";
    r.cash_flows = [{ amount_cad: "100" }];
    r.source_basis = {
      complete_contributions_cad: "100",
      complete_portfolio_returns: "0.5",
    };
    expect(ids(r)).toContain("flow_coverage_unknown");
    expect(ids(r)).not.toContain("source_carried");
    expect(ids(r)).not.toContain("source_dates_differ");
  });
  it("distinguishes instants, missing dates and explicit carry-forward from inferred stale data", () => {
    const r = report();
    r.source_dates.push({
      provider: "other",
      as_of: "2024-02-01T07:00:00-05:00",
      usage: "recorded_purchase",
    });
    expect(ids(r)).not.toContain("source_dates_differ");
    r.source_dates[1].as_of = "2024-01-01T12:00:00Z";
    expect(ids(r)).toContain("source_dates_differ");
    expect(ids(r)).not.toContain("source_carried");
    r.source_dates[1].usage = "carried_forward";
    expect(ids(r)).toContain("source_carried");
    r.source_dates[1].as_of = null;
    expect(ids(r)).toContain("source_dates_unknown");
  });
  it("preserves unknown, valid zero, estimated, declared and blocked BTC without inventing a reconciliation gap", () => {
    const r = report();
    r.btc = {
      quantity_btc: "0",
      quantity_status: "user_reported_balance",
      actual_full_cost_cad: "0",
    };
    expect(ids(r)).toContain("btc_declared");
    expect(ids(r)).not.toContain("btc_cost_unknown");
    r.btc.actual_full_cost_cad = "NaN";
    expect(ids(r)).toContain("btc_cost_unknown");
    r.btc.quantity_status = "ledger_plus_events_estimate";
    expect(ids(r)).toContain("btc_estimated");
    r.btc.quantity_btc = null;
    expect(ids(r)).toContain("btc_unknown");
    r.btc.valuation_blocked = true;
    expect(ids(r)).toContain("btc_blocked");
    expect(evidenceItems(r)[0].id).toBe("btc_blocked");
    r.btc = {
      quantity_btc: "1",
      quantity_status: "future_status",
      known_purchase_spend_cad: "500",
    };
    expect(ids(r)).toContain("btc_basis_unknown");
    expect(ids(r)).toContain("btc_cost_unknown");
  });
  it("keeps account-specific warnings and all original notices; grouping/order do not depend on translated prose", () => {
    const r = report();
    r.issues = [
      { severity: "warning", code: "cash", account_id: "a", message: "First" },
      { severity: "warning", code: "cash", account_id: "b", message: "Second" },
      { severity: "warning", code: "cash", account_id: "a", message: "Third" },
      { severity: "info", code: "note", message: "Original note" },
    ];
    const before = JSON.stringify(r);
    const items = evidenceItems(r);
    const checks = items.filter((i) => i.title === "evidenceCheckTitle");
    expect(checks).toHaveLength(2);
    expect(checks[0].count).toBe(2);
    expect(JSON.stringify(r)).toBe(before);
    r.issues.forEach((i) => (i.message = "Translated"));
    expect(evidenceItems(r).map((i) => i.id)).toEqual(items.map((i) => i.id));
    expect(r.issues).toHaveLength(4);
  });
  it("does not interpret human findings as facts or inherit later wallet declarations", () => {
    const r = report();
    r.findings = ["Wallet verified; no activity; all contributions known"];
    expect(ids(r)).toEqual(["flow_coverage_unknown"]);
    expect(evidenceItems(r)[0].severity).toBe("unknown");
  });
});
describe("Current operational state", () => {
  it("shows every unresolved status, separates commit from publication, and navigates only to supported job views", () => {
    const jobs = [
      "queued",
      "running",
      "data_committed",
      "report_failed",
      "interrupted",
      "needs_review",
      "published",
      "cancelled",
    ].map(
      (status, i) =>
        ({
          id: String(i),
          kind: "update",
          status,
          created_at: 1,
          updated_at: 2,
          execution_at: "2024-01-01T00:00:00Z",
          preview_id: null,
          core_operation_id: null,
          error_code: null,
          result: null,
        }) as Job,
    );
    expect(unresolvedJobs(jobs)).toHaveLength(6);
    expect(jobMessage("report_failed")).toBe("processingUnpublished");
    expect(jobMessage("data_committed")).toBe("processingUnpublished");
    expect(jobDestination(jobs[0])).toBe("imports");
    expect(jobDestination({ ...jobs[0], kind: "record" })).toBe("records");
    expect(jobDestination({ ...jobs[0], kind: "source_commit" })).toBeNull();
  });
});
