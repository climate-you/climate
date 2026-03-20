import type { EChartsOption } from "echarts";

import { CHART_ANIMATION_DURATION_MS } from "@/lib/explorer/constants";
import {
  formatAxisTitle,
  formatDayMonthYearLabel,
  seriesColor,
  seriesLabel,
  seriesRole,
  toChartTimestamp,
  type ChartRow,
  type GraphPayload,
  type SeriesPayload,
} from "@/lib/explorer/chartData";

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
      axisLabelColor: "#c8c8c8",
      axisLineColor: "#4e4e4e",
      splitLineColor: "rgba(184, 184, 184, 0.28)",
      legendColor: "#ededed",
      tooltipBg: "#171717",
      tooltipBorder: "rgba(255, 255, 255, 0.35)",
      tooltipText: "#f1f1f1",
      barBase: "#7c7c7c",
      barAccent: "#ff5b7f",
      meanLine: "#d4d4d4",
      trendArea: "rgba(255, 91, 127, 0.28)",
      dailyLine: "rgba(206, 206, 206, 0.75)",
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

export function isMobileViewport(): boolean {
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
  preferShort = false,
): string {
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
  if (graph.ui?.chart_mode === "hot_days_combo") {
    return `${seriesLabel(series, trendKey, { preferShort })}: ${sign}${perDecade.toFixed(1)} days/decade`;
  }
  const suffix = `${unit === "F" ? "ºF" : "ºC"}/decade`;
  return `${seriesLabel(series, trendKey, { preferShort })}: ${sign}${perDecade.toFixed(1)}${suffix}`;
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

type BuildOptionArgs = {
  graph: GraphPayload;
  series: Record<string, SeriesPayload>;
  data: ChartRow[];
  visibleKeys: string[];
  transitionMs: number;
  unit: "C" | "F";
};

export function buildHotDaysOption({
  graph,
  series,
  data,
  visibleKeys,
  transitionMs,
  unit,
}: BuildOptionArgs): EChartsOption {
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
  const meanKey = graph.series_keys.find(
    (k) => seriesRole(series, k) === "mean",
  );
  const trendKey = graph.series_keys.find(
    (k) => seriesRole(series, k) === "trend",
  );
  const isVisible = (key: string | undefined) =>
    Boolean(key && visibleKeys.includes(key));
  const barLabel = barKey
    ? seriesLabel(series, barKey, { preferShort: isMobile })
    : "Value";
  const meanLabel = meanKey
    ? seriesLabel(series, meanKey, { preferShort: isMobile })
    : "Mean";
  const trendLabel = trendKey
    ? trendLegendLabel(graph, data, trendKey, series, unit, isMobile)
    : "Trend";
  const barBaseColor = seriesColor(series, barKey, theme.barBase);
  const barAccentColor = theme.barAccent;
  const meanColor = seriesColor(series, meanKey, theme.meanLine);
  const trendColor = seriesColor(series, trendKey, theme.trendArea);
  const valueSuffix =
    String(series[barKey ?? ""]?.unit ?? "").toLowerCase() === "days" ||
    /day/i.test(String(graph.y_axis_label ?? ""))
      ? " days"
      : "";

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
      emphasis: { focus: isMobile ? "none" : "series" },
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
      symbol: "none",
      itemStyle: { color: trendColor },
      lineStyle: { width: 0, color: "rgba(255, 0, 0, 0)" },
      areaStyle: { color: trendColor },
      z: 4,
      animationDurationUpdate: transitionMs,
      emphasis: { focus: isMobile ? "none" : "series" },
    });
  }

  return {
    animationDuration: CHART_ANIMATION_DURATION_MS,
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
            lines.push(`${barLabel}: ${Math.round(v)}${valueSuffix}`);
          }
        }
        const extra = new Map<string, number>();
        rows
          .map((item) => item as { value?: unknown; seriesName?: string })
          .forEach((r) => {
            const label = String(r.seriesName ?? "").trim();
            if (!label || label === trendLabel || label === barLabel) return;
            if (typeof r.value === "number" && Number.isFinite(r.value)) {
              extra.set(label, Number(r.value));
            }
          });
        lines.push(
          ...Array.from(extra.entries()).map(
            ([label, value]) => `${label}: ${Math.round(value)}${valueSuffix}`,
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

export function buildStackedBarOption({
  graph,
  series,
  data,
  visibleKeys,
  transitionMs,
  unit,
}: BuildOptionArgs): EChartsOption {
  const theme = chartThemeTokens();
  const isMobile = isMobileViewport();
  const xValues = data.map((row) => row.x);
  const barKeys = visibleKeys.filter(
    (key) => series[key]?.style?.type === "bar",
  );
  const isDaysStackedBar =
    barKeys.some(
      (key) => String(series[key]?.unit ?? "").toLowerCase() === "days",
    ) || /day/i.test(String(graph.y_axis_label ?? ""));
  const defaultStack = "stacked-bars";
  const chartSeries: NonNullable<EChartsOption["series"]> = barKeys.map(
    (key) => {
      const s = series[key];
      const stackName =
        typeof s?.style?.stack === "string" && s.style.stack.trim().length > 0
          ? s.style.stack
          : defaultStack;
      return {
        name: seriesLabel(series, key, { preferShort: isMobile }),
        type: "bar",
        stack: stackName,
        data: data.map((row) => (row[key] as number | null) ?? null),
        itemStyle: { color: seriesColor(series, key, "") },
        emphasis: { focus: isMobile ? "none" : "series" },
        z: 2,
        animationDurationUpdate: transitionMs,
      };
    },
  );
  const chartScaffold = sharedChartScaffold();

  return {
    animationDuration: CHART_ANIMATION_DURATION_MS,
    animationDurationUpdate: transitionMs,
    animationEasing: "cubicOut",
    ...chartScaffold,
    legend: chartScaffold.legend,
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
          .map((r) => {
            const rawLabel = String(r.seriesName ?? "");
            const label = rawLabel;
            const suffix = isDaysStackedBar ? " days" : "";
            return `${r.marker ?? ""}${label}: ${Math.round(Number(r.value))}${suffix}`;
          });
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

type BuildTemperatureOptionArgs = BuildOptionArgs & {
  xMin?: number;
  xMax?: number;
};

export function buildTemperatureOption({
  graph,
  series,
  data,
  visibleKeys,
  transitionMs,
  unit,
  xMin,
  xMax,
}: BuildTemperatureOptionArgs): EChartsOption {
  const theme = chartThemeTokens();
  const isMobile = isMobileViewport();
  const trendKeys = visibleKeys.filter(
    (key) => seriesRole(series, key) === "trend",
  );
  const isDateBasedView =
    data.length > 0 && /^\d{4}-\d{2}/.test(String(data[0]?.x ?? ""));
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
        ? trendLegendLabel(graph, data, key, series, unit, isMobile)
        : seriesLabel(series, key, { preferShort: isMobile });
      if (isTrend) trendSeriesNames.add(displayName);
      return {
        id: key,
        name: displayName,
        type: "line",
        color: baseColor,
        data: points,
        smooth: isTrend ? false : 0.35,
        showSymbol: false,
        symbol: isTrend ? "none" : undefined,
        connectNulls: true,
        universalTransition: true,
        itemStyle: {
          color: baseColor,
        },
        lineStyle: {
          width: isTrend ? 0 : isMean ? 3 : 1.5,
          color: isTrend ? "transparent" : baseColor,
        },
        z: isTrend ? 1 : isMean ? 3 : 2,
        areaStyle: isTrend ? { color: theme.trendArea } : undefined,
        animationDuration: CHART_ANIMATION_DURATION_MS,
        animationDelay: 0,
        animationDurationUpdate: transitionMs,
        emphasis: { focus: isMobile ? "none" : "series" },
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
    yMin = min - 0.2;
    yMax = max + 0.2;
  }

  return {
    animationDuration: CHART_ANIMATION_DURATION_MS,
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
          ? isDateBasedView
            ? formatDayMonthYearLabel(ts)
            : formatAxisTitle(graph, ts)
          : String(rows[0]?.axisValue ?? "");
        const values = rows
          .map(
            (item) =>
              item as {
                value?: unknown;
                marker?: string;
                seriesName?: string;
                seriesId?: unknown;
              },
          )
          .filter(
            (r) =>
              Array.isArray(r.value) && Number.isFinite(Number(r.value[1])),
          )
          .filter((r) => !trendSeriesNames.has(String(r.seriesName ?? "")));
        const lines = values.map((r) => {
          const key = typeof r.seriesId === "string" ? r.seriesId : "";
          const label = key
            ? seriesLabel(series, key, { preferShort: isMobile })
            : String(r.seriesName ?? "");
          return `${label}: ${Number((r.value as unknown[])[1]).toFixed(1)}${unit === "F" ? "°F" : "°C"}`;
        });
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
