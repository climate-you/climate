"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from "recharts";
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
  if (typeof v === "number" && Number.isFinite(v)) return { numeric: v };
  const n = Number(v);
  if (Number.isFinite(n) && String(v).trim() !== "") return { numeric: n };
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

const LINE_COLORS = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#7c3aed",
  "#f59e0b",
  "#0ea5e9",
  "#db2777",
  "#65a30d",
  "#9333ea",
  "#334155",
];

function colorForKey(key: string) {
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  const idx = Math.abs(hash) % LINE_COLORS.length;
  return LINE_COLORS[idx];
}

function axisLabel(label: string | null | undefined, unit: "C" | "F") {
  if (!label) return undefined;
  if (unit === "F") {
    return label.replace("°C", "°F");
  }
  return label;
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
  const filteredData = useMemo(
    () => sliceRowsByTimeRange(data, activeRange),
    [data, activeRange],
  );
  const transitionMs = graph.animation?.transition_ms ?? 900;
  const activeSet = useMemo(() => new Set(visibleKeys), [visibleKeys]);

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

      <div style={{ width: "100%", height: 420 }}>
        <ResponsiveContainer>
          <ComposedChart
            data={filteredData}
            margin={{ top: 10, right: 20, left: 0, bottom: 10 }}
          >
            <XAxis
              dataKey="x"
              minTickGap={24}
              label={
                graph.x_axis_label
                  ? {
                      value: graph.x_axis_label,
                      position: "insideBottom",
                      offset: -5,
                    }
                  : undefined
              }
            />
            <YAxis
              domain={[
                (dataMin: number) => Math.floor((dataMin - 0.5) * 10) / 10,
                (dataMax: number) => Math.ceil((dataMax + 0.5) * 10) / 10,
              ]}
              label={
                graph.y_axis_label
                  ? {
                      value: axisLabel(graph.y_axis_label, unit),
                      angle: -90,
                      position: "insideLeft",
                    }
                  : undefined
              }
            />
            <Tooltip />
            <Legend />

            {graph.series_keys.map((key) => {
              const style = series[key]?.style?.type ?? "line";
              const visible = activeSet.has(key);
              if (style === "bar") {
                return (
                  <Bar
                    key={key}
                    dataKey={key}
                    fill={colorForKey(key)}
                    opacity={visible ? 0.65 : 0}
                    isAnimationActive
                    animationDuration={transitionMs}
                    animationEasing="ease-in-out"
                  />
                );
              }
              return (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  dot={false}
                  stroke={colorForKey(key)}
                  strokeOpacity={visible ? 1 : 0}
                  connectNulls
                  isAnimationActive
                  animationDuration={transitionMs}
                  animationEasing="ease-in-out"
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

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
        <button onClick={() => load()} style={{ padding: "6px 10px" }}>
          Load
        </button>
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
