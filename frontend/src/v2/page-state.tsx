import type { ReactNode } from "react";
import { CircleAlert, Inbox, LoaderCircle } from "lucide-react";
import { Button } from "../components/ui/button";
import { useI18n } from "../lib/i18n";

// Shared page states for V2 destinations. Each page ticket replaces the
// placeholder content but keeps these states so loading, empty and error
// pages read the same everywhere.

export function PageLoading() {
  const { t } = useI18n();
  return (
    <div className="v2-state" role="status">
      <LoaderCircle className="v2-spin" size={22} aria-hidden="true" />
      <p>{t("loading")}</p>
    </div>
  );
}

export function PageEmpty({
  message,
  action,
}: {
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="v2-state">
      <Inbox size={22} aria-hidden="true" />
      <p>{message}</p>
      {action}
    </div>
  );
}

export function PageError({
  message,
  onRetry,
}: {
  message?: string;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="v2-state v2-state-error">
      <p role="alert">
        <CircleAlert size={18} aria-hidden="true" />
        {message ?? t("failed")}
      </p>
      <Button variant="secondary" onClick={onRetry}>
        {t("retry")}
      </Button>
    </div>
  );
}
