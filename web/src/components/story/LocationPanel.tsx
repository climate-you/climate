"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./story.module.css";

type SeriesPayload = { x: string[]; y: (number | null)[]; unit?: string };

type PanelData = {
  label: string;
  daily: { date: string; value: number }[];
};

type Props = {
  apiBase: string;
  release: string;
  lat: number;
  lon: number;
  /** Only plot days on/after this ISO date (omit to plot the whole series). */
  fromDate?: string;
  /** Period shown in the subtitle, e.g. "2026". */
  periodLabel?: string;
  onClose: () => void;
};

const CHART_W = 320;
const CHART_H = 150;
const PAD_L = 34;
const PAD_R = 10;
const PAD_T = 14;
const PAD_B = 22;

async function fetchDaily(
  apiBase: string,
  release: string,
  lat: number,
  lon: number,
  fromDate: string | undefined,
  signal: AbortSignal,
): Promise<PanelData> {
  const url = `${apiBase}/api/v/${encodeURIComponent(release)}/panel?lat=${lat}&lon=${lon}&unit=C`;
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  const series: SeriesPayload | undefined = data.series?.t2m_daily_mean;
  const place = data.location?.place ?? {};
  const label: string =
    place.label ||
    [place.name, place.country_code].filter(Boolean).join(", ") ||
    `${lat.toFixed(1)}°, ${lon.toFixed(1)}°`;
  const daily: { date: string; value: number }[] = [];
  if (series?.x && series?.y) {
    for (let i = 0; i < series.x.length; i++) {
      const d = series.x[i];
      const v = series.y[i];
      if (typeof v === "number" && (!fromDate || d >= fromDate)) {
        daily.push({ date: d, value: v });
      }
    }
  }
  return { label, daily };
}

function niceTicks(
  lo: number,
  hi: number,
): { min: number; max: number; ticks: number[] } {
  const span = hi - lo;
  const step = span > 28 ? 10 : span > 12 ? 5 : 2;
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

function MiniChart({ daily }: { daily: { date: string; value: number }[] }) {
  const values = daily.map((d) => d.value);
  let peakI = 0;
  for (let i = 1; i < values.length; i++)
    if (values[i] > values[peakI]) peakI = i;
  const [hover, setHover] = useState<number>(peakI);

  if (daily.length < 2) return null;
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const { min, max, ticks } = niceTicks(dataMin, dataMax);
  const range = max - min || 1;
  const plotW = CHART_W - PAD_L - PAD_R;
  const plotH = CHART_H - PAD_T - PAD_B;
  const xOf = (i: number) => PAD_L + (i / (daily.length - 1)) * plotW;
  const yOf = (v: number) => PAD_T + (1 - (v - min) / range) * plotH;

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

  const hv = daily[hover];
  const hx = xOf(hover);
  const hy = yOf(hv.value);
  const tipText = `${hv.value.toFixed(1)}° · ${shortDate(hv.date)}`;
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
      aria-label="Daily mean temperature at the selected location"
      onPointerMove={onMove}
      onPointerLeave={() => setHover(peakI)}
    >
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
            {t}°
          </text>
        </g>
      ))}
      <path d={linePath} className={styles.panelLine} />

      {/* hover guide + point */}
      <line
        x1={hx}
        x2={hx}
        y1={PAD_T}
        y2={PAD_T + plotH}
        className={styles.panelGuide}
      />
      <circle cx={hx} cy={hy} r={2.8} className={styles.panelPeak} />
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
  periodLabel,
  onClose,
}: Props) {
  const [data, setData] = useState<PanelData | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const reqId = useRef(0);

  useEffect(() => {
    const id = ++reqId.current;
    const controller = new AbortController();
    fetchDaily(apiBase, release, lat, lon, fromDate, controller.signal)
      .then((d) => {
        if (id !== reqId.current) return;
        setData(d);
        setStatus(d.daily.length >= 2 ? "ok" : "error");
      })
      .catch(() => {
        if (id !== reqId.current) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [apiBase, release, lat, lon, fromDate]);

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
      <div className={styles.panelSub}>
        Daily mean temperature{periodLabel ? ` · ${periodLabel}` : ""}
      </div>
      {status === "loading" && <div className={styles.panelMsg}>Loading…</div>}
      {status === "error" && (
        <div className={styles.panelMsg}>No daily data for this location.</div>
      )}
      {status === "ok" && data && <MiniChart daily={data.daily} />}
    </aside>
  );
}
