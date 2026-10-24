import { Component, lazy, Suspense, type ReactNode } from "react";
import { useI18n } from "../lib/i18n";
const ChartView = lazy(() =>
  import("./chart-view").then((module) => ({ default: module.Chart })),
);
class CountryChartBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
export function Chart(props: React.ComponentProps<typeof ChartView>) {
  const { t } = useI18n();
  const content = (
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
  if (!props.scrollable) return content;
  return (
    <CountryChartBoundary
      key={JSON.stringify([props.title, props.labels, props.values])}
      fallback={<p role="status">{t("chartUnavailable")}</p>}
    >
      {content}
    </CountryChartBoundary>
  );
}
