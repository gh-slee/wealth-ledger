import { lazy, Suspense } from "react";
import { useI18n } from "../lib/i18n";
const ChartView = lazy(() =>
  import("./chart-view").then((module) => ({ default: module.Chart })),
);
export function Chart(props: React.ComponentProps<typeof ChartView>) {
  const { t } = useI18n();
  return (
    <Suspense
      fallback={
        <div className="chart" aria-busy="true">
          {t("loading")}
        </div>
      }
    >
      <ChartView {...props} />
    </Suspense>
  );
}
