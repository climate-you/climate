"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const DEFAULT_API_PORT = 8001;

// Inline style — no external style.json dependency.
// Tiles are inherently external (OSM raster), but the style config is stable.
const MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    },
  },
  layers: [
    {
      id: "osm",
      type: "raster",
      source: "osm",
      paint: { "raster-opacity": 0.55 },
    },
  ],
};

type ClickCell = { lat: number; lon: number; count: number };
type OriginCell = {
  country: string | null;
  lat: number | null;
  lon: number | null;
  count: number;
};
type AdminEvents = { clicks: ClickCell[]; origins: OriginCell[] };
type AdminStatus = {
  app: { version: string; tag: string | null; commit: string | null };
  release: string;
  analytics: { enabled: boolean; db_size_bytes: number | null };
  system: {
    disk_total_bytes: number;
    disk_used_bytes: number;
    disk_free_bytes: number;
    rss_bytes: number;
    cpu_1m_pct: number | null;
    mem_total_bytes: number | null;
    mem_available_bytes: number | null;
  };
};

function toClickGeoJSON(
  clicks: ClickCell[],
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: "FeatureCollection",
    features: clicks.map((c) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [c.lon, c.lat] },
      properties: { count: c.count },
    })),
  };
}

function toOriginGeoJSON(
  origins: OriginCell[],
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: "FeatureCollection",
    features: origins
      .filter((o) => o.lat != null && o.lon != null)
      .map((o) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [o.lon!, o.lat!] },
        properties: { count: o.count, country: o.country ?? "" },
      })),
  };
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function fmtBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`;
  return `${bytes} B`;
}

export default function AdminPage() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [events, setEvents] = useState<AdminEvents | null>(null);
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [healthMs, setHealthMs] = useState<number | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [visibleLayers, setVisibleLayers] = useState({ clicks: true, origins: true });

  const toggleLayer = useCallback((layer: "clicks" | "origins") => {
    setVisibleLayers((prev) => {
      const next = { ...prev, [layer]: !prev[layer] };
      const map = mapRef.current;
      if (map) {
        if (layer === "clicks" && map.getLayer("clicks-heat"))
          map.setLayoutProperty("clicks-heat", "visibility", next.clicks ? "visible" : "none");
        if (layer === "origins" && map.getLayer("origins-circle"))
          map.setLayoutProperty("origins-circle", "visibility", next.origins ? "visible" : "none");
      }
      return next;
    });
  }, []);

  const apiBase = useMemo(() => {
    if (process.env.NEXT_PUBLIC_CLIMATE_API_BASE) {
      return process.env.NEXT_PUBLIC_CLIMATE_API_BASE.replace(/\/+$/, "");
    }
    if (typeof window === "undefined")
      return `http://localhost:${DEFAULT_API_PORT}`;
    return `http://${window.location.hostname}:${DEFAULT_API_PORT}`;
  }, []);

  useEffect(() => {
    const t0 = performance.now();
    fetch(`${apiBase}/healthz`)
      .then((r) => {
        if (r.ok) setHealthMs(performance.now() - t0);
      })
      .catch(() => {});

    fetch(`${apiBase}/api/admin/events`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<AdminEvents>;
      })
      .then(setEvents)
      .catch((e: unknown) =>
        setEventsError(
          e instanceof Error ? e.message : "Failed to load analytics",
        ),
      );
  }, [apiBase]);

  useEffect(() => {
    const fetchStatus = () => {
      fetch(`${apiBase}/api/admin/status`)
        .then((r) => {
          if (!r.ok) return;
          return r.json() as Promise<AdminStatus>;
        })
        .then((s) => s && setStatus(s))
        .catch(() => {});
    };
    fetchStatus();
    const id = setInterval(fetchStatus, 15_000);
    return () => clearInterval(id);
  }, [apiBase]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [0, 20],
      zoom: 1.5,
      attributionControl: false,
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }));
    map.on("load", () => setMapReady(true));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !events) return;

    const clickGeo = toClickGeoJSON(events.clicks);
    const originGeo = toOriginGeoJSON(events.origins);
    const maxCount = Math.max(1, ...events.clicks.map((c) => c.count));

    if (map.getSource("clicks")) {
      (map.getSource("clicks") as maplibregl.GeoJSONSource).setData(clickGeo);
    } else {
      map.addSource("clicks", { type: "geojson", data: clickGeo });
      map.addLayer({
        id: "clicks-heat",
        type: "heatmap",
        source: "clicks",
        paint: {
          "heatmap-weight": [
            "interpolate",
            ["linear"],
            ["get", "count"],
            0, 0,
            maxCount, 1,
          ],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 1, 8, 3],
          "heatmap-color": [
            "interpolate",
            ["linear"],
            ["heatmap-density"],
            0, "rgba(0,0,255,0)",
            0.2, "rgb(0,100,255)",
            0.5, "rgb(0,220,160)",
            0.8, "rgb(255,220,0)",
            1, "rgb(255,80,0)",
          ],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 8, 6, 20],
          "heatmap-opacity": 0.85,
        },
      });
    }

    if (map.getSource("origins")) {
      (map.getSource("origins") as maplibregl.GeoJSONSource).setData(
        originGeo,
      );
    } else {
      map.addSource("origins", { type: "geojson", data: originGeo });
      map.addLayer({
        id: "origins-circle",
        type: "circle",
        source: "origins",
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["get", "count"],
            1, 5,
            50, 20,
          ],
          "circle-color": "rgba(255, 160, 40, 0.7)",
          "circle-stroke-color": "rgba(255, 200, 100, 0.9)",
          "circle-stroke-width": 1,
        },
      });

      const popup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
      });
      map.on("mouseenter", "origins-circle", (e) => {
        map.getCanvas().style.cursor = "pointer";
        const feat = e.features?.[0];
        if (!feat) return;
        const country = feat.properties?.country || "Unknown";
        const count = feat.properties?.count ?? 0;
        const coords = (feat.geometry as GeoJSON.Point).coordinates.slice();
        popup
          .setLngLat([coords[0], coords[1]])
          .setHTML(
            `<strong>${country}</strong><br/>${count} session${count === 1 ? "" : "s"}`,
          )
          .addTo(map);
      });
      map.on("mouseleave", "origins-circle", () => {
        map.getCanvas().style.cursor = "";
        popup.remove();
      });
    }
  }, [events, mapReady]);

  const totalClicks = events?.clicks.reduce((s, c) => s + c.count, 0) ?? 0;
  const totalSessions =
    events?.origins.reduce((s, o) => s + o.count, 0) ?? 0;
  const uniqueCountries = events
    ? new Set(events.origins.map((o) => o.country).filter(Boolean)).size
    : 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100dvh",
        background: "#111",
        color: "#eee",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      {/* header */}
      <div
        style={{
          padding: "12px 20px",
          borderBottom: "1px solid #2a2a2a",
          flexShrink: 0,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: 0.3 }}>
          Admin Dashboard
        </span>
      </div>

      {/* status cards */}
      <div
        style={{
          display: "flex",
          gap: 10,
          padding: "10px 14px",
          flexShrink: 0,
          flexWrap: "wrap",
        }}
      >
        <Card title="Backend">
          <Row
            label="Health"
            value={healthMs != null ? `${healthMs.toFixed(0)} ms` : "–"}
            ok={healthMs != null ? healthMs < 500 : undefined}
          />
          {eventsError && <Row label="Events" value={eventsError} ok={false} />}
        </Card>

        <Card title="Version">
          <Row label="App" value={status?.app.version ?? "–"} />
          <Row label="Tag" value={status?.app.tag ?? "–"} />
          <Row
            label="Commit"
            value={status?.app.commit?.slice(0, 8) ?? "–"}
          />
          <Row label="Release" value={status?.release ?? "–"} />
        </Card>

        <Card title="System">
          <Row
            label="Disk used"
            value={
              status
                ? `${fmtBytes(status.system.disk_used_bytes)} / ${fmtBytes(status.system.disk_total_bytes)}`
                : "–"
            }
          />
          <Row
            label="Disk free"
            value={status ? fmtBytes(status.system.disk_free_bytes) : "–"}
          />
          <Row
            label="RAM (process)"
            value={status ? fmtBytes(status.system.rss_bytes) : "–"}
          />
          {status?.system.mem_total_bytes != null &&
            status.system.mem_available_bytes != null && (
              <Row
                label="RAM (system)"
                value={`${fmtBytes(status.system.mem_total_bytes - status.system.mem_available_bytes)} / ${fmtBytes(status.system.mem_total_bytes)}`}
              />
            )}
          <Row
            label="CPU (1 min avg)"
            value={
              status
                ? status.system.cpu_1m_pct != null
                  ? `${status.system.cpu_1m_pct}%`
                  : "sampling…"
                : "–"
            }
          />
        </Card>

        <Card title="Analytics">
          <Row
            label="Recording"
            value={
              status
                ? status.analytics.enabled
                  ? "enabled"
                  : "disabled"
                : "–"
            }
            ok={status?.analytics.enabled}
          />
          <Row label="Sessions" value={events ? fmt(totalSessions) : "–"} />
          <Row label="Clicks" value={events ? fmt(totalClicks) : "–"} />
          <Row
            label="Countries"
            value={events ? fmt(uniqueCountries) : "–"}
          />
          {status?.analytics.db_size_bytes != null && (
            <Row
              label="DB size"
              value={fmtBytes(status.analytics.db_size_bytes)}
            />
          )}
        </Card>
      </div>

      {/* map */}
      <div ref={mapContainerRef} style={{ flex: 1, minHeight: 0 }} />

      {/* legend */}
      <div
        style={{
          padding: "8px 16px",
          borderTop: "1px solid #2a2a2a",
          display: "flex",
          gap: "24px",
          fontSize: 12,
          color: "#aaa",
          flexShrink: 0,
        }}
      >
        <LegendItem
          color="rgba(255,220,0,0.85)"
          label="Map clicks (heatmap)"
          active={visibleLayers.clicks}
          onClick={() => toggleLayer("clicks")}
        />
        <LegendItem
          color="rgba(255,160,40,0.7)"
          label="User origins (circles)"
          circle
          active={visibleLayers.origins}
          onClick={() => toggleLayer("origins")}
        />
      </div>
    </div>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderRadius: 8,
        padding: "10px 14px",
        minWidth: 160,
        flex: "1 1 160px",
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: "#666",
          textTransform: "uppercase",
          letterSpacing: 1,
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok?: boolean;
}) {
  const valueColor =
    ok === true ? "#4caf50" : ok === false ? "#f66" : "#ddd";
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
        fontSize: 12,
      }}
    >
      <span style={{ color: "#777" }}>{label}</span>
      <span style={{ color: valueColor, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </span>
    </div>
  );
}

function LegendItem({
  color,
  label,
  circle,
  active = true,
  onClick,
}: {
  color: string;
  label: string;
  circle?: boolean;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <span
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        cursor: onClick ? "pointer" : undefined,
        opacity: active ? 1 : 0.35,
        userSelect: "none",
      }}
    >
      <span
        style={{
          width: 12,
          height: 12,
          background: color,
          borderRadius: circle ? "50%" : 2,
          display: "inline-block",
          flexShrink: 0,
        }}
      />
      {label}
    </span>
  );
}
