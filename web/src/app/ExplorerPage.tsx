"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import MapLibreGlobe from "@/components/MapLibreGlobe";
import type { MapLayerOption } from "@/components/MapLibreGlobe";
import AboutOverlay from "@/components/AboutOverlay";
import SourcesOverlay from "@/components/SourcesOverlay";
import { defaultTemperatureUnitForLocale } from "@/lib/temperatureUnit";
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
  label?: string | null;
  ui?: { role?: "raw" | "mean" | "trend" | "category" } | null;
  style?: { type?: "line" | "bar"; color?: string; stack?: string } | null;
};
type GraphPayload = {
  id: string;
  title: string;
  ui?: {
    info_text?: string | null;
    chart_mode?: "temperature_line" | "hot_days_combo" | "stacked_bar";
    axis_title_mode?: "year" | "date";
  } | null;
  series_keys: string[];
  source?: string | null;
  caption?: string | null;
  error?: string | null;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
  time_range?: TimeRange;
  animation?: GraphAnimation;
};

type PanelResponse = {
  release: string;
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
  headlines?: Array<{
    key: string;
    label: string;
    value: number | null;
    unit: string;
    baseline?: string | null;
    period?: string | null;
    method?: string | null;
  }>;
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

type ResolveLocationResponse = {
  result?: AutocompleteItem | null;
};

type ReleaseResolveResponse = {
  requested_release: string;
  release: string;
  layers: Array<{
    id: string;
    label: string;
    map_id: string;
    asset_path: string;
    description?: string | null;
    icon?: string | null;
    opacity?: number | null;
    resampling?: "linear" | "nearest" | null;
    legend?: Record<string, unknown> | null;
  }>;
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

type ExplorerPageProps = {
  coldOpen?: boolean;
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

function fallbackKeyLabel(key: string): string {
  return key.replaceAll("_", " ");
}

function seriesLabel(series: Record<string, SeriesPayload>, key: string): string {
  const configured = series[key]?.label;
  if (typeof configured === "string" && configured.trim().length > 0) {
    return configured;
  }
  return fallbackKeyLabel(key);
}

function seriesRole(
  series: Record<string, SeriesPayload>,
  key: string | undefined,
): "raw" | "mean" | "trend" | "category" | undefined {
  if (!key) return undefined;
  const role = series[key]?.ui?.role;
  if (
    role === "raw" ||
    role === "mean" ||
    role === "trend" ||
    role === "category"
  ) {
    return role;
  }
  return undefined;
}

function seriesColor(
  series: Record<string, SeriesPayload>,
  key: string | undefined,
  fallback: string,
): string {
  if (!key) return fallback;
  const configured = series[key]?.style?.color;
  if (typeof configured === "string" && configured.trim().length > 0) {
    return configured;
  }
  return fallback;
}

function graphChartMode(
  graph: GraphPayload,
  visibleKeys: string[],
  series: Record<string, SeriesPayload>,
): "temperature_line" | "hot_days_combo" | "stacked_bar" {
  if (
    graph.ui?.chart_mode === "temperature_line" ||
    graph.ui?.chart_mode === "hot_days_combo" ||
    graph.ui?.chart_mode === "stacked_bar"
  ) {
    return graph.ui.chart_mode;
  }
  const barSeriesCount = visibleKeys.filter(
    (key) => series[key]?.style?.type === "bar",
  ).length;
  if (barSeriesCount >= 2) return "stacked_bar";
  if (barSeriesCount === 1 && visibleKeys.length > 1) return "hot_days_combo";
  return "temperature_line";
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

function formatHeadlineDelta(value: number, unit: "C" | "F"): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}º${unit}`;
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
      replaceMerge: ["series", "xAxis", "yAxis"],
      lazyUpdate: true,
    });
  }, [option]);

  return (
    <div
      ref={rootRef}
      data-echart-canvas="true"
      style={{ width: "100%", height }}
    />
  );
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
  if (graph.ui?.axis_title_mode !== "date") {
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

function formatPopulation(value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return new Intl.NumberFormat("en-US").format(Math.trunc(value));
}

function InfoBubble({ text, label }: { text: string; label: string }) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{
    left: number;
    top: number;
    placement: "below" | "left" | "right";
  } | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const updateCoords = useCallback(() => {
    const btn = buttonRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const tooltipMinWidth = 170;
    const spaceRight = viewportWidth - rect.right;
    const spaceLeft = rect.left;
    if (spaceRight >= tooltipMinWidth || spaceLeft >= tooltipMinWidth) {
      if (spaceRight >= spaceLeft) {
        setCoords({
          left: Math.round(rect.right),
          top: Math.round(rect.bottom + 8),
          placement: "right",
        });
        return;
      }
      setCoords({
        left: Math.round(rect.left),
        top: Math.round(rect.bottom),
        placement: "left",
      });
      return;
    }
    const fallbackLeft = Math.min(
      Math.max(Math.round(rect.left), 0),
      Math.max(0, viewportWidth - tooltipMinWidth),
    );
    setCoords({
      left: fallbackLeft,
      top: Math.round(rect.bottom),
      placement: "below",
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    updateCoords();
    window.addEventListener("resize", updateCoords);
    window.addEventListener("scroll", updateCoords, true);
    return () => {
      window.removeEventListener("resize", updateCoords);
      window.removeEventListener("scroll", updateCoords, true);
    };
  }, [open, updateCoords]);

  return (
    <span className={styles.infoBubble}>
      <button
        ref={buttonRef}
        type="button"
        className={styles.infoBubbleButton}
        aria-label={label}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        i
      </button>
      {open && coords
        ? createPortal(
            <span
              className={`${styles.infoBubbleTooltipGlobal} ${
                coords.placement === "left" ? styles.infoBubbleTooltipLeft : ""
              } ${
                coords.placement === "right"
                  ? styles.infoBubbleTooltipRight
                  : ""
              }`}
              style={{ left: `${coords.left}px`, top: `${coords.top}px` }}
              role="tooltip"
            >
              {text}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}

function yAxisTitle(graph: GraphPayload, unit: "C" | "F"): string {
  const unitLabel = unit === "F" ? "°F" : "°C";
  if (graph.y_axis_label) {
    if (graph.y_axis_label.includes("{unit}")) {
      return graph.y_axis_label.replace("{unit}", unitLabel);
    }
    return graph.y_axis_label;
  }
  return `Temperature (${unitLabel})`;
}

function formatIntegerOnlyAxisTick(value: number): string {
  if (!Number.isFinite(value)) return "";
  const rounded = Math.round(value);
  return Math.abs(value - rounded) < 1e-6 ? `${rounded}` : "";
}

type ChartThemeTokens = {
  axisLabelColor: string;
  axisLineColor: string;
  splitLineColor: string;
  legendColor: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  barBase: string;
  barAccent: string;
  meanLine: string;
  trendArea: string;
  dailyLine: string;
  rawLine: string;
};

function chartThemeTokens(): ChartThemeTokens {
  const dark =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  if (dark) {
    return {
      axisLabelColor: "#b8c2da",
      axisLineColor: "#3b4a6f",
      splitLineColor: "rgba(110, 135, 194, 0.35)",
      legendColor: "#dbe6ff",
      tooltipBg: "#0f172a",
      tooltipBorder: "rgba(140, 179, 255, 0.45)",
      tooltipText: "#e6eeff",
      barBase: "#6d7aa8",
      barAccent: "#ff5b7f",
      meanLine: "#8cb3ff",
      trendArea: "rgba(255, 91, 127, 0.28)",
      dailyLine: "rgba(184, 194, 218, 0.75)",
      rawLine: "#ff6f8d",
    };
  }
  return {
    axisLabelColor: "#666b78",
    axisLineColor: "#cfd4dd",
    splitLineColor: "rgba(200,200,200,0.3)",
    legendColor: "#2d3139",
    tooltipBg: "#ffffff",
    tooltipBorder: "rgba(0, 0, 0, 0.18)",
    tooltipText: "#111111",
    barBase: "#ccccff",
    barAccent: "#ff1744",
    meanLine: "#1736ff",
    trendArea: "rgba(255, 0, 0, 0.24)",
    dailyLine: "rgba(180,180,180,0.7)",
    rawLine: "#ff2e55",
  };
}

function isMobileViewport(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(max-width: 900px)").matches
  );
}

function sharedChartScaffold() {
  const theme = chartThemeTokens();
  const isMobile = isMobileViewport();
  const mobileGridSidePadding = 8;
  const gridLeft = isMobile ? mobileGridSidePadding : 36;
  const gridRight = isMobile ? mobileGridSidePadding : 24;
  const legendRight = isMobile ? mobileGridSidePadding : 24;
  const legendFontSize = isMobile ? 10 : 12;
  const legendType = isMobile ? ("scroll" as const) : ("plain" as const);
  const legendItemWidth = isMobile ? 9 : 30;
  const legendItemHeight = isMobile ? 9 : 10;
  return {
    grid: {
      left: gridLeft,
      right: gridRight,
      top: 36,
      bottom: 20,
      containLabel: true,
    },
    legend: {
      type: legendType,
      orient: "horizontal" as const,
      ...(isMobile ? { icon: "circle" as const } : {}),
      right: legendRight,
      top: 0,
      itemWidth: legendItemWidth,
      itemHeight: legendItemHeight,
      textStyle: { color: theme.legendColor, fontSize: legendFontSize },
    },
  };
}

function sharedXAxisStyle() {
  const theme = chartThemeTokens();
  return {
    axisLabel: { color: theme.axisLabelColor },
    axisLine: { lineStyle: { color: theme.axisLineColor } },
    splitLine: { show: true, lineStyle: { color: theme.splitLineColor } },
  };
}

function sharedYAxisStyle() {
  const theme = chartThemeTokens();
  return {
    nameLocation: "middle" as const,
    nameRotate: 90,
    nameGap: 46,
    nameTextStyle: {
      color: theme.axisLabelColor,
      fontSize: 13,
      align: "center" as const,
      verticalAlign: "middle" as const,
    },
    minInterval: 1,
    splitLine: { lineStyle: { color: theme.splitLineColor } },
  };
}

function trendLegendLabel(
  graph: GraphPayload,
  data: ChartRow[],
  trendKey: string,
  series: Record<string, SeriesPayload>,
  unit: "C" | "F",
): string {
  if (graph.ui?.chart_mode === "hot_days_combo") {
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
  return `${seriesLabel(series, trendKey)}: ${sign}${perDecade.toFixed(1)}${suffix}`;
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
  const theme = chartThemeTokens();
  const isMobile = isMobileViewport();
  const xValues = data.map((row) => row.x);
  const barKey =
    graph.series_keys.find(
      (k) =>
        series[k]?.style?.type === "bar" &&
        seriesRole(series, k) !== "trend" &&
        seriesRole(series, k) !== "mean",
    ) ?? graph.series_keys.find((k) => series[k]?.style?.type === "bar");
  const meanKey = graph.series_keys.find((k) => seriesRole(series, k) === "mean");
  const trendKey = graph.series_keys.find(
    (k) => seriesRole(series, k) === "trend",
  );
  const isVisible = (key: string | undefined) =>
    Boolean(key && visibleKeys.includes(key));
  const barLabel = barKey ? seriesLabel(series, barKey) : "Value";
  const meanLabel = meanKey ? seriesLabel(series, meanKey) : "Mean";
  const trendLabel = trendKey
    ? trendLegendLabel(graph, data, trendKey, series, unit)
    : "Trend";
  const barBaseColor = seriesColor(series, barKey, theme.barBase);
  const barAccentColor = theme.barAccent;
  const meanColor = seriesColor(series, meanKey, theme.meanLine);
  const trendColor = seriesColor(series, trendKey, theme.trendArea);

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
      name: barLabel,
      type: "bar",
      stack: "hot-days",
      data: belowMean,
      itemStyle: { color: barBaseColor },
      emphasis: { focus: "none" },
      z: 2,
      animationDurationUpdate: transitionMs,
    });
    chartSeries.push({
      name: barLabel,
      type: "bar",
      stack: "hot-days",
      data: aboveMean,
      itemStyle: { color: barAccentColor },
      emphasis: { focus: "none" },
      z: 2,
      animationDurationUpdate: transitionMs,
    });
  }
  if (meanKey && isVisible(meanKey)) {
    chartSeries.push({
      name: meanLabel,
      type: "line",
      color: meanColor,
      data: meanDisplayValues,
      smooth: 0.35,
      showSymbol: false,
      itemStyle: { color: meanColor },
      lineStyle: { width: 3, color: meanColor },
      z: 3,
      animationDurationUpdate: transitionMs,
      emphasis: { focus: "series" },
    });
  }
  if (trendKey && isVisible(trendKey)) {
    chartSeries.push({
      name: trendLabel,
      type: "line",
      color: trendColor,
      data: data.map((row) => (row[trendKey] as number | null) ?? null),
      smooth: false,
      showSymbol: false,
      itemStyle: { color: trendColor },
      lineStyle: { width: 0, color: "rgba(255, 0, 0, 0)" },
      areaStyle: { color: trendColor },
      z: 4,
      animationDurationUpdate: transitionMs,
      emphasis: { focus: "series" },
    });
  }

  return {
    animationDuration: 700,
    animationDurationUpdate: transitionMs,
    animationEasing: "cubicOut",
    ...sharedChartScaffold(),
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText },
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
            lines.push(`${barLabel}: ${Math.round(v)}`);
          }
        }
        const extra = new Map<string, number>();
        rows
          .map((item) => item as { value?: unknown; seriesName?: string })
          .forEach((r) => {
            const label = String(r.seriesName ?? "").trim();
            if (!label || label === trendLabel || label === barLabel)
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
      ...sharedXAxisStyle(),
    },
    yAxis: {
      type: "value",
      name: isMobile ? "" : yAxisTitle(graph, unit),
      ...sharedYAxisStyle(),
      axisLabel: {
        color: theme.axisLabelColor,
        formatter: (value: number) => `${Math.round(value)}`,
      },
      min: 0,
    },
    series: chartSeries,
  };
}

function stackedBarColor(
  seriesItem: SeriesPayload | undefined,
  index: number,
): string {
  const configured = seriesItem?.style?.color;
  if (typeof configured === "string" && configured.trim().length > 0) {
    return configured;
  }
  const fallback = ["#4caf50", "#fbc02d", "#ef5350", "#fb8c00", "#8e24aa"];
  return fallback[index % fallback.length];
}

function buildStackedBarOption({
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
  const theme = chartThemeTokens();
  const xValues = data.map((row) => row.x);
  const barKeys = visibleKeys.filter(
    (key) => series[key]?.style?.type === "bar",
  );
  const defaultStack = "stacked-bars";
  const chartSeries: NonNullable<EChartsOption["series"]> = barKeys.map(
    (key, idx) => {
      const s = series[key];
      const stackName =
        typeof s?.style?.stack === "string" && s.style.stack.trim().length > 0
          ? s.style.stack
          : defaultStack;
      return {
        name: seriesLabel(series, key),
        type: "bar",
        stack: stackName,
        data: data.map((row) => (row[key] as number | null) ?? null),
        itemStyle: { color: stackedBarColor(s, idx) },
        emphasis: { focus: "series" },
        z: 2,
        animationDurationUpdate: transitionMs,
      };
    },
  );

  return {
    animationDuration: 700,
    animationDurationUpdate: transitionMs,
    animationEasing: "cubicOut",
    ...sharedChartScaffold(),
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText },
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = (rows[0] ?? {}) as { axisValue?: unknown };
        const title = formatAxisTitle(graph, first.axisValue);
        const lines = rows
          .map(
            (item) =>
              item as { value?: unknown; marker?: string; seriesName?: string },
          )
          .filter(
            (r) => typeof r.value === "number" && Number.isFinite(r.value),
          )
          .map(
            (r) =>
              `${r.marker ?? ""}${r.seriesName ?? ""}: ${Math.round(Number(r.value))}`,
          );
        return [title, ...lines].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: xValues,
      ...sharedXAxisStyle(),
    },
    yAxis: {
      type: "value",
      name: yAxisTitle(graph, unit),
      ...sharedYAxisStyle(),
      axisLabel: {
        color: theme.axisLabelColor,
        formatter: (value: number) => `${Math.round(value)}`,
      },
      min: 0,
    },
    series: chartSeries,
  };
}

function buildTemperatureOption({
  graph,
  series,
  data,
  visibleKeys,
  transitionMs,
  unit,
  xMin,
  xMax,
}: {
  graph: GraphPayload;
  series: Record<string, SeriesPayload>;
  data: ChartRow[];
  visibleKeys: string[];
  transitionMs: number;
  unit: "C" | "F";
  xMin?: number;
  xMax?: number;
}): EChartsOption {
  const theme = chartThemeTokens();
  const isMobile = isMobileViewport();
  const trendKeys = visibleKeys.filter((key) => seriesRole(series, key) === "trend");
  const trendSeriesNames = new Set<string>();
  const chartSeries: NonNullable<EChartsOption["series"]> = visibleKeys.map(
    (key) => {
      const role = seriesRole(series, key);
      const isTrend = role === "trend";
      const isMean = role === "mean";
      const baseColor = seriesColor(
        series,
        key,
        isTrend ? theme.trendArea : isMean ? theme.meanLine : theme.rawLine,
      );
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
      const displayName = isTrend
        ? trendLegendLabel(graph, data, key, series, unit)
        : seriesLabel(series, key);
      if (isTrend) trendSeriesNames.add(displayName);
      return {
        id: key,
        name: displayName,
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
        areaStyle: isTrend ? { color: theme.trendArea } : undefined,
        animationDuration: 700,
        animationDelay: 0,
        animationDurationUpdate: transitionMs,
        emphasis: { focus: "series" },
      };
    },
  );

  const keysForRange = visibleKeys.some((k) => !trendKeys.includes(k))
    ? visibleKeys.filter((k) => !trendKeys.includes(k))
    : visibleKeys;
  const allValues = keysForRange.flatMap((key) =>
    data
      .map((row) => row[key])
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v)),
  );
  let yMin: number | undefined;
  let yMax: number | undefined;
  const yAxisName = yAxisTitle(graph, unit);
  const isTemperatureAxis =
    !graph.y_axis_label || graph.y_axis_label.includes("{unit}");
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
    ...sharedChartScaffold(),
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText },
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
          .filter((r) => !trendSeriesNames.has(String(r.seriesName ?? "")))
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
      ...sharedXAxisStyle(),
    },
    yAxis: {
      type: "value",
      name: isMobile ? "" : yAxisName,
      ...sharedYAxisStyle(),
      axisLabel: {
        color: theme.axisLabelColor,
        formatter: (value: number) =>
          isTemperatureAxis
            ? formatIntegerOnlyAxisTick(value)
            : `${Math.round(value)}`,
      },
      scale: true,
      min: yMin,
      max: yMax,
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
  stepIndex,
  onStepIndexChange,
}: {
  graph: GraphPayload;
  data: ChartRow[];
  series: Record<string, SeriesPayload>;
  unit: "C" | "F";
  showTitle?: boolean;
  stepIndex: number;
  onStepIndexChange: (graphId: string, nextStepIndex: number) => void;
}) {
  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const [chartHeight, setChartHeight] = useState(260);
  const steps = graph.animation?.steps ?? [];
  const hasAnimation = steps.length >= 2;
  const chartMaxHeight = 260;
  const chartMinAspectRatio = 1.5;
  const safeStepIndex = hasAnimation
    ? Math.max(0, Math.min(steps.length - 1, Math.trunc(stepIndex)))
    : 0;

  useEffect(() => {
    const host = chartHostRef.current;
    if (!host) return;
    const updateChartHeight = () => {
      const width = host.clientWidth;
      if (!Number.isFinite(width) || width <= 0) return;
      const nextHeight = Math.max(
        1,
        Math.min(chartMaxHeight, Math.floor(width / chartMinAspectRatio)),
      );
      setChartHeight((prev) => (prev === nextHeight ? prev : nextHeight));
    };
    updateChartHeight();
    const observer = new ResizeObserver(updateChartHeight);
    observer.observe(host);
    return () => observer.disconnect();
  }, [chartMaxHeight, chartMinAspectRatio]);

  useEffect(() => {
    if (!hasAnimation || graph.animation?.autoplay === false) return;
    const stepDuration = graph.animation?.step_duration_ms ?? 2600;
    const timer = window.setTimeout(() => {
      const nextStepIndex =
        safeStepIndex + 1 < steps.length
          ? safeStepIndex + 1
          : graph.animation?.loop === false
            ? safeStepIndex
            : 0;
      onStepIndexChange(graph.id, nextStepIndex);
    }, stepDuration);
    return () => window.clearTimeout(timer);
  }, [
    graph.animation,
    graph.id,
    hasAnimation,
    onStepIndexChange,
    safeStepIndex,
    steps.length,
  ]);

  const activeStep = hasAnimation
    ? steps[safeStepIndex]
    : null;
  const visibleKeys = activeStep?.series_keys?.length
    ? activeStep.series_keys
    : graph.series_keys;
  const chartMode = graphChartMode(graph, visibleKeys, series);
  const isStackedBarChart = chartMode === "stacked_bar";
  const hasGraphError =
    typeof graph.error === "string" && graph.error.trim().length > 0;
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
  const isHotDaysChart = chartMode === "hot_days_combo";
  const graphInfoText =
    typeof graph.ui?.info_text === "string" ? graph.ui.info_text : "";
  const useAllVisibleDataForSeries = graph.ui?.axis_title_mode === "date";
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
    if (isStackedBarChart) {
      return buildStackedBarOption({
        graph,
        series,
        data: filteredData,
        visibleKeys,
        transitionMs,
        unit,
      });
    }
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
      series,
      data: useAllVisibleDataForSeries ? allVisibleData : filteredData,
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
    isStackedBarChart,
    useAllVisibleDataForSeries,
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
        <div className={styles.graphTitleRow}>
          <h3 className={styles.graphTitle}>{graph.title}</h3>
          {graphInfoText ? (
            <InfoBubble label="Graph title information" text={graphInfoText} />
          ) : null}
        </div>
      ) : null}
      {hasAnimation && !hasGraphError ? (
        <div className={styles.stepButtons}>
          {steps.map((step, idx) => {
            const active = idx === safeStepIndex;
            return (
              <button
                key={`${graph.id}:${step.id}`}
                onClick={() => onStepIndexChange(graph.id, idx)}
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

      {!hasGraphError ? (
        <div ref={chartHostRef}>
          <EChartCanvas option={option} height={chartHeight} />
        </div>
      ) : null}

      {hasGraphError ? (
        <div className={styles.graphError}>{graph.error}</div>
      ) : null}
      {!hasGraphError && graph.caption ? (
        <div className={styles.graphCaption}>{graph.caption}</div>
      ) : null}
    </div>
  );
}

const COLD_OPEN_FADE_MS = 520;
const COLD_OPEN_QUESTION_DELAY_MS = 1700;
const COLD_OPEN_PROMPT_DELAY_MS = 6000;
const COLD_OPEN_PRIMARY_REVEAL_DELAY_MS = 80;
const COLD_OPEN_WHEEL_GESTURE_IDLE_MS = 55;
const COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN = 0.35;

export default function ExplorerPage({ coldOpen = false }: ExplorerPageProps) {
  const envDefaultReleaseRaw = process.env.NEXT_PUBLIC_RELEASE;
  const envDefaultRelease = envDefaultReleaseRaw
    ? envDefaultReleaseRaw.trim()
    : "";
  const minPanelViewportHeightForTwoGraphs = 600;
  const wheelStepThreshold = 130;
  const wheelGestureGapMs = 160;
  const wheelSustainRepeatMs = 520;
  const wheelRepeatKickThreshold = 55;
  const touchSwipeThresholdPx = 44;
  const touchClosePanelThresholdPx = 72;
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
  const [panelLoadError, setPanelLoadError] = useState<string | null>(null);
  const [panelLoading, setPanelLoading] = useState<boolean>(false);
  const [panelRetrying, setPanelRetrying] = useState<boolean>(false);
  const [panelOpen, setPanelOpen] = useState<boolean>(false);
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(
    null,
  );
  const [selectedLocation, setSelectedLocation] =
    useState<SelectedLocationMeta | null>(null);
  const [selectedGeonameidForPanel, setSelectedGeonameidForPanel] = useState<
    number | null
  >(null);
  const debounceRef = useRef<number | null>(null);
  const searchWrapRef = useRef<HTMLDivElement | null>(null);
  const wheelAccumRef = useRef(0);
  const wheelLastEventTsRef = useRef(0);
  const wheelGestureConsumedRef = useRef(false);
  const wheelGestureConsumedAtRef = useRef(0);
  const wheelGestureResetTimerRef = useRef<number | null>(null);
  const touchStartYRef = useRef<number | null>(null);
  const touchStartXRef = useRef<number | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const panelViewportRef = useRef<HTMLDivElement | null>(null);
  const pendingGraphRestoreIdsRef = useRef<string[] | null>(null);
  const [graphsPerPage, setGraphsPerPage] = useState(2);
  const prevGraphsPerPageRef = useRef(2);
  const [graphPage, setGraphPage] = useState(0);
  const [graphStepById, setGraphStepById] = useState<Record<string, number>>({});
  const [introVisible, setIntroVisible] = useState(coldOpen);
  const [introFading, setIntroFading] = useState(false);
  const [introPromptVisible, setIntroPromptVisible] = useState(!coldOpen);
  const [introPrimaryVisible, setIntroPrimaryVisible] = useState(!coldOpen);
  const [introQuestionVisible, setIntroQuestionVisible] = useState(!coldOpen);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const introDismissTimerRef = useRef<number | null>(null);
  const introPhaseTimerRef = useRef<number | null>(null);
  const introPrimaryTimerRef = useRef<number | null>(null);
  const introQuestionTimerRef = useRef<number | null>(null);
  const coldOpenWheelGestureActiveRef = useRef(false);
  const coldOpenWheelGestureResetTimerRef = useRef<number | null>(null);
  const [requestedRelease, setRequestedRelease] = useState<string>(
    envDefaultRelease
      ? envDefaultRelease.toLowerCase() === "latest"
        ? "latest"
        : envDefaultRelease
      : "latest",
  );
  const [sessionRelease, setSessionRelease] = useState<string | null>(null);
  const [releaseLayers, setReleaseLayers] = useState<
    ReleaseResolveResponse["layers"]
  >([]);
  const apiBase = useMemo(() => {
    if (process.env.NEXT_PUBLIC_CLIMATE_API_BASE) {
      return process.env.NEXT_PUBLIC_CLIMATE_API_BASE.replace(/\/+$/, "");
    }
    if (typeof window === "undefined") return "http://localhost:8001";
    return `http://${window.location.hostname}:8001`;
  }, []);
  const mapAssetBase = useMemo(() => {
    if (process.env.NEXT_PUBLIC_MAP_ASSET_BASE) {
      return process.env.NEXT_PUBLIC_MAP_ASSET_BASE.replace(/\/+$/, "");
    }
    return apiBase;
  }, [apiBase]);
  const releaseForSession = sessionRelease ?? requestedRelease;
  const encodedRelease = encodeURIComponent(releaseForSession);
  const pinSessionRelease = useCallback(
    (releaseValue: string | null | undefined) => {
      if (!releaseValue) return;
      setSessionRelease((prev) => prev ?? releaseValue);
    },
    [],
  );
  const mapLayers = useMemo<MapLayerOption[]>(() => {
    const configuredLayers = releaseLayers.map((layer) => ({
      id: layer.id,
      label: layer.label,
      imageUrl: `${mapAssetBase}/assets/v/${encodedRelease}/${layer.asset_path}`,
      opacity: typeof layer.opacity === "number" ? layer.opacity : 0.72,
      resampling:
        layer.resampling === "linear" || layer.resampling === "nearest"
          ? layer.resampling
          : ("nearest" as const),
    }));
    return [{ id: "none", label: "None" }, ...configuredLayers];
  }, [encodedRelease, mapAssetBase, releaseLayers]);
  const [activeLayerId, setActiveLayerId] = useState<string>(
    mapLayers[0]?.id ?? "",
  );
  const tempHeadline = useMemo(() => {
    if (!resp?.headlines?.length) return null;
    return (
      resp.headlines.find((h) => h.key === "t2m_vs_preindustrial_local") ?? null
    );
  }, [resp]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const qp = new URLSearchParams(window.location.search).get("release");
    if (!qp) return;
    const trimmed = qp.trim();
    if (!trimmed) return;
    const normalized = trimmed.toLowerCase() === "latest" ? "latest" : trimmed;
    setRequestedRelease(normalized);
  }, []);

  const setAboutOpenWithUrl = useCallback((open: boolean) => {
    setAboutOpen(open);
    if (open) setSourcesOpen(false);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (open) {
      url.searchParams.set("about", "1");
      url.searchParams.delete("sources");
    } else {
      url.searchParams.delete("about");
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
  }, []);

  const setSourcesOpenWithUrl = useCallback((open: boolean) => {
    setSourcesOpen(open);
    if (open) setAboutOpen(false);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (open) {
      url.searchParams.set("sources", "1");
      url.searchParams.delete("about");
    } else {
      url.searchParams.delete("sources");
    }
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const showAbout = params.has("about");
    const showSources = params.has("sources");
    if (showAbout) {
      setAboutOpen(true);
      return;
    }
    if (showSources) setSourcesOpen(true);
  }, []);

  useEffect(() => {
    if (defaultTemperatureUnitForLocale() !== "F") return;
    setUnit("F");
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function resolveRelease() {
      try {
        const url = `${apiBase}/api/v/${encodeURIComponent(requestedRelease)}/release`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const data = (await r.json()) as ReleaseResolveResponse;
        if (cancelled) return;
        setSessionRelease(data.release);
        setReleaseLayers(Array.isArray(data.layers) ? data.layers : []);
      } catch {
        if (cancelled) return;
        setSessionRelease(requestedRelease);
        setReleaseLayers([]);
      }
    }

    void resolveRelease();
    return () => {
      cancelled = true;
    };
  }, [apiBase, requestedRelease]);

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
  const stepCount = maxGraphPage + 1;
  const pageStart = graphPage * graphsPerPage;
  const visibleGraphs = pagedGraphs.slice(pageStart, pageStart + graphsPerPage);
  const graphSlots = useMemo(
    () =>
      Array.from(
        { length: graphsPerPage },
        (_, index) => visibleGraphs[index] ?? null,
      ),
    [graphsPerPage, visibleGraphs],
  );
  const queueGraphRestoreFromVisible = useCallback(() => {
    const visibleIds = visibleGraphs
      .map((entry) => entry?.graph.id)
      .filter((id): id is string => typeof id === "string" && id.length > 0);
    pendingGraphRestoreIdsRef.current = visibleIds.length > 0 ? visibleIds : null;
  }, [visibleGraphs]);

  useEffect(() => {
    setGraphPage((prev) => Math.min(prev, maxGraphPage));
  }, [maxGraphPage]);

  useEffect(() => {
    const previous = prevGraphsPerPageRef.current;
    if (previous === graphsPerPage) return;
    setGraphPage((prev) =>
      Math.floor((prev * previous) / Math.max(1, graphsPerPage)),
    );
    prevGraphsPerPageRef.current = graphsPerPage;
  }, [graphsPerPage]);

  const goGraphPage = useCallback(
    (direction: 1 | -1): boolean => {
      const nextPage =
        direction > 0
          ? Math.min(maxGraphPage, graphPage + 1)
          : Math.max(0, graphPage - 1);
      if (nextPage === graphPage) return false;
      const viewport = panelViewportRef.current;
      if (viewport) {
        viewport
          .querySelectorAll<HTMLElement>('[data-echart-canvas="true"]')
          .forEach((node) => {
            const chart = echarts.getInstanceByDom(node);
            if (!chart) return;
            chart.dispatchAction({ type: "hideTip" });
          });
      }
      setGraphPage(nextPage);
      return true;
    },
    [graphPage, maxGraphPage],
  );
  const goToGraphPage = useCallback(
    (nextPage: number): boolean => {
      const clamped = Math.max(0, Math.min(maxGraphPage, nextPage));
      if (clamped === graphPage) return false;
      const viewport = panelViewportRef.current;
      if (viewport) {
        viewport
          .querySelectorAll<HTMLElement>('[data-echart-canvas="true"]')
          .forEach((node) => {
            const chart = echarts.getInstanceByDom(node);
            if (!chart) return;
            chart.dispatchAction({ type: "hideTip" });
          });
      }
      setGraphPage(clamped);
      return true;
    },
    [graphPage, maxGraphPage],
  );
  const handleGraphStepChange = useCallback(
    (graphId: string, nextStepIndex: number) => {
      setGraphStepById((prev) => {
        const normalized = Math.max(0, Math.trunc(nextStepIndex));
        if (prev[graphId] === normalized) return prev;
        return { ...prev, [graphId]: normalized };
      });
    },
    [],
  );

  async function load(
    nextLat = lat,
    nextLon = lon,
    nextUnit = unit,
    nextSelectedGeonameid = selectedGeonameidForPanel,
  ) {
    const params = new URLSearchParams({
      lat: String(nextLat),
      lon: String(nextLon),
      unit: nextUnit,
    });
    if (nextSelectedGeonameid !== null) {
      params.set("selected_geonameid", String(nextSelectedGeonameid));
    }
    const url = `${apiBase}/api/v/${encodeURIComponent(releaseForSession)}/panel?${params.toString()}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as PanelResponse;
    pinSessionRelease(data.release);
    setResp(data);
    return data;
  }

  async function loadPanel(
    nextLat = lat,
    nextLon = lon,
    nextUnit = unit,
    nextSelectedGeonameid = selectedGeonameidForPanel,
  ) {
    setPanelLoading(true);
    setPanelLoadError(null);
    try {
      const data = await load(
        nextLat,
        nextLon,
        nextUnit,
        nextSelectedGeonameid,
      );
      setPanelLoadError(null);
      return data;
    } catch {
      pendingGraphRestoreIdsRef.current = null;
      setResp(null);
      setSelectedLocation((prev) =>
        prev ? { ...prev, population: null } : prev,
      );
      setPanelLoadError("Couldn’t load climate data.");
      return null;
    } finally {
      setPanelLoading(false);
    }
  }

  const fetchAutocomplete = useCallback(
    async (q: string) => {
      const url = `${apiBase}/api/v/${encodeURIComponent(releaseForSession)}/locations/autocomplete?q=${encodeURIComponent(
        q,
      )}&limit=8`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as AutocompleteResponse;
      return data.results ?? [];
    },
    [apiBase, releaseForSession],
  );

  async function resolveByLabel(label: string) {
    const url = `${apiBase}/api/v/${encodeURIComponent(releaseForSession)}/locations/resolve?label=${encodeURIComponent(label)}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as ResolveLocationResponse;
    return data.result ?? null;
  }

  async function fetchNearestLocation(nextLat: number, nextLon: number) {
    const url = `${apiBase}/api/v/${encodeURIComponent(releaseForSession)}/locations/nearest?lat=${encodeURIComponent(nextLat)}&lon=${encodeURIComponent(
      nextLon,
    )}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as NearestLocationResponse;
    return data.result;
  }

  function applyLocation(item: AutocompleteItem) {
    queueGraphRestoreFromVisible();
    setSearch("");
    setLat(item.lat);
    setLon(item.lon);
    setPicked({ lat: item.lat, lon: item.lon });
    setSelectedGeonameidForPanel(item.geonameid);
    setSelectedLocation({
      geonameid: item.geonameid,
      label: item.label,
      countryCode: item.country_code,
      population: item.population,
    });
    setPanelOpen(true);
    void loadPanel(item.lat, item.lon, unit, item.geonameid);
  }

  async function handlePick(la: number, lo: number) {
    queueGraphRestoreFromVisible();
    setLat(la);
    setLon(lo);
    setPicked({ lat: la, lon: lo });
    setSelectedGeonameidForPanel(null);
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
        setPanelLoadError(null);
        return;
      }
      await loadPanel(la, lo, unit, null);
    } catch (err) {
      setResp(null);
      setSelectedLocation((prev) =>
        prev ? { ...prev, population: null } : prev,
      );
      setPanelLoadError("Couldn’t load climate data.");
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
    if (!suggestOpen) return;
    const closeIfOutside = (target: EventTarget | null) => {
      if (!searchWrapRef.current) return;
      if (!(target instanceof Node)) return;
      if (searchWrapRef.current.contains(target)) return;
      setSuggestOpen(false);
      setSuggestIndex(-1);
    };
    const onWindowPointerDown = (event: PointerEvent) => {
      closeIfOutside(event.target);
    };
    const onWindowFocusIn = (event: FocusEvent) => {
      closeIfOutside(event.target);
    };
    const onWindowWheel = (event: WheelEvent) => {
      closeIfOutside(event.target);
    };
    window.addEventListener("pointerdown", onWindowPointerDown, true);
    window.addEventListener("focusin", onWindowFocusIn, true);
    window.addEventListener("wheel", onWindowWheel, true);
    return () => {
      window.removeEventListener("pointerdown", onWindowPointerDown, true);
      window.removeEventListener("focusin", onWindowFocusIn, true);
      window.removeEventListener("wheel", onWindowWheel, true);
    };
  }, [suggestOpen]);

  useEffect(() => {
    if (!mapLayers.length) return;
    if (mapLayers.some((layer) => layer.id === activeLayerId)) return;
    setActiveLayerId(mapLayers[0].id);
  }, [activeLayerId, mapLayers]);

  useEffect(() => {
    const viewport = panelViewportRef.current;
    if (!viewport) return;
    const updateGraphsPerPage = () => {
      const next =
        viewport.clientHeight < minPanelViewportHeightForTwoGraphs ? 1 : 2;
      setGraphsPerPage((prev) => (prev === next ? prev : next));
    };
    updateGraphsPerPage();
    const observer = new ResizeObserver(updateGraphsPerPage);
    observer.observe(viewport);
    window.addEventListener("resize", updateGraphsPerPage);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateGraphsPerPage);
    };
  }, []);

  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    if (panelOpen) {
      panel.focus({ preventScroll: true });
      return;
    }
    const active = document.activeElement;
    if (active instanceof HTMLElement && panel.contains(active)) {
      active.blur();
    }
  }, [panelOpen]);

  const keepPanelFocused = useCallback(() => {
    if (!panelOpen || introVisible) return;
    window.requestAnimationFrame(() => {
      panelRef.current?.focus({ preventScroll: true });
    });
  }, [introVisible, panelOpen]);

  const dismissColdOpen = useCallback(() => {
    if (!introVisible || introFading) return;
    setIntroFading(true);
    introDismissTimerRef.current = window.setTimeout(() => {
      setIntroVisible(false);
      setIntroFading(false);
      introDismissTimerRef.current = null;
    }, COLD_OPEN_FADE_MS);
  }, [introFading, introVisible]);

  const showIntroPrompt = useCallback(() => {
    if (!introVisible || introPromptVisible) return;
    if (introPhaseTimerRef.current) {
      window.clearTimeout(introPhaseTimerRef.current);
      introPhaseTimerRef.current = null;
    }
    setIntroPromptVisible(true);
  }, [introPromptVisible, introVisible]);

  const showIntroQuestion = useCallback(() => {
    if (!introVisible || introQuestionVisible) return;
    if (introQuestionTimerRef.current) {
      window.clearTimeout(introQuestionTimerRef.current);
      introQuestionTimerRef.current = null;
    }
    setIntroQuestionVisible(true);
  }, [introQuestionVisible, introVisible]);

  useEffect(() => {
    if (!introVisible || introQuestionVisible) return;
    introPhaseTimerRef.current = window.setTimeout(() => {
      setIntroQuestionVisible(true);
      introPhaseTimerRef.current = null;
    }, COLD_OPEN_QUESTION_DELAY_MS);
  }, [introQuestionVisible, introVisible]);

  useEffect(() => {
    if (!introVisible || introPromptVisible || introPrimaryVisible) return;
    introPrimaryTimerRef.current = window.setTimeout(() => {
      setIntroPrimaryVisible(true);
      introPrimaryTimerRef.current = null;
    }, COLD_OPEN_PRIMARY_REVEAL_DELAY_MS);
  }, [introPrimaryVisible, introPromptVisible, introVisible]);

  useEffect(() => {
    if (!introVisible || !introQuestionVisible || introPromptVisible) return;
    introQuestionTimerRef.current = window.setTimeout(() => {
      setIntroPromptVisible(true);
      introQuestionTimerRef.current = null;
    }, COLD_OPEN_PROMPT_DELAY_MS);
  }, [introPromptVisible, introQuestionVisible, introVisible]);

  const handleColdOpenInteractionCapture = useCallback(
    (e: React.SyntheticEvent) => {
      if (!introVisible) return;
      e.preventDefault();
      e.stopPropagation();
      if (!introQuestionVisible) {
        showIntroQuestion();
        return;
      }
      if (!introPromptVisible) {
        showIntroPrompt();
        return;
      }
      dismissColdOpen();
    },
    [
      dismissColdOpen,
      introPromptVisible,
      introQuestionVisible,
      introVisible,
      showIntroPrompt,
      showIntroQuestion,
    ],
  );

  const handleColdOpenPointerDownCapture = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (!introVisible) return;
      if (e.pointerType === "touch") {
        // Touch interactions are handled in onTouchStartCapture to avoid
        // processing the same tap twice on mobile browsers.
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      handleColdOpenInteractionCapture(e);
    },
    [handleColdOpenInteractionCapture, introVisible],
  );

  const handleColdOpenWheelCapture = useCallback(
    (e: React.WheelEvent<HTMLElement>) => {
      if (!introVisible) return;
      e.preventDefault();
      e.stopPropagation();
      const gestureDelta = Math.max(Math.abs(e.deltaX), Math.abs(e.deltaY));
      if (!coldOpenWheelGestureActiveRef.current) {
        if (gestureDelta < COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN) {
          return;
        }
        coldOpenWheelGestureActiveRef.current = true;
        handleColdOpenInteractionCapture(e);
      }
      // Do not extend the gesture session for tiny inertial wheel events.
      if (gestureDelta < COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN) {
        return;
      }
      if (coldOpenWheelGestureResetTimerRef.current) {
        window.clearTimeout(coldOpenWheelGestureResetTimerRef.current);
      }
      coldOpenWheelGestureResetTimerRef.current = window.setTimeout(() => {
        coldOpenWheelGestureActiveRef.current = false;
        coldOpenWheelGestureResetTimerRef.current = null;
      }, COLD_OPEN_WHEEL_GESTURE_IDLE_MS);
    },
    [handleColdOpenInteractionCapture, introVisible],
  );

  useEffect(() => {
    if (!introVisible) return;
    const onWindowKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (
        event.key === "Shift" ||
        event.key === "Control" ||
        event.key === "Alt" ||
        event.key === "Meta"
      ) {
        return;
      }
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      if (!introQuestionVisible) {
        showIntroQuestion();
        return;
      }
      if (!introPromptVisible) {
        showIntroPrompt();
        return;
      }
      dismissColdOpen();
    };
    window.addEventListener("keydown", onWindowKeyDown, true);
    return () => {
      window.removeEventListener("keydown", onWindowKeyDown, true);
    };
  }, [
    dismissColdOpen,
    introPromptVisible,
    introQuestionVisible,
    introVisible,
    showIntroPrompt,
    showIntroQuestion,
  ]);

  useEffect(
    () => () => {
      if (introDismissTimerRef.current) {
        window.clearTimeout(introDismissTimerRef.current);
      }
      if (introPhaseTimerRef.current) {
        window.clearTimeout(introPhaseTimerRef.current);
      }
      if (introPrimaryTimerRef.current) {
        window.clearTimeout(introPrimaryTimerRef.current);
      }
      if (introQuestionTimerRef.current) {
        window.clearTimeout(introQuestionTimerRef.current);
      }
      if (coldOpenWheelGestureResetTimerRef.current) {
        window.clearTimeout(coldOpenWheelGestureResetTimerRef.current);
      }
    },
    [],
  );

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
    const pendingIds = pendingGraphRestoreIdsRef.current;
    if (!pendingIds) return;
    const indexByGraphId = new Map<string, number>();
    pagedGraphs.forEach((entry, index) => {
      indexByGraphId.set(entry.graph.id, index);
    });
    const matchedIndexes = pendingIds
      .map((id) => indexByGraphId.get(id))
      .filter((index): index is number => index !== undefined);
    const nextPage =
      matchedIndexes.length > 0
        ? Math.floor(matchedIndexes[0] / Math.max(1, graphsPerPage))
        : 0;
    setGraphPage(Math.max(0, Math.min(maxGraphPage, nextPage)));
    pendingGraphRestoreIdsRef.current = null;
    wheelAccumRef.current = 0;
    wheelLastEventTsRef.current = 0;
    wheelGestureConsumedRef.current = false;
    wheelGestureConsumedAtRef.current = 0;
  }, [graphsPerPage, maxGraphPage, pagedGraphs]);

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
        wheelGestureConsumedAtRef.current = 0;
        wheelAccumRef.current = 0;
      }, wheelGestureGapMs);
      if (wheelGestureConsumedRef.current) {
        if (now - wheelGestureConsumedAtRef.current < wheelSustainRepeatMs) {
          return;
        }
        // Allow another step only on a fresh strong impulse.
        // This blocks trackpad momentum from cascading through many pages.
        if (Math.abs(e.deltaY) < wheelRepeatKickThreshold) {
          return;
        }
        wheelGestureConsumedRef.current = false;
        wheelAccumRef.current = 0;
      }
      wheelAccumRef.current += e.deltaY;
      if (Math.abs(wheelAccumRef.current) < wheelStepThreshold) return;
      const changed = goGraphPage(wheelAccumRef.current > 0 ? 1 : -1);
      wheelAccumRef.current = 0;
      if (changed) {
        wheelGestureConsumedRef.current = true;
        wheelGestureConsumedAtRef.current = now;
      }
    },
    [
      goGraphPage,
      wheelGestureGapMs,
      wheelRepeatKickThreshold,
      wheelStepThreshold,
      wheelSustainRepeatMs,
    ],
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

  const handlePanelTouchStart = useCallback(
    (e: React.TouchEvent<HTMLElement>) => {
      if (e.touches.length !== 1) {
        touchStartYRef.current = null;
        touchStartXRef.current = null;
        return;
      }
      touchStartYRef.current = e.touches[0].clientY;
      touchStartXRef.current = e.touches[0].clientX;
    },
    [],
  );

  const handlePanelTouchMove = useCallback(
    (e: React.TouchEvent<HTMLElement>) => {
      if (touchStartYRef.current === null || touchStartXRef.current === null) {
        return;
      }
      if (e.touches.length !== 1) return;
      if (
        typeof window !== "undefined" &&
        !window.matchMedia("(max-width: 900px)").matches
      ) {
        return;
      }
      const deltaY = e.touches[0].clientY - touchStartYRef.current;
      const deltaX = e.touches[0].clientX - touchStartXRef.current;
      if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 8) {
        // Prevent native scrolling while a horizontal swipe gesture is in progress.
        e.preventDefault();
      }
    },
    [],
  );

  const handlePanelTouchEnd = useCallback(
    (e: React.TouchEvent<HTMLElement>) => {
      if (touchStartYRef.current === null || touchStartXRef.current === null) {
        return;
      }
      const touch = e.changedTouches[0];
      if (!touch) {
        touchStartYRef.current = null;
        touchStartXRef.current = null;
        return;
      }
      const deltaY = touch.clientY - touchStartYRef.current;
      const deltaX = touch.clientX - touchStartXRef.current;
      touchStartYRef.current = null;
      touchStartXRef.current = null;
      if (
        typeof window !== "undefined" &&
        !window.matchMedia("(max-width: 900px)").matches
      ) {
        return;
      }
      if (deltaY > 0 && Math.abs(deltaY) > Math.abs(deltaX)) {
        if (deltaY >= touchClosePanelThresholdPx) {
          setPanelOpen(false);
        }
        return;
      }
      if (Math.abs(deltaX) < touchSwipeThresholdPx) return;
      if (Math.abs(deltaX) <= Math.abs(deltaY)) return;
      goGraphPage(deltaX < 0 ? 1 : -1);
    },
    [goGraphPage, touchClosePanelThresholdPx, touchSwipeThresholdPx],
  );

  const handlePanelTouchCancel = useCallback(() => {
    touchStartYRef.current = null;
    touchStartXRef.current = null;
  }, []);

  const locationLabel =
    selectedLocation?.label ?? resp?.location.place.label ?? "";
  const titleLocationLabel = locationLabel || "this location";
  const populationText = formatPopulation(selectedLocation?.population);
  const coldOpenWarmingText =
    defaultTemperatureUnitForLocale() === "F" ? "+1.9°F" : "+1.1°C";
  const showIntroMap = !introVisible || introPromptVisible;
  return (
    <main
      className={`${styles.app} ${introVisible ? styles.appIntro : styles.appReady}`}
      onPointerDownCapture={handleColdOpenPointerDownCapture}
      onTouchStartCapture={handleColdOpenInteractionCapture}
      onWheelCapture={handleColdOpenWheelCapture}
    >
      <div
        className={`${styles.map} ${showIntroMap ? styles.mapVisible : styles.mapHidden}`}
        onPointerDownCapture={keepPanelFocused}
      >
        <MapLibreGlobe
          panelOpen={panelOpen}
          focusLocation={picked}
          layerOptions={mapLayers}
          activeLayerId={activeLayerId || null}
          onLayerChange={(layerId) => setActiveLayerId(layerId)}
          onLayerMenuOpen={() => setSuggestOpen(false)}
          onPick={(la, lo) => {
            void handlePick(la, lo);
          }}
          onHome={() => {
            setPanelOpen(false);
            setPicked(null);
          }}
          enablePick={!introVisible}
        />
      </div>

      {introVisible ? (
        <div
          className={`${styles.coldOpenOverlay} ${introFading ? styles.coldOpenOverlayFading : ""}`}
          aria-hidden="true"
        >
          <div className={styles.coldOpenMessageStack}>
            <h1
              className={`${styles.coldOpenMessage} ${styles.coldOpenMessagePrimary} ${
                introPromptVisible ? styles.coldOpenMessagePrimaryHidden : ""
              }`}
            >
              <span
                className={`${styles.coldOpenPrimaryLine} ${
                  introPrimaryVisible ? styles.coldOpenPrimaryLineVisible : ""
                }`}
              >
                Human activities have caused{" "}
                <span className={styles.coldOpenMessageAccent}>
                  {coldOpenWarmingText}
                </span>{" "}
                of global warming since 1850-1900.
              </span>
              <span
                className={`${styles.coldOpenQuestion} ${
                  introQuestionVisible ? styles.coldOpenQuestionVisible : ""
                }`}
              >
                What does this mean{" "}
                <span className={styles.coldOpenMessageAccent}>for you</span> ?
              </span>
            </h1>
            <h1
              className={`${styles.coldOpenMessage} ${
                introPromptVisible ? styles.coldOpenMessageSecondaryVisible : ""
              }`}
            >
              <span className={styles.coldOpenMessageAccent}>Ple</span>
              <span className={styles.coldOpenMessageDark}>
                ase select locat
              </span>
              <span className={styles.coldOpenMessageAccent}>ion</span>
            </h1>
          </div>
        </div>
      ) : null}

      <div className={styles.searchOverlay}>
        <div ref={searchWrapRef} className={styles.searchWrap}>
          <input
            className={styles.searchInput}
            placeholder="Type a city name..."
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
        </div>
        {suggestLoading ? (
          <div className={styles.searchStatus}>Searching...</div>
        ) : null}
        {suggestError ? (
          <div className={styles.searchError}>{suggestError}</div>
        ) : null}
      </div>
      {!introVisible ? (
        <div className={styles.sourcesLinkDock}>
          <button
            type="button"
            className={styles.searchMetaLink}
            onClick={() => setAboutOpenWithUrl(true)}
          >
            About
          </button>
          <button
            type="button"
            className={styles.searchMetaLink}
            onClick={() => setSourcesOpenWithUrl(true)}
          >
            Sources
          </button>
        </div>
      ) : null}

      {aboutOpen ? (
        <AboutOverlay
          onClose={() => setAboutOpenWithUrl(false)}
          releaseLabel={sessionRelease ?? requestedRelease}
        />
      ) : null}

      {sourcesOpen ? (
        <SourcesOverlay onClose={() => setSourcesOpenWithUrl(false)} />
      ) : null}

      <aside
        ref={panelRef}
        className={`${styles.locationPanel} ${panelOpen ? styles.locationPanelOpen : ""}`}
        aria-live="polite"
        tabIndex={0}
        onWheel={handlePanelWheel}
        onKeyDown={handlePanelKeyDown}
        onTouchStart={handlePanelTouchStart}
        onTouchMove={handlePanelTouchMove}
        onTouchEnd={handlePanelTouchEnd}
        onTouchCancel={handlePanelTouchCancel}
      >
        {stepCount >= 2 ? (
          <div
            className={styles.panelSteps}
            role="tablist"
            aria-label="Graph steps"
          >
            {Array.from({ length: stepCount }, (_, idx) => (
              <button
                key={`step-dot-${idx}`}
                type="button"
                role="tab"
                aria-label={`Go to step ${idx + 1} of ${stepCount}`}
                aria-selected={idx === graphPage}
                onClick={() => {
                  const changed = goToGraphPage(idx);
                  if (!changed) return;
                  wheelAccumRef.current = 0;
                  wheelGestureConsumedRef.current = false;
                  wheelGestureConsumedAtRef.current = 0;
                }}
                className={`${styles.panelStepDot} ${
                  idx === graphPage ? styles.panelStepDotActive : ""
                }`}
              />
            ))}
          </div>
        ) : null}

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
                    queueGraphRestoreFromVisible();
                    setUnit("C");
                    void loadPanel(lat, lon, "C");
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
                    queueGraphRestoreFromVisible();
                    setUnit("F");
                    void loadPanel(lat, lon, "F");
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
              <svg
                className={styles.panelCloseIcon}
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path d="M6 6L18 18" />
                <path d="M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div className={styles.panelTitleWrap}>
            <div>
              <div className={styles.panelTitleLine}>
                <h2 className={styles.panelTitle}>
                  {panelLoadError ? (
                    <span className={styles.panelTitleTempAccent}>
                      Couldn’t load climate data.
                    </span>
                  ) : typeof tempHeadline?.value === "number" &&
                    Number.isFinite(tempHeadline.value) ? (
                    <>
                      <span className={styles.panelTitleSmall}>In</span>{" "}
                      {titleLocationLabel},{" "}
                      <span className={styles.panelTitleSmall}>
                        human activities have caused{" "}
                      </span>
                      <span className={styles.panelTitleTempAccent}>
                        {formatHeadlineDelta(tempHeadline.value, unit)}
                      </span>
                      <span className={styles.panelTitleSmall}>
                        {" "}
                        since 1850-1900.
                      </span>
                    </>
                  ) : panelLoading ? (
                    <span>Loading climate data...</span>
                  ) : (
                    <span>Pick a location to load climate data.</span>
                  )}
                  {!panelLoadError ? (
                    <InfoBubble
                      label="Panel title information"
                      text="Local warming since pre-industrial is estimated as: observed local warming since 1979-2000, plus a model-based offset from 1850-1900 to 1979-2000."
                    />
                  ) : null}
                </h2>
              </div>
              {populationText ? (
                <p className={styles.panelPopulation}>
                  Population: {populationText}
                </p>
              ) : null}
              {panelLoadError ? (
                <div className={styles.panelInlineError}>
                  <button
                    type="button"
                    className={styles.panelRetryButton}
                    onClick={async () => {
                      if (panelRetrying) return;
                      queueGraphRestoreFromVisible();
                      setPanelRetrying(true);
                      await loadPanel(
                        lat,
                        lon,
                        unit,
                        selectedGeonameidForPanel,
                      );
                      setPanelRetrying(false);
                    }}
                  >
                    {panelRetrying ? "Retrying..." : "Retry"}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div ref={panelViewportRef} className={styles.panelViewport}>
          {graphSlots.map((entry, slotIndex) =>
            entry ? (
              <GraphCard
                key={`slot-${slotIndex}`}
                graph={entry.graph}
                data={entry.data}
                series={resp?.series ?? {}}
                unit={unit}
                stepIndex={graphStepById[entry.graph.id] ?? 0}
                onStepIndexChange={handleGraphStepChange}
              />
            ) : null,
          )}
        </div>
      </aside>
    </main>
  );
}
