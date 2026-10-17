import { useEffect, useRef } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  AriaComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { amount, date, chartNumber } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { Currency } from "../lib/api";
use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  AriaComponent,
  SVGRenderer,
]);
export function Chart({
  title,
  labels,
  values,
  line = false,
  currency = "CAD",
}: {
  title: string;
  labels: string[];
  values: (string | null | undefined)[];
  line?: boolean;
  currency?: Currency;
}) {
  const { locale } = useI18n();
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!root.current) return;
    const chart = init(root.current, undefined, { renderer: "svg" });
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const option: EChartsOption = {
      useUTC: true,
      animation: !reduce,
      animationDuration: 250,
      aria: { enabled: true, label: { description: title } },
      textStyle: {
        fontFamily: "Atkinson Hyperlegible, sans-serif",
        color: "#193B51",
      },
      grid: { left: 14, right: 20, top: 15, bottom: 12, containLabel: true },
      tooltip: {
        trigger: "axis",
        renderMode: "richText",
        confine: true,
        formatter: (params: unknown) => {
          const item = (Array.isArray(params) ? params[0] : params) as {
            dataIndex?: number;
          };
          const index = item?.dataIndex;
          if (index == null || index < 0 || index >= labels.length) return "";
          return `${line ? date(labels[index], locale) : labels[index]}\n${amount(values[index], currency, locale)}`;
        },
      },
      xAxis: line
        ? {
            type: "time",
            axisLabel: {
              hideOverlap: true,
              formatter: (value: number | string) =>
                new Intl.DateTimeFormat(locale, {
                  month: "short",
                  day: "numeric",
                  timeZone: "America/Toronto",
                }).format(new Date(Number(value))),
            },
            axisLine: { lineStyle: { color: "#CBD8DF" } },
          }
        : { type: "value", splitLine: { lineStyle: { color: "#E6EDF1" } } },
      yAxis: line
        ? {
            type: "value",
            scale: true,
            splitLine: { lineStyle: { color: "#E6EDF1" } },
          }
        : {
            type: "category",
            data: labels,
            inverse: true,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { width: 155, overflow: "truncate" },
          },
      series: [
        line
          ? {
              type: "line",
              data: values.map((value, index) => [
                labels[index],
                chartNumber(value),
              ]),
              connectNulls: false,
              showSymbol: true,
              symbolSize: 7,
              smooth: false,
              lineStyle: { width: 2, color: "#157F7A" },
              itemStyle: { color: "#157F7A" },
              areaStyle: { color: "#157F7A", opacity: 0.06 },
            }
          : {
              type: "bar",
              data: values.map(chartNumber),
              barMaxWidth: 22,
              itemStyle: { color: "#367B9B", borderRadius: [0, 4, 4, 0] },
            },
      ],
    };
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(root.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [title, labels, values, line, locale, currency]);
  return <div className="chart" role="img" aria-label={title} ref={root} />;
}
