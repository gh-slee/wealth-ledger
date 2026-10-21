import { describe, expect, it } from "vitest";
import {
  compareReportCells,
  groupedIssues,
  groupEditions,
} from "../src/lib/report-library";
import { validTheme } from "../src/lib/theme";
import type { Models } from "../src/lib/api";
const edition = (
  id: string,
  scope: string | null,
  date = "2024-01-01T12:00:00Z",
): Models["ReportSummary"] => ({
  id,
  valuation_as_of: date,
  published_at: 1,
  verification_basis: "publication_manifest",
  artifacts: [],
  scope_key: scope,
});
describe("Report reading", () => {
  it("groups only matching instants and scopes while preserving publication order", () => {
    const groups = groupEditions([
      edition("new", "a"),
      edition("old", "a", "2024-01-01T07:00:00-05:00"),
      edition("other-scope", "b"),
      edition("later", "a", "2024-02-01T12:00:00Z"),
      edition("unknown1", null),
      edition("unknown2", null),
    ]);
    expect(groups).toHaveLength(5);
    expect(groups[0].latest.id).toBe("new");
    expect(groups[0].older.map((row) => row.id)).toEqual(["old"]);
  });
  it("groups duplicate messages without losing affected accounts or severity", () => {
    const groups = groupedIssues({
      accounts: [
        { account_id: "a", label: "TFSA" },
        { account_id: "b", label: "RRSP" },
      ],
      issues: [
        {
          severity: "warning",
          code: "cash",
          message: "Check cash",
          account_id: "a",
        },
        {
          severity: "warning",
          code: "cash",
          message: "Check cash",
          account_id: "b",
        },
        { severity: "info", code: "cash", message: "Check cash" },
      ],
    });
    expect(groups).toHaveLength(2);
    expect(groups[0].contexts).toEqual(["TFSA", "RRSP"]);
    expect(groups[0].count).toBe(2);
  });
  it("sorts displayed financial strings exactly without rounding or date guessing", () => {
    expect(compareReportCells("1,000.00", "90.00")).toBe(1);
    expect(
      compareReportCells("9007199254740993.12", "9007199254740993.11"),
    ).toBe(1);
    expect(compareReportCells("−0.00000001", "0")).toBe(-1);
    expect(compareReportCells("9.00%", "10.00%")).toBe(-1);
  });
  it("accepts only nonfinancial theme preference enums", () => {
    expect(validTheme("dark")).toBe("dark");
    expect(validTheme("light")).toBe("light");
    expect(validTheme(null)).toBe("system");
    expect(validTheme("unexpected")).toBe("system");
  });
});
