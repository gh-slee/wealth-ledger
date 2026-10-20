import { useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
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
import { useI18n, type Message } from "../lib/i18n";
import { Button } from "./ui/button";

type Command =
  | "balance"
  | "event"
  | "revision"
  | "opening"
  | "cash_flow"
  | "cash_flow_upload"
  | "coverage";
const commands: Command[] = [
  "balance",
  "event",
  "revision",
  "opening",
  "cash_flow",
  "cash_flow_upload",
  "coverage",
];
const events = [
  "fee",
  "sale",
  "spend",
  "external_out",
  "external_in",
  "own_transfer",
  "conversion",
];
const active = new Set(["queued", "running", "data_committed"]);
type Row = Record<string, unknown>;
const object = (v: unknown): Row =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Row) : {};
const titles: Record<Command, Message> = {
  balance: "recordBalance",
  event: "recordEvent",
  revision: "recordRevision",
  opening: "recordOpening",
  cash_flow: "recordFlow",
  cash_flow_upload: "recordFlowUpload",
  coverage: "recordCoverage",
};
const fields: Record<string, Message> = {
  quantity_btc: "btcQuantity",
  as_of: "observedAt",
  source: "recordSource",
  occurred_at: "eventAt",
  reference: "eventReference",
  reason: "revisionReason",
  reported_total_btc_equivalent: "btcQuantity",
  reference_as_of: "openingReferenceAt",
  declared_on: "declaredOn",
  basis: "openingBasis",
  confirmed_by: "confirmedBy",
  date: "flowDate",
  amount: "flowAmount",
  flow_id: "flowReference",
  transfer_id: "transferReference",
  usd_cad: "flowRate",
  amount_cad: "flowCad",
  fx_date: "flowFxDate",
  fx_source: "flowFxSource",
  start_date: "coverageStart",
  end_date: "coverageEnd",
  replaces: "replacementRecord",
};
export function Financial({ portfolio }: { portfolio: string }) {
  const { t, error, label } = useI18n();
  const client = useQueryClient();
  const [command, setCommand] = useState<Command>("balance"),
    [action, setAction] = useState("revise"),
    [chosenRecord, setChosenRecord] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState(""),
    [confirming, setConfirming] = useState(false),
    [detailId, setDetailId] = useState("");
  const key = useRef(crypto.randomUUID()),
    confirmKey = useRef(crypto.randomUUID());
  const state = useQuery({
    queryKey: [portfolio, "financial"],
    queryFn: ({ signal }) =>
      read<Models["FinancialState"]>(scope(portfolio) + "/financial", signal),
  });
  const jobs = useQuery({
    queryKey: [portfolio, "jobs"],
    queryFn: ({ signal }) =>
      read<Models["JobList"]>(scope(portfolio) + "/jobs", signal),
    refetchInterval: (q) =>
      q.state.data?.jobs.some((j) => active.has(j.status)) ? 1000 : 5000,
  });
  const detail = useQuery({
    queryKey: [portfolio, "financial-record", detailId],
    queryFn: ({ signal }) =>
      read<Models["FinancialRecordDetail"]>(
        scope(portfolio) + "/financial/records/" + detailId,
        signal,
      ),
    enabled: Boolean(detailId),
  });
  const records = [
    ...(state.data?.balances ?? []),
    ...(state.data?.events ?? []),
  ];
  const current = records.find((r) => r.record_id === chosenRecord);
  const history =
    jobs.data?.jobs.filter((j) =>
      ["record", "record_preview"].includes(j.kind),
    ) ?? [];
  const job = history.find((j) => j.id === selected);
  const result = object(job?.result),
    preview = object(result.declaration),
    output = object(result.result);
  const changed = () => {
    key.current = crypto.randomUUID();
    setSelected(null);
    setFailure("");
  };
  function input(name: string, required = true, type = "text") {
    return (
      <label key={name}>
        {t(fields[name])}
        <input
          name={name}
          required={required}
          type={type}
          maxLength={240}
          inputMode={
            name.includes("quantity") ||
            [
              "amount",
              "usd_cad",
              "amount_cad",
              "reported_total_btc_equivalent",
            ].includes(name)
              ? "decimal"
              : undefined
          }
        />
      </label>
    );
  }
  function select(
    name: string,
    title: Message,
    options: string[],
    required = true,
  ) {
    return (
      <label>
        {t(title)}
        <select name={name} required={required} defaultValue="">
          <option value="">{t("chooseValue")}</option>
          {options.map((value) => (
            <option key={value} value={value}>
              {label(value) === t("unknown") ? value : label(value)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setFailure("");
    try {
      const body: Row = { command };
      for (const [name, value] of form.entries())
        if (typeof value === "string" && value.trim())
          body[name] = value.trim();
      if (command === "revision") {
        body.expected_revision = current?.revision;
        if (action === "unlink" || action === "void")
          for (const name of [
            "quantity_btc",
            "source",
            "type",
            "occurred_at",
            "balance_id",
          ])
            delete body[name];
      }
      if (command === "opening") {
        body.expected_revision = state.data?.opening?.revision ?? 0;
        body.balance_scope = "all_wallets_btc_plus_lbtc";
      }
      if (command === "cash_flow_upload") {
        const file = form.get("file");
        if (!(file instanceof File) || !file.size) return;
        body.upload_id = (await upload(portfolio, file, "cash_flows")).id;
      }
      const value = await mutate<Job>(
        scope(portfolio) + "/financial/previews",
        body,
        "POST",
        key.current,
      );
      setSelected(value.id);
      await client.invalidateQueries({ queryKey: [portfolio, "jobs"] });
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError"))
        setFailure(reason instanceof ApiError ? reason.code : "request_failed");
    } finally {
      setBusy(false);
    }
  }
  async function commit() {
    if (!job) return;
    setBusy(true);
    setFailure("");
    try {
      const value = await mutate<Job>(
        scope(portfolio) + "/financial/jobs",
        { preview_id: job.id },
        "POST",
        confirmKey.current,
      );
      setSelected(value.id);
      setConfirming(false);
      await client.invalidateQueries({ queryKey: [portfolio] });
    } catch (reason) {
      if (reason instanceof ApiError) setFailure(reason.code);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    await client.invalidateQueries({ queryKey: [portfolio, "financial"] });
    await client.invalidateQueries({
      queryKey: [portfolio, "financial-record"],
    });
  }
  function summary(value: Row) {
    return (
      <dl className="record-summary">
        {Object.entries(value)
          .filter(
            ([name, v]) =>
              ![
                "command",
                "expected_revision",
                "balance_scope",
                "id",
                "record_type",
                "kind",
              ].includes(name) &&
              (v == null
                ? [
                    "recorded_expected_btc",
                    "recorded_residual_btc",
                    "cost_cad",
                    "historical_contribution_cad",
                  ].includes(name)
                : typeof v !== "object"),
          )
          .map(([name, v]) => (
            <div key={name}>
              <dt>
                {fields[name]
                  ? t(fields[name])
                  : ((
                      {
                        record_id: t("recordId"),
                        revision: t("revisionVersion"),
                        balance_id: t("linkedBalance"),
                        quantity_btc: t("btcQuantity"),
                        type: t("eventType"),
                        action: t("revisionAction"),
                        void: t("voidState"),
                        status: t("recordStatus"),
                        recorded_expected_btc: t("expectedBtc"),
                        recorded_residual_btc: t("residualBtc"),
                        opening_btc_equivalent_qty: t("openingQuantity"),
                        reference_purchased_btc_equivalent:
                          t("purchasedQuantity"),
                        reference_known_event_btc: t("knownEventsAtReference"),
                        cost_cad: t("openingActualCost"),
                        historical_contribution_cad: t(
                          "openingHistoricalContributions",
                        ),
                        imported: t("importedFlows"),
                        integrity_ok: t("evidenceChecksum"),
                      } as Record<string, string>
                    )[name] ?? name)}
              </dt>
              <dd>
                {v == null
                  ? t("unknown")
                  : typeof v === "boolean"
                    ? t(v ? "yesValue" : "noValue")
                    : ["status", "action", "type"].includes(name)
                      ? label(String(v))
                      : String(v)}
              </dd>
            </div>
          ))}
      </dl>
    );
  }
  return (
    <>
      <section className="panel">
        <h2>{t("recordsTitle")}</h2>
        <p className="muted">{t("recordsHint")}</p>
        <div className="record-workflow">
          <span>{t("recordStepPreview")}</span>
          <span>{t("recordStepSave")}</span>
          <span>{t("recordStepReport")}</span>
        </div>
        <label>
          {t("recordTask")}
          <select
            value={command}
            disabled={busy}
            onChange={(e) => {
              setCommand(e.target.value as Command);
              changed();
            }}
          >
            {commands.map((c) => (
              <option key={c} value={c}>
                {t(titles[c])}
              </option>
            ))}
          </select>
        </label>
        <form
          key={command}
          className="import-form"
          onSubmit={submit}
          onChange={changed}
        >
          <fieldset
            disabled={busy || state.isPending}
            className="record-fields"
          >
            <div className="form-grid">
              {command === "balance" && (
                <>
                  {input("quantity_btc")}
                  {input("as_of")}
                  {input("source")}
                  {input("replaces", false)}
                </>
              )}
              {command === "event" && (
                <>
                  {select("type", "eventType", events)}
                  {input("quantity_btc")}
                  {input("occurred_at")}
                  {input("source")}
                  {input("reference")}
                  {select(
                    "balance_id",
                    "linkedBalance",
                    (state.data?.balances ?? [])
                      .filter((r) => !r.void)
                      .map((r) => String(r.record_id)),
                    false,
                  )}
                  {input("replaces", false)}
                </>
              )}
              {command === "revision" && (
                <>
                  <label>
                    {t("recordId")}
                    <select
                      name="record_id"
                      required
                      value={chosenRecord}
                      onChange={(e) => {
                        setChosenRecord(e.target.value);
                        setAction("revise");
                      }}
                    >
                      <option value="">{t("chooseValue")}</option>
                      {records
                        .filter((r) => !r.void)
                        .map((r) => (
                          <option
                            key={String(r.record_id)}
                            value={String(r.record_id)}
                          >
                            {String(r.record_id)} · r{String(r.revision)}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    {t("revisionAction")}
                    <select
                      name="action"
                      value={action}
                      onChange={(e) => setAction(e.target.value)}
                    >
                      {[
                        "revise",
                        "void",
                        ...(current?.kind === "event"
                          ? ["link", "unlink"]
                          : []),
                      ].map((v) => (
                        <option key={v} value={v}>
                          {label(v)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {input("reason")}
                  {action === "revise" && (
                    <>
                      {input("quantity_btc", false)}
                      {current?.kind === "balance" ? (
                        input("source", false)
                      ) : (
                        <>
                          {select("type", "eventType", events, false)}
                          {input("occurred_at", false)}
                        </>
                      )}
                    </>
                  )}
                  {action === "link" &&
                    select(
                      "balance_id",
                      "linkedBalance",
                      (state.data?.balances ?? [])
                        .filter((r) => !r.void)
                        .map((r) => String(r.record_id)),
                    )}
                </>
              )}
              {command === "opening" && (
                <>
                  {input("reported_total_btc_equivalent")}
                  {input("reference_as_of")}
                  {input("declared_on", true, "date")}
                  {input("basis")}
                  {input("confirmed_by")}
                </>
              )}
              {command === "cash_flow" && (
                <>
                  {input("date", true, "date")}
                  <label>
                    {t("flowAccount")}
                    <select name="account_id" required>
                      {(state.data?.accounts ?? []).map((a) => (
                        <option
                          key={String(a.account_id)}
                          value={String(a.account_id)}
                        >
                          {String(a.label)} · {String(a.masked_number)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {select("flow_type", "flowType", [
                    "deposit",
                    "withdrawal",
                    "transfer_in",
                    "transfer_out",
                    "income",
                    "fee",
                    "internal",
                  ])}
                  {select("currency", "currency", ["CAD", "USD"])}
                  {input("amount")}
                  {input("flow_id")}
                  {input("transfer_id", false)}
                  {input("usd_cad", false)}
                  {input("amount_cad", false)}
                  {input("fx_date", false, "date")}
                  {input("fx_source", false)}
                </>
              )}
              {command === "cash_flow_upload" && (
                <label>
                  {t("flowCsv")}
                  <input
                    name="file"
                    type="file"
                    accept=".csv,text/csv"
                    required
                  />
                </label>
              )}
              {command === "coverage" && (
                <>
                  {input("start_date", true, "date")}
                  {input("end_date", true, "date")}
                  {select("status", "coverageStatus", [
                    "partial",
                    "complete",
                    "no_external",
                  ])}
                  <label>
                    {t("coverageScope")}
                    <select name="account_id">
                      <option value="portfolio">{t("wholeBrokerage")}</option>
                      {(state.data?.accounts ?? []).map((a) => (
                        <option
                          key={String(a.account_id)}
                          value={String(a.account_id)}
                        >
                          {String(a.label)}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
            </div>
            <p className="muted">
              {t(
                command === "opening"
                  ? "openingDeclarationHint"
                  : command === "cash_flow" || command === "cash_flow_upload"
                    ? "flowDeclarationHint"
                    : command === "coverage"
                      ? "coverageDeclarationHint"
                      : command === "revision"
                        ? "revisionDeclarationHint"
                        : "balanceDeclarationHint",
              )}
            </p>
            <Button type="submit">
              {busy ? t("loading") : t("recordPreview")}
            </Button>
          </fieldset>
        </form>
      </section>
      {(failure || state.isError || jobs.isError) && (
        <p role="alert" className="error">
          {error(failure || "request_failed")}
        </p>
      )}
      {job && (
        <section className="panel" aria-live="polite">
          <div className="panel-heading">
            <h2>{t("previewResult")}</h2>
            <span className="status">{label(job.status)}</span>
          </div>
          {Object.keys(preview).length > 0 && (
            <>
              <h3>{t("proposedDeclaration")}</h3>
              {summary(preview)}
            </>
          )}
          {Object.keys(output).length > 0 && (
            <>
              <h3>{t("declarationResult")}</h3>
              {summary(output)}
            </>
          )}
          {job.error_code && (
            <p role="alert" className="error">
              {error(job.error_code)} <code>{job.error_code}</code>
            </p>
          )}
          {job.kind === "record_preview" && job.status === "ready" && (
            <Button
              disabled={busy}
              onClick={() => {
                confirmKey.current = crypto.randomUUID();
                setConfirming(true);
              }}
            >
              {t("saveDeclaration")}
            </Button>
          )}
          {job.status === "recorded" && (
            <p>
              {t("recordSavedHint")}{" "}
              <Button variant="secondary" onClick={refresh}>
                {t("refreshRecords")}
              </Button>{" "}
              <Link to={`/app/${portfolio}/imports`}>{t("prepareReport")}</Link>
            </p>
          )}
        </section>
      )}
      <Dialog.Root open={confirming} onOpenChange={setConfirming}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog">
            <Dialog.Title>{t("saveDeclaration")}</Dialog.Title>
            <Dialog.Description>{t("recordConfirmHint")}</Dialog.Description>
            <div className="actions">
              <Button disabled={busy} onClick={commit}>
                {t("saveDeclaration")}
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
      <section className="panel">
        <div className="panel-heading">
          <h2>{t("currentRecords")}</h2>
          <Button variant="secondary" onClick={refresh}>
            {t("refreshRecords")}
          </Button>
        </div>
        {state.data?.truncated && <p>{t("recordsTruncated")}</p>}
        {state.data?.opening && (
          <>
            <h3>{t("recordOpening")}</h3>
            {summary(state.data.opening)}
          </>
        )}
        {records.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t("recordId")}</th>
                  <th>{t("btcQuantity")}</th>
                  <th>{t("revisionVersion")}</th>
                  <th>{t("recordStatus")}</th>
                  <th>{t("recordDetails")}</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={String(r.record_id)}>
                    <td>{String(r.record_id)}</td>
                    <td>{String(r.quantity_btc)}</td>
                    <td>{String(r.revision)}</td>
                    <td>{t(r.void ? "voidValue" : "activeValue")}</td>
                    <td>
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setDetailId(String(r.record_id));
                          void refresh();
                        }}
                      >
                        {t("recordDetails")} {String(r.record_id)}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>{t("noRecords")}</p>
        )}
        {detailId && (
          <div>
            <h3>
              {t("recordDetails")} {detailId}
            </h3>
            {detail.isError ? (
              <p role="alert">{t("failed")}</p>
            ) : (
              <>
                {summary(object(detail.data?.record))}
                {detail.data?.reconciliation && (
                  <dl className="record-summary">
                    <div>
                      <dt>{t("expectedBtc")}</dt>
                      <dd>
                        {String(
                          detail.data.reconciliation.expected_btc ??
                            t("unknown"),
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("residualBtc")}</dt>
                      <dd>
                        {String(
                          detail.data.reconciliation.residual_btc ??
                            t("unknown"),
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{t("recordStatus")}</dt>
                      <dd>
                        {label(String(detail.data.reconciliation.status))}
                      </dd>
                    </div>
                  </dl>
                )}
                {Array.isArray(detail.data?.revisions) &&
                  detail.data.revisions.map((v, i) => (
                    <details key={i}>
                      <summary>
                        {t("revisionVersion")} {String(object(v).revision)}
                      </summary>
                      {summary(object(v))}
                    </details>
                  ))}
              </>
            )}
          </div>
        )}
        <h3>{t("recordFlow")}</h3>
        {state.data?.cash_flows.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{t("flowDate")}</th>
                  <th>{t("flowType")}</th>
                  <th>{t("flowAmount")}</th>
                  <th>{t("flowCad")}</th>
                  <th>{t("flowReference")}</th>
                </tr>
              </thead>
              <tbody>
                {state.data.cash_flows.map((r, i) => (
                  <tr key={i}>
                    <td>{String(r.date)}</td>
                    <td>{label(String(r.flow_type))}</td>
                    <td>
                      {String(r.amount)} {String(r.currency)}
                    </td>
                    <td>{String(r.amount_cad)}</td>
                    <td>{String(r.flow_id)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>{t("noRecords")}</p>
        )}
        <h3>{t("recordCoverage")}</h3>
        {state.data?.coverage.map((r, i) => (
          <p key={i}>
            {String(r.start_date)} → {String(r.end_date)} ·{" "}
            {String(r.account_id)} · {label(String(r.status))}
          </p>
        ))}
      </section>
      <section className="panel">
        <h2>{t("flowAccount")}</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("flowAccount")}</th>
                <th>{t("recordId")}</th>
              </tr>
            </thead>
            <tbody>
              {state.data?.accounts.map((a) => (
                <tr key={String(a.account_id)}>
                  <td>
                    {String(a.label)} · {String(a.masked_number)}
                  </td>
                  <td>
                    <code>{String(a.account_id)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <h2>{t("recordJobs")}</h2>
        <div className="job-list">
          {history.map((j) => (
            <button key={j.id} onClick={() => setSelected(j.id)}>
              <span>
                {t(
                  j.kind === "record_preview"
                    ? "recordPreview"
                    : "saveDeclaration",
                )}
              </span>
              <span className="status">{label(j.status)}</span>
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
