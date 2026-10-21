import type { Report } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { groupedIssues } from "../lib/report-library";

export function ReportNotices({ data }: { data: Report }) {
  const { t } = useI18n();
  if (!data.issues.length) return null;
  const groups = groupedIssues(data);
  const counts = (severity: string) =>
    data.issues.filter((issue) => issue.severity === severity).length;
  return (
    <details className="report-notices panel">
      <summary>
        {t("reportChecks")} · {t("issueError")} {counts("error")} ·{" "}
        {t("issueWarning")} {counts("warning")} · {t("issueInfo")}{" "}
        {counts("info")}
      </summary>
      <ul>
        {groups.map((group, index) => (
          <li key={index}>
            <span
              className={`status ${group.severity === "info" ? "" : "status-review"}`}
            >
              {group.severity === "error"
                ? t("issueError")
                : group.severity === "warning"
                  ? t("issueWarning")
                  : t("issueInfo")}
            </span>{" "}
            {group.message}
            <small>
              {group.code}
              {group.count > 1 ? ` · ×${group.count}` : ""}
            </small>
            {group.contexts.length > 0 && (
              <p className="muted">{group.contexts.join("; ")}</p>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
