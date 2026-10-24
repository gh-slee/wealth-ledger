import { useEffect, useId, useRef } from "react";
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
import { useTheme } from "../lib/theme";
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
  scrollable = false,
}: {
  title: string;
  labels: string[];
  values: (string | null | undefined)[];
  line?: boolean;
  currency?: Currency;
  scrollable?: boolean;
}) {
  const { locale, t } = useI18n();
  const hintId = useId();
  const complete = scrollable && !line;
  const { resolved } = useTheme();
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!root.current) return;
    const target = root.current;
    const viewport = complete ? target.parentElement : target;
    const layout = () => {
      const labelWidth = Math.max(
        70,
        Math.min(220, Math.floor(target.clientWidth / 2) - 20),
      );
      // Reserve enough room for wrapped 12px labels, including wide CJK glyphs.
      const lines = labels.reduce(
        (maximum, label) =>
          Math.max(
            maximum,
            Math.ceil((Array.from(label).length * 12) / labelWidth),
          ),
        1,
      );
      return {
        labelWidth,
        height: Math.max(
          viewport?.clientHeight ?? 320,
          labels.length * Math.max(40, lines * 16 + 12) + 50,
        ),
      };
    };
    const initial = layout();
    if (complete) target.style.height = `${initial.height}px`;
    const chart = init(target, undefined, { renderer: "svg" });
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const colors = getComputedStyle(document.documentElement);
    const color = (token: string) => colors.getPropertyValue(token).trim();
    const option: EChartsOption = {
      useUTC: true,
      darkMode: resolved === "dark",
      animation: !reduce,
      animationDuration: 250,
      aria: { enabled: true, label: { description: title } },
      textStyle: {
        fontFamily: "Atkinson Hyperlegible, sans-serif",
        color: color("--navy"),
      },
      color: [color("--chart-bar")],
      grid: { left: 14, right: 20, top: 15, bottom: 12, containLabel: true },
      tooltip: {
        trigger: "axis",
        renderMode: "richText",
        confine: true,
        backgroundColor: color("--paper"),
        borderColor: color("--border"),
        textStyle: { color: color("--navy") },
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
              color: color("--muted"),
              hideOverlap: true,
              formatter: (value: number | string) =>
                new Intl.DateTimeFormat(locale, {
                  month: "short",
                  day: "numeric",
                  timeZone: "America/Toronto",
                }).format(new Date(Number(value))),
            },
            axisLine: { lineStyle: { color: color("--border") } },
          }
        : {
            type: "value",
            axisLabel: {
              color: color("--muted"),
              ...(complete ? { hideOverlap: true } : {}),
            },
            splitLine: { lineStyle: { color: color("--border") } },
          },
      yAxis: line
        ? {
            type: "value",
            axisLabel: { color: color("--muted") },
            scale: true,
            splitLine: { lineStyle: { color: color("--border") } },
          }
        : {
            type: "category",
            data: labels,
            inverse: true,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: {
              color: color("--muted"),
              width: complete ? initial.labelWidth : 155,
              overflow: complete ? "break" : "truncate",
              ...(complete
                ? { interval: 0, hideOverlap: false, lineHeight: 16 }
                : {}),
            },
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
              lineStyle: { width: 2, color: color("--teal") },
              itemStyle: { color: color("--teal") },
              areaStyle: { color: color("--teal"), opacity: 0.06 },
            }
          : {
              type: "bar",
              data: values.map(chartNumber),
              barMaxWidth: 22,
              itemStyle: {
                color: color("--chart-bar"),
                borderRadius: [0, 4, 4, 0],
              },
            },
      ],
    };
    chart.setOption(option);
    const observer = new ResizeObserver(() => {
      if (complete) {
        const next = layout();
        target.style.height = `${next.height}px`;
        chart.resize();
        chart.setOption({ yAxis: { axisLabel: { width: next.labelWidth } } });
      } else chart.resize();
    });
    observer.observe(viewport ?? target);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [title, labels, values, line, locale, currency, resolved, complete]);
  if (complete) {
    if (!labels.length) return <p role="status">{t("emptyRows")}</p>;
    return (
      <>
        <p className="muted chart-hint" id={hintId}>
          {t("chartScrollHint")}
        </p>
        <div
          className="chart chart-scroll"
          role="region"
          aria-label={title}
          aria-describedby={hintId}
          tabIndex={0}
        >
          <div
            className="chart-content"
            role="img"
            aria-label={title}
            ref={root}
          />
        </div>
      </>
    );
  }
  return <div className="chart" role="img" aria-label={title} ref={root} />;
}
