"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./story.module.css";

type SeriesPayload = { x: string[]; y: (number | null)[]; unit?: string };

type Daily = { date: string; value: number }[];

type PanelData = {
  label: string;
  series: Record<string, Daily>;
};

/**
 * A date span to mark on one of the panel's charts, so the window chosen on
 * the map can be found in the place's own daily record.
 */
export type PanelHighlight = {
  /** Which chart it belongs to; the others are drawn unmarked. */
  seriesKey: string;
  /** Inclusive ISO dates. */
  from: string;
  to: string;
  /** Which accent to mark it in; defaults to the heat tone. */
  tone?: "heat" | "rain";
};

/** One mini chart in the panel, drawn from one series of the /panel payload. */
export type PanelChartSpec = {
  /** Key in the /panel `series` map, e.g. "t2m_daily_mean". */
  seriesKey: string;
  /** Subtitle above the chart. */
  title: string;
  kind?: "line" | "bar";
  /** Appended to values in the tooltip and axis, e.g. "°" or " mm". */
  unit?: string;
  /** Pin the axis floor to zero (rainfall). */
  fromZero?: boolean;
};

const DEFAULT_CHARTS: PanelChartSpec[] = [
  {
    seriesKey: "t2m_daily_mean",
    title: "Daily mean temperature",
    kind: "line",
    unit: "°",
  },
];

type Props = {
  apiBase: string;
  release: string;
  lat: number;
  lon: number;
  /** Only plot days on/after this ISO date (omit to plot the whole series). */
  fromDate?: string;
  /** Only plot days on/before this ISO date. */
  toDate?: string;
  /** Period shown in the subtitle, e.g. "2026". */
  periodLabel?: string;
  /** Span to mark on the chart whose seriesKey it names. */
  highlight?: PanelHighlight | null;
  /** Charts to draw, top to bottom. Defaults to the daily mean temperature. */
  charts?: PanelChartSpec[];
  onClose: () => void;
};

const CHART_W = 320;
const CHART_H = 150;
const PAD_L = 38;
const PAD_R = 10;
const PAD_T = 14;
const PAD_B = 22;

async function fetchDaily(
  apiBase: string,
  release: string,
  lat: number,
  lon: number,
  keys: string[],
  fromDate: string | undefined,
  toDate: string | undefined,
  signal: AbortSignal,
): Promise<PanelData> {
  const url = `${apiBase}/api/v/${encodeURIComponent(release)}/panel?lat=${lat}&lon=${lon}&unit=C`;
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  const place = data.location?.place ?? {};
  const label: string =
    place.label ||
    [place.name, place.country_code].filter(Boolean).join(", ") ||
    `${lat.toFixed(1)}°, ${lon.toFixed(1)}°`;
  const series: Record<string, Daily> = {};
  for (const key of keys) {
    const payload: SeriesPayload | undefined = data.series?.[key];
    const daily: Daily = [];
    if (payload?.x && payload?.y) {
      for (let i = 0; i < payload.x.length; i++) {
        const d = payload.x[i];
        const v = payload.y[i];
        if (
          typeof v === "number" &&
          (!fromDate || d >= fromDate) &&
          (!toDate || d <= toDate)
        ) {
          daily.push({ date: d, value: v });
        }
      }
    }
    series[key] = daily;
  }
  return { label, series };
}

function niceTicks(
  lo: number,
  hi: number,
): { min: number; max: number; ticks: number[] } {
  const span = hi - lo;
  const step = span > 28 ? 10 : span > 12 ? 5 : span > 5 ? 2 : 1;
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let t = min; t <= max + 0.001; t += step) ticks.push(t);
  return { min, max, ticks };
}

function shortDate(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return `${d.getDate()} ${d.toLocaleString("en", { month: "short" })}`;
}

function MiniChart({
  daily,
  kind = "line",
  unit = "",
  fromZero = false,
  ariaLabel,
  highlight,
}: {
  daily: Daily;
  kind?: "line" | "bar";
  unit?: string;
  fromZero?: boolean;
  ariaLabel: string;
  highlight?: PanelHighlight | null;
}) {
  const values = daily.map((d) => d.value);
  let peakI = 0;
  for (let i = 1; i < values.length; i++)
    if (values[i] > values[peakI]) peakI = i;
  const [hover, setHover] = useState<number>(peakI);

  if (daily.length < 2) return null;
  const dataMin = fromZero ? 0 : Math.min(...values);
  const dataMax = Math.max(...values);
  const { min, max, ticks } = niceTicks(dataMin, dataMax);
  const range = max - min || 1;
  const plotW = CHART_W - PAD_L - PAD_R;
  const plotH = CHART_H - PAD_T - PAD_B;
  const xOf = (i: number) => PAD_L + (i / (daily.length - 1)) * plotW;
  const yOf = (v: number) => PAD_T + (1 - (v - min) / range) * plotH;
  const barW = Math.max(0.8, plotW / daily.length - 0.4);

  const linePath = daily
    .map(
      (d, i) =>
        `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(d.value).toFixed(1)}`,
    )
    .join(" ");

  // month ticks (first day of each month present)
  const monthTicks: { i: number; label: string }[] = [];
  let lastMonth = "";
  daily.forEach((d, i) => {
    const mo = d.date.slice(0, 7);
    if (mo !== lastMonth) {
      lastMonth = mo;
      monthTicks.push({
        i,
        label: new Date(d.date + "T00:00:00").toLocaleString("en", {
          month: "short",
        }),
      });
    }
  });

  // The window may fall partly outside the plotted range, so it is clamped to
  // the days actually drawn rather than skipped.
  let band: { x: number; w: number } | null = null;
  if (highlight) {
    const first = daily.findIndex((d) => d.date >= highlight.from);
    let last = -1;
    for (let i = daily.length - 1; i >= 0; i--) {
      if (daily[i].date <= highlight.to) {
        last = i;
        break;
      }
    }
    if (first !== -1 && last !== -1 && last >= first) {
      const x0 = xOf(first);
      const x1 = xOf(last);
      band = { x: x0, w: Math.max(1.5, x1 - x0) };
    }
  }

  const hv = daily[hover];
  const hx = xOf(hover);
  const hy = yOf(hv.value);
  const tipText = `${hv.value.toFixed(1)}${unit} · ${shortDate(hv.date)}`;
  const tipW = tipText.length * 5.2 + 12;
  const tipX = Math.max(2, Math.min(CHART_W - tipW - 2, hx - tipW / 2));
  const tipY = Math.max(2, hy - 24);

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * CHART_W;
    const i = Math.round(((vbX - PAD_L) / plotW) * (daily.length - 1));
    setHover(Math.max(0, Math.min(daily.length - 1, i)));
  };

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      className={styles.panelChart}
      role="img"
      aria-label={ariaLabel}
      onPointerMove={onMove}
      onPointerLeave={() => setHover(peakI)}
    >
      {band ? (
        <rect
          x={band.x}
          y={PAD_T}
          width={band.w}
          height={plotH}
          className={
            highlight?.tone === "rain" ? styles.panelBandRain : styles.panelBand
          }
        />
      ) : null}
      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={PAD_L}
            x2={CHART_W - PAD_R}
            y1={yOf(t)}
            y2={yOf(t)}
            className={styles.panelGrid}
          />
          <text
            x={PAD_L - 5}
            y={yOf(t) + 3}
            textAnchor="end"
            className={styles.panelAx}
          >
            {t}
            {unit.trim()}
          </text>
        </g>
      ))}
      {kind === "bar" ? (
        daily.map((d, i) => (
          <rect
            key={d.date}
            x={xOf(i) - barW / 2}
            y={yOf(d.value)}
            width={barW}
            height={Math.max(0, yOf(min) - yOf(d.value))}
            className={styles.panelBar}
          />
        ))
      ) : (
        <path d={linePath} className={styles.panelLine} />
      )}

      {/* hover guide + point */}
      <line
        x1={hx}
        x2={hx}
        y1={PAD_T}
        y2={PAD_T + plotH}
        className={styles.panelGuide}
      />
      <circle
        cx={hx}
        cy={hy}
        r={2.8}
        className={kind === "bar" ? styles.panelPeakBar : styles.panelPeak}
      />
      <g>
        <rect
          x={tipX}
          y={tipY}
          width={tipW}
          height={16}
          rx={2}
          className={styles.panelTipBox}
        />
        <text
          x={tipX + tipW / 2}
          y={tipY + 8.5}
          textAnchor="middle"
          className={styles.panelTipText}
        >
          {tipText}
        </text>
      </g>

      {monthTicks.map((t) => (
        <text
          key={t.label}
          x={xOf(t.i)}
          y={CHART_H - 6}
          textAnchor="middle"
          className={styles.panelAx}
        >
          {t.label}
        </text>
      ))}
    </svg>
  );
}

export default function LocationPanel({
  apiBase,
  release,
  lat,
  lon,
  fromDate,
  toDate,
  periodLabel,
  charts = DEFAULT_CHARTS,
  highlight,
  onClose,
}: Props) {
  const [data, setData] = useState<PanelData | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const reqId = useRef(0);
  const keys = charts.map((c) => c.seriesKey).join(",");

  useEffect(() => {
    const id = ++reqId.current;
    const controller = new AbortController();
    fetchDaily(
      apiBase,
      release,
      lat,
      lon,
      keys.split(","),
      fromDate,
      toDate,
      controller.signal,
    )
      .then((d) => {
        if (id !== reqId.current) return;
        setData(d);
        const any = Object.values(d.series).some((s) => s.length >= 2);
        setStatus(any ? "ok" : "error");
      })
      .catch(() => {
        if (id !== reqId.current) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [apiBase, release, lat, lon, fromDate, toDate, keys]);

  return (
    <aside className={styles.panel}>
      <button
        type="button"
        className={styles.panelClose}
        onClick={onClose}
        aria-label="Close location panel"
      >
        ×
      </button>
      <div className={styles.panelLabel}>
        {data?.label ?? "Selected location"}
      </div>
      {status === "loading" && <div className={styles.panelMsg}>Loading…</div>}
      {status === "error" && (
        <div className={styles.panelMsg}>No daily data for this location.</div>
      )}
      {status === "ok" &&
        data &&
        charts.map((c) => {
          const daily = data.series[c.seriesKey] ?? [];
          if (daily.length < 2) return null;
          return (
            <div key={c.seriesKey}>
              <div className={styles.panelSub}>
                {c.title}
                {periodLabel ? ` · ${periodLabel}` : ""}
              </div>
              <MiniChart
                daily={daily}
                kind={c.kind}
                unit={c.unit}
                fromZero={c.fromZero}
                ariaLabel={`${c.title} at the selected location`}
                highlight={
                  highlight && highlight.seriesKey === c.seriesKey
                    ? highlight
                    : null
                }
              />
            </div>
          );
        })}
    </aside>
  );
}
