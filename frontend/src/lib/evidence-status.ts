import Decimal from "decimal.js";
import type { Job, Report } from "./api";
import type { Message } from "./i18n";

export type EvidenceItem = {
  id: string;
  severity: "error" | "review" | "unknown" | "info";
  title: Message;
  body: Message;
  destination: "sources" | "records" | "details";
  at: string | null;
  context: string[];
  count: number;
};
const text = (value: unknown) => (typeof value === "string" ? value : null);
const knownAmount = (value: unknown): boolean => {
  if (typeof value !== "string" || !value.trim()) return false;
  try {
    const n = new Decimal(value);
    return n.isFinite() && !n.isNegative();
  } catch {
    return false;
  }
};
const estimated = new Set([
  "opening_plus_orders_unadjusted_for_wallet_fees",
  "order_derived_unadjusted_for_wallet_fees",
  "order_derived_estimate",
  "balance_plus_known_changes_estimate",
  "ledger_plus_events_estimate",
  "wallet_only_unknown_history",
]);

// Only frozen, structured fields establish financial status. No live declarations
// or translated findings are inputs; a missing field never becomes valid zero.
export function evidenceItems(data: Report): EvidenceItem[] {
  const items: EvidenceItem[] = [];
  const add = (
    id: string,
    severity: EvidenceItem["severity"],
    title: Message,
    body: Message,
    destination: EvidenceItem["destination"],
    context: string[] = [],
  ) =>
    items.push({
      id,
      severity,
      title,
      body,
      destination,
      at: data.as_of || null,
      context,
      count: 1,
    });
  const dates = data.source_dates.map((s) =>
    s.as_of ? Date.parse(s.as_of) : NaN,
  );
  if (!dates.length || dates.some((d) => !Number.isFinite(d)))
    add(
      "source_dates_unknown",
      "unknown",
      "evidenceDatesTitle",
      "evidenceDatesUnknown",
      "sources",
    );
  if (new Set(dates.filter(Number.isFinite)).size > 1)
    add(
      "source_dates_differ",
      "review",
      "evidenceDatesTitle",
      "evidenceDatesDiffer",
      "sources",
    );
  if (data.source_dates.some((s) => s.usage === "carried_forward"))
    add(
      "source_carried",
      "review",
      "evidenceCarriedTitle",
      "evidenceCarriedBody",
      "sources",
    );
  if (data.source_basis || !data.is_complete)
    add(
      "supplied_scope",
      "info",
      "evidenceScopeTitle",
      "evidenceScopeBody",
      "details",
    );
  if (data.btc) {
    const status = text(data.btc.quantity_status);
    if (data.btc.valuation_blocked === true)
      add(
        "btc_blocked",
        "error",
        "evidenceBtcTitle",
        "evidenceBtcBlocked",
        "records",
      );
    else if (!knownAmount(data.btc.quantity_btc))
      add(
        "btc_unknown",
        "unknown",
        "evidenceBtcTitle",
        "evidenceBtcUnknown",
        "records",
      );
    else if (status === "user_reported_balance")
      add(
        "btc_declared",
        "info",
        "evidenceBtcTitle",
        "evidenceBtcDeclared",
        "records",
      );
    else if (status && estimated.has(status))
      add(
        "btc_estimated",
        "review",
        "evidenceBtcTitle",
        "evidenceBtcEstimated",
        "records",
      );
    else
      add(
        "btc_basis_unknown",
        "unknown",
        "evidenceBtcTitle",
        "evidenceBtcUnknown",
        "records",
      );
    // Purchase spend or an opt-in estimate cannot establish full acquisition cost.
    if (!knownAmount(data.btc.actual_full_cost_cad))
      add(
        "btc_cost_unknown",
        "unknown",
        "evidenceCostTitle",
        "evidenceCostUnknown",
        "details",
      );
  }
  // Existing DTOs do not establish complete coverage intervals or eligible full
  // returns, including when recorded cash flows or contribution subtotals exist.
  add(
    "flow_coverage_unknown",
    "unknown",
    "evidenceFlowsTitle",
    "evidenceFlowsUnknown",
    "records",
  );
  const groups = new Map<string, EvidenceItem>();
  for (const issue of data.issues) {
    const severity =
      issue.severity === "error"
        ? "error"
        : issue.severity === "warning"
          ? "review"
          : "info";
    if (severity === "info") continue; // Original informational notices remain in details.
    const context = [
      "provider",
      "account_id",
      "account",
      "account_type",
      "currency",
      "symbol",
      "record_id",
    ].flatMap((k) => (text(issue[k]) ? [k + ": " + text(issue[k])] : []));
    const code = text(issue.code) ?? "unrecognized_check";
    const id = JSON.stringify([severity, code, context]);
    const previous = groups.get(id);
    if (previous) previous.count++;
    else
      groups.set(id, {
        id,
        severity,
        title: "evidenceCheckTitle",
        body: "evidenceCheckBody",
        destination: "details",
        at: text(issue.as_of),
        context: [code, ...context],
        count: 1,
      });
  }
  items.push(...groups.values());
  const order = { error: 0, review: 1, unknown: 2, info: 3 };
  return items.sort(
    (a, b) =>
      order[a.severity] - order[b.severity] ||
      (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );
}
export function unresolvedJobs(jobs: Job[]) {
  const statuses = new Set([
    "queued",
    "running",
    "data_committed",
    "report_failed",
    "interrupted",
    "needs_review",
  ]);
  return jobs.filter((j) => statuses.has(j.status));
}
export function jobDestination(job: Job): "records" | "imports" | null {
  if (["record", "record_preview"].includes(job.kind)) return "records";
  return ["preview", "update"].includes(job.kind) ? "imports" : null;
}
export function jobMessage(status: string): Message {
  return status === "queued" || status === "running"
    ? "processingActive"
    : status === "data_committed" || status === "report_failed"
      ? "processingUnpublished"
      : "processingReview";
}
