import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { read, scope, type Models, type Report } from "../lib/api";
import { date } from "../lib/format";
import { useI18n } from "../lib/i18n";
import {
  evidenceItems,
  jobDestination,
  jobMessage,
  unresolvedJobs,
} from "../lib/evidence-status";
import { Button } from "./ui/button";
import { ReportNotices } from "./report-notices";

export function CurrentProcessing({ portfolio }: { portfolio: string }) {
  const { t, locale } = useI18n();
  const jobs = useQuery({
    queryKey: [portfolio, "jobs"],
    queryFn: ({ signal }) =>
      read<Models["JobList"]>(scope(portfolio) + "/jobs", signal),
    refetchInterval: (q) =>
      q.state.data?.jobs.some((j) =>
        ["queued", "running", "data_committed"].includes(j.status),
      )
        ? 1500
        : 15000,
  });
  const pending = unresolvedJobs(jobs.data?.jobs ?? []);
  if (!jobs.isPending && !jobs.isError && !pending.length) return null;
  return (
    <section
      className="panel processing-status"
      aria-label={t("processingTitle")}
    >
      <h2>{t("processingTitle")}</h2>
      <p className="muted">{t("processingHint")}</p>
      <p className="sr-only" role="status">
        {jobs.isPending
          ? t("loading")
          : jobs.isError
            ? t("processingUnavailable")
            : `${t("processingCount")}: ${pending.length}. ${pending.map((job) => t(jobMessage(job.status))).join("; ")}`}
      </p>
      {jobs.isPending ? (
        <p aria-busy="true">{t("loading")}</p>
      ) : jobs.isError ? (
        <div>
          <p>{t("processingUnavailable")}</p>
          <Button variant="secondary" onClick={() => void jobs.refetch()}>
            {t("retry")}
          </Button>
        </div>
      ) : (
        <ul className="status-actions">
          {pending.map((job) => {
            const destination = jobDestination(job);
            return (
              <li key={job.id}>
                <div>
                  <strong>{t(jobMessage(job.status))}</strong>
                  <p className="muted">
                    <code>{job.status}</code> ·{" "}
                    <time>
                      {date(
                        new Date(job.updated_at * 1000).toISOString(),
                        locale,
                      )}
                    </time>
                  </p>
                  <small>
                    <code>{job.id}</code>
                    {job.error_code && (
                      <>
                        {" "}
                        · <code>{job.error_code}</code>
                      </>
                    )}
                  </small>
                </div>
                {destination ? (
                  <Link
                    className="button button-secondary"
                    to={`/app/${portfolio}/${destination}?job=${encodeURIComponent(job.id)}`}
                  >
                    {t("processingViewJob")}
                  </Link>
                ) : (
                  <span>{t("processingHostReview")}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function EvidenceStatus({
  data,
  portfolio,
  latest,
}: {
  data: Report;
  portfolio: string;
  latest?: Models["ReportSummary"];
}) {
  const { t, locale } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const items = evidenceItems(data);
  const actions = items.filter((i) => i.severity !== "info");
  const review = items.filter(
    (i) => i.severity === "review" || i.severity === "error",
  ).length;
  const unknown = items.filter((i) => i.severity === "unknown").length;
  return (
    <section
      className="panel evidence-status"
      aria-label={t("evidenceStatusTitle")}
    >
      <div className="panel-heading">
        <h2>{t("evidenceStatusTitle")}</h2>
        <span className="status">
          {t("evidenceReviewCount")}: {review} · {t("evidenceUnknownCount")}:{" "}
          {unknown}
        </span>
      </div>
      <p className="muted">{t("evidenceStatusHint")}</p>
      <dl className="status-dates">
        <div>
          <dt>{t("cutoff")}</dt>
          <dd>{date(data.as_of, locale)}</dd>
        </div>
        <div>
          <dt>{t("evidencePublishedAt")}</dt>
          <dd>
            {date(
              new Date(data.report.published_at * 1000).toISOString(),
              locale,
            )}
          </dd>
        </div>
        <div>
          <dt>{t("evidenceEditionState")}</dt>
          <dd>
            {latest
              ? t(
                  latest.id === data.report.id
                    ? "evidenceLatest"
                    : "evidenceHistorical",
                )
              : t("evidenceLatestUnknown")}
          </dd>
        </div>
      </dl>
      <h3>
        {t("evidenceNextActions")} ({actions.length})
      </h3>
      <ul className="status-actions" id="evidence-actions">
        {(expanded ? actions : actions.slice(0, 3)).map((item) => (
          <li key={item.id}>
            <div>
              <span
                className={`status ${item.severity === "error" || item.severity === "review" ? "status-review" : ""}`}
              >
                {t(
                  item.severity === "error"
                    ? "issueError"
                    : item.severity === "unknown"
                      ? "evidenceUnknownCount"
                      : "evidenceReviewCount",
                )}
              </span>
              <strong>{t(item.title)}</strong>
              <p>{t(item.body)}</p>
              <small>
                {t("evidenceAsOf")}:{" "}
                {item.at ? date(item.at, locale) : t("unknown")}
                {item.context.length > 0 && <> · {item.context.join(" · ")}</>}
                {item.count > 1 && <> · ×{item.count}</>}
              </small>
            </div>
            {item.destination === "records" ? (
              <Link
                className="button button-secondary"
                to={`/app/${portfolio}/records`}
              >
                {t("records")}
              </Link>
            ) : (
              <a
                className="button button-secondary"
                href={
                  item.destination === "sources"
                    ? "#source-evidence"
                    : "#saved-status-evidence"
                }
                onClick={
                  item.destination === "details"
                    ? () => {
                        const target = document.getElementById(
                          "saved-status-evidence",
                        ) as HTMLDetailsElement | null;
                        if (target) target.open = true;
                      }
                    : undefined
                }
              >
                {t(
                  item.destination === "sources"
                    ? "evidenceViewSources"
                    : "evidenceViewDetails",
                )}
              </a>
            )}
          </li>
        ))}
      </ul>
      {actions.length > 3 && (
        <Button
          variant="ghost"
          aria-expanded={expanded}
          aria-controls="evidence-actions"
          onClick={() => setExpanded(!expanded)}
        >
          {t(expanded ? "evidenceShowLess" : "evidenceShowAll")} (
          {actions.length})
        </Button>
      )}
      <details id="saved-status-evidence">
        <summary>{t("evidenceDetails")}</summary>
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <strong>{t(item.title)}:</strong> {t(item.body)}
            </li>
          ))}
        </ul>
        {data.btc && <p className="muted">{t("evidenceGapUnavailable")}</p>}
        {data.missing_official_months.length > 0 && (
          <p>
            {t("evidenceMissingMonths")}:{" "}
            {data.missing_official_months.join(", ")}
          </p>
        )}
        {data.findings.length > 0 && (
          <div>
            <h3>{t("findings")}</h3>
            <ul>
              {data.findings.map((finding, index) => (
                <li key={index}>{finding}</li>
              ))}
            </ul>
          </div>
        )}
        <ReportNotices data={data} embedded />
      </details>
    </section>
  );
}
