export type TimeDuration = {
  value: number;
  unit: "points" | "days" | "months" | "years";
};

export type TimeRange = {
  start?: number | string;
  end?: number | string;
  last?: TimeDuration;
  offset?: TimeDuration;
};

export type SeriesPayload = {
  x: Array<number | string>;
  y: (number | null)[];
  unit?: string | null;
  label?: string | null;
  shortLabel?: string | null;
  ui?: { role?: "raw" | "mean" | "trend" | "category" } | null;
  style?: { type?: "line" | "bar"; color?: string; accent_color?: string; stack?: string } | null;
};

export type GraphPayload = {
  id: string;
  title: string;
  ui?: {
    info_text?: string | null;
    chart_mode?: "temperature_line" | "hot_days_combo" | "stacked_bar" | "comparison_bar";
    axis_title_mode?: "year" | "date";
  } | null;
  series_keys: string[];
  source?: string | null;
  caption?: string | null;
  error?: string | null;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
  time_range?: TimeRange;
};

export type ChartRow = {
  x: number | string;
  [key: string]: number | string | null | undefined;
};

export type GlobeLegendSpec = {
  colors: string[];
  ticks: string[];
  showTemperatureUnitToggle: boolean;
};

type LayerLegendUnit = "temperature" | "score" | "unknown";

function parseLegendColors(
  legend: Record<string, unknown> | null | undefined,
): string[] | null {
  const colors = legend?.colors;
  if (!Array.isArray(colors)) return null;
  const normalized = colors.filter(
    (c): c is string => typeof c === "string" && c.trim().length > 0,
  );
  return normalized.length > 0 ? normalized : null;
}

function parseLegendScaleBounds(
  legend: Record<string, unknown> | null | undefined,
): { vmin: number; vmax: number } | null {
  const vmin = legend?.vmin;
  const vmax = legend?.vmax;
  if (typeof vmin !== "number" || !Number.isFinite(vmin)) return null;
  if (typeof vmax !== "number" || !Number.isFinite(vmax)) return null;
  if (vmax <= vmin) return null;
  return { vmin, vmax };
}

function buildTicksFromBounds(
  bounds: { vmin: number; vmax: number } | null,
): number[] | null {
  if (!bounds) return null;
  const { vmin, vmax } = bounds;
  const step = (vmax - vmin) / 4;
  if (!Number.isFinite(step) || step <= 0) return null;
  return Array.from({ length: 5 }, (_, idx) =>
    Number((vmax - idx * step).toFixed(2)),
  );
}

function formatTemperatureLegendTick(valueC: number, unit: "C" | "F"): string {
  if (unit === "F") {
    const valueF = valueC * (9 / 5);
    const rounded = Math.round(valueF);
    const sign = rounded > 0 ? "+" : "";
    return `${sign}${rounded}`;
  }
  const sign = valueC > 0 ? "+" : "";
  return `${sign}${valueC}`;
}

function formatScoreLegendTick(value: number): string {
  if (!Number.isFinite(value)) return "";
  const rounded = Number(value.toFixed(2));
  if (Number.isInteger(rounded)) return `${rounded}`;
  if (Math.abs(rounded) >= 1) return rounded.toFixed(1).replace(/\.0$/, "");
  return rounded.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function layerLegendUnit(
  layer: {
    unit?: string | null;
  } | null,
): LayerLegendUnit {
  const raw = String(layer?.unit ?? "")
    .trim()
    .toLowerCase();
  if (raw === "temperature") return "temperature";
  if (raw === "score") return "score";
  return "unknown";
}

export function legendForLayer(
  layer: {
    id: string;
    unit?: string | null;
    legend?: Record<string, unknown> | null;
  } | null,
  temperatureUnit: "C" | "F",
): GlobeLegendSpec | null {
  if (!layer) return null;
  const colors = parseLegendColors(layer.legend);
  const bounds = parseLegendScaleBounds(layer.legend);
  const ticks = buildTicksFromBounds(bounds);
  if (!colors || !ticks) return null;
  const legendUnit = layerLegendUnit(layer);
  const showTemperatureUnitToggle = legendUnit === "temperature";
  return {
    colors,
    ticks: ticks.map((value) =>
      showTemperatureUnitToggle
        ? formatTemperatureLegendTick(value, temperatureUnit)
        : formatScoreLegendTick(value),
    ),
    showTemperatureUnitToggle,
  };
}

export function mergeSeries(
  series: Record<string, SeriesPayload>,
  keys: string[],
): ChartRow[] {
  const rows = new Map<string, ChartRow>();

  for (const k of keys) {
    const s = series[k];
    if (!s) continue;
    for (let i = 0; i < s.x.length; i++) {
      const x = s.x[i];
      const key = String(x);
      const row = rows.get(key) ?? { x };
      row[k] = s.y[i];
      rows.set(key, row);
    }
  }

  return Array.from(rows.values()).sort((a, b) =>
    String(a.x).localeCompare(String(b.x)),
  );
}

export function isYearValue(n: number): boolean {
  return n >= 1000 && n <= 3000;
}

function parseAxisValue(v: unknown): { numeric?: number; timestamp?: number } {
  if (typeof v === "number" && Number.isFinite(v)) {
    if (isYearValue(v)) {
      const ts = new Date(`${Math.trunc(v)}-01-01`).getTime();
      return { numeric: v, timestamp: Number.isFinite(ts) ? ts : undefined };
    }
    return { numeric: v };
  }
  const n = Number(v);
  if (Number.isFinite(n) && String(v).trim() !== "") {
    if (isYearValue(n)) {
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

export function sliceRowsByTimeRange(
  rows: ChartRow[],
  range?: TimeRange,
): ChartRow[] {
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

export function inBbox(
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
): boolean {
  if (!bbox) return false;
  const latOk = lat >= bbox.lat_min && lat <= bbox.lat_max;
  const lonOk = lon >= bbox.lon_min && lon <= bbox.lon_max;
  return latOk && lonOk;
}

function fallbackKeyLabel(key: string): string {
  return key.replaceAll("_", " ");
}

export function seriesLabel(
  series: Record<string, SeriesPayload>,
  key: string,
  options?: { preferShort?: boolean },
): string {
  const configuredShort = series[key]?.shortLabel;
  if (
    options?.preferShort &&
    typeof configuredShort === "string" &&
    configuredShort.trim().length > 0
  ) {
    return configuredShort;
  }
  const configured = series[key]?.label;
  if (typeof configured === "string" && configured.trim().length > 0) {
    return configured;
  }
  return fallbackKeyLabel(key);
}

export function seriesRole(
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

export function seriesColor(
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

export function graphChartMode(
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

export function toChartTimestamp(x: number | string): number {
  if (typeof x === "number" && Number.isFinite(x)) {
    const n = Math.trunc(x);
    if (isYearValue(n)) {
      const t = new Date(`${n}-01-01`).getTime();
      return Number.isFinite(t) ? t : Date.now();
    }
    // Distinguish ms timestamps (~1e12) from second timestamps (~1e9).
    if (Math.abs(n) >= 1e11) return n; // already ms
    if (Math.abs(n) >= 1e9) return n * 1000; // seconds → ms
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

export function formatHeadlineDelta(value: number, unit: "C" | "F"): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}º${unit}`;
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

export function formatAxisTitle(graph: GraphPayload, value: unknown): string {
  const asString = String(value ?? "");
  if (graph.ui?.axis_title_mode !== "date") {
    const directYear = Number.parseInt(asString, 10);
    const year =
      Number.isFinite(directYear) && isYearValue(directYear)
        ? directYear
        : new Date(toChartTimestamp(value as number | string)).getUTCFullYear();
    const yearText = Number.isFinite(year) ? String(year) : asString;
    return `Year ${yearText}`;
  }
  const label = formatDateLabel(toChartTimestamp(value as number | string));
  return label || asString;
}

export function formatDayMonthYearLabel(value: number | string): string {
  const date = new Date(toChartTimestamp(value));
  if (!Number.isFinite(date.getTime())) return "";
  const dd = String(date.getUTCDate()).padStart(2, "0");
  const mon = new Intl.DateTimeFormat("en-GB", {
    month: "short",
    timeZone: "UTC",
  }).format(date);
  const yy = String(date.getUTCFullYear()).slice(-2);
  return `${dd} ${mon} ${yy}`;
}

export function formatPopulation(
  value: number | null | undefined,
): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return new Intl.NumberFormat("en-US").format(Math.trunc(value));
}
