import Decimal from "decimal.js";
import type { Models, Report } from "./api";

export function groupEditions(editions: Models["ReportSummary"][]) {
  const groups = new Map<string, Models["ReportSummary"][]>();
  for (const report of editions) {
    const parsed = Date.parse(report.valuation_as_of);
    const key = `${Number.isNaN(parsed) ? report.valuation_as_of : parsed}:${report.scope_key ?? report.id}`;
    const values = groups.get(key) ?? [];
    values.push(report);
    groups.set(key, values);
  }
  return [...groups.entries()].map(([key, values]) => ({
    key,
    // Preserve the server's publication order, including captured legacy editions.
    latest: values[0],
    older: values.slice(1),
  }));
}

export function groupedIssues(data: {
  accounts: Pick<Models["Account"], "account_id" | "label">[];
  issues: Report["issues"];
}) {
  const groups = new Map<
    string,
    {
      severity: string;
      code: string;
      message: string;
      contexts: string[];
      count: number;
    }
  >();
  for (const issue of data.issues) {
    const severity = String(issue.severity ?? "info");
    const code = String(issue.code ?? "");
    const message = String(issue.message ?? "");
    const key = JSON.stringify([severity, code, message]);
    const group = groups.get(key) ?? {
      severity,
      code,
      message,
      contexts: [],
      count: 0,
    };
    const context = [
      "account_id",
      "account",
      "account_type",
      "currency",
      "symbol",
      "provider",
    ]
      .map((field) => {
        const value = issue[field];
        if (typeof value !== "string") return null;
        return field === "account_id"
          ? (data.accounts.find((account) => account.account_id === value)
              ?.label ?? value)
          : value;
      })
      .filter((value): value is string => value !== null)
      .join(" · ");
    if (context && !group.contexts.includes(context))
      group.contexts.push(context);
    group.count++;
    groups.set(key, group);
  }
  return [...groups.values()];
}

export function compareReportCells(a: string, b: string) {
  const numeric = (value: string) => {
    const normalized = value.trim().replaceAll("−", "-");
    return /^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?%?$/.test(normalized)
      ? new Decimal(normalized.replaceAll(",", "").replace(/%$/, ""))
      : null;
  };
  const left = numeric(a),
    right = numeric(b);
  return left !== null && right !== null
    ? left.comparedTo(right)
    : a.localeCompare(b);
}
