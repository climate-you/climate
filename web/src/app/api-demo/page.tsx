"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import dynamic from "next/dynamic";

const MapPicker = dynamic(() => import("@/components/MapPicker"), {
  ssr: false,
});

type TimeDuration = {
  value: number;
  unit: "points" | "days" | "months" | "years";
};
type TimeRange = {
  start?: number | string;
  end?: number | string;
  last?: TimeDuration;
  offset?: TimeDuration;
};
type GraphAnimationStep = {
  id: string;
  title?: string;
  time_range?: TimeRange;
  series_keys?: string[];
};
type GraphAnimation = {
  autoplay?: boolean;
  loop?: boolean;
  step_duration_ms?: number;
  transition_ms?: number;
  steps: GraphAnimationStep[];
};
type SeriesPayload = {
  x: Array<number | string>;
  y: (number | null)[];
  unit?: string | null;
  style?: { type?: "line" | "bar" } | null;
};
type GraphAnnotation = { series_key: string; text: string };
type GraphPayload = {
  id: string;
  title: string;
  series_keys: string[];
  annotations?: GraphAnnotation[];
  caption?: string | null;
  error?: string | null;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
  time_range?: TimeRange;
  animation?: GraphAnimation;
};
type DataCell = {
  grid: string;
  deg: number;
  i_lat: number;
  i_lon: number;
  lat_center: number;
  lon_center: number;
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
  tile_r?: number | null;
  tile_c?: number | null;
  o_lat?: number | null;
  o_lon?: number | null;
};

type PanelResponse = {
  release: string;
  unit: string;
  location: {
    query?: { lat: number; lon: number };
    place: {
      geonameid: number;
      label?: string | null;
      lat: number;
      lon: number;
      distance_km: number;
    };
    data_cells?: DataCell[];
    panel_valid_bbox?: {
      lat_min: number;
      lat_max: number;
      lon_min: number;
      lon_max: number;
    } | null;
  };
  panels: Array<{
    score: number;
    panel: {
      id: string;
      title: string;
      graphs: GraphPayload[];
      text_md?: string | null;
    };
  }>;
  series: Record<string, SeriesPayload>;
};

type AutocompleteItem = {
  geonameid: number;
  label: string;
  lat: number;
  lon: number;
  country_code: string;
};

type AutocompleteResponse = {
  query: string;
  results: AutocompleteItem[];
};

type NearestLocationResponse = {
  query: { lat: number; lon: number };
  result: {
    geonameid: number;
    label?: string | null;
    lat: number;
    lon: number;
    distance_km: number;
  };
};

type ChartRow = {
  x: number | string;
  [key: string]: number | string | null | undefined;
};

function mergeSeries(series: Record<string, SeriesPayload>, keys: string[]) {
  // Merge into rows keyed by x (ISO date or year). We assume x values are unique per series.
  const rows = new Map<string, ChartRow>();

  for (const k of keys) {
    const s = series[k];
    if (!s) continue;
    for (let i = 0; i < s.x.length; i++) {
      const x = s.x[i];
      const key = String(x); // ISO date string or year int -> string
      const row = rows.get(key) ?? { x };
      row[k] = s.y[i];
      rows.set(key, row);
    }
  }

  // Sort: if ISO date, string sort works; if years, string sort still works for 4-digit years
  return Array.from(rows.values()).sort((a, b) =>
    String(a.x).localeCompare(String(b.x)),
  );
}

function parseAxisValue(v: unknown): { numeric?: number; timestamp?: number } {
  if (typeof v === "number" && Number.isFinite(v)) {
    if (v >= 1000 && v <= 3000) {
      const ts = new Date(`${Math.trunc(v)}-01-01`).getTime();
      return { numeric: v, timestamp: Number.isFinite(ts) ? ts : undefined };
    }
    return { numeric: v };
  }
  const n = Number(v);
  if (Number.isFinite(n) && String(v).trim() !== "") {
    if (n >= 1000 && n <= 3000) {
      const ts = new Date(`${Math.trunc(n)}-01-01`).getTime();
      return { numeric: n, timestamp: Number.isFinite(ts) ? ts : undefined };
    }
    return { numeric: n };
  }
  const t = new Date(String(v)).getTime();
  if (Number.isFinite(t)) return { timestamp: t };
  return {};
}

function durationToMs(d: TimeDuration): number {
  if (d.unit === "days") return d.value * 24 * 60 * 60 * 1000;
  if (d.unit === "months") return d.value * 30 * 24 * 60 * 60 * 1000;
  if (d.unit === "years") return d.value * 365.25 * 24 * 60 * 60 * 1000;
  return 0;
}

function sliceRowsByTimeRange(rows: ChartRow[], range?: TimeRange): ChartRow[] {
  if (!range || rows.length === 0) return rows;

  if (
    range.last &&
    (range.last.unit === "points" || range.offset?.unit === "points")
  ) {
    const lastN = Math.max(1, range.last.value);
    const offsetN = Math.max(0, range.offset?.value ?? 0);
    const endIdx = rows.length - 1 - offsetN;
    if (endIdx < 0) return [];
    const startIdx = Math.max(0, endIdx - lastN + 1);
    return rows.slice(startIdx, endIdx + 1);
  }

  const parsed = rows.map((r) => ({ row: r, parsed: parseAxisValue(r.x) }));
  const numericCount = parsed.filter(
    (p) => p.parsed.numeric !== undefined,
  ).length;
  const useNumeric = numericCount === parsed.length;

  if (range.last) {
    if (
      useNumeric &&
      (range.last.unit === "years" || range.last.unit === "points")
    ) {
      const vals = parsed.map((p) => p.parsed.numeric as number);
      const max = Math.max(...vals);
      const offset = range.offset?.value ?? 0;
      const end = max - offset;
      const start = end - range.last.value + 1;
      return parsed
        .filter((p) => {
          const v = p.parsed.numeric as number;
          return v >= start && v <= end;
        })
        .map((p) => p.row);
    }

    const stamps = parsed
      .map((p) => p.parsed.timestamp)
      .filter((v): v is number => v !== undefined);
    if (stamps.length === 0) return rows;
    const max = Math.max(...stamps);
    const offsetMs = range.offset ? durationToMs(range.offset) : 0;
    const endTs = max - offsetMs;
    const startTs = endTs - durationToMs(range.last);
    return parsed
      .filter((p) => {
        if (p.parsed.timestamp === undefined) return false;
        return p.parsed.timestamp >= startTs && p.parsed.timestamp <= endTs;
      })
      .map((p) => p.row);
  }

  let startN: number | null = null;
  let endN: number | null = null;
  let startTs: number | null = null;
  let endTs: number | null = null;
  if (range.start !== undefined) {
    const p = parseAxisValue(range.start);
    startN = p.numeric ?? null;
    startTs = p.timestamp ?? null;
  }
  if (range.end !== undefined) {
    const p = parseAxisValue(range.end);
    endN = p.numeric ?? null;
    endTs = p.timestamp ?? null;
  }

  return parsed
    .filter((p) => {
      if (useNumeric) {
        const v = p.parsed.numeric as number;
        if (startN !== null && v < startN) return false;
        if (endN !== null && v > endN) return false;
        return true;
      }
      if (p.parsed.timestamp === undefined) return false;
      if (startTs !== null && p.parsed.timestamp < startTs) return false;
      if (endTs !== null && p.parsed.timestamp > endTs) return false;
      return true;
    })
    .map((p) => p.row);
}

function inBbox(
  lat: number,
  lon: number,
  bbox:
    | {
        lat_min: number;
        lat_max: number;
        lon_min: number;
        lon_max: number;
      }
    | null
    | undefined,
) {
  if (!bbox) return false;
  const latOk = lat >= bbox.lat_min && lat <= bbox.lat_max;
  const lonOk = lon >= bbox.lon_min && lon <= bbox.lon_max;
  return latOk && lonOk;
}

function keyLabel(key: string): string {
  if (key.includes("hotdays")) return "Hot days";
  if (key.includes("trend")) return "Trend";
  if (key.includes("5y")) return "5-year mean";
  if (key.includes("7d")) return "7-day mean";
  if (key.includes("daily")) return "Daily mean";
  if (key.includes("monthly")) return "Monthly mean";
  if (key.includes("yearly")) return "Yearly mean";
  return key.replaceAll("_", " ");
}

function toChartTimestamp(x: number | string): number {
  if (typeof x === "number" && Number.isFinite(x)) {
    return new Date(`${Math.trunc(x)}-01-01`).getTime();
  }
  const s = String(x);
  if (/^\d{4}-\d{2}$/.test(s)) {
    const t = new Date(`${s}-01`).getTime();
    return Number.isFinite(t) ? t : Date.now();
  }
  const t = new Date(s).getTime();
  return Number.isFinite(t) ? t : Date.now();
}

function EChartCanvas({
  option,
  height = 420,
}: {
  option: EChartsOption;
  height?: number;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!rootRef.current) return;
    const chart = echarts.init(rootRef.current);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(rootRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.setOption(option, {
      notMerge: false,
      replaceMerge: ["series"],
      lazyUpdate: true,
    });
  }, [option]);

  return <div ref={rootRef} style={{ width: "100%", height }} />;
}

function formatDateLabel(ts: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(ts));
}

function formatAxisTitle(graph: GraphPayload, value: unknown): string {
  const asString = String(value ?? "");
  if (graph.id !== "t2m_zoomout") {
    const directYear = Number.parseInt(asString, 10);
    const year =
      Number.isFinite(directYear) && directYear >= 1000 && directYear <= 3000
        ? directYear
        : new Date(toChartTimestamp(value as number | string)).getUTCFullYear();
    const yearText = Number.isFinite(year) ? String(year) : "";
    return `Year ${yearText}`;
  }
  return formatDateLabel(toChartTimestamp(value as number | string));
}

function xAxisTitle(graph: GraphPayload): string {
  if (graph.id === "t2m_zoomout") return "Date";
  return "Year";
}

function yAxisTitle(graph: GraphPayload, unit: "C" | "F"): string {
  if (graph.id === "t2m_hot_days" || graph.id === "sst_hot_days") {
    return "Number of days";
  }
  return `Temperature (${unit === "F" ? "°F" : "°C"})`;
}

function buildHotDaysOption({
  graph,
  series,
  data,
  visibleKeys,
  transitionMs,
  unit,
}: {
  graph: GraphPayload;
  series: Record<string, SeriesPayload>;
  data: ChartRow[];
  visibleKeys: string[];
  transitionMs: number;
  unit: "C" | "F";
}): EChartsOption {
  const xValues = data.map((row) => row.x);
  const barKey = graph.series_keys.find((k) => series[k]?.style?.type === "bar");
  const meanKey = graph.series_keys.find((k) => k.includes("5y"));
  const trendKey = graph.series_keys.find((k) => k.includes("trend"));
  const isVisible = (key: string | undefined) => Boolean(key && visibleKeys.includes(key));

  const barValues = barKey ? data.map((row) => (row[barKey] as number | null) ?? null) : [];
  const meanValues = meanKey ? data.map((row) => (row[meanKey] as number | null) ?? null) : [];
  const belowMean = barValues.map((v, i) => {
    if (v === null) return null;
    const m = meanValues[i];
    if (m === null || m === undefined) return v;
    return Math.min(v, m);
  });
  const aboveMean = barValues.map((v, i) => {
    if (v === null) return null;
    const m = meanValues[i];
    if (m === null || m === undefined) return 0;
    return Math.max(0, v - m);
  });

  const chartSeries: NonNullable<EChartsOption["series"]> = [];
  if (barKey && isVisible(barKey)) {
    chartSeries.push({
      name: keyLabel(barKey),
      type: "bar",
      stack: "hot-days",
      data: belowMean,
      itemStyle: { color: "#ccccff" },
      emphasis: { focus: "series" },
      animationDurationUpdate: transitionMs,
    });
    chartSeries.push({
      name: keyLabel(barKey),
      type: "bar",
      stack: "hot-days",
      data: aboveMean,
      itemStyle: { color: "#ff1744" },
      emphasis: { focus: "series" },
      animationDurationUpdate: transitionMs,
    });
  }
  if (meanKey && isVisible(meanKey)) {
    chartSeries.push({
      name: keyLabel(meanKey),
      type: "line",
      data: meanValues,
      smooth: 0.35,
      showSymbol: false,
      lineStyle: { width: 4, color: "#1736ff" },
      animationDurationUpdate: transitionMs,
    });
  }
  if (trendKey && isVisible(trendKey)) {
    chartSeries.push({
      name: keyLabel(trendKey),
      type: "line",
      data: data.map((row) => (row[trendKey] as number | null) ?? null),
      smooth: false,
      showSymbol: false,
      lineStyle: { width: 3, color: "#cccccc" },
      areaStyle: { color: "rgba(255, 0, 0, 0.24)" },
      animationDurationUpdate: transitionMs,
    });
  }

  return {
    animationDuration: 700,
    animationDurationUpdate: transitionMs,
    animationEasing: "cubicOut",
    grid: { left: 74, right: 24, top: 36, bottom: 68, containLabel: true },
    legend: {
      right: 0,
      top: 0,
      itemWidth: 30,
      itemHeight: 10,
      textStyle: { color: "#2d3139", fontSize: 12 },
    },
    tooltip: {
      trigger: "axis",
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = (rows[0] ?? {}) as { axisValue?: unknown };
        const title = formatAxisTitle(graph, first.axisValue);
        const grouped = new Map<string, number>();
        rows
          .map((item) => item as { value?: unknown; marker?: string; seriesName?: string })
          .filter((r) => typeof r.value === "number" && Number.isFinite(r.value))
          .forEach((r) => {
            const label = String(r.seriesName ?? "").trim();
            const value = Number(r.value);
            grouped.set(label, (grouped.get(label) ?? 0) + value);
          });
        const lines = Array.from(grouped.entries()).map(
          ([label, value]) => `${label}: ${Math.round(value)}`,
        );
        return [title, ...lines].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: xValues,
      name: xAxisTitle(graph),
      nameLocation: "middle",
      nameRotate: 0,
      nameGap: 44,
      nameTextStyle: { color: "#666b78", fontSize: 13, align: "center", verticalAlign: "top" },
      axisLabel: { color: "#666b78" },
      axisLine: { lineStyle: { color: "#cfd4dd" } },
      splitLine: { show: true, lineStyle: { color: "rgba(200,200,200,0.3)" } },
    },
    yAxis: {
      type: "value",
      name: yAxisTitle(graph, unit),
      nameLocation: "middle",
      nameRotate: 90,
      nameGap: 56,
      nameTextStyle: { color: "#666b78", fontSize: 13, align: "center", verticalAlign: "middle" },
      axisLabel: { color: "#666b78", formatter: (value: number) => `${Math.round(value)}` },
      minInterval: 1,
      splitLine: { lineStyle: { color: "rgba(200,200,200,0.3)" } },
    },
    series: chartSeries,
  };
}

function buildTemperatureOption({
  graph,
  data,
  visibleKeys,
  transitionMs,
  unit,
  xMin,
  xMax,
}: {
  graph: GraphPayload;
  data: ChartRow[];
  visibleKeys: string[];
  transitionMs: number;
  unit: "C" | "F";
  xMin?: number;
  xMax?: number;
}): EChartsOption {
  const chartSeries: NonNullable<EChartsOption["series"]> = visibleKeys.map((key) => {
    const isTrend = key.includes("trend");
    const isMean = key.includes("5y") || key.includes("7d");
    const isMonthly = key.includes("monthly");
    const points = data
      .filter((row) => row[key] !== null && row[key] !== undefined)
      .map((row) => [toChartTimestamp(row.x), Number(row[key])]);
    return {
      id: key,
      name: keyLabel(key),
      type: "line",
      data: points,
      smooth: isTrend ? false : 0.35,
      showSymbol: false,
      connectNulls: true,
      universalTransition: true,
      lineStyle: {
        width: isTrend ? 3 : isMean ? 4 : 3,
        color: isTrend ? "#cccccc" : isMean ? "#1736ff" : "#ff2e55",
      },
      areaStyle: isTrend ? { color: "rgba(255, 0, 0, 0.24)" } : undefined,
      animationDuration: isMonthly ? 1200 : 700,
      animationDelay: isMonthly ? ((idx: number) => idx * 6) : 0,
      animationDurationUpdate: transitionMs,
      emphasis: { focus: "series" },
    };
  });

  const keysForRange = visibleKeys.some((k) => !k.includes("trend"))
    ? visibleKeys.filter((k) => !k.includes("trend"))
    : visibleKeys;
  const allValues = keysForRange.flatMap((key) =>
    data
      .map((row) => row[key])
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v)),
  );
  let yMin: number | undefined;
  let yMax: number | undefined;
  if (allValues.length > 0) {
    const min = Math.min(...allValues);
    const max = Math.max(...allValues);
    const span = Math.max(max - min, 5);
    const center = (min + max) / 2;
    let lower = Math.floor(center - span / 2);
    let upper = Math.ceil(center + span / 2);
    if (upper - lower < 5) {
      const extra = 5 - (upper - lower);
      lower -= Math.floor(extra / 2);
      upper += Math.ceil(extra / 2);
    }
    yMin = lower;
    yMax = upper;
  }

  return {
    animationDuration: 700,
    animationDurationUpdate: transitionMs,
    animationEasing: "cubicOut",
    grid: { left: 74, right: 24, top: 36, bottom: 68, containLabel: true },
    legend: {
      right: 0,
      top: 0,
      itemWidth: 30,
      itemHeight: 10,
      textStyle: { color: "#2d3139", fontSize: 12 },
    },
    tooltip: {
      trigger: "axis",
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = (rows[0] ?? {}) as { value?: unknown; axisValue?: unknown };
        const firstValue = Array.isArray(first.value) ? first.value[0] : undefined;
        const ts = Number(firstValue ?? first.axisValue ?? 0);
        const title = Number.isFinite(ts)
          ? formatAxisTitle(graph, ts)
          : String(rows[0]?.axisValue ?? "");
        const lines = rows
          .map((item) => item as { value?: unknown; marker?: string; seriesName?: string })
          .filter((r) => Array.isArray(r.value) && Number.isFinite(Number(r.value[1])))
          .map(
            (r) =>
              `${r.marker ?? ""} ${r.seriesName ?? ""}: ${Number((r.value as unknown[])[1]).toFixed(1)}${unit === "F" ? "°F" : "°C"}`,
          );
        return [title, ...lines].join("<br/>");
      },
    },
    xAxis: {
      type: "time",
      name: xAxisTitle(graph),
      nameLocation: "middle",
      nameRotate: 0,
      nameGap: 44,
      nameTextStyle: { color: "#666b78", fontSize: 13, align: "center", verticalAlign: "top" },
      min: xMin,
      max: xMax,
      axisLabel: { color: "#666b78" },
      axisLine: { lineStyle: { color: "#cfd4dd" } },
      splitLine: { show: true, lineStyle: { color: "rgba(200,200,200,0.3)" } },
    },
    yAxis: {
      type: "value",
      name: yAxisTitle(graph, unit),
      nameLocation: "middle",
      nameRotate: 90,
      nameGap: 56,
      nameTextStyle: { color: "#666b78", fontSize: 13, align: "center", verticalAlign: "middle" },
      axisLabel: { color: "#666b78", formatter: (value: number) => `${Math.round(value)}` },
      minInterval: 1,
      scale: true,
      min: yMin,
      max: yMax,
      splitLine: { lineStyle: { color: "rgba(200,200,200,0.3)" } },
    },
    series: chartSeries,
  };
}

function GraphCard({
  graph,
  data,
  series,
  unit,
  showTitle = true,
}: {
  graph: GraphPayload;
  data: ChartRow[];
  series: Record<string, SeriesPayload>;
  unit: "C" | "F";
  showTitle?: boolean;
}) {
  const steps = graph.animation?.steps ?? [];
  const hasAnimation = steps.length >= 2;
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (!hasAnimation || graph.animation?.autoplay === false) return;
    const stepDuration = graph.animation?.step_duration_ms ?? 2600;
    const timer = window.setTimeout(() => {
      setStepIndex((prev) => {
        if (prev + 1 < steps.length) return prev + 1;
        return graph.animation?.loop === false ? prev : 0;
      });
    }, stepDuration);
    return () => window.clearTimeout(timer);
  }, [graph.animation, hasAnimation, stepIndex, steps.length]);

  const activeStep = hasAnimation
    ? steps[Math.min(stepIndex, steps.length - 1)]
    : null;
  const visibleKeys = activeStep?.series_keys?.length
    ? activeStep.series_keys
    : graph.series_keys;
  const activeRange = activeStep?.time_range ?? graph.time_range;
  const rangedData = useMemo(
    () => sliceRowsByTimeRange(data, activeRange),
    [data, activeRange],
  );
  const filteredData = useMemo(
    () =>
      rangedData.filter((row) =>
        visibleKeys.some((key) => row[key] !== null && row[key] !== undefined),
      ),
    [rangedData, visibleKeys],
  );
  const transitionMs = graph.animation?.transition_ms ?? 900;
  const isHotDaysChart = graph.id === "t2m_hot_days" || graph.id === "sst_hot_days";
  const isZoomOutGraph = graph.id === "t2m_zoomout";
  const allVisibleData = useMemo(
    () =>
      data.filter((row) =>
        visibleKeys.some((key) => row[key] !== null && row[key] !== undefined),
      ),
    [data, visibleKeys],
  );
  const [xMin, xMax] = useMemo((): [number | undefined, number | undefined] => {
    const ref = filteredData.length ? filteredData : allVisibleData;
    if (!ref.length) return [undefined, undefined];
    const stamps = ref.map((row) => toChartTimestamp(row.x));
    return [Math.min(...stamps), Math.max(...stamps)];
  }, [allVisibleData, filteredData]);
  const option = useMemo(() => {
    if (isHotDaysChart) {
      return buildHotDaysOption({
        graph,
        series,
        data: filteredData,
        visibleKeys,
        transitionMs,
        unit,
      });
    }
    return buildTemperatureOption({
      graph,
      data: isZoomOutGraph ? allVisibleData : filteredData,
      visibleKeys,
      transitionMs,
      unit,
      xMin,
      xMax,
    });
  }, [
    allVisibleData,
    filteredData,
    graph,
    isHotDaysChart,
    isZoomOutGraph,
    series,
    transitionMs,
    unit,
    visibleKeys,
    xMax,
    xMin,
  ]);

  return (
    <div style={{ marginTop: 12 }}>
      {showTitle ? (
        <h3 style={{ fontSize: 15, fontWeight: 600 }}>{graph.title}</h3>
      ) : null}
      {hasAnimation ? (
        <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {steps.map((step, idx) => {
            const active = idx === stepIndex;
            return (
              <button
                key={`${graph.id}:${step.id}`}
                onClick={() => setStepIndex(idx)}
                style={{
                  fontSize: 12,
                  borderRadius: 999,
                  border: "1px solid rgba(0,0,0,0.2)",
                  padding: "4px 10px",
                  background: active ? "rgba(37, 99, 235, 0.12)" : "white",
                  cursor: "pointer",
                }}
              >
                {step.title ?? step.id}
              </button>
            );
          })}
        </div>
      ) : null}

      <EChartCanvas option={option} height={420} />

      {graph.error ? (
        <div style={{ marginTop: 8, fontSize: 13, opacity: 0.8 }}>{graph.error}</div>
      ) : null}
      {graph.annotations?.length ? (
        <div style={{ marginTop: 8, fontSize: 13, opacity: 0.85 }}>
          {graph.annotations.map((a) => (
            <div key={`${graph.id}:${a.series_key}:${a.text}`}>
              <code>{a.series_key}</code>: {a.text}
            </div>
          ))}
        </div>
      ) : null}
      {graph.caption ? (
        <div
          style={{
            marginTop: 8,
            padding: 10,
            border: "1px solid rgba(0,0,0,0.1)",
            borderRadius: 8,
            fontSize: 13,
            opacity: 0.85,
          }}
        >
          {graph.caption}
        </div>
      ) : null}
    </div>
  );
}

export default function ApiDemoPage() {
  const FIXED_ZOOM = 5;
  const [lat, setLat] = useState<number>(-20.32556);
  const [lon, setLon] = useState<number>(57.37056);
  const [mapZoom, setMapZoom] = useState<number>(FIXED_ZOOM);
  const [unit, setUnit] = useState<"C" | "F">("C");
  const [resp, setResp] = useState<PanelResponse | null>(null);
  const [search, setSearch] = useState<string>("");
  const [suggestions, setSuggestions] = useState<AutocompleteItem[]>([]);
  const [suggestOpen, setSuggestOpen] = useState<boolean>(false);
  const [suggestIndex, setSuggestIndex] = useState<number>(-1);
  const [suggestLoading, setSuggestLoading] = useState<boolean>(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const debounceRef = useRef<number | null>(null);
  const cell = resp?.location?.data_cells?.[0] ?? null;

  const panelData = useMemo(() => {
    if (!resp) return [];
    return resp.panels.map((item) => ({
      score: item.score,
      panel: item.panel,
      graphs: item.panel.graphs.map((graph) => ({
        graph,
        data: mergeSeries(
          resp.series,
          Array.from(
            new Set([
              ...graph.series_keys,
              ...(graph.animation?.steps ?? []).flatMap(
                (s) => s.series_keys ?? [],
              ),
            ]),
          ),
        ),
      })),
    }));
  }, [resp]);

  async function load(nextLat = lat, nextLon = lon, nextUnit = unit) {
    const url = `http://localhost:8001/api/v/dev/panel?lat=${encodeURIComponent(nextLat)}&lon=${encodeURIComponent(
      nextLon,
    )}&unit=${nextUnit}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as PanelResponse;
    setResp(data);
    return data;
  }

  async function fetchAutocomplete(q: string) {
    const url = `http://localhost:8001/api/v/dev/locations/autocomplete?q=${encodeURIComponent(
      q,
    )}&limit=8`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as AutocompleteResponse;
    return data.results ?? [];
  }

  async function resolveByLabel(label: string) {
    const url = `http://localhost:8001/api/v/dev/locations/resolve?label=${encodeURIComponent(
      label,
    )}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as { result?: AutocompleteItem | null };
    return data.result ?? null;
  }

  async function fetchNearestLocation(nextLat: number, nextLon: number) {
    const url = `http://localhost:8001/api/v/dev/location/nearest?lat=${encodeURIComponent(nextLat)}&lon=${encodeURIComponent(
      nextLon,
    )}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as NearestLocationResponse;
    return data.result;
  }

  function applyLocation(item: AutocompleteItem) {
    setSearch("");
    setLat(item.lat);
    setLon(item.lon);
    setMapZoom(FIXED_ZOOM);
    load(item.lat, item.lon);
  }

  useEffect(() => {
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }
    if (search.trim().length < 3) {
      setSuggestions([]);
      setSuggestOpen(false);
      setSuggestIndex(-1);
      setSuggestLoading(false);
      setSuggestError(null);
      return;
    }

    setSuggestLoading(true);
    setSuggestError(null);
    debounceRef.current = window.setTimeout(async () => {
      try {
        const results = await fetchAutocomplete(search.trim());
        setSuggestions(results);
        setSuggestOpen(true);
        setSuggestIndex(results.length ? 0 : -1);
      } catch (err: unknown) {
        setSuggestError(err instanceof Error ? err.message : "Autocomplete failed");
        setSuggestions([]);
        setSuggestOpen(false);
        setSuggestIndex(-1);
      } finally {
        setSuggestLoading(false);
      }
    }, 250);
  }, [search]);

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ fontSize: 20, fontWeight: 700 }}>API Demo</h1>
      <div
        style={{
          marginTop: 12,
          position: "relative",
          maxWidth: 520,
          zIndex: 50,
        }}
      >
        <input
          placeholder="Search a city (min 3 chars)…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onFocus={() => {
            if (suggestions.length) setSuggestOpen(true);
          }}
          onKeyDown={async (e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setSuggestIndex((i) =>
                Math.min(i + 1, suggestions.length - 1),
              );
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setSuggestIndex((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              if (suggestIndex >= 0 && suggestions[suggestIndex]) {
                applyLocation(suggestions[suggestIndex]);
                setSuggestOpen(false);
                return;
              }
              if (search.trim().length >= 3) {
                const hit = await resolveByLabel(search.trim());
                if (hit) {
                  applyLocation(hit);
                }
                setSuggestOpen(false);
              }
            } else if (e.key === "Escape") {
              setSuggestOpen(false);
            }
          }}
          style={{
            width: "100%",
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid rgba(0,0,0,0.2)",
          }}
        />
        {suggestOpen && suggestions.length > 0 ? (
          <div
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              right: 0,
              background: "white",
              border: "1px solid rgba(0,0,0,0.15)",
              borderRadius: 8,
              marginTop: 4,
              zIndex: 1000,
              maxHeight: 220,
              overflowY: "auto",
              boxShadow: "0 8px 20px rgba(0,0,0,0.08)",
            }}
          >
            {suggestions.map((s, i) => (
              <div
                key={`${s.geonameid}:${s.label}`}
                onMouseDown={(evt) => {
                  evt.preventDefault();
                  applyLocation(s);
                  setSuggestOpen(false);
                }}
                onMouseEnter={() => setSuggestIndex(i)}
                style={{
                  padding: "8px 10px",
                  cursor: "pointer",
                  background:
                    i === suggestIndex ? "rgba(37, 99, 235, 0.1)" : "white",
                }}
              >
                {s.label}
              </div>
            ))}
          </div>
        ) : null}
        {suggestLoading ? (
          <div style={{ fontSize: 12, opacity: 0.6, marginTop: 4 }}>
            Searching…
          </div>
        ) : null}
        {suggestError ? (
          <div style={{ fontSize: 12, color: "#b91c1c", marginTop: 4 }}>
            {suggestError}
          </div>
        ) : null}
      </div>
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          marginTop: 12,
          flexWrap: "wrap",
        }}
      >
        {/* Map + overlay */}
        <div style={{ width: 520, maxWidth: "100%" }}>
          <MapPicker
            onPick={async (la, lo) => {
              setLat(la);
              setLon(lo);
              const bbox = resp?.location?.panel_valid_bbox;
              if (inBbox(la, lo, bbox)) {
                const place = await fetchNearestLocation(la, lo);
                setResp((prev) => {
                  if (!prev) return prev;
                  return {
                    ...prev,
                    location: {
                      ...prev.location,
                      query: { lat: la, lon: lo },
                      place: {
                        ...prev.location.place,
                        geonameid: place.geonameid,
                        label: place.label ?? null,
                        lat: place.lat,
                        lon: place.lon,
                        distance_km: place.distance_km,
                      },
                    },
                  };
                });
                return;
              }
              await load(la, lo);
            }}
            onZoomChange={(z) => setMapZoom(z)}
            picked={{ lat, lon }}
            center={[lat, lon]}
            zoom={mapZoom}
            cell={
              cell
                ? {
                    lat_min: cell.lat_min,
                    lat_max: cell.lat_max,
                    lon_min: cell.lon_min,
                    lon_max: cell.lon_max,
                  }
                : null
            }
            cellCenter={
              cell ? { lat: cell.lat_center, lon: cell.lon_center } : null
            }
          />
        </div>

        <div style={{ marginTop: 8, opacity: 0.75 }}>
          Picked: {lat.toFixed(4)}, {lon.toFixed(4)}
          {cell ? (
            <div
              style={{
                marginTop: 4,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: 12,
                opacity: 0.75,
              }}
            >
              cell {cell.grid} deg={cell.deg} i_lat={cell.i_lat} i_lon=
              {cell.i_lon} tile=r{cell.tile_r ?? "?"} c{cell.tile_c ?? "?"} off=
              {cell.o_lat ?? "?"},{cell.o_lon ?? "?"} center=(
              {cell.lat_center.toFixed(4)},{cell.lon_center.toFixed(4)}){" "}
              bounds=[{cell.lat_min.toFixed(4)}..{cell.lat_max.toFixed(4)},{" "}
              {cell.lon_min.toFixed(4)}..{cell.lon_max.toFixed(4)}]
            </div>
          ) : null}
        </div>

        <label>
          Unit{" "}
          <select
            value={unit}
            onChange={(e) => {
              const nextUnit = (e.target.value as "C" | "F") ?? "C";
              if (nextUnit === unit) return;
              setUnit(nextUnit);
              void load(lat, lon, nextUnit);
            }}
          >
            <option value="C">°C</option>
            <option value="F">°F</option>
          </select>
        </label>
      </div>

      {resp && (
        <div style={{ marginTop: 16, opacity: 0.8 }}>
          Place: {resp.location.place.label ?? "—"} • Panels: {resp.panels.length}
        </div>
      )}
      {panelData.map(({ score, panel, graphs }) => (
        <div key={panel.id} style={{ marginTop: 18 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700 }}>
            {panel.title} (score {score})
          </h2>
          {graphs.map(({ graph, data }) => (
            <GraphCard
              key={`${panel.id}:${graph.id}:${data.length}`}
              graph={graph}
              data={data}
              series={resp?.series ?? {}}
              unit={unit}
            />
          ))}
          {panel?.text_md ? (
            <div
              style={{
                marginTop: 12,
                padding: 12,
                border: "1px solid rgba(0,0,0,0.1)",
                borderRadius: 8,
              }}
            >
              {panel.text_md}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
