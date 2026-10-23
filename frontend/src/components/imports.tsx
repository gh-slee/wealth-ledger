import { Link, useSearchParams } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ApiError,
  mutate,
  read,
  scope,
  upload,
  type Job,
  type Models,
} from "../lib/api";
import { useI18n } from "../lib/i18n";
import { amount, date, quantity } from "../lib/format";
import {
  canConfirmPreview,
  importOutcome,
  importFailureMessage,
  needsFreshPreview,
  providerName,
} from "../lib/import-review";
import { Button } from "./ui/button";
const active = new Set(["queued", "running", "data_committed"]);
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const items = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : [];
const correctionOptions = (value: FormDataEntryValue | null) => {
  if (!value) return {};
  const parsed: unknown = JSON.parse(String(value));
  if (
    !parsed ||
    typeof parsed !== "object" ||
    Array.isArray(parsed) ||
    Object.keys(parsed).some(
      (key) => !["revisions", "scope_revisions"].includes(key),
    )
  )
    throw new ApiError(422, "invalid_context");
  return parsed;
};
type Binding = {
  provider: string;
  source_account_id: string;
  target_kind: "new" | "canonical" | "legacy_holdings" | "legacy_crypto";
  ledger_account_id?: string;
};
export function Imports({ portfolio }: { portfolio: string }) {
  const { t, label, error, locale } = useI18n();
  const client = useQueryClient();
  const [jobParams, setJobParams] = useSearchParams();
  const requestedJob = jobParams.get("job");
  const [parserMode, setParserMode] = useState(true);
  const [sourceFiles, setSourceFiles] = useState<File[]>([]);
  const [choices, setChoices] = useState<Binding[]>([]);
  const [selectedProfiles, setSelectedProfiles] = useState<
    Record<number, string>
  >({});
  const profiles = useQuery({
    queryKey: [portfolio, "source-import-contexts"],
    queryFn: ({ signal }) =>
      read<Models["SourceProfileList"]>(
        scope(portfolio) + "/source-import-contexts",
        signal,
      ),
    enabled: parserMode,
  });
  const formRef = useRef<HTMLFormElement>(null);
  const reviewRef = useRef<HTMLElement>(null);
  const focusReview = useRef(false);
  const inFlight = useRef(false);
  const [draftEdited, setDraftEdited] = useState(false);
  const [invalidatedPreviews, setInvalidatedPreviews] = useState<Set<string>>(
    () => new Set(),
  );
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState(""),
    [selected, setSelected] = useState<string | null>(requestedJob),
    [confirming, setConfirming] = useState(false);
  // Stable request keys survive uncertain network retries, but not edited input.
  const previewKey = useRef(crypto.randomUUID()),
    confirmKey = useRef(crypto.randomUUID());
  const uploadedForPreview = useRef<{ key: string; ids: string[] } | null>(
    null,
  );
  const submittedPreview = useRef<{ key: string; body: unknown } | null>(null);
  const jobs = useQuery({
    queryKey: [portfolio, "jobs"],
    queryFn: ({ signal }) =>
      read<Models["JobList"]>(scope(portfolio) + "/jobs", signal),
    refetchInterval: (query) =>
      query.state.data?.jobs.some((job) => active.has(job.status))
        ? 1500
        : 5000,
  });
  const importJobs =
    jobs.data?.jobs.filter((job) => ["preview", "update"].includes(job.kind)) ??
    [];
  const publishedIds =
    importJobs
      .filter((job) => job.kind === "update" && job.status === "published")
      .map((job) => job.id)
      .sort()
      .join(",") ?? "";
  useEffect(() => {
    if (publishedIds) {
      void client.invalidateQueries({ queryKey: [portfolio, "reports"] });
      void client.invalidateQueries({
        queryKey: [portfolio, "source-import-contexts"],
      });
    }
  }, [publishedIds, client, portfolio]);
  useEffect(() => {
    setSelected(requestedJob);
  }, [requestedJob]);
  const job =
    importJobs.find((job) => job.id === selected) ??
    (selected ? undefined : importJobs[0]);
  const result = record(job?.result),
    preview = record(result.preview ?? result);
  useEffect(() => {
    confirmKey.current = crypto.randomUUID();
  }, [job?.id]);
  useEffect(() => {
    if (preview.status === "mapping_required") {
      setChoices(
        items(preview.account_review).map(
          (value) => record(record(value).suggested_choice) as Binding,
        ),
      );
    }
  }, [job?.id, preview.status]);
  useEffect(() => {
    if (focusReview.current && job && reviewRef.current) {
      focusReview.current = false;
      reviewRef.current.focus();
    }
  });
  const linkedUpdate =
    job?.kind === "preview"
      ? importJobs.find(
          (value) => value.kind === "update" && value.preview_id === job.id,
        )
      : undefined;
  const blockingUpdate = jobs.data?.jobs.find(
    (value) =>
      ["update", "record", "source_commit"].includes(value.kind) &&
      [
        "queued",
        "running",
        "data_committed",
        "report_failed",
        "interrupted",
        "needs_review",
      ].includes(value.status),
  );
  const confirmable = Boolean(
    !linkedUpdate &&
    !blockingUpdate &&
    job &&
    canConfirmPreview(
      job,
      preview,
      draftEdited || invalidatedPreviews.has(job.id),
    ),
  );
  const stage = draftEdited
    ? 1
    : job?.kind === "update"
      ? 3
      : job && !invalidatedPreviews.has(job.id)
        ? 2
        : 1;
  const openReferences = () => {
    const details = document.getElementById(
      "import-references",
    ) as HTMLDetailsElement | null;
    if (details) details.open = true;
  };
  const metrics = [
    ["row_count", "rowCount"],
    ["account_count", "accountCount"],
    ["new_orders", "newOrders"],
    ["revised_orders", "revisedOrders"],
    ["unchanged_orders", "unchangedOrders"],
    ["duplicate_rows", "duplicateRows"],
  ] as const;
  const changed = () => {
    previewKey.current = crypto.randomUUID();
    setDraftEdited(true);
    if (job?.kind === "preview")
      setInvalidatedPreviews((old) => new Set([...old, job.id]));
    setConfirming(false);
    setFailure("");
  };
  async function refresh(value: Job) {
    focusReview.current = true;
    setSelected(value.id);
    await client.invalidateQueries({ queryKey: [portfolio] });
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    const form = new FormData(event.currentTarget);
    const requestKey = previewKey.current;
    setBusy(true);
    setFailure("");
    try {
      let uploaded =
        uploadedForPreview.current?.key === requestKey
          ? uploadedForPreview.current.ids
          : null;
      if (!uploaded) {
        uploaded = [];
        for (const kind of ["csv", "fx", "price", "opening"])
          for (const value of form.getAll(kind)) {
            if (value instanceof File && value.size)
              uploaded.push(
                (
                  await upload(
                    portfolio,
                    value,
                    parserMode && kind === "csv" ? "source_csv" : kind,
                  )
                ).id,
              );
          }
        uploadedForPreview.current = { key: requestKey, ids: uploaded };
      }
      const balance = String(form.get("balance") ?? "").trim();
      const nativeBody = {
        upload_ids: uploaded,
        kind: form.get("kind"),
        render_saved: form.get("render_saved") === "on",
        ...(balance
          ? {
              btc_balance: balance,
              btc_balance_as_of: form.get("observed"),
              btc_balance_source: "Browser balance observation",
            }
          : {}),
        ...(form.get("as_of") ? { as_of: form.get("as_of") } : {}),
      };
      const body = parserMode
        ? {
            upload_ids: uploaded,
            kind: form.get("kind"),
            bindings: choices,
            context_options: sourceFiles.map((_, index) => ({
              ...(selectedProfiles[index]
                ? { profile_id: selectedProfiles[index] }
                : {
                    ...(form.get(`alias-${index}`)
                      ? { account_alias: form.get(`alias-${index}`) }
                      : {}),
                    ...(form.get(`timezone-${index}`)
                      ? { source_timezone: form.get(`timezone-${index}`) }
                      : {}),
                  }),
              ...correctionOptions(form.get(`correction-${index}`)),
            })),
            selections: Object.fromEntries(
              sourceFiles
                .map((_, index) => [
                  String(index + 1),
                  String(form.get(`adapter-${index}`) ?? "").trim(),
                ])
                .filter(([, value]) => value),
            ),
            reference_policy:
              form.get("fetch_references") === "on"
                ? "fetch_public"
                : "saved_only",
            ...(balance
              ? {
                  balance: {
                    quantity_btc: balance,
                    as_of: form.get("observed"),
                    source: "Browser balance observation",
                  },
                }
              : {}),
            ...(form.get("as_of") ? { as_of: form.get("as_of") } : {}),
          }
        : nativeBody;
      // Background review suggestions cannot change an uncertain request retry.
      const requestBody =
        submittedPreview.current?.key === requestKey
          ? submittedPreview.current.body
          : body;
      submittedPreview.current = { key: requestKey, body: requestBody };
      const prepared = await mutate<Job>(
        scope(portfolio) +
          (parserMode ? "/source-import-previews" : "/previews"),
        requestBody,
        "POST",
        requestKey,
      );
      if (previewKey.current === requestKey) setDraftEdited(false);
      await refresh(prepared);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError"))
        setFailure(
          reason instanceof ApiError
            ? reason.code
            : reason instanceof SyntaxError
              ? "invalid_context"
              : "request_failed",
        );
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  async function action(kind: "confirm" | "cancel" | "resume", current: Job) {
    if (inFlight.current) return;
    const currentPreview = record(
      record(current.result).preview ?? current.result,
    );
    if (
      kind === "confirm" &&
      (linkedUpdate ||
        blockingUpdate ||
        !canConfirmPreview(
          current,
          currentPreview,
          draftEdited || invalidatedPreviews.has(current.id),
        ))
    ) {
      setConfirming(false);
      setFailure("stale_preview");
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setFailure("");
    try {
      const currentResult = record(current.result);
      const currentPreview = record(currentResult.preview ?? currentResult);
      const value =
        kind === "confirm"
          ? await mutate<Job>(
              scope(portfolio) +
                (typeof currentPreview.approval_sha256 === "string"
                  ? "/source-reports"
                  : "/jobs"),
              {
                preview_id: current.id,
                ...(typeof currentPreview.approval_sha256 === "string"
                  ? { approval_sha256: currentPreview.approval_sha256 }
                  : {}),
              },
              "POST",
              confirmKey.current,
            )
          : await mutate<Job>(scope(portfolio) + `/jobs/${current.id}/${kind}`);
      setConfirming(false);
      await refresh(value);
    } catch (reason) {
      const code = reason instanceof ApiError ? reason.code : "request_failed";
      if (kind === "confirm" && needsFreshPreview(code)) changed();
      setFailure(code);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      <ol className="import-stages" aria-label={t("importStages")}>
        {(
          [
            "importPrepareStep",
            "importReviewStep",
            "importPublishStep",
          ] as const
        ).map((message, index) => (
          <li
            key={message}
            aria-current={stage === index + 1 ? "step" : undefined}
          >
            <span>{index + 1}</span>
            {t(message)}
          </li>
        ))}
      </ol>
      <section className="panel" id="import-draft">
        <h2>{t("uploadTitle")}</h2>
        <p className="muted">{t("uploadHint")}</p>
        <p className="muted">{t("importInputOptions")}</p>
        <form
          ref={formRef}
          className="import-form"
          onSubmit={submit}
          onChange={changed}
        >
          <fieldset className="import-controls" disabled={busy}>
            <legend className="sr-only">{t("importPrepareStep")}</legend>
            <h3>{t("importEvidenceHeading")}</h3>
            {parserMode && profiles.isError && (
              <p role="alert">{t("contextLoadFailed")}</p>
            )}
            <label className="file-drop">
              {t("evidenceFiles")}
              <input
                aria-label={t("evidenceFiles")}
                name="csv"
                type="file"
                accept=".csv,text/csv"
                multiple
                disabled={busy}
                onChange={(event) => {
                  setSourceFiles(Array.from(event.target.files ?? []));
                  setChoices([]);
                  setSelectedProfiles({});
                }}
              />
              <small>
                {parserMode
                  ? t("enabledParsers")
                  : "Wealthsimple / Bull Bitcoin"}{" "}
                · CSV ≤ 10 MiB
              </small>
            </label>
            {parserMode &&
              sourceFiles.map((file, index) => (
                <fieldset key={`${file.name}-${index}`}>
                  <legend>{file.name}</legend>
                  <p className="muted">{t("importContextHint")}</p>
                  <div className="form-grid">
                    <label>
                      {t("sourceProfile")}
                      <select
                        value={selectedProfiles[index] ?? ""}
                        onChange={(event) => {
                          setSelectedProfiles((old) => ({
                            ...old,
                            [index]: event.target.value,
                          }));
                        }}
                      >
                        <option value="">{t("manualContext")}</option>
                        {profiles.data?.profiles.map((profile) => (
                          <option key={profile.id} value={profile.id}>
                            {profile.label} · {profile.adapter_id}{" "}
                            {profile.options.source_timezone ?? ""}{" "}
                            {profile.options.format_selection ?? ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      {t("sourceAlias")}
                      <input
                        name={`alias-${index}`}
                        maxLength={160}
                        disabled={Boolean(selectedProfiles[index])}
                      />
                    </label>
                    <label>
                      {t("sourceTimezone")}
                      <input
                        name={`timezone-${index}`}
                        disabled={Boolean(selectedProfiles[index])}
                        placeholder="America/Toronto"
                      />
                    </label>
                  </div>
                  <details>
                    <summary>{t("correctionContext")}</summary>
                    <label>
                      {t("sourceAdapter")}
                      <input name={`adapter-${index}`} />
                    </label>
                    <p className="muted">{t("correctionContextHint")}</p>
                    <label>
                      {t("revisionParents")}
                      <textarea
                        name={`correction-${index}`}
                        rows={4}
                        maxLength={65536}
                        placeholder='{"revisions":[],"scope_revisions":[]}'
                      />
                    </label>
                  </details>
                </fieldset>
              ))}
            <h3>{t("importTimingHeading")}</h3>
            <p className="muted">{t("importTimingHint")}</p>
            <div className="form-grid">
              <label>
                {t("kind")}
                <select name="kind" defaultValue="monthly">
                  {(["baseline", "monthly", "interim"] as const).map((kind) => (
                    <option key={kind} value={kind}>
                      {t(kind)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("valuationAt")}
                <input name="as_of" placeholder="2026-10-17T18:00:00-04:00" />
              </label>
              <label>
                {t("btcOptional")}
                <input
                  name="balance"
                  inputMode="decimal"
                  pattern="(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,8})?"
                  placeholder="0.00000000"
                />
              </label>
              <label>
                {t("observedAt")}
                <input
                  name="observed"
                  placeholder="2026-10-17T18:00:00-04:00"
                />
              </label>
            </div>
            {!parserMode && (
              <label className="check-label">
                <input type="checkbox" name="render_saved" />
                {t("renderSaved")}
              </label>
            )}
            <details className="import-advanced">
              <summary>{t("importAdvanced")}</summary>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={parserMode}
                  onChange={(event) => {
                    setParserMode(event.target.checked);
                    setChoices([]);
                    setSelectedProfiles({});
                  }}
                />
                {t("parserMode")}
              </label>
              {parserMode && <p className="muted">{t("parserModeHint")}</p>}
              <p className="muted">{t("importCompatibilityHint")}</p>
            </details>
            <details id="import-references">
              <summary>{t("references")}</summary>
              <p className="muted">{t("importReferenceHint")}</p>
              {parserMode && (
                <label className="check-label">
                  <input type="checkbox" name="fetch_references" />
                  {t("fetchPublicReferences")}
                </label>
              )}

              <div className="form-grid">
                {(parserMode
                  ? (["fx", "price"] as const)
                  : (["fx", "price", "opening"] as const)
                ).map((kind) => (
                  <label key={kind}>
                    {t(
                      kind === "fx"
                        ? "fxFile"
                        : kind === "price"
                          ? "priceFile"
                          : "openingFile",
                    )}
                    <input
                      type="file"
                      name={kind}
                      accept=".json,application/json"
                      disabled={busy}
                    />
                  </label>
                ))}
              </div>
              {!parserMode && <p className="muted">{t("openingHint")}</p>}
            </details>
            <p className="muted">{t("importDraftHint")}</p>
          </fieldset>
          <Button type="submit" disabled={busy}>
            {busy ? t("loading") : t("preview")}
          </Button>
        </form>
      </section>
      {failure && !confirming && (
        <p role="alert" className="error">
          {error(failure)} <code>{failure}</code>
          <span className="import-error-guidance">
            {t(importFailureMessage(failure))}
          </span>
        </p>
      )}
      {jobs.isError && (
        <p role="alert" className="error">
          {t("failed")}{" "}
          <Button variant="secondary" onClick={() => jobs.refetch()}>
            {t("retry")}
          </Button>
        </p>
      )}
      {job && (
        <section
          className="panel import-review"
          id="import-review"
          tabIndex={-1}
          ref={reviewRef}
        >
          <div className="panel-heading">
            <h2>
              {t(
                job.kind === "preview" ? "previewResult" : "importOutcomeTitle",
              )}
            </h2>
            <span className="status">{label(job.status)}</span>
          </div>
          <p role="status">{t(importOutcome(job, preview))}</p>
          {linkedUpdate && (
            <p>
              {t("importLinkedJob")}{" "}
              <Link
                to={`/app/${portfolio}/imports?job=${encodeURIComponent(linkedUpdate.id)}`}
              >
                {t("processingViewJob")}
              </Link>
            </p>
          )}
          {!linkedUpdate && blockingUpdate && job.kind === "preview" && (
            <p className="status status-review">{t("importBlockedByJob")}</p>
          )}
          {job.kind === "preview" &&
            (draftEdited || invalidatedPreviews.has(job.id)) && (
              <p className="status status-review">{t("importDraftChanged")}</p>
            )}
          {job.kind === "preview" && (
            <p className="muted">{t("importFrozenReviewHint")}</p>
          )}
          {job.status === "published" && (
            <Link
              className="button button-secondary"
              to={`/app/${portfolio}/reports${typeof result.report_id === "string" ? `?report=${encodeURIComponent(result.report_id)}` : ""}`}
            >
              {t("importOpenReport")}
            </Link>
          )}
          {["needs_review", "interrupted"].includes(job.status) && (
            <details>
              <summary>{t("importRecoveryGuide")}</summary>
              <p>{t("importRecoveryGuideBody")}</p>
            </details>
          )}
          {job.kind === "preview" &&
            ["blocked", "failed"].includes(job.status) && (
              <a className="button button-secondary" href="#import-draft">
                {t("importReviewDraft")}
              </a>
            )}
          {["queued", "running", "data_committed"].includes(job.status) && (
            <p className="muted">{t("workerHint")}</p>
          )}
          {job.kind === "update" && draftEdited && (
            <p className="muted">{t("importSelectedJobHint")}</p>
          )}
          <dl className="job-facts">
            <div>
              <dt>{t("importJobKind")}</dt>
              <dd>{job.kind === "preview" ? t("preview") : t("confirm")}</dd>
            </div>
            <div>
              <dt>{t("cutoff")}</dt>
              <dd>
                {date(
                  String(
                    preview.valuation_as_of ??
                      result.valuation_as_of ??
                      record(result.preparation).valuation_as_of ??
                      job.execution_at,
                  ),
                  locale,
                )}
              </dd>
            </div>
          </dl>
          {job.error_code && (
            <p role="alert" className="error">
              {error(job.error_code)} <code>{job.error_code}</code>
            </p>
          )}
          {items(preview.account_review).length > 0 && (
            <section>
              <h3>{t("accountMappingReview")}</h3>
              <p className="muted">{t("sourceApprovalHint")}</p>
              {items(preview.account_review).map((value, index) => {
                const account = record(value),
                  choice = record(account.suggested_choice);
                return (
                  <div className="preview-source" key={index}>
                    <strong>{String(account.label ?? "")}</strong>
                    <span>
                      {String(account.provider ?? choice.provider ?? "")} ·{" "}
                      {String(
                        account.source_account_id ??
                          choice.source_account_id ??
                          "",
                      )}
                    </span>
                    <span>
                      {String(account.target_kind ?? choice.target_kind ?? "")}{" "}
                      ·{" "}
                      {String(
                        account.ledger_account_id ??
                          choice.ledger_account_id ??
                          "",
                      )}
                    </span>
                  </div>
                );
              })}
            </section>
          )}
          {preview.status === "mapping_required" && (
            <p className="muted">{t("sourceMappingRequired")}</p>
          )}
          {parserMode &&
            preview.status === "mapping_required" &&
            choices.map((choice, index) => (
              <div
                className="form-grid"
                key={`${choice.provider}-${choice.source_account_id}`}
              >
                <label>
                  {choice.provider} · {choice.source_account_id}
                  <select
                    aria-label={`${t("mappingDestination")} ${index + 1}`}
                    disabled={busy}
                    value={choice.target_kind}
                    onChange={(event) => {
                      setChoices((old) =>
                        old.map((value, row) =>
                          row === index
                            ? {
                                ...value,
                                target_kind: event.target
                                  .value as Binding["target_kind"],
                                ...(event.target.value === "new"
                                  ? { ledger_account_id: undefined }
                                  : {}),
                              }
                            : value,
                        ),
                      );
                      changed();
                    }}
                  >
                    {(
                      [
                        "new",
                        "canonical",
                        "legacy_holdings",
                        "legacy_crypto",
                      ] as const
                    ).map((kind) => (
                      <option key={kind} value={kind}>
                        {t(`mapping.${kind}`)}
                      </option>
                    ))}
                  </select>
                </label>
                {choice.target_kind !== "new" && (
                  <label>
                    {t("ledgerAccountId")}
                    <input
                      value={choice.ledger_account_id ?? ""}
                      disabled={busy}
                      onChange={(event) => {
                        setChoices((old) =>
                          old.map((value, row) =>
                            row === index
                              ? {
                                  ...value,
                                  ledger_account_id: event.target.value,
                                }
                              : value,
                          ),
                        );
                        changed();
                      }}
                    />
                  </label>
                )}
              </div>
            ))}
          {parserMode && preview.status === "mapping_required" && (
            <Button
              disabled={busy}
              onClick={() => {
                changed();
                formRef.current?.requestSubmit();
              }}
            >
              {t("previewMappings")}
            </Button>
          )}
          {preview.status === "reference_required" && (
            <p className="muted">
              {t("referencesRequired")}{" "}
              {items(preview.missing_references).join(" · ")}{" "}
              <a href="#import-references" onClick={openReferences}>
                {t("importReviewReferences")}
              </a>
            </p>
          )}
          {Object.keys(record(result.preparation)).length > 0 && (
            <p className="muted">
              {t("sourcePreparation")} ·{" "}
              {date(String(record(result.preparation).valuation_as_of), locale)}{" "}
              · {label(String(record(result.preparation).valuation_policy))}
            </p>
          )}
          {Object.keys(record(preview.observed_totals)).length > 0 && (
            <p className="muted">
              {t("observedSubtotalHint")}{" "}
              {(["CAD", "USD", "TWD"] as const)
                .map((unit) =>
                  amount(
                    typeof record(preview.observed_totals)[
                      `total_${unit.toLowerCase()}`
                    ] === "string"
                      ? String(
                          record(preview.observed_totals)[
                            `total_${unit.toLowerCase()}`
                          ],
                        )
                      : null,
                    unit,
                    locale,
                  ),
                )
                .join(" · ")}
            </p>
          )}
          {Object.keys(record(preview.sources)).length > 0 && (
            <div>
              <h3>{t("sourceUsage")}</h3>
              {Object.entries(record(preview.sources)).map(
                ([provider, value]) => (
                  <div className="preview-source" key={provider}>
                    <strong>
                      {providerName(provider, t("btcQuantity"), t("unknown"))}
                    </strong>
                    <span>
                      {label(String(record(value).status ?? "provided"))}
                    </span>
                    <span>
                      {String(
                        record(value).as_of ??
                          record(value).latest_completed_at ??
                          "",
                      )}
                    </span>
                    <dl className="preview-metrics">
                      {metrics
                        .filter(([key]) => record(value)[key] != null)
                        .map(([key, message]) => (
                          <div key={key}>
                            <dt>{t(message)}</dt>
                            <dd>{String(record(value)[key])}</dd>
                          </div>
                        ))}
                    </dl>
                  </div>
                ),
              )}
            </div>
          )}
          {Object.keys(record(preview.source_usage)).length > 0 && (
            <p className="muted">
              {Object.entries(record(preview.source_usage))
                .map(
                  ([provider, status]) =>
                    `${providerName(provider, t("btcQuantity"), t("unknown"))}: ${label(String(status))}`,
                )
                .join(" · ")}
            </p>
          )}
          {record(preview.balance).quantity_btc != null && (
            <p>
              {t("btcQuantity")}:{" "}
              {quantity(String(record(preview.balance).quantity_btc))} BTC ·{" "}
              {date(String(record(preview.balance).as_of), locale)}
            </p>
          )}
          {record(preview.btc).quantity_btc != null && (
            <p>
              {t("btcQuantity")}:{" "}
              {quantity(String(record(preview.btc).quantity_btc))} BTC ·{" "}
              {t("unresolvedCount")}:{" "}
              {String(record(preview.btc).unresolved_count ?? "—")}
            </p>
          )}
          {(["blockers", "pending_checks"] as const).map(
            (key) =>
              items(preview[key]).length > 0 && (
                <div key={key}>
                  <h3>{t(key === "blockers" ? "blockers" : "pending")}</h3>
                  <ul>
                    {items(preview[key]).map((value, index) => (
                      <li key={index}>
                        {typeof value === "string" ? (
                          <code>{value}</code>
                        ) : (
                          <>
                            <strong>
                              {String(record(value).component ?? "")}
                            </strong>{" "}
                            {String(record(value).message ?? "")}
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ),
          )}
          <details>
            <summary>{t("importPreviewIdentity")}</summary>
            <dl className="job-facts">
              <div>
                <dt>{t("importJobId")}</dt>
                <dd>
                  <code>{job.id}</code>
                </dd>
              </div>
              {job.core_operation_id && (
                <div>
                  <dt>{t("importOperationId")}</dt>
                  <dd>
                    <code>{job.core_operation_id}</code>
                  </dd>
                </div>
              )}
              {job.kind === "preview" && (
                <div>
                  <dt>{t("importExpires")}</dt>
                  <dd>
                    {date(
                      new Date((job.created_at + 86400) * 1000).toISOString(),
                      locale,
                    )}
                  </dd>
                </div>
              )}
              {typeof preview.approval_sha256 === "string" && (
                <div>
                  <dt>{t("importApprovalDigest")}</dt>
                  <dd>
                    <code>{preview.approval_sha256}</code>
                  </dd>
                </div>
              )}
            </dl>
          </details>
          {job.kind === "preview" && (
            <p className="muted">{t("previewHint")}</p>
          )}
          <div className="actions">
            {confirmable && (
              <Button
                disabled={busy}
                onClick={() => {
                  setConfirming(true);
                }}
              >
                {t("confirm")}
              </Button>
            )}
            {job.status === "queued" && (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => action("cancel", job)}
              >
                {t("cancel")}
              </Button>
            )}
            {job.kind === "update" && job.status === "report_failed" && (
              <Button disabled={busy} onClick={() => action("resume", job)}>
                {t("resume")}
              </Button>
            )}
          </div>
          <Dialog.Root
            open={confirming && confirmable}
            onOpenChange={(open) => {
              if (!busy) setConfirming(open);
            }}
          >
            <Dialog.Portal>
              <Dialog.Overlay className="dialog-overlay" />
              <Dialog.Content className="dialog">
                <Dialog.Title>{t("confirmTitle")}</Dialog.Title>
                <Dialog.Description>{t("confirmHint")}</Dialog.Description>
                <p>{t("importFrozenReviewHint")}</p>
                {failure && (
                  <p role="alert" className="error">
                    {error(failure)} <code>{failure}</code>
                    <span className="import-error-guidance">
                      {t(importFailureMessage(failure))}
                    </span>
                  </p>
                )}
                <div className="actions">
                  <Button
                    disabled={busy}
                    onClick={() => action("confirm", job)}
                  >
                    {t("confirm")}
                  </Button>
                  <Dialog.Close asChild>
                    <Button variant="secondary" disabled={busy}>
                      {t("back")}
                    </Button>
                  </Dialog.Close>
                </div>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        </section>
      )}
      <section className="panel">
        <h2>{t("jobs")}</h2>
        {selected && !job && jobs.isSuccess && (
          <p role="status">{t("processingJobMissing")}</p>
        )}
        {importJobs.length ? (
          <div className="job-list">
            {importJobs.map((value) => (
              <button
                className={job?.id === value.id ? "selected" : ""}
                key={value.id}
                disabled={busy}
                onClick={() => {
                  setSelected(value.id);
                  setJobParams({ job: value.id }, { replace: true });
                  setFailure("");
                }}
              >
                <span>
                  {value.kind === "preview" ? t("preview") : t("confirm")}
                </span>
                <time>
                  {date(
                    new Date(value.created_at * 1000).toISOString(),
                    locale,
                  )}
                </time>
                <span className="status">{label(value.status)}</span>
              </button>
            ))}
          </div>
        ) : (
          <p>{t("noJobs")}</p>
        )}
      </section>
    </>
  );
}
