"use client";

import React, { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { buildTemperatureOption } from "@/lib/explorer/chartOptions";
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
};

export type ChatChartPayload = {
  title: string;
  unit: string; // "C" or "F" or other
  series: ChatChartSeries[];
};

type ChatChartProps = {
  chart: ChatChartPayload;
  temperatureUnit: "C" | "F";
};

const CHART_HEIGHT = 200;

// Bauhaus colours: primaries first, then secondaries
const MULTI_SERIES_COLORS = [
  "#0000FF", // blue
  "#FF0000", // red
  "#FFCC00", // yellow
  "#000000", // black
  "#FF6600", // orange
  "#007700", // green
];

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
  let rawIndex = 0;
  chart.series.forEach((s) => {
    const isTrend = s.role === "trend";
    const key = seriesKey(s);
    record[key] = {
      x: s.x,
      y: s.y,
      label: s.label,
      ui: { role: isTrend ? "trend" : "raw" },
      // Assign distinct colours for multi-series (raw only)
      ...(multiSeries && !isTrend
        ? { style: { color: MULTI_SERIES_COLORS[rawIndex % MULTI_SERIES_COLORS.length] } }
        : {}),
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
  return {
    id: "chat-chart",
    title: chart.title,
    series_keys,
    ui: { chart_mode: "temperature_line" },
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatChart({ chart, temperatureUnit }: ChatChartProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [colorScheme, setColorScheme] = useState<"light" | "dark">("light");

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
      height: CHART_HEIGHT,
    });
    chartRef.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(rootRef.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chartRef.current = null;
    };
  }, []);

  // Build and apply chart option whenever chart data or unit changes
  useEffect(() => {
    if (!chartRef.current) return;
    const seriesRecord = buildSeriesRecord(chart);
    const graph = buildGraphPayload(chart);
    const visibleKeys = graph.series_keys;
    const data = mergeSeries(seriesRecord, visibleKeys);
    const rawCount = chart.series.filter((s) => s.role !== "trend").length;
    const multiSeries = rawCount > 1;

    const option = buildTemperatureOption({
      graph,
      series: seriesRecord,
      data,
      visibleKeys,
      transitionMs: 0,
      unit: temperatureUnit,
    });

    const dark = colorScheme === "dark";

    // Tighter grid for the narrow chat drawer; extra top space when legend is
    // present (multi-series) to prevent it overlapping the plot area.
    // show: true + backgroundColor colors only the plot area, not the legend/axis area.
    const plotBg = dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)";
    (option as Record<string, unknown>).grid = {
      left: 8,
      right: 12,
      top: rawCount > 3 ? 72 : multiSeries ? 44 : 28,
      bottom: 12,
      containLabel: true,
      show: true,
      backgroundColor: plotBg,
      borderColor: "transparent",
    };
    // Render tooltip into document.body so it escapes the drawer's overflow:hidden
    if (option.tooltip && !Array.isArray(option.tooltip)) {
      (option.tooltip as Record<string, unknown>).appendToBody = true;
    }
    // Trend series don't count as a legend-worthy entry; hide legend for single-location charts
    if (!multiSeries) {
      (option as Record<string, unknown>).legend = { show: false };
    }

    // Min/max markPoints — when there is a single raw series (trend doesn't count)
    if (rawCount === 1 && Array.isArray(option.series)) {
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
          option.yAxis = { ...yAxis, min: dataMin - padding, max: dataMax + padding };
        }
      }

      option.series = option.series.map((s) => {
        // Skip trend series — markPoints only belong on the raw data line
        const echartsS = s as { id?: string };
        if (typeof echartsS.id === "string" && echartsS.id.endsWith(":trend")) return s;
        return { ...s, markPoint: {
          symbol: "circle",
          symbolSize: 7,
          data: [
            {
              type: "min",
              itemStyle: { color: "#0000FF" },
              label: {
                show: true,
                position: "bottom" as const,
                formatter: (p: { value: number }) =>
                  `${p.value.toFixed(1)}°${temperatureUnit}`,
                fontSize: 10,
                color: "#0000FF",
              },
            },
            {
              type: "max",
              itemStyle: { color: "#FF0000" },
              label: {
                show: true,
                position: "top" as const,
                formatter: (p: { value: number }) =>
                  `${p.value.toFixed(1)}°${temperatureUnit}`,
                fontSize: 10,
                color: "#FF0000",
              },
            },
          ],
        } };
      });
    }

    // Force symbols visible when series have ≤1 real data point — a line needs
    // ≥2 points to render, so the dot is the only visual indicator.
    if (Array.isArray(option.series)) {
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
    <div className={styles.chartCard}>
      <div
        ref={rootRef}
        data-chat-chart="true"
        style={{ width: "100%", height: CHART_HEIGHT }}
      />
      <div className={styles.chartTitle}>{chart.title}</div>
    </div>
  );
}
