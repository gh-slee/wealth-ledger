import { Link } from "react-router-dom";
import { useI18n } from "../lib/i18n";
import { Button } from "./ui/button";

export function GettingStarted({ portfolio }: { portfolio: string }) {
  const { t } = useI18n();
  return (
    <section className="panel getting-started" aria-labelledby="start-heading">
      <span className="eyebrow">{t("startEyebrow")}</span>
      <h2 id="start-heading">{t("noReport")}</h2>
      <p className="muted">{t("startIntro")}</p>
      <ol className="start-steps">
        <li>
          <h3>{t("startChooseTitle")}</h3>
          <p>{t("startChooseBody")}</p>
        </li>
        <li>
          <h3>{t("startReviewTitle")}</h3>
          <p>{t("startReviewBody")}</p>
        </li>
        <li>
          <h3>{t("startPublishTitle")}</h3>
          <p>{t("startPublishBody")}</p>
        </li>
      </ol>
      <Button asChild>
        <Link to={`/app/${portfolio}/imports`}>{t("startAction")}</Link>
      </Button>
      <details className="start-help">
        <summary>{t("startPrepare")}</summary>
        <dl>
          <dt>{t("startExportsTitle")}</dt>
          <dd>{t("startExportsBody")}</dd>
          <dt>{t("startContextTitle")}</dt>
          <dd>{t("startContextBody")}</dd>
          <dt>{t("startReferencesTitle")}</dt>
          <dd>{t("startReferencesBody")}</dd>
          <dt>{t("startHistoryTitle")}</dt>
          <dd>{t("startHistoryBody")}</dd>
        </dl>
      </details>
      <div className="start-followup">
        <h3>{t("startFlowsTitle")}</h3>
        <p>{t("startFlowsBody")}</p>
        <Link to={`/app/${portfolio}/records`}>{t("startRecordsAction")}</Link>
        <Link to={`/app/${portfolio}/settings`}>
          {t("startSettingsAction")}
        </Link>
      </div>
    </section>
  );
}
