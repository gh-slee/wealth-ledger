import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { FileDown } from "lucide-react";
import {
  ApiError,
  download,
  read,
  readChart,
  scope,
  type Models,
  type Report,
} from "../lib/api";
import { date } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { compareReportCells, groupEditions } from "../lib/report-library";
import { Evidence } from "./analysis";
import { Chart } from "./chart";
import { ReportExports } from "./report-exports";
import { ReportNotices } from "./report-notices";
import { Button } from "./ui/button";

type Block = Required<Models["DocumentBlock"]>;
function ReportTable({ block, caption }: { block: Block; caption: string }) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{
    column: number;
    descending: boolean;
  } | null>(null);
  const rows = useMemo(() => {
    const visible = block.rows.filter((row) =>
      row.some((cell) =>
        cell.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
      ),
    );
    return sort
      ? visible
          .slice()
          .sort(
            (a, b) =>
              compareReportCells(a[sort.column], b[sort.column]) *
              (sort.descending ? -1 : 1),
          )
      : visible;
  }, [block.rows, search, sort]);
  return (
    <div className="report-table">
      {block.rows.length > 10 && (
        <label className="report-table-filter">
          {t("filterReportTable")}
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      )}
      <div
        className="table-scroll"
        role="region"
        aria-label={caption}
        tabIndex={0}
      >
        <table>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {block.headers.map((header, column) => (
                <th
                  key={column}
                  scope="col"
                  aria-sort={
                    sort?.column === column
                      ? sort.descending
                        ? "descending"
                        : "ascending"
                      : "none"
                  }
                >
                  <button
                    onClick={() =>
                      setSort({
                        column,
                        descending: sort?.column === column && !sort.descending,
                      })
                    }
                  >
                    {header}
                    {sort?.column === column
                      ? sort.descending
                        ? " ↓"
                        : " ↑"
                      : " ↕"}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {row.map((cell, column) => (
                  <td key={column}>{cell}</td>
                ))}
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={Math.max(1, block.headers.length)}>
                  {t("emptyRows")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SavedChart({ portfolio, block }: { portfolio: string; block: Block }) {
  const { t, error } = useI18n();
  const [image, setImage] = useState("");
  const [failure, setFailure] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let url = "";
    if (block.artifact_id) {
      void readChart(
        `${scope(portfolio)}/artifacts/${block.artifact_id}`,
        controller.signal,
      )
        .then((blob) => {
          if (!controller.signal.aborted) {
            url = URL.createObjectURL(blob);
            setImage(url);
          }
        })
        .catch((reason) => {
          if (!controller.signal.aborted)
            setFailure(
              reason instanceof ApiError ? reason.code : "request_failed",
            );
        });
    }
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [portfolio, block.artifact_id]);
  return (
    <figure className="saved-report-chart">
      {failure ? (
        <p role="alert">{error(failure)}</p>
      ) : !block.artifact_id ? (
        <p>{t("savedChartUnavailable")}</p>
      ) : image ? (
        <img src={image} alt={block.text} loading="lazy" />
      ) : (
        <p aria-live="polite">{t("loading")}</p>
      )}
      <figcaption>{block.filename}</figcaption>
    </figure>
  );
}

function ReportChart({
  portfolio,
  block,
  data,
}: {
  portfolio: string;
  block: Block;
  data: Report;
}) {
  const { t } = useI18n();
  const [interactive, setInteractive] = useState(false);
  // Interactive alternatives use exact saved DTO values and explicitly label CAD.
  const series =
    block.filename === "01_account_values.png"
      ? {
          labels: data.accounts.map((row) => row.label),
          values: data.accounts.map((row) => row.total_cad),
          title: t("accountBreakdown"),
        }
      : block.filename === "12_company_exposure.png"
        ? {
            labels: data.companies.map((row) => row.name),
            values: data.companies.map((row) => row.total_cad),
            title: t("topCompanies"),
          }
        : null;
  return (
    <div className="report-chart">
      {series && series.values.some((value) => value != null) && (
        <Button
          variant="ghost"
          aria-pressed={interactive}
          onClick={() => setInteractive(!interactive)}
        >
          {t(interactive ? "showSavedChart" : "showInteractiveChart")}
        </Button>
      )}
      {interactive && series ? (
        <Chart {...series} />
      ) : (
        <SavedChart
          key={`${portfolio}-${block.artifact_id}`}
          portfolio={portfolio}
          block={block as Block}
        />
      )}
    </div>
  );
}

export function ReportReader({
  portfolio,
  data,
  editions,
  hasMore,
  loadingMore,
  loadMore,
}: {
  portfolio: string;
  data: Report;
  editions: Models["ReportSummary"][];
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
}) {
  const { t, locale, error } = useI18n();
  const [failure, setFailure] = useState("");
  const report = data.report;
  const document = useQuery({
    queryKey: [portfolio, "report-document", report.id],
    queryFn: ({ signal }) =>
      read<Models["ReportDocument"]>(
        `${scope(portfolio)}/reports/${report.id}/document`,
        signal,
      ),
    staleTime: Infinity,
  });
  const groups = groupEditions(editions);
  const primary = report.artifacts.filter((artifact) =>
    ["report.pdf", "portfolio.ods", "report.md"].includes(artifact.filename),
  );
  async function save(artifact: Models["Artifact"]) {
    setFailure("");
    try {
      await download(portfolio, artifact);
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError"))
        setFailure(reason instanceof ApiError ? reason.code : "request_failed");
    }
  }
  const editionName = (value: Models["ReportSummary"]) =>
    value.edition_label ?? value.id.slice(0, 8);
  const editionLink = (value: Models["ReportSummary"]) =>
    `/app/${portfolio}/reports?report=${value.id}`;
  return (
    <>
      <section className="report-cover panel">
        <span className="eyebrow">{t("reportReading")}</span>
        <h2>
          {date(data.as_of, locale)}{" "}
          <span className="report-version">{editionName(report)}</span>
        </h2>
        <p className="muted">
          {t("published")}:{" "}
          {date(new Date(report.published_at * 1000).toISOString(), locale)}
        </p>
        <p className="muted">
          {t("originalReportLanguage")}:{" "}
          {document.data?.locale ?? report.report_locale ?? t("unknown")}.{" "}
          {t("reportLanguageHint")}
        </p>
        <div className="actions">
          {primary.map((artifact) => (
            <Button
              key={artifact.id}
              variant="secondary"
              onClick={() => void save(artifact)}
            >
              <FileDown size={16} aria-hidden="true" />
              {artifact.filename}
            </Button>
          ))}
        </div>
        <ReportExports
          key={report.id}
          portfolio={portfolio}
          report={report.id}
        />
        <details className="report-attachments">
          <summary>{t("reportAttachments")}</summary>
          <div className="actions">
            {report.artifacts
              .filter((artifact) => !primary.includes(artifact))
              .map((artifact) => (
                <Button
                  key={artifact.id}
                  variant="ghost"
                  onClick={() => void save(artifact)}
                >
                  {artifact.filename}
                </Button>
              ))}
          </div>
        </details>
        {failure && (
          <p className="error" role="alert">
            {error(failure)}
          </p>
        )}
      </section>
      <Evidence data={data} />
      <ReportNotices data={data} />
      <details className="report-history panel">
        <summary>
          {t("reportHistory")} · {groups.length} {t("reportGroups")}
        </summary>
        <p className="muted">{t("reportHistoryHint")}</p>
        {groups.map((group) => (
          <div className="report-history-group" key={group.key}>
            <Link
              to={editionLink(group.latest)}
              aria-current={report.id === group.latest.id ? "page" : undefined}
            >
              {date(group.latest.valuation_as_of, locale)} ·{" "}
              {editionName(group.latest)}
            </Link>
            <p className="muted">
              {(group.latest.scope_labels ?? []).join(" · ") || t("unknown")}
            </p>
            {!!group.older.length && (
              <details>
                <summary>
                  {t("otherEditions")} ({group.older.length})
                </summary>
                {group.older.map((value) => (
                  <Link
                    key={value.id}
                    to={editionLink(value)}
                    aria-current={report.id === value.id ? "page" : undefined}
                  >
                    {editionName(value)} ·{" "}
                    {date(
                      new Date(value.published_at * 1000).toISOString(),
                      locale,
                    )}
                  </Link>
                ))}
              </details>
            )}
          </div>
        ))}
        {hasMore && (
          <Button variant="secondary" disabled={loadingMore} onClick={loadMore}>
            {t("loadMore")}
          </Button>
        )}
      </details>
      {document.isPending ? (
        <p aria-live="polite">{t("loading")}</p>
      ) : document.isError ? (
        <section className="panel" role="alert">
          <h2>{t("documentUnavailable")}</h2>
          <p>{t("documentUnavailableHint")}</p>
          <p>{error((document.error as ApiError).code)}</p>
          <Button onClick={() => void document.refetch()}>{t("retry")}</Button>
        </section>
      ) : (
        <div className="report-layout">
          <aside className="report-toc">
            <details open>
              <summary>{t("reportContents")}</summary>
              <nav aria-label={t("reportContents")}>
                {document.data.sections.map((section) => (
                  <a key={section.id} href={`#${section.id}`}>
                    {section.title}
                  </a>
                ))}
              </nav>
            </details>
          </aside>
          <article
            className="report-document"
            lang={document.data.locale ?? undefined}
            aria-label={t("reportReading")}
          >
            <p className="muted document-basis">{t("savedDocumentHint")}</p>
            {document.data.sections.map((section) => (
              <section
                className="panel report-section"
                id={section.id}
                key={section.id}
              >
                <h2>{section.title}</h2>
                {section.blocks.map((block, index) =>
                  block.kind === "table" ? (
                    <ReportTable
                      key={index}
                      block={block as Block}
                      caption={`${section.title} · ${index + 1}`}
                    />
                  ) : block.kind === "chart" ? (
                    <ReportChart
                      key={index}
                      portfolio={portfolio}
                      block={block as Block}
                      data={data}
                    />
                  ) : block.kind === "subheading" ? (
                    <h3 key={index}>{block.text}</h3>
                  ) : (
                    <p key={index}>{block.text}</p>
                  ),
                )}
              </section>
            ))}
          </article>
        </div>
      )}
    </>
  );
}
