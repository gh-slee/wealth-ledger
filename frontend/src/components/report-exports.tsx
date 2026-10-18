import { useState, type FormEvent } from "react";
import { ApiError, downloadFile, scope } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Button } from "./ui/button";

const datasets = [
  "holdings",
  "accounts",
  "history",
  "cash_flows",
  "btc_monthly",
] as const;
export function ReportExports({
  portfolio,
  report,
}: {
  portfolio: string;
  report: string;
}) {
  const { t, error } = useI18n();
  const [dataset, setDataset] = useState<(typeof datasets)[number]>("holdings");
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  const base = scope(portfolio) + `/reports/${report}`;
  async function save(path: string, filename: string) {
    setBusy(true);
    setFailure("");
    try {
      await downloadFile(path, filename);
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError")
        return;
      setFailure(reason instanceof ApiError ? reason.code : "request_failed");
    } finally {
      setBusy(false);
    }
  }
  function exportRows(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const format = String(values.get("format"));
    const query = new URLSearchParams({ dataset, format });
    for (const key of ["start", "end"]) {
      const value = values.get(key);
      if (value) query.set(key, String(value));
    }
    void save(base + "/export?" + query, `${dataset}-${report}.${format}`);
  }
  const dated = ["history", "cash_flows", "btc_monthly"].includes(dataset);
  return (
    <div className="report-exports">
      <Button
        disabled={busy}
        onClick={() => void save(base + "/bundle.zip", `report-${report}.zip`)}
      >
        {t("bundleDownload")}
      </Button>
      {failure && (
        <p role="alert" className="error">
          {error(failure)}
        </p>
      )}
      <details>
        <summary>{t("exportData")}</summary>
        <p>{t("exportScope")}</p>
        <form className="export-form" onSubmit={exportRows}>
          <label>
            {t("exportDataset")}
            <select
              value={dataset}
              onChange={(event) =>
                setDataset(event.target.value as typeof dataset)
              }
            >
              {datasets.map((name) => (
                <option key={name} value={name}>
                  {t(`export.${name}`)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("exportFormat")}
            <select name="format">
              <option value="csv">CSV</option>
              <option value="json">JSON</option>
            </select>
          </label>
          {dated && (
            <>
              <label>
                {t("exportStart")}
                <input type="date" name="start" />
              </label>
              <label>
                {t("exportEnd")}
                <input type="date" name="end" />
              </label>
            </>
          )}
          <Button disabled={busy} type="submit">
            {t("exportDownload")}
          </Button>
        </form>
      </details>
    </div>
  );
}
