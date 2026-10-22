import type { Job } from "./api";
import type { Message } from "./i18n";

export function providerName(
  provider: string,
  wallet: string,
  unknown: string,
): string {
  return (
    new Map([
      ["wealthsimple", "Wealthsimple"],
      ["bullbitcoin", "Bull Bitcoin"],
      ["wallet", wallet],
    ]).get(provider) ??
    (provider || unknown)
  );
}
export function canConfirmPreview(
  job: Job,
  preview: Record<string, unknown>,
  edited: boolean,
): boolean {
  if (
    edited ||
    job.kind !== "preview" ||
    job.status !== "ready" ||
    (preview.blockers != null &&
      (!Array.isArray(preview.blockers) || preview.blockers.length > 0))
  )
    return false;
  if (preview.status === "awaiting_confirmation")
    return (
      typeof preview.approval_sha256 === "string" &&
      /^[a-f0-9]{64}$/.test(preview.approval_sha256)
    );
  return (
    preview.approval_sha256 == null &&
    ["checked", "pending_reference"].includes(String(preview.status))
  );
}
export function importOutcome(
  job: Job,
  preview: Record<string, unknown>,
): Message {
  if (job.status === "published") return "importPublished";
  if (job.status === "data_committed") return "importCommitted";
  if (job.status === "report_failed") return "importReportFailed";
  if (["needs_review", "interrupted"].includes(job.status))
    return "importLocalReview";
  if (job.status === "cancelled") return "importCancelled";
  if (job.status === "queued" || job.status === "running")
    return "importWaiting";
  if (job.kind === "preview") {
    if (job.status === "blocked" || job.status === "failed")
      return "importCorrectPreview";
    if (job.status === "ready") {
      if (preview.status === "mapping_required") return "importMapNext";
      if (preview.status === "reference_required")
        return "importReferencesNext";
      if (canConfirmPreview(job, preview, false)) return "importReady";
    }
  }
  return "importUnknownOutcome";
}
export function needsFreshPreview(code: string): boolean {
  return [
    "stale_preview",
    "stale_engine",
    "preview_unavailable",
    "stale_source_preview",
    "approval_mismatch",
  ].includes(code);
}

export function importFailureMessage(code: string): Message {
  if (needsFreshPreview(code)) return "importStaleHint";
  if (code === "invalid_context") return "importContextErrorHint";
  return code === "request_failed"
    ? "importRetryHint"
    : "importErrorReviewHint";
}
