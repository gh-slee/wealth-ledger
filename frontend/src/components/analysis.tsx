import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import type { Currency, Models, Report } from "../lib/api";
import { amount, date, percent, quantity } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { DataTable } from "./data-table";
import { Chart } from "./chart";
import { CurrentProcessing, EvidenceStatus } from "./evidence-status";
import { ReportNotices } from "./report-notices";
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const rows = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value) ? value.map(object) : [];
const text = (value: unknown): string | null =>
  typeof value === "string" ? value : null;
export function Evidence({ data }: { data: Report }) {
  const { t, locale, label } = useI18n();
  return (
    <section
      id="source-evidence"
      className="evidence-rail"
      aria-label={t("evidence")}
    >
      <div className="evidence-cutoff">
        <span className="eyebrow">{t("cutoff")}</span>
        <strong>{date(data.as_of, locale)}</strong>
      </div>
      {data.source_dates.map((source, index) => (
        <div
          className="source-date"
          key={`${source.provider}-${source.as_of}-${source.usage}-${index}`}
        >
          <span>
            {source.provider === "wallet"
              ? t("btcQuantity")
              : source.provider === "wealthsimple"
                ? "Wealthsimple"
                : source.provider === "bullbitcoin"
                  ? "Bull Bitcoin"
                  : source.provider}
          </span>
          <strong>{date(source.as_of, locale)}</strong>
          <span
            className={
              source.usage === "carried_forward"
                ? "status status-review"
                : "status"
            }
          >
            {label(source.usage)}
          </span>
        </div>
      ))}
      <p className="evidence-note">{t("sourceHint")}</p>
    </section>
  );
}
export function Overview({
  data,
  currency,
  portfolio,
  latest,
}: {
  data: Report;
  currency: Currency;
  portfolio: string;
  latest?: Models["ReportSummary"];
}) {
  const { t, locale } = useI18n();
  const field = `total_${currency.toLowerCase()}` as "total_cad";
  return (
    <>
      <div className="value-strip">
        <div>
          <span className="eyebrow">{t("value")}</span>
          <h2 className="portfolio-value">
            {amount(data.totals[field], currency, locale)}
          </h2>
          <p className="muted">{t("frozen")}</p>
          {data.source_basis && (
            <p className="muted">{t("observedSubtotalHint")}</p>
          )}
        </div>
        <div className="summary-stats">
          <div>
            <span>{t("accounts")}</span>
            <strong>{data.accounts.length}</strong>
          </div>
          <div>
            <span>{t("cash")}</span>
            <strong>{amount(data.totals.cash_cad, "CAD", locale)}</strong>
          </div>
          <span
            className={`status ${data.is_complete ? "status-good" : "status-review"}`}
          >
            {t(data.is_complete ? "complete" : "incomplete")}
          </span>
        </div>
      </div>
      <CurrentProcessing portfolio={portfolio} />
      <EvidenceStatus
        key={data.report.id}
        data={data}
        portfolio={portfolio}
        latest={latest}
      />
      <div className="analysis-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>{t("growth")}</h2>
            <span className="eyebrow">{currency}</span>
          </div>
          <Chart
            title={t("growth")}
            line
            currency={currency}
            labels={data.history.map((row) => row.as_of)}
            values={data.history.map((row) => row[field])}
          />
          <p className="muted">
            {data.history.length === 1 ? t("onePoint") : t("growthHint")}
          </p>
          <details>
            <summary>{t("viewData")}</summary>
            <DataTable
              data={data.history}
              caption={t("growth")}
              columns={[
                {
                  accessorKey: "as_of",
                  header: t("cutoff"),
                  cell: ({ getValue }) => date(getValue() as string, locale),
                },
                {
                  accessorKey: field,
                  header: currency,
                  cell: ({ getValue }) =>
                    amount(getValue() as string | null, currency, locale),
                },
              ]}
            />
          </details>
        </section>
        <section className="panel">
          <h2>{t("accountBreakdown")}</h2>
          <div className="account-list">
            {data.accounts.map((account) => (
              <div key={account.account_id}>
                <span>{account.label}</span>
                <strong>{amount(account[field], currency, locale)}</strong>
                <span className="muted">
                  {percent(account.portfolio_weight)}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
      <section className="panel">
        <h2>{t("fxRates")}</h2>
        <div className="coverage">
          <span>
            1 USD → {quantity(data.fx.usd_cad)} CAD ·{" "}
            {data.fx.usd_cad_date ?? "—"}
          </span>
          <span>
            1 USD → {quantity(data.fx.usd_twd)} TWD ·{" "}
            {data.fx.usd_twd_date ?? "—"}
          </span>
        </div>
        <p className="muted">{t("frozen")}</p>
      </section>
    </>
  );
}
export function Holdings({
  data,
  currency,
}: {
  data: Report;
  currency: Currency;
}) {
  const { t, locale } = useI18n();
  const [search, setSearch] = useState("");
  const [account, setAccount] = useState("");
  const [native, setNative] = useState("");
  const securities = data.holdings.filter(
    (row) =>
      row.security_type !== "CRYPTO" &&
      (!account || row.account_id === account) &&
      (!native || row.currency === native) &&
      `${row.symbol} ${row.name}`.toLowerCase().includes(search.toLowerCase()),
  );
  const columns: ColumnDef<Models["Holding"]>[] = [
    {
      accessorKey: "symbol",
      header: t("symbol"),
      cell: ({ row }) => (
        <div className="security-label">
          <strong>{row.original.symbol}</strong>
          <small>{row.original.name}</small>
        </div>
      ),
    },
    { accessorKey: "account_label", header: t("account") },
    { accessorKey: "currency", header: t("originalCurrency") },
    {
      accessorKey: "quantity",
      header: t("quantity"),
      cell: ({ getValue }) => quantity(getValue() as string | null),
    },
    {
      accessorKey: "avg_cost",
      header: t("averageCost"),
      cell: ({ row }) =>
        amount(
          row.original.avg_cost,
          row.original.currency as Currency,
          locale,
        ),
    },
    {
      accessorKey: `market_${currency.toLowerCase()}`,
      header: `${t("marketValue")} · ${currency}`,
      cell: ({ getValue }) =>
        amount(getValue() as string | null, currency, locale),
    },
    {
      accessorKey: "unrealized_native",
      header: t("unrealized"),
      cell: ({ row }) =>
        amount(
          row.original.unrealized_native,
          row.original.currency as Currency,
          locale,
        ),
    },
    {
      accessorKey: "portfolio_weight",
      header: t("weight"),
      cell: ({ getValue }) => percent(getValue() as string | null),
    },
  ];
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{t("holdings")}</h2>
        <span className="status">{securities.length}</span>
      </div>
      <p className="muted">{t("nativeHint")}</p>
      <div className="filters">
        <label>
          {t("search")}
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          {t("account")}
          <select
            value={account}
            onChange={(event) => setAccount(event.target.value)}
          >
            <option value="">{t("allAccounts")}</option>
            {data.accounts
              .filter((a) => a.source_provider !== "bullbitcoin")
              .map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.label}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("originalCurrency")}
          <select
            value={native}
            onChange={(event) => setNative(event.target.value)}
          >
            <option value="">{t("allCurrencies")}</option>
            <option>CAD</option>
            <option>USD</option>
          </select>
        </label>
      </div>
      <DataTable data={securities} columns={columns} caption={t("holdings")} />
    </section>
  );
}
export function Exposure({ data }: { data: Report }) {
  const { t, locale, label } = useI18n();
  const [dimension, setDimension] = useState<"sector" | "country" | "region">(
    "sector",
  );
  const section = data.dimensions[dimension];
  const columns: ColumnDef<Models["Company"]>[] = [
    { accessorKey: "rank", header: t("rank") },
    { accessorKey: "name", header: t("company") },
    {
      accessorKey: "direct_cad",
      header: t("direct"),
      cell: ({ getValue }) =>
        amount(getValue() as string | null, "CAD", locale),
    },
    {
      accessorKey: "indirect_cad",
      header: t("indirect"),
      cell: ({ getValue }) =>
        amount(getValue() as string | null, "CAD", locale),
    },
    {
      accessorKey: "asset_weight",
      header: t("weight"),
      cell: ({ getValue }) => percent(getValue() as string | null),
    },
  ];
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <h2>{t("exposure")}</h2>
          <select
            aria-label={t("exposure")}
            value={dimension}
            onChange={(event) =>
              setDimension(event.target.value as typeof dimension)
            }
          >
            {(["sector", "country", "region"] as const).map((key) => (
              <option key={key} value={key}>
                {t(key)}
              </option>
            ))}
          </select>
        </div>
        {section ? (
          <>
            <div className="coverage">
              <span>
                {t("coverage")}{" "}
                <strong>{percent(section.equity_coverage)}</strong>
              </span>
              <span>
                {t("investmentCoverage")}{" "}
                <strong>{percent(section.investment_coverage)}</strong>
              </span>
              <span>
                {t("effective")}: {section.as_of_min ?? "—"} —{" "}
                {section.as_of_max ?? "—"}
              </span>
            </div>
            <Chart
              title={`${t(dimension)} · CAD`}
              labels={section.rows.map((row) => row.name)}
              values={section.rows.map((row) => row.market_cad)}
            />
            <details>
              <summary>{t("viewData")}</summary>
              <DataTable
                caption={t(dimension)}
                data={section.rows}
                columns={[
                  { accessorKey: "name", header: t(dimension) },
                  {
                    accessorKey: "market_cad",
                    header: "CAD",
                    cell: ({ getValue }) =>
                      amount(getValue() as string | null, "CAD", locale),
                  },
                  {
                    accessorKey: "investment_weight",
                    header: t("weight"),
                    cell: ({ getValue }) =>
                      percent(getValue() as string | null),
                  },
                ]}
              />
            </details>
          </>
        ) : (
          <p>{t("noExposure")}</p>
        )}
      </section>
      <section className="panel">
        <h2>{t("topCompanies")}</h2>
        <p className="muted">{t("companyHint")}</p>
        <DataTable
          data={data.companies}
          columns={columns}
          caption={t("topCompanies")}
        />
      </section>
      <section className="panel">
        <h2>{t("officialSources")}</h2>
        <DataTable
          data={data.exposure_sources}
          caption={t("officialSources")}
          columns={[
            { accessorKey: "fund_id", header: t("security") },
            { accessorKey: "as_of", header: t("effective") },
            {
              accessorKey: "retrieved_at",
              header: t("published"),
              cell: ({ getValue }) => date(getValue() as string, locale),
            },
            {
              accessorKey: "status",
              header: t("details"),
              cell: ({ getValue }) => label(String(getValue())),
            },
          ]}
        />
      </section>
    </>
  );
}
export function History({
  data,
  currency,
}: {
  data: Report;
  currency: Currency;
}) {
  const { t, locale, label } = useI18n();
  const field = `total_${currency.toLowerCase()}` as "total_cad";
  return (
    <section className="panel">
      <h2>{t("growth")}</h2>
      <p className="muted">{t("growthHint")}</p>
      <Chart
        line
        currency={currency}
        title={t("growth")}
        labels={data.history.map((row) => row.as_of)}
        values={data.history.map((row) => row[field])}
      />
      {!!data.missing_official_months.length && (
        <p className="status status-review">
          {data.missing_official_months.join(", ")}
        </p>
      )}
      <DataTable
        data={data.history}
        caption={t("history")}
        columns={[
          {
            accessorKey: "as_of",
            header: t("cutoff"),
            cell: ({ getValue }) => date(getValue() as string, locale),
          },
          {
            accessorKey: "kind",
            header: t("kind"),
            cell: ({ getValue }) =>
              t(getValue() as "baseline" | "monthly" | "interim"),
          },
          {
            accessorKey: field,
            header: currency,
            cell: ({ getValue }) =>
              amount(getValue() as string | null, currency, locale),
          },
          {
            accessorKey: "data_status",
            header: t("details"),
            cell: ({ getValue }) => label(getValue() as string),
          },
        ]}
      />
    </section>
  );
}
export function Bitcoin({ data }: { data: Report }) {
  const { t, locale, label } = useI18n();
  const btc = object(data.btc);
  const monthly = rows(btc.monthly);
  const valuation = object(btc.valuation);
  return (
    <>
      <section className="panel">
        <h2>{t("bitcoin")}</h2>
        {data.btc ? (
          <>
            <div className="btc-stats">
              <div>
                <span>{t("btcQuantity")}</span>
                <strong>{quantity(text(btc.quantity_btc))} BTC</strong>
              </div>
              <div>
                <span>
                  {t(data.source_basis ? "sourcePurchases" : "bullPurchases")}
                </span>
                <strong>{quantity(text(btc.purchased_btc))}</strong>
              </div>
              <div>
                <span>{t("marketValue")}</span>
                <strong>
                  {amount(text(valuation.market_cad), "CAD", locale)}
                </strong>
              </div>
            </div>
            <p className="muted">{t("btcHint")}</p>
            <p>
              {t("quantityBasis")}:{" "}
              {text(btc.quantity_status_label) ??
                label(text(btc.quantity_status) ?? "")}
            </p>
            <p>
              {t("costPolicy")}: {label(text(btc.cost_policy) ?? "")}
            </p>
            <p>
              {t(data.source_basis ? "buySpend" : "knownCost")}:{" "}
              {amount(
                text(
                  data.source_basis
                    ? btc.known_purchase_spend_cad
                    : valuation.known_bull_cost_cad,
                ),
                "CAD",
                locale,
              )}{" "}
              · {t("unrealized")}:{" "}
              {amount(text(valuation.unrealized_cad), "CAD", locale)}
            </p>
            <DataTable
              data={monthly}
              caption={t("bitcoin")}
              columns={[
                { accessorKey: "month", header: t("month") },
                {
                  accessorKey: "contribution_cad",
                  header: t("contribution"),
                  cell: ({ getValue }) =>
                    amount(getValue() as string | null, "CAD", locale),
                },
                {
                  accessorKey: "buy_cost_cad",
                  header: t("buySpend"),
                  cell: ({ getValue }) =>
                    amount(getValue() as string | null, "CAD", locale),
                },
                {
                  accessorKey: "average_purchase_price_cad_per_btc",
                  header: t("purchaseRate"),
                  cell: ({ getValue }) =>
                    amount(getValue() as string | null, "CAD", locale),
                },
                {
                  accessorKey: "cumulative_btc_equivalent_qty",
                  header: t("cumulative"),
                  cell: ({ getValue }) => quantity(getValue() as string | null),
                },
              ]}
            />
          </>
        ) : (
          <p>{t("noBtc")}</p>
        )}
      </section>
      <section className="panel">
        <h2>{t("flows")}</h2>
        {data.cash_flows.length ? (
          <DataTable
            data={data.cash_flows}
            caption={t("flows")}
            columns={[
              { accessorKey: "date", header: t("cutoff") },
              {
                accessorKey: "amount_cad",
                header: "CAD",
                cell: ({ getValue }) =>
                  amount(getValue() as string | null, "CAD", locale),
              },
              { accessorKey: "flow_type", header: t("details") },
            ]}
          />
        ) : (
          <p>{t("noFlows")}</p>
        )}
        <p className="muted">{t("maintenance")}</p>
      </section>
    </>
  );
}
