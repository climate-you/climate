"use client";

import React, { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from "recharts";
import dynamic from "next/dynamic";

const MapPicker = dynamic(() => import("@/components/MapPicker"), {
  ssr: false,
});

type SeriesPayload = { x: any[]; y: (number | null)[]; unit?: string | null };
type GraphAnnotation = { series_key: string; text: string };
type GraphPayload = {
  id: string;
  title: string;
  series_keys: string[];
  annotations?: GraphAnnotation[];
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
  unit: string;
  location: {
    place: { label?: string | null };
    data_cells?: DataCell[];
  };
  panel: {
    id: string;
    title: string;
    graphs: GraphPayload[];
    text_md?: string | null;
  };
  series: Record<string, SeriesPayload>;
};

function mergeSeries(series: Record<string, SeriesPayload>, keys: string[]) {
  // Merge into rows keyed by x (ISO date or year). We assume x values are unique per series.
  const rows = new Map<string, any>();

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

export default function ApiDemoPage() {
  const [lat, setLat] = useState<number>(-20.32556);
  const [lon, setLon] = useState<number>(57.37056);
  const [unit, setUnit] = useState<"C" | "F">("C");
  const [resp, setResp] = useState<PanelResponse | null>(null);
  const cell = resp?.location?.data_cells?.[0] ?? null;

  const graph = resp?.panel.graphs?.[0];
  const data = useMemo(() => {
    if (!resp || !graph) return [];
    return mergeSeries(resp.series, graph.series_keys);
  }, [resp, graph]);

  // update load() to use numbers
  async function load(nextLat = lat, nextLon = lon) {
    const url = `http://localhost:8001/api/v/dev/panel?lat=${encodeURIComponent(nextLat)}&lon=${encodeURIComponent(
      nextLon,
    )}&panel_id=t2m_50y&unit=${unit}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    setResp(await r.json());
  }

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ fontSize: 20, fontWeight: 700 }}>API Demo</h1>
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
            onPick={(la, lo) => {
              setLat(la);
              setLon(lo);
              load(la, lo);
            }}
            picked={{ lat, lon }}
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
          <select value={unit} onChange={(e) => setUnit(e.target.value as any)}>
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
          Place: {resp.location.place.label ?? "—"} • Panel: {resp.panel.title}
        </div>
      )}
      {graph && (
        <div style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600 }}>{graph.title}</h2>

          <div style={{ width: "100%", height: 420 }}>
            <ResponsiveContainer>
              <LineChart
                data={data}
                margin={{ top: 10, right: 20, left: 0, bottom: 10 }}
              >
                <XAxis dataKey="x" minTickGap={24} />
                <YAxis
                  domain={[
                    (dataMin: number) => Math.floor((dataMin - 0.5) * 10) / 10,
                    (dataMax: number) => Math.ceil((dataMax + 0.5) * 10) / 10,
                  ]}
                />
                <Tooltip />
                <Legend />

                {/* Annual mean (grey) */}
                <Line
                  type="monotone"
                  dataKey="t2m_yearly_mean"
                  dot={false}
                  stroke="#999"
                  connectNulls
                />

                {/* 5-year mean (blue) */}
                <Line
                  type="monotone"
                  dataKey="t2m_yearly_mean_5y"
                  dot={false}
                  stroke="#2563eb"
                  connectNulls
                />

                {/* Trend (red) */}
                <Line
                  type="monotone"
                  dataKey="t2m_yearly_trend"
                  dot={false}
                  stroke="#dc2626"
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {graph.annotations?.length ? (
            <div style={{ marginTop: 8, fontSize: 13, opacity: 0.85 }}>
              {graph.annotations.map((a) => (
                <div key={a.series_key}>
                  <code>{a.series_key}</code>: {a.text}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}
      {resp?.panel?.text_md ? (
        <div
          style={{
            marginTop: 12,
            padding: 12,
            border: "1px solid rgba(0,0,0,0.1)",
            borderRadius: 8,
          }}
        >
          {resp.panel.text_md}
        </div>
      ) : null}
    </div>
  );
}
