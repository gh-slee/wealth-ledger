import { describe, expect, it } from "vitest";
import {
  canConfirmPreview,
  importFailureMessage,
  importOutcome,
  needsFreshPreview,
  providerName,
} from "../src/lib/import-review";
import type { Job } from "../src/lib/api";
const job = (status = "ready", kind = "preview"): Job => ({
  id: "f".repeat(32),
  status,
  kind,
  created_at: 1,
  updated_at: 1,
  execution_at: "2024-01-01T12:00:00Z",
  preview_id: null,
  core_operation_id: null,
  error_code: null,
  result: null,
});
describe("Import review guards", () => {
  it("permits only supported unchanged native/source approvals", () => {
    for (const status of ["checked", "pending_reference"])
      expect(canConfirmPreview(job(), { status }, false)).toBe(true);
    expect(
      canConfirmPreview(
        job(),
        { status: "awaiting_confirmation", approval_sha256: "a".repeat(64) },
        false,
      ),
    ).toBe(true);
    for (const status of [
      "mapping_required",
      "reference_required",
      "blocked",
      "future_state",
      undefined,
    ])
      expect(canConfirmPreview(job(), { status }, false)).toBe(false);
    for (const digest of [null, "", 123, "a".repeat(63), "g".repeat(64)])
      expect(
        canConfirmPreview(
          job(),
          { status: "awaiting_confirmation", approval_sha256: digest },
          false,
        ),
      ).toBe(false);
  });
  it("invalidates edited/blocked/nonready jobs and malformed blocker evidence", () => {
    for (const status of [
      "queued",
      "running",
      "blocked",
      "cancelled",
      "failed",
      "report_failed",
      "needs_review",
    ])
      expect(canConfirmPreview(job(status), { status: "checked" }, false)).toBe(
        false,
      );
    expect(canConfirmPreview(job(), { status: "checked" }, true)).toBe(false);
    expect(
      canConfirmPreview(job("ready", "update"), { status: "checked" }, false),
    ).toBe(false);
    for (const blockers of [["unresolved"], {}])
      expect(
        canConfirmPreview(job(), { status: "checked", blockers }, false),
      ).toBe(false);
    expect(
      canConfirmPreview(
        job(),
        { status: "checked", approval_sha256: "a".repeat(64) },
        false,
      ),
    ).toBe(false);
  });
  it("preserves generic and prototype-like provider IDs without relabeling them as a broker", () => {
    expect(providerName("wealthsimple", "Wallet", "Unknown")).toBe(
      "Wealthsimple",
    );
    expect(providerName("bullbitcoin", "Wallet", "Unknown")).toBe(
      "Bull Bitcoin",
    );
    expect(providerName("wallet", "Wallet", "Unknown")).toBe("Wallet");
    for (const provider of ["synthetic-bank", "__proto__", "toString"])
      expect(providerName(provider, "Wallet", "Unknown")).toBe(provider);
    expect(providerName("", "Wallet", "Unknown")).toBe("Unknown");
  });
  it("separates publication, commit, safe report recovery and unknown outcomes", () => {
    for (const [status, message] of [
      ["published", "importPublished"],
      ["data_committed", "importCommitted"],
      ["report_failed", "importReportFailed"],
      ["interrupted", "importLocalReview"],
      ["needs_review", "importLocalReview"],
      ["cancelled", "importCancelled"],
      ["queued", "importWaiting"],
      ["running", "importWaiting"],
      ["failed", "importUnknownOutcome"],
      ["future_state", "importUnknownOutcome"],
    ])
      expect(importOutcome(job(status, "update"), {})).toBe(message);
    expect(importOutcome(job("blocked"), {})).toBe("importCorrectPreview");
    expect(importOutcome(job("ready"), { status: "mapping_required" })).toBe(
      "importMapNext",
    );
    expect(importOutcome(job("ready"), { status: "reference_required" })).toBe(
      "importReferencesNext",
    );
    expect(importOutcome(job("ready"), { status: "checked" })).toBe(
      "importReady",
    );
  });
  it("routes stale approval, source-context and uncertain network errors to different instructions", () => {
    for (const code of [
      "stale_preview",
      "stale_engine",
      "preview_unavailable",
      "approval_mismatch",
    ])
      expect(needsFreshPreview(code)).toBe(true);
    expect(importFailureMessage("stale_preview")).toBe("importStaleHint");
    expect(importFailureMessage("invalid_context")).toBe(
      "importContextErrorHint",
    );
    expect(importFailureMessage("request_failed")).toBe("importRetryHint");
    expect(importFailureMessage("unrecognized")).toBe("importErrorReviewHint");
  });
});
