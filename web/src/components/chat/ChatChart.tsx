"use client";

import React, { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import {
  buildComparisonBarOption,
  buildStackedBarOption,
  buildTimeSeriesOption,
  getMultiSeriesColors,
} from "@/lib/explorer/chartOptions";
import {
  mergeSeries,
  type GraphPayload,
  type SeriesPayload,
} from "@/lib/explorer/chartData";
import styles from "./ChatDrawer.module.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ChatChartSeries = {
  label: string;
  x: (number | string)[];
  y: (number | null)[];
  role?: string;
  style?: { type?: "line" | "bar"; color?: string; stack?: string };
};

export type ChatChartPayload = {
  title: string;
  unit: string; // "C" or "F" or other
  chart_mode?: string; // "temperature_line" | "stacked_bar" | "hot_days_combo"
  series: ChatChartSeries[];
};

type ChatChartProps = {
  chart: ChatChartPayload;
  temperatureUnit: "C" | "F";
};

const CHART_MAX_HEIGHT = 260;
const CHART_MIN_ASPECT_RATIO = 1.5;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function seriesKey(s: ChatChartSeries): string {
  return s.role === "trend" ? `${s.label}:trend` : s.label;
}

function buildSeriesRecord(
  chart: ChatChartPayload,
): Record<string, SeriesPayload> {
  const record: Record<string, SeriesPayload> = {};
  const rawCount = chart.series.filter((s) => s.role !== "trend").length;
  const multiSeries = rawCount > 1;
  const isStackedBar = chart.chart_mode === "stacked_bar";
  let rawIndex = 0;
  chart.series.forEach((s) => {
    const isTrend = s.role === "trend";
    const key = seriesKey(s);
    // For stacked bar, use the per-series style from the payload.
    // For multi-series line charts, use an explicit per-series colour if provided
    // (e.g. aggregation-based colours from the backend), otherwise cycle Bauhaus palette.
    const styleOverride =
      isStackedBar && s.style
        ? s.style
        : multiSeries && !isTrend && !isStackedBar
          ? {
              color:
                getMultiSeriesColors()[
                  rawIndex % getMultiSeriesColors().length
                ],
            }
          : s.style?.color
            ? { color: s.style.color }
            : undefined;
    record[key] = {
      x: s.x,
      y: s.y,
      label: s.label,
      ui: { role: isTrend ? "trend" : "raw" },
      ...(styleOverride ? { style: styleOverride } : {}),
    };
    if (!isTrend) rawIndex++;
  });
  return record;
}

function buildGraphPayload(chart: ChatChartPayload): GraphPayload {
  // Deduplicate keys — ECharts throws on duplicate series ids
  const seen = new Set<string>();
  const series_keys = chart.series
    .map(seriesKey)
    .filter((k) => (seen.has(k) ? false : (seen.add(k), true)));
  const chartMode = (
    chart.chart_mode === "stacked_bar" ||
    chart.chart_mode === "hot_days_combo" ||
    chart.chart_mode === "temperature_line" ||
    chart.chart_mode === "comparison_bar"
      ? chart.chart_mode
      : "temperature_line"
  ) as "temperature_line" | "hot_days_combo" | "stacked_bar" | "comparison_bar";
  return {
    id: "chat-chart",
    title: chart.title,
    series_keys,
    ui: { chart_mode: chartMode },
    // Stacked bar charts show days on the y-axis, not temperature.
    // For other non-temperature units (e.g. "score"), pass the unit as the y-axis label
    // so buildTimeSeriesOption doesn't default to "°C".
    ...(chart.chart_mode === "stacked_bar"
      ? { y_axis_label: "Number of days" }
      : chart.unit === "mm"
        ? { y_axis_label: "Precipitation (mm)" }
        : chart.unit === "days"
          ? { y_axis_label: "Days/year" }
          : chart.unit && !["C", "F"].includes(chart.unit)
            ? { y_axis_label: chart.unit }
            : {}),
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatChart({ chart, temperatureUnit }: ChatChartProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [colorScheme, setColorScheme] = useState<"light" | "dark">("light");
  const [chartHeight, setChartHeight] = useState(CHART_MAX_HEIGHT);

  useEffect(() => {
    const host = chartHostRef.current;
    if (!host) return;
    const update = () => {
      const width = host.clientWidth;
      if (!Number.isFinite(width) || width <= 0) return;
      const next = Math.max(
        1,
        Math.min(CHART_MAX_HEIGHT, Math.floor(width / CHART_MIN_ASPECT_RATIO)),
      );
      setChartHeight((prev) => (prev === next ? prev : next));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setColorScheme(mq.matches ? "dark" : "light");
    const handler = (e: MediaQueryListEvent) =>
      setColorScheme(e.matches ? "dark" : "light");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Init ECharts with explicit dimensions to avoid 0-size canvas on mount
  useEffect(() => {
    if (!rootRef.current) return;
    const instance = echarts.init(rootRef.current, undefined, {
      width: rootRef.current.clientWidth || undefined,
      height: chartHeight,
    });
    chartRef.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(rootRef.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Build and apply chart option whenever chart data or unit changes
  useEffect(() => {
    if (!chartRef.current) return;

    // Comparison bar: scalar region-vs-region (e.g. Germany vs France trend)
    if (chart.chart_mode === "comparison_bar" && chart.series.length > 0) {
      const s = chart.series[0];
      const xLabels = s.x as string[];
      const manyBars = xLabels.length >= 5;
      const option = buildComparisonBarOption({
        xLabels,
        yValues: s.y,
        unit: temperatureUnit === "F" && chart.unit === "C" ? "F" : chart.unit,
      });
      (option as Record<string, unknown>).grid = {
        left: 60,
        right: 12,
        top: 28,
        // Extra bottom room when x labels are rotated to avoid clipping.
        bottom: manyBars ? 48 : 12,
        containLabel: true,
      };
      chartRef.current.setOption(option, { notMerge: true, lazyUpdate: false });
      return;
    }

    const seriesRecord = buildSeriesRecord(chart);
    const graph = buildGraphPayload(chart);
    const visibleKeys = graph.series_keys;
    const data = mergeSeries(seriesRecord, visibleKeys);
    const rawCount = chart.series.filter((s) => s.role !== "trend").length;
    const multiSeries = rawCount > 1;
    const isStackedBar = chart.chart_mode === "stacked_bar";
    // For non-temperature units (e.g. "score", "days"), pass the raw unit string
    // so the chart library doesn't format values as °C/°F.
    const isTemp = ["C", "F"].includes(chart.unit);
    const effectiveUnit = isTemp ? temperatureUnit : chart.unit;

    const option = isStackedBar
      ? buildStackedBarOption({
          graph,
          series: seriesRecord,
          data,
          visibleKeys,
          transitionMs: 0,
          unit: temperatureUnit,
          showYAxisName: true,
        })
      : buildTimeSeriesOption({
          graph,
          series: seriesRecord,
          data,
          visibleKeys,
          transitionMs: 0,
          unit: effectiveUnit,
          showYAxisName: true,
        });

    // Tighter grid for the narrow chat drawer; extra top space when legend is
    // present (multi-series) to prevent it overlapping the plot area.
    (option as Record<string, unknown>).grid = {
      left: 36,
      right: 12,
      top: isStackedBar || rawCount > 3 ? 72 : multiSeries ? 44 : 28,
      bottom: 12,
      containLabel: true,
    };
    // Render tooltip into document.body so it escapes the drawer's overflow:hidden
    if (option.tooltip && !Array.isArray(option.tooltip)) {
      (option.tooltip as Record<string, unknown>).appendToBody = true;
    }
    // Trend series don't count as a legend-worthy entry; hide legend for single-location charts.
    // Always show legend for stacked bar charts (colour = category meaning).
    if (!multiSeries && !isStackedBar) {
      (option as Record<string, unknown>).legend = { show: false };
    }

    // Min/max markPoints — when there is a single raw series (trend doesn't count).
    // Not applicable to stacked bar charts.
    if (rawCount === 1 && !isStackedBar && Array.isArray(option.series)) {
      // Expand y-axis bounds so markPoint labels don't overlap axes or legend.
      // Compute from raw series only; pad by at least 1° or 10% of range.
      const allYValues = chart.series
        .filter((s) => s.role !== "trend")
        .flatMap((s) => s.y)
        .filter((v): v is number => v !== null && Number.isFinite(v));
      if (allYValues.length > 0) {
        const dataMin = Math.min(...allYValues);
        const dataMax = Math.max(...allYValues);
        const range = dataMax - dataMin;
        const padding = Math.max(1, range * 0.1);
        const yAxis = option.yAxis as Record<string, unknown> | undefined;
        if (yAxis) {
          option.yAxis = {
            ...yAxis,
            min: dataMin - padding,
            max: dataMax + padding,
          };
        }
      }

      option.series = (option.series as unknown[]).map((s) => {
        // Skip trend series — markPoints only belong on the raw data line
        const echartsS = s as { id?: string };
        if (typeof echartsS.id === "string" && echartsS.id.endsWith(":trend"))
          return s;
        return {
          ...(s as object),
          markPoint: {
            symbol: "circle",
            symbolSize: 7,
            data: [
              {
                name: "min",
                type: "min" as const,
                itemStyle: { color: "#0000FF" },
                label: {
                  show: true,
                  position: "bottom" as const,
                  formatter: (p: { value: number }) =>
                    isTemp
                      ? `${p.value.toFixed(1)}°${temperatureUnit}`
                      : `${p.value.toFixed(1)} ${chart.unit}`,
                  fontSize: 10,
                  color: "#0000FF",
                },
              },
              {
                name: "max",
                type: "max" as const,
                itemStyle: { color: "#FF0000" },
                label: {
                  show: true,
                  position: "top" as const,
                  formatter: (p: { value: number }) =>
                    isTemp
                      ? `${p.value.toFixed(1)}°${temperatureUnit}`
                      : `${p.value.toFixed(1)} ${chart.unit}`,
                  fontSize: 10,
                  color: "#FF0000",
                },
              },
            ],
          },
        };
      }) as typeof option.series;
    }

    // Force symbols visible when series have ≤1 real data point — a line needs
    // ≥2 points to render, so the dot is the only visual indicator.
    // Not applicable to stacked bar charts.
    if (!isStackedBar && Array.isArray(option.series)) {
      const maxRawPoints = Math.max(
        0,
        ...chart.series
          .filter((s) => s.role !== "trend")
          .map((s) => s.y.filter((v) => v !== null).length),
      );
      if (maxRawPoints <= 1) {
        option.series = option.series.map((s) => {
          const echartsS = s as { id?: string };
          if (typeof echartsS.id === "string" && echartsS.id.endsWith(":trend"))
            return s;
          return { ...s, showSymbol: true, symbolSize: 8 };
        });
      }
    }

    chartRef.current.setOption(option, {
      notMerge: true,
      lazyUpdate: false,
    });
  }, [chart, colorScheme, temperatureUnit]);

  return (
    <div className={styles.chartCard} ref={chartHostRef}>
      <div className={styles.chartTitle}>{chart.title}</div>
      <div
        ref={rootRef}
        data-chat-chart="true"
        style={{ width: "100%", height: chartHeight }}
      />
    </div>
  );
}
