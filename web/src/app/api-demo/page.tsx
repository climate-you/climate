"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import MapLibreGlobe from "@/components/MapLibreGlobe";
import type { MapLayerOption } from "@/components/MapLibreGlobe";
import styles from "./page.module.css";

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
type GraphPayload = {
  id: string;
  title: string;
  series_keys: string[];
  caption?: string | null;
  error?: string | null;
  time_range?: TimeRange;
  animation?: GraphAnimation;
};

type PanelResponse = {
  location: {
    query?: { lat: number; lon: number };
    place: {
      geonameid: number;
      label?: string | null;
      lat: number;
      lon: number;
      distance_km: number;
      country_code?: string | null;
      population?: number | null;
    };
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
  population: number;
};

type AutocompleteResponse = {
  results: AutocompleteItem[];
};

type NearestLocationResponse = {
  result: {
    geonameid: number;
    label?: string | null;
    lat: number;
    lon: number;
    distance_km: number;
    country_code?: string | null;
    population?: number | null;
  };
};

type ChartRow = {
  x: number | string;
  [key: string]: number | string | null | undefined;
};

type SelectedLocationMeta = {
  geonameid: number;
  label: string;
  countryCode: string;
  population: number | null;
};
type PagedGraphItem = {
  panelId: string;
  graph: GraphPayload;
  data: ChartRow[];
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
  if (key.includes("trend")) return "Trend";
  if (key.includes("5y")) return "5-year mean";
  if (key.includes("7d")) return "7-day mean";
  if (key.includes("daily")) return "Daily mean";
  if (key.includes("monthly")) return "Monthly mean";
  if (key.includes("yearly")) return "Yearly mean";
  if (key.includes("hotdays")) return "Hot days";
  return key.replaceAll("_", " ");
}

function toChartTimestamp(x: number | string): number {
  if (typeof x === "number" && Number.isFinite(x)) {
    const n = Math.trunc(x);
    if (n >= 1000 && n <= 3000) {
      const t = new Date(`${n}-01-01`).getTime();
      return Number.isFinite(t) ? t : Date.now();
    }
    // Already an epoch timestamp in milliseconds (or close enough for chart use).
    if (Math.abs(n) >= 1e11) return n;
    // Epoch seconds fallback.
    if (Math.abs(n) >= 1e9) return n * 1000;
    const t = new Date(String(x)).getTime();
    return Number.isFinite(t) ? t : Date.now();
  }
  const s = String(x);
  if (/^\d{4}$/.test(s)) {
    const t = new Date(`${s}-01-01`).getTime();
    return Number.isFinite(t) ? t : Date.now();
  }
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
  if (!Number.isFinite(ts) || Math.abs(ts) > 8.64e15) {
    return "";
  }
  const date = new Date(ts);
  if (!Number.isFinite(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatAxisTitle(graph: GraphPayload, value: unknown): string {
  const asString = String(value ?? "");
  if (graph.id !== "t2m_zoomout") {
    const directYear = Number.parseInt(asString, 10);
    const year =
      Number.isFinite(directYear) && directYear >= 1000 && directYear <= 3000
        ? directYear
        : new Date(toChartTimestamp(value as number | string)).getUTCFullYear();
    const yearText = Number.isFinite(year) ? String(year) : asString;
    return `Year ${yearText}`;
  }
  const label = formatDateLabel(toChartTimestamp(value as number | string));
  return label || asString;
}

function countryCodeToFlag(countryCode: string | null | undefined): string {
  const cc = String(countryCode ?? "")
    .trim()
    .toUpperCase();
  if (!/^[A-Z]{2}$/.test(cc)) return "";
  const base = 127397;
  return String.fromCodePoint(cc.charCodeAt(0) + base, cc.charCodeAt(1) + base);
}

function formatPopulation(value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return new Intl.NumberFormat("en-US").format(Math.trunc(value));
}

function yAxisTitle(graph: GraphPayload, unit: "C" | "F"): string {
  if (graph.id === "t2m_hot_days" || graph.id === "sst_hot_days") {
    return "Number of days";
  }
  return `Temperature (${unit === "F" ? "°F" : "°C"})`;
}

function trendLegendLabel(
  graph: GraphPayload,
  data: ChartRow[],
  trendKey: string,
  unit: "C" | "F",
): string {
  if (graph.id === "t2m_hot_days" || graph.id === "sst_hot_days") {
    return "Trend";
  }
  const samples = data
    .map((row) => ({ t: toChartTimestamp(row.x), y: row[trendKey] }))
    .filter(
      (p): p is { t: number; y: number } =>
        Number.isFinite(p.t) && typeof p.y === "number" && Number.isFinite(p.y),
    )
    .sort((a, b) => a.t - b.t);
  if (samples.length < 2) return "Trend";

  const first = samples[0];
  const last = samples[samples.length - 1];
  const years = (last.t - first.t) / (1000 * 60 * 60 * 24 * 365.2425);
  if (!Number.isFinite(years) || years <= 0) return "Trend";

  const perDecade = ((last.y - first.y) / years) * 10;
  const sign = perDecade >= 0 ? "+" : "";
  const suffix = `${unit === "F" ? "ºF" : "ºC"}/decade`;
  return `Trend: ${sign}${perDecade.toFixed(1)}${suffix}`;
}

function rollingMeanCentered(
  values: Array<number | null>,
  windowSize: number,
  minPeriods: number,
): Array<number | null> {
  if (windowSize <= 1) return [...values];
  const half = Math.floor(windowSize / 2);
  const out: Array<number | null> = new Array(values.length).fill(null);
  for (let i = 0; i < values.length; i++) {
    let sum = 0;
    let count = 0;
    for (
      let j = Math.max(0, i - half);
      j <= Math.min(values.length - 1, i + half);
      j++
    ) {
      const v = values[j];
      if (typeof v === "number" && Number.isFinite(v)) {
        sum += v;
        count += 1;
      }
    }
    out[i] = count >= minPeriods ? sum / count : null;
  }
  return out;
}

function parseRollingToken(
  key: string,
): { token: string; windowSize: number; unit: string } | null {
  const matches = [...key.matchAll(/(?:^|_)(\d+)([a-z])(?=_|$)/gi)];
  if (!matches.length) return null;
  const last = matches[matches.length - 1];
  const windowSize = Number.parseInt(last[1], 10);
  const unit = String(last[2] ?? "").toLowerCase();
  if (!Number.isFinite(windowSize) || windowSize <= 1 || !unit) return null;
  return { token: `${windowSize}${unit}`, windowSize, unit };
}

function rollingMinPeriods(windowSize: number, unit: string): number {
  if (unit === "d") return windowSize;
  if (unit === "y") return 2;
  return Math.max(2, Math.ceil(windowSize / 2));
}

function resolveBaseKeyFromRollingKey(
  data: ChartRow[],
  meanKey: string,
): string | null {
  const parsed = parseRollingToken(meanKey);
  if (!parsed) return null;
  const { token, unit } = parsed;
  const unitWord: Record<string, string> = {
    d: "daily",
    w: "weekly",
    m: "monthly",
    y: "yearly",
  };
  const mapped = unitWord[unit];
  const candidates = [
    meanKey.replace(new RegExp(`_${token}$`, "i"), ""),
    meanKey.replace(new RegExp(`_${token}_`, "i"), "_"),
    mapped
      ? meanKey.replace(new RegExp(`_${token}$`, "i"), `_${mapped}`)
      : meanKey,
    mapped
      ? meanKey.replace(new RegExp(`_${token}_`, "i"), `_${mapped}_`)
      : meanKey,
  ];
  for (const candidate of candidates) {
    if (
      candidate !== meanKey &&
      data.some(
        (row) =>
          typeof row[candidate] === "number" &&
          Number.isFinite(row[candidate] as number),
      )
    ) {
      return candidate;
    }
  }
  return null;
}

function deriveMeanFromBase(
  data: ChartRow[],
  meanKey: string,
  rawMeanValues: Array<number | null>,
): Array<number | null> {
  const parsed = parseRollingToken(meanKey);
  if (!parsed) return rawMeanValues;
  const baseKey = resolveBaseKeyFromRollingKey(data, meanKey);
  if (!baseKey) return rawMeanValues;
  const { windowSize, unit } = parsed;
  const minPeriods = rollingMinPeriods(windowSize, unit);

  const baseValues = data.map((row) => (row[baseKey] as number | null) ?? null);
  if (!baseValues.some((v) => typeof v === "number" && Number.isFinite(v))) {
    return rawMeanValues;
  }
  const rolled = rollingMeanCentered(baseValues, windowSize, minPeriods);
  return rawMeanValues.map((v, i) => v ?? rolled[i]);
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
  const barKey = graph.series_keys.find(
    (k) => series[k]?.style?.type === "bar",
  );
  const meanKey = graph.series_keys.find((k) => k.includes("5y"));
  const trendKey = graph.series_keys.find((k) => k.includes("trend"));
  const isVisible = (key: string | undefined) =>
    Boolean(key && visibleKeys.includes(key));

  const barValues = barKey
    ? data.map((row) => (row[barKey] as number | null) ?? null)
    : [];
  const meanValues = meanKey
    ? data.map((row) => (row[meanKey] as number | null) ?? null)
    : [];
  const meanDisplayValues = meanKey
    ? deriveMeanFromBase(data, meanKey, meanValues)
    : meanValues;
  const belowMean = barValues.map((v, i) => {
    if (v === null) return null;
    const m = meanDisplayValues[i];
    if (m === null || m === undefined) return v;
    return Math.min(v, m);
  });
  const aboveMean = barValues.map((v, i) => {
    if (v === null) return null;
    const m = meanDisplayValues[i];
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
      emphasis: { focus: "none" },
      z: 2,
      animationDurationUpdate: transitionMs,
    });
    chartSeries.push({
      name: keyLabel(barKey),
      type: "bar",
      stack: "hot-days",
      data: aboveMean,
      itemStyle: { color: "#ff1744" },
      emphasis: { focus: "none" },
      z: 2,
      animationDurationUpdate: transitionMs,
    });
  }
  if (meanKey && isVisible(meanKey)) {
    chartSeries.push({
      name: keyLabel(meanKey),
      type: "line",
      color: "#1736ff",
      data: meanDisplayValues,
      smooth: 0.35,
      showSymbol: false,
      itemStyle: { color: "#1736ff" },
      lineStyle: { width: 3, color: "#1736ff" },
      z: 3,
      animationDurationUpdate: transitionMs,
      emphasis: { focus: "series" },
    });
  }
  if (trendKey && isVisible(trendKey)) {
    chartSeries.push({
      name: trendLegendLabel(graph, data, trendKey, unit),
      type: "line",
      color: "rgba(255, 0, 0, 0.24)",
      data: data.map((row) => (row[trendKey] as number | null) ?? null),
      smooth: false,
      showSymbol: false,
      itemStyle: { color: "rgba(255, 0, 0, 0.24)" },
      lineStyle: { width: 0, color: "rgba(255, 0, 0, 0)" },
      areaStyle: { color: "rgba(255, 0, 0, 0.24)" },
      z: 4,
      animationDurationUpdate: transitionMs,
      emphasis: { focus: "series" },
    });
  }

  return {
    animationDuration: 700,
    animationDurationUpdate: transitionMs,
    animationEasing: "cubicOut",
    grid: { left: 74, right: 24, top: 36, bottom: 20, containLabel: true },
    legend: {
      right: 24,
      top: 0,
      itemWidth: 30,
      itemHeight: 10,
      textStyle: { color: "#2d3139", fontSize: 12 },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = (rows[0] ?? {}) as {
          axisValue?: unknown;
          dataIndex?: unknown;
        };
        const title = formatAxisTitle(graph, first.axisValue);
        const lines: string[] = [];
        const idx = Number(first.dataIndex);
        if (Number.isInteger(idx) && idx >= 0 && idx < barValues.length) {
          const v = barValues[idx];
          if (typeof v === "number" && Number.isFinite(v)) {
            lines.push(`Hot days: ${Math.round(v)}`);
          }
        }
        const extra = new Map<string, number>();
        rows
          .map((item) => item as { value?: unknown; seriesName?: string })
          .forEach((r) => {
            const label = String(r.seriesName ?? "").trim();
            if (!label || label.startsWith("Trend") || label === "Hot days")
              return;
            if (typeof r.value === "number" && Number.isFinite(r.value)) {
              extra.set(label, Number(r.value));
            }
          });
        lines.push(
          ...Array.from(extra.entries()).map(
            ([label, value]) => `${label}: ${Math.round(value)}`,
          ),
        );
        return [title, ...lines].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: xValues,
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
      nameTextStyle: {
        color: "#666b78",
        fontSize: 13,
        align: "center",
        verticalAlign: "middle",
      },
      axisLabel: {
        color: "#666b78",
        formatter: (value: number) => `${Math.round(value)}`,
      },
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
  const chartSeries: NonNullable<EChartsOption["series"]> = visibleKeys.map(
    (key) => {
      const isTrend = key.includes("trend");
      const isMean = key.includes("5y") || key.includes("7d");
      const isMonthly = key.includes("monthly");
      const isDaily = key.includes("daily");
      const baseColor = isTrend
        ? "rgba(255, 0, 0, 0.24)"
        : isMean
          ? "#1736ff"
          : isDaily
            ? "rgba(180,180,180,0.7)"
            : "#ff2e55";
      const rawValues = data.map((row) => (row[key] as number | null) ?? null);
      const displayValues = isMean
        ? deriveMeanFromBase(data, key, rawValues)
        : rawValues;
      const points = displayValues
        .map((value, idx) => ({ x: data[idx]?.x, value }))
        .filter(
          (p): p is { x: string | number; value: number } =>
            typeof p.value === "number",
        )
        .map((p) => [toChartTimestamp(p.x), p.value]);
      return {
        id: key,
        name: isTrend
          ? trendLegendLabel(graph, data, key, unit)
          : keyLabel(key),
        type: "line",
        color: baseColor,
        data: points,
        smooth: isTrend ? false : 0.35,
        showSymbol: false,
        connectNulls: true,
        universalTransition: true,
        itemStyle: {
          color: baseColor,
        },
        lineStyle: {
          width: isTrend ? 0 : isMean ? 3 : 1.5,
          color: isTrend ? "rgba(255, 0, 0, 0)" : baseColor,
        },
        z: isTrend ? 1 : isMean ? 3 : 2,
        areaStyle: isTrend ? { color: "rgba(255, 0, 0, 0.24)" } : undefined,
        animationDuration: isMonthly ? 1200 : 700,
        animationDelay: isMonthly ? (idx: number) => idx * 6 : 0,
        animationDurationUpdate: transitionMs,
        emphasis: { focus: "series" },
      };
    },
  );

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
    // const minSpan = unit === "F" ? 3.6 : 2.0;
    // const span = Math.max(max - min, minSpan);
    // const pad = span * 0.1;
    // const center = (min + max) / 2;
    // const rawMin = center - span / 2 - pad;
    // const rawMax = center + span / 2 + pad;
    yMin = min - 0.2; //Math.floor(min);
    yMax = max + 0.2; //Math.ceil(max);
  }

  return {
    animationDuration: 700,
    animationDurationUpdate: transitionMs,
    animationEasing: "cubicOut",
    grid: { left: 74, right: 24, top: 36, bottom: 20, containLabel: true },
    legend: {
      right: 24,
      top: 0,
      itemWidth: 30,
      itemHeight: 10,
      textStyle: { color: "#2d3139", fontSize: 12 },
    },
    tooltip: {
      trigger: "axis",
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = (rows[0] ?? {}) as {
          value?: unknown;
          axisValue?: unknown;
        };
        const firstValue = Array.isArray(first.value)
          ? first.value[0]
          : undefined;
        const ts = Number(firstValue ?? first.axisValue ?? 0);
        const title = Number.isFinite(ts)
          ? formatAxisTitle(graph, ts)
          : String(rows[0]?.axisValue ?? "");
        const lines = rows
          .map(
            (item) =>
              item as { value?: unknown; marker?: string; seriesName?: string },
          )
          .filter((r) => !String(r.seriesName ?? "").startsWith("Trend"))
          .filter(
            (r) =>
              Array.isArray(r.value) && Number.isFinite(Number(r.value[1])),
          )
          .map(
            (r) =>
              `${r.seriesName ?? ""}: ${Number((r.value as unknown[])[1]).toFixed(1)}${unit === "F" ? "°F" : "°C"}`,
          );
        return [title, ...lines].join("<br/>");
      },
    },
    xAxis: {
      type: "time",
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
      nameTextStyle: {
        color: "#666b78",
        fontSize: 13,
        align: "center",
        verticalAlign: "middle",
      },
      axisLabel: {
        color: "#666b78",
        formatter: (value: number) => `${Math.round(value)}`,
      },
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
  const isHotDaysChart =
    graph.id === "t2m_hot_days" || graph.id === "sst_hot_days";
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
    <div className={styles.graphCard}>
      {showTitle ? (
        <h3 className={styles.graphTitle}>
          {graph.title === "Annual temperature"
            ? "Annual air temperature"
            : graph.title}
        </h3>
      ) : null}
      {hasAnimation ? (
        <div className={styles.stepButtons}>
          {steps.map((step, idx) => {
            const active = idx === stepIndex;
            return (
              <button
                key={`${graph.id}:${step.id}`}
                onClick={() => setStepIndex(idx)}
                className={`${styles.stepButton} ${
                  active ? styles.stepButtonActive : ""
                }`}
              >
                {step.title ?? step.id}
              </button>
            );
          })}
        </div>
      ) : null}

      <EChartCanvas option={option} height={260} />

      {graph.error ? (
        <div className={styles.graphError}>{graph.error}</div>
      ) : null}
      {graph.caption ? (
        <div className={styles.graphCaption}>{graph.caption}</div>
      ) : null}
    </div>
  );
}

export default function ApiDemoPage() {
  const graphsPerPage = 2;
  const wheelStepThreshold = 130;
  const wheelGestureGapMs = 160;
  const [lat, setLat] = useState<number>(-20.32556);
  const [lon, setLon] = useState<number>(57.37056);
  const [unit, setUnit] = useState<"C" | "F">("C");
  const [resp, setResp] = useState<PanelResponse | null>(null);
  const [search, setSearch] = useState<string>("");
  const [suggestions, setSuggestions] = useState<AutocompleteItem[]>([]);
  const [suggestOpen, setSuggestOpen] = useState<boolean>(false);
  const [suggestIndex, setSuggestIndex] = useState<number>(-1);
  const [suggestLoading, setSuggestLoading] = useState<boolean>(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState<boolean>(false);
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(
    null,
  );
  const [selectedLocation, setSelectedLocation] =
    useState<SelectedLocationMeta | null>(null);
  const debounceRef = useRef<number | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const wheelAccumRef = useRef(0);
  const wheelLastEventTsRef = useRef(0);
  const wheelGestureConsumedRef = useRef(false);
  const wheelGestureResetTimerRef = useRef<number | null>(null);
  const [graphPage, setGraphPage] = useState(0);
  const apiBase = useMemo(() => {
    if (process.env.NEXT_PUBLIC_CLIMATE_API_BASE) {
      return process.env.NEXT_PUBLIC_CLIMATE_API_BASE.replace(/\/+$/, "");
    }
    if (typeof window === "undefined") return "http://localhost:8001";
    return `http://${window.location.hostname}:8001`;
  }, []);
  const mapLayerRoot = useMemo(() => {
    if (process.env.NEXT_PUBLIC_MAP_LAYER_ROOT) {
      return process.env.NEXT_PUBLIC_MAP_LAYER_ROOT.replace(/\/+$/, "");
    }
    return "/data/maps";
  }, []);
  const mapLayers = useMemo<MapLayerOption[]>(
    () => [
      {
        id: "none",
        label: "None",
      },
      {
        id: "t2m_warming_2025_vs_1979_1988_mercator_texture",
        label: "Warming (air)",
        imageUrl: `${mapLayerRoot}/t2m_warming_2025_vs_1979_1988_mercator.webp`,
        opacity: 0.72,
      },
      {
        id: "sst_warming_2025_vs_1982_1991_mercator_texture",
        label: "Warming (sea surface)",
        imageUrl: `${mapLayerRoot}/sst_warming_2025_vs_1982_1991_mercator.webp`,
        opacity: 0.72,
      },
    ],
    [mapLayerRoot],
  );
  const [activeLayerId, setActiveLayerId] = useState<string>(
    mapLayers[0]?.id ?? "",
  );

  const panelData = useMemo(() => {
    if (!resp) return [];
    return resp.panels.map((item) => ({
      score: item.score,
      panel: item.panel,
      graphs: [...item.panel.graphs]
        .sort((a, b) => {
          const isAHotDays = a.title === "Hot days per year (air temperature)";
          const isBHotDays = b.title === "Hot days per year (air temperature)";
          const isAZoomOut = a.title === "Temperature zoom-out";
          const isBZoomOut = b.title === "Temperature zoom-out";
          if (isAHotDays && isBZoomOut) return -1;
          if (isAZoomOut && isBHotDays) return 1;
          return 0;
        })
        .map((graph) => ({
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

  const pagedGraphs = useMemo<PagedGraphItem[]>(
    () =>
      panelData.flatMap(({ panel, graphs }) =>
        graphs.map(({ graph, data }) => ({ panelId: panel.id, graph, data })),
      ),
    [panelData],
  );
  const maxGraphPage = Math.max(
    0,
    Math.ceil(pagedGraphs.length / graphsPerPage) - 1,
  );
  const pageStart = graphPage * graphsPerPage;
  const visibleGraphs = pagedGraphs.slice(pageStart, pageStart + graphsPerPage);
  const graphSlots = [visibleGraphs[0] ?? null, visibleGraphs[1] ?? null] as const;

  const goGraphPage = useCallback(
    (direction: 1 | -1): boolean => {
      const nextPage =
        direction > 0
          ? Math.min(maxGraphPage, graphPage + 1)
          : Math.max(0, graphPage - 1);
      if (nextPage === graphPage) return false;
      setGraphPage(nextPage);
      return true;
    },
    [graphPage, maxGraphPage],
  );

  async function load(nextLat = lat, nextLon = lon, nextUnit = unit) {
    const url = `${apiBase}/api/v/dev/panel?lat=${encodeURIComponent(nextLat)}&lon=${encodeURIComponent(
      nextLon,
    )}&unit=${nextUnit}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as PanelResponse;
    setResp(data);
    return data;
  }

  const fetchAutocomplete = useCallback(
    async (q: string) => {
      const url = `${apiBase}/api/v/dev/locations/autocomplete?q=${encodeURIComponent(
        q,
      )}&limit=8`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as AutocompleteResponse;
      return data.results ?? [];
    },
    [apiBase],
  );

  async function resolveByLabel(label: string) {
    const url = `${apiBase}/api/v/dev/locations/resolve?label=${encodeURIComponent(
      label,
    )}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as { result?: AutocompleteItem | null };
    return data.result ?? null;
  }

  async function fetchNearestLocation(nextLat: number, nextLon: number) {
    const url = `${apiBase}/api/v/dev/location/nearest?lat=${encodeURIComponent(nextLat)}&lon=${encodeURIComponent(
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
    setPicked({ lat: item.lat, lon: item.lon });
    setSelectedLocation({
      geonameid: item.geonameid,
      label: item.label,
      countryCode: item.country_code,
      population: item.population,
    });
    setPanelOpen(true);
    void load(item.lat, item.lon);
  }

  async function handlePick(la: number, lo: number) {
    setLat(la);
    setLon(lo);
    setPicked({ lat: la, lon: lo });
    setPanelOpen(true);

    try {
      const bbox = resp?.location?.panel_valid_bbox;
      if (inBbox(la, lo, bbox)) {
        const place = await fetchNearestLocation(la, lo);
        setSelectedLocation({
          geonameid: place.geonameid,
          label: place.label ?? "",
          countryCode: place.country_code ?? "",
          population:
            typeof place.population === "number" &&
            Number.isFinite(place.population)
              ? place.population
              : null,
        });
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
                country_code: place.country_code ?? null,
                population: place.population ?? null,
              },
            },
          };
        });
        return;
      }
      await load(la, lo);
    } catch (err) {
      setSuggestError(
        err instanceof Error ? err.message : "Failed to load location data",
      );
    }
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
        setSuggestError(
          err instanceof Error ? err.message : "Autocomplete failed",
        );
        setSuggestions([]);
        setSuggestOpen(false);
        setSuggestIndex(-1);
      } finally {
        setSuggestLoading(false);
      }
    }, 250);
  }, [fetchAutocomplete, search]);

  useEffect(() => {
    if (!mapLayers.length) return;
    if (mapLayers.some((layer) => layer.id === activeLayerId)) return;
    setActiveLayerId(mapLayers[0].id);
  }, [activeLayerId, mapLayers]);

  useEffect(() => {
    const place = resp?.location.place;
    if (!place?.geonameid) return;
    setSelectedLocation({
      geonameid: place.geonameid,
      label: place.label ?? "",
      countryCode: place.country_code ?? "",
      population:
        typeof place.population === "number" &&
        Number.isFinite(place.population)
          ? place.population
          : null,
    });
  }, [resp?.location.place]);

  useEffect(() => {
    setGraphPage(0);
    wheelAccumRef.current = 0;
    wheelLastEventTsRef.current = 0;
    wheelGestureConsumedRef.current = false;
  }, [lat, lon, unit, pagedGraphs.length]);

  useEffect(() => {
    if (!panelOpen) return;
    panelRef.current?.focus();
  }, [panelOpen]);

  useEffect(
    () => () => {
      if (wheelGestureResetTimerRef.current) {
        window.clearTimeout(wheelGestureResetTimerRef.current);
      }
    },
    [],
  );

  const handlePanelWheel = useCallback(
    (e: React.WheelEvent<HTMLElement>) => {
      if (Math.abs(e.deltaY) < 5) return;
      e.preventDefault();
      const now = Date.now();
      if (now - wheelLastEventTsRef.current > wheelGestureGapMs) {
        wheelAccumRef.current = 0;
      }
      wheelLastEventTsRef.current = now;
      if (wheelGestureResetTimerRef.current) {
        window.clearTimeout(wheelGestureResetTimerRef.current);
      }
      wheelGestureResetTimerRef.current = window.setTimeout(() => {
        wheelGestureConsumedRef.current = false;
        wheelAccumRef.current = 0;
      }, wheelGestureGapMs);
      if (wheelGestureConsumedRef.current) return;
      wheelAccumRef.current += e.deltaY;
      if (Math.abs(wheelAccumRef.current) < wheelStepThreshold) return;
      const changed = goGraphPage(wheelAccumRef.current > 0 ? 1 : -1);
      wheelAccumRef.current = 0;
      if (changed) {
        wheelGestureConsumedRef.current = true;
      }
    },
    [goGraphPage, wheelGestureGapMs, wheelStepThreshold],
  );

  const handlePanelKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      if (e.key === "ArrowDown" || e.key === "PageDown") {
        e.preventDefault();
        goGraphPage(1);
      } else if (e.key === "ArrowUp" || e.key === "PageUp") {
        e.preventDefault();
        goGraphPage(-1);
      }
    },
    [goGraphPage],
  );

  const locationLabel =
    selectedLocation?.label ?? resp?.location.place.label ?? "";
  const locationFlag = countryCodeToFlag(selectedLocation?.countryCode);
  const populationText = formatPopulation(selectedLocation?.population);

  return (
    <main className={styles.app}>
      <div className={styles.map}>
        <MapLibreGlobe
          panelOpen={panelOpen}
          focusLocation={picked}
          layerOptions={mapLayers}
          activeLayerId={activeLayerId || null}
          onLayerChange={(layerId) => setActiveLayerId(layerId)}
          onPick={(la, lo) => {
            void handlePick(la, lo);
          }}
          onHome={() => {
            setPanelOpen(false);
            setPicked(null);
          }}
        />
      </div>

      <div className={styles.searchOverlay}>
        <div className={styles.searchWrap}>
          <input
            className={styles.searchInput}
            placeholder="Search a city (min 3 chars)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onFocus={() => {
              if (suggestions.length) setSuggestOpen(true);
            }}
            onKeyDown={async (e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSuggestIndex((i) => Math.min(i + 1, suggestions.length - 1));
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
          />
          {suggestOpen && suggestions.length > 0 ? (
            <div className={styles.suggestionList}>
              {suggestions.map((s, i) => (
                <div
                  key={`${s.geonameid}:${s.label}`}
                  onMouseDown={(evt) => {
                    evt.preventDefault();
                    applyLocation(s);
                    setSuggestOpen(false);
                  }}
                  onMouseEnter={() => setSuggestIndex(i)}
                  className={`${styles.suggestionItem} ${
                    i === suggestIndex ? styles.suggestionItemActive : ""
                  }`}
                >
                  {s.label}
                </div>
              ))}
            </div>
          ) : null}
          {suggestLoading ? (
            <div className={styles.searchStatus}>Searching...</div>
          ) : null}
          {suggestError ? (
            <div className={styles.searchError}>{suggestError}</div>
          ) : null}
        </div>
      </div>

      <aside
        ref={panelRef}
        className={`${styles.locationPanel} ${panelOpen ? styles.locationPanelOpen : ""}`}
        aria-live="polite"
        tabIndex={panelOpen ? 0 : -1}
        onWheel={handlePanelWheel}
        onKeyDown={handlePanelKeyDown}
      >
        <div className={styles.panelActions}>
          <div className={styles.panelTopRow}>
            <div className={styles.unitControl}>
              <div className={styles.unitToggle} role="group" aria-label="Unit">
                <button
                  type="button"
                  className={`${styles.unitOption} ${
                    unit === "C" ? styles.unitOptionActive : ""
                  }`}
                  aria-pressed={unit === "C"}
                  onClick={() => {
                    if (unit === "C") return;
                    setUnit("C");
                    void load(lat, lon, "C");
                  }}
                >
                  °C
                </button>
                <button
                  type="button"
                  className={`${styles.unitOption} ${
                    unit === "F" ? styles.unitOptionActive : ""
                  }`}
                  aria-pressed={unit === "F"}
                  onClick={() => {
                    if (unit === "F") return;
                    setUnit("F");
                    void load(lat, lon, "F");
                  }}
                >
                  °F
                </button>
              </div>
            </div>
            <button
              className={styles.panelClose}
              type="button"
              aria-label="Close panel"
              onClick={() => setPanelOpen(false)}
            >
              x
            </button>
          </div>
          <div className={styles.panelTitleWrap}>
            {locationFlag ? (
              <span className={styles.panelFlag} aria-hidden="true">
                {locationFlag}
              </span>
            ) : null}
            <div>
              <h2 className={styles.panelTitle}>{locationLabel}</h2>
              {populationText ? (
                <p className={styles.panelPopulation}>
                  Population: {populationText}
                </p>
              ) : null}
            </div>
          </div>
        </div>

        <div className={styles.panelViewport}>
          {graphSlots.map((entry, slotIndex) =>
            entry ? (
              <GraphCard
                key={`slot-${slotIndex}`}
                graph={entry.graph}
                data={entry.data}
                series={resp?.series ?? {}}
                unit={unit}
              />
            ) : null,
          )}
        </div>
      </aside>
    </main>
  );
}
