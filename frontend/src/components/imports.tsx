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
import { Button } from "./ui/button";
const active = new Set(["queued", "running", "data_committed"]);
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const items = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : [];
type Binding = {
  provider: string;
  source_account_id: string;
  target_kind: "new" | "canonical" | "legacy_holdings" | "legacy_crypto";
  ledger_account_id?: string;
};
export function Imports({ portfolio }: { portfolio: string }) {
  const { t, label, error, locale } = useI18n();
  const client = useQueryClient();
  const [parserMode, setParserMode] = useState(false);
  const [sourceFiles, setSourceFiles] = useState<File[]>([]);
  const [choices, setChoices] = useState<Binding[]>([]);
  const formRef = useRef<HTMLFormElement>(null);
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
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
    if (publishedIds)
      void client.invalidateQueries({ queryKey: [portfolio, "reports"] });
  }, [publishedIds, client, portfolio]);
  const job = importJobs.find((job) => job.id === selected) ?? importJobs[0];
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
    setFailure("");
  };
  async function refresh(value: Job) {
    setSelected(value.id);
    await client.invalidateQueries({ queryKey: [portfolio] });
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
              ...(form.get(`alias-${index}`)
                ? { account_alias: form.get(`alias-${index}`) }
                : {}),
              ...(form.get(`timezone-${index}`)
                ? { source_timezone: form.get(`timezone-${index}`) }
                : {}),
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
      await refresh(
        await mutate<Job>(
          scope(portfolio) +
            (parserMode ? "/source-import-previews" : "/previews"),
          requestBody,
          "POST",
          requestKey,
        ),
      );
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError"))
        setFailure(reason instanceof ApiError ? reason.code : "request_failed");
    } finally {
      setBusy(false);
    }
  }
  async function action(kind: "confirm" | "cancel" | "resume", current: Job) {
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
      if (reason instanceof ApiError) setFailure(reason.code);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="panel">
        <h2>{t("uploadTitle")}</h2>
        <p className="muted">{t("uploadHint")}</p>
        <form
          ref={formRef}
          className="import-form"
          onSubmit={submit}
          onChange={changed}
        >
          <label className="check-label">
            <input
              type="checkbox"
              checked={parserMode}
              onChange={(event) => {
                setParserMode(event.target.checked);
                setChoices([]);
              }}
            />
            {t("parserMode")}
          </label>
          {parserMode && <p className="muted">{t("parserModeHint")}</p>}
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
              }}
            />
            <small>
              {parserMode ? t("enabledParsers") : "Wealthsimple / Bull Bitcoin"}{" "}
              · CSV ≤ 10 MiB
            </small>
          </label>
          {parserMode &&
            sourceFiles.map((file, index) => (
              <fieldset key={`${file.name}-${index}`}>
                <legend>{file.name}</legend>
                <div className="form-grid">
                  <label>
                    {t("sourceAlias")}
                    <input name={`alias-${index}`} maxLength={160} />
                  </label>
                  <label>
                    {t("sourceTimezone")}
                    <input
                      name={`timezone-${index}`}
                      placeholder="America/Toronto"
                    />
                  </label>
                  <label>
                    {t("sourceAdapter")}
                    <input name={`adapter-${index}`} />
                  </label>
                </div>
              </fieldset>
            ))}
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
              <input name="observed" placeholder="2026-10-17T18:00:00-04:00" />
            </label>
          </div>
          {parserMode && (
            <label className="check-label">
              <input type="checkbox" name="fetch_references" />
              {t("fetchPublicReferences")}
            </label>
          )}
          {!parserMode && (
            <label className="check-label">
              <input type="checkbox" name="render_saved" />
              {t("renderSaved")}
            </label>
          )}
          <details>
            <summary>{t("references")}</summary>
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
          <Button type="submit" disabled={busy}>
            {busy ? t("loading") : t("preview")}
          </Button>
        </form>
      </section>
      {failure && (
        <p role="alert" className="error">
          {error(failure)} <code>{failure}</code>
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
        <section className="panel">
          <div className="panel-heading">
            <h2>{t("previewResult")}</h2>
            <span className="status">{label(job.status)}</span>
          </div>
          <p className="muted">{t("workerHint")}</p>
          <dl className="job-facts">
            <div>
              <dt>{t("kind")}</dt>
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
              {items(preview.missing_references).join(" · ")}
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
                      {provider === "wealthsimple"
                        ? "Wealthsimple"
                        : provider === "bullbitcoin"
                          ? "Bull Bitcoin"
                          : t("btcQuantity")}
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
                    `${provider === "wealthsimple" ? "Wealthsimple" : "Bull Bitcoin"}: ${label(String(status))}`,
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
          <p className="muted">{t("previewHint")}</p>
          <div className="actions">
            {job.kind === "preview" &&
              job.status === "ready" &&
              preview.status !== "mapping_required" &&
              preview.status !== "reference_required" && (
                <Button
                  disabled={busy}
                  onClick={() => {
                    confirmKey.current = crypto.randomUUID();
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
          <Dialog.Root open={confirming} onOpenChange={setConfirming}>
            <Dialog.Portal>
              <Dialog.Overlay className="dialog-overlay" />
              <Dialog.Content className="dialog">
                <Dialog.Title>{t("confirmTitle")}</Dialog.Title>
                <Dialog.Description>{t("confirmHint")}</Dialog.Description>
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
        {importJobs.length ? (
          <div className="job-list">
            {importJobs.map((value) => (
              <button
                className={job?.id === value.id ? "selected" : ""}
                key={value.id}
                onClick={() => {
                  setSelected(value.id);
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
