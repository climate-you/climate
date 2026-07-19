"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { MapLayerOption } from "@/components/MapLibreGlobe";
import { useReleaseResolution } from "@/hooks/explorer/useReleaseResolution";
import type { ReleaseLayer } from "@/hooks/explorer/useReleaseResolution";
import {
  type Bbox,
  DEFAULT_MERCATOR_LAT_MAX,
  mercatorAspect,
} from "@/lib/story/mercator";
import DownloadIcon from "@/components/story/DownloadIcon";
import GlobeBoundary from "@/components/story/GlobeBoundary";
import AnomalyMap, { type AnomalyMapHandle } from "@/components/story/AnomalyMap";
import HeatwaveChart from "./HeatwaveChart";
import StoryGlobe, { type GlobeStep } from "@/components/story/StoryGlobe";
import styles from "@/components/story/story.module.css";

const LINES_URL = "/story/europe-lines.json";
// Landscape Europe frame that keeps all 15 cities in view. Displayed at the
// true conformal mercator aspect (~1.63), so the maps are not stretched.
const EUROPE_BBOX: Bbox = { west: -10, south: 37, east: 30, north: 54 };
const MAP_ASPECT = mercatorAspect(EUROPE_BBOX);
// Tighter frame for the globe (span ~21° → zoom 4), centred on Europe.
const GLOBE_BBOX: [number, number, number, number] = [-4, 37, 17, 55];
const ATTRIB_BASE = "Source: ECMWF ERA5 · 2 m air temperature vs 1991–2020";
// YlOrRd palette used by the anomaly maps (0 → +12 °C).
const SCALE_COLORS = [
  "#ffffcc",
  "#ffeda0",
  "#fed976",
  "#feb24c",
  "#fd8d3c",
  "#fc4e2a",
  "#e31a1c",
  "#b10026",
];

type WindowDef = {
  layerId: string;
  dates: string;
  place: string;
  peak: string;
  flabel: string;
  filename: string;
};

const WINDOWS: WindowDef[] = [
  {
    layerId: "heatwave_2026_w1",
    dates: "20–22 June",
    place: "Iberia",
    peak: "Madrid +7.8°C",
    flabel: "20–22 June · Iberia",
    filename: "europe-heat-2026-jun20-22-iberia.png",
  },
  {
    layerId: "heatwave_2026_w2",
    dates: "23–25 June",
    place: "France and Belgium",
    peak: "Paris +13.9°C",
    flabel: "23–25 June · France",
    filename: "europe-heat-2026-jun23-25-france.png",
  },
  {
    layerId: "heatwave_2026_w3",
    dates: "27–29 June",
    place: "Central Europe and Italy",
    peak: "Berlin +10.9°C",
    flabel: "27–29 June · Central Europe",
    filename: "europe-heat-2026-jun27-29-central.png",
  },
];

const DOME2: WindowDef = {
  layerId: "heatwave_2026_w4",
  dates: "6–10 July",
  place: "France and Iberia",
  peak: "Paris +6.8°C",
  flabel: "6–10 July · Second episode",
  filename: "europe-heat-2026-jul6-10-southwest.png",
};

const GLOBE_STEPS: GlobeStep[] = [
  { id: "heatwave_2026_w1", label: "Jun 20–22" },
  { id: "heatwave_2026_w2", label: "Jun 23–25" },
  { id: "heatwave_2026_w3", label: "Jun 27–29" },
  { id: "heatwave_2026_w4", label: "Jul 6–10" },
];

const HERO_INTERVAL_MS = 4200;

type TextureInfo = {
  url: string;
  width: number;
  height: number;
  latMax: number;
};

function useClimateApiBase() {
  return useMemo(() => {
    const DEFAULT_API_PORT = 8001;
    const apiBase = process.env.NEXT_PUBLIC_CLIMATE_API_BASE
      ? process.env.NEXT_PUBLIC_CLIMATE_API_BASE.replace(/\/+$/, "")
      : typeof window === "undefined"
        ? `http://localhost:${DEFAULT_API_PORT}`
        : `http://${window.location.hostname}:${DEFAULT_API_PORT}`;
    const mapAssetBase = process.env.NEXT_PUBLIC_MAP_ASSET_BASE
      ? process.env.NEXT_PUBLIC_MAP_ASSET_BASE.replace(/\/+$/, "")
      : apiBase;
    return { apiBase, mapAssetBase };
  }, []);
}

function toMapLayerOption(
  layer: ReleaseLayer,
  mapAssetBase: string,
  encodedRelease: string,
): MapLayerOption {
  return {
    id: layer.id,
    label: layer.label,
    imageUrl: `${mapAssetBase}/assets/v/${encodedRelease}/${layer.asset_path}`,
    imageWidth: layer.asset_width ?? undefined,
    imageHeight: layer.asset_height ?? undefined,
    projectionBounds: layer.projection_bounds ?? undefined,
    opacity: typeof layer.opacity === "number" ? layer.opacity : 0.8,
    resampling: layer.resampling === "linear" ? "linear" : "nearest",
  };
}

function MapFigure({
  texture,
  def,
  height,
}: {
  texture: TextureInfo;
  def: WindowDef;
  height?: number;
}) {
  const ref = useRef<AnomalyMapHandle>(null);
  return (
    <figure>
      <AnomalyMap
        ref={ref}
        textureUrl={texture.url}
        textureWidth={texture.width}
        textureHeight={texture.height}
        latMax={texture.latMax}
        bbox={EUROPE_BBOX}
        linesUrl={LINES_URL}
        renderHeight={height}
        alt={`Temperature anomaly over Europe, ${def.dates} 2026`}
      />
      <figcaption>
        <span className={styles.capText}>
          <span className={styles.dates}>{def.dates}</span>
          <span className={styles.place}>{def.place}</span>
          <span className={styles.pk}>{def.peak}</span>
        </span>
        <DownloadIcon
          label={`Download ${def.dates} map`}
          onClick={() =>
            ref.current?.download(
              {
                title: `${def.dates} 2026 · ${def.place}`,
                sourceText: ATTRIB_BASE,
                scale: {
                  min: "0°C",
                  max: "+12°C above normal",
                  colors: SCALE_COLORS,
                },
              },
              def.filename,
            )
          }
        />
      </figcaption>
    </figure>
  );
}

export default function HeatwaveStory() {
  const { apiBase, mapAssetBase } = useClimateApiBase();
  const envDefaultReleaseRaw = process.env.NEXT_PUBLIC_RELEASE;
  const { requestedRelease, sessionRelease, releaseLayers } =
    useReleaseResolution(apiBase, envDefaultReleaseRaw);
  const encodedRelease = encodeURIComponent(sessionRelease ?? requestedRelease);

  const layersById = useMemo(() => {
    const map = new Map<string, ReleaseLayer>();
    for (const layer of releaseLayers) map.set(layer.id, layer);
    return map;
  }, [releaseLayers]);

  const textureFor = useMemo(() => {
    return (layerId: string): TextureInfo | null => {
      const layer = layersById.get(layerId);
      if (!layer || !layer.asset_width || !layer.asset_height) return null;
      return {
        url: `${mapAssetBase}/assets/v/${encodedRelease}/${layer.asset_path}`,
        width: layer.asset_width,
        height: layer.asset_height,
        latMax: layer.projection_bounds?.lat_max ?? DEFAULT_MERCATOR_LAT_MAX,
      };
    };
  }, [layersById, mapAssetBase, encodedRelease]);

  const globeLayerOptions = useMemo<MapLayerOption[]>(() => {
    const options: MapLayerOption[] = [{ id: "none", label: "None" }];
    for (const step of GLOBE_STEPS) {
      const layer = layersById.get(step.id);
      if (layer)
        options.push(toMapLayerOption(layer, mapAssetBase, encodedRelease));
    }
    return options;
  }, [layersById, mapAssetBase, encodedRelease]);

  const globeReady = globeLayerOptions.length > 1;

  // Hero crossfade across the three June windows (respecting reduced motion).
  const [heroIndex, setHeroIndex] = useState(0);
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => {
      setHeroIndex((i) => (i + 1) % WINDOWS.length);
    }, HERO_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <article className={styles.story}>
      <header className={styles.hero}>
        <p className={styles.eyebrow}>climate.you · Case study</p>
        <h1>The June–July 2026 heat over Europe</h1>
        <p className={styles.dek}>
          Between mid-June and mid-July 2026, Europe went through two spells of
          extreme heat: a dome that swept across the continent, then a second
          build-up over the southwest. This page shows where the heat sat, how it
          moved, and how far above the seasonal average it was.
        </p>
        <p className={styles.meta}>
          Data: Copernicus ERA5 climate record · 2&#8202;m air temperature ·
          anomalies vs the 1991–2020 average for the same time of year · through
          13 July 2026 · processed with the{" "}
          <a href="https://github.com/climate-you/climate">
            open-source pipeline
          </a>{" "}
          powering <a href="https://climate.you">climate.you</a>
        </p>
      </header>

      <div
        className={styles.heroAnim}
        aria-label="The first heat dome moving across Europe, 20 to 29 June 2026"
      >
        {WINDOWS.map((def, i) => {
          const texture = textureFor(def.layerId);
          return (
            <div
              key={def.layerId}
              className={styles.heroFrame}
              style={{ opacity: i === heroIndex ? 1 : 0 }}
            >
              {texture ? (
                <AnomalyMap
                  textureUrl={texture.url}
                  textureWidth={texture.width}
                  textureHeight={texture.height}
                  latMax={texture.latMax}
                  bbox={EUROPE_BBOX}
                  linesUrl={LINES_URL}
                  renderHeight={800}
                  alt={`${def.dates} 2026 anomaly`}
                />
              ) : (
                <div />
              )}
              <span className={styles.flabel}>{def.flabel}</span>
            </div>
          );
        })}
      </div>
      <p className={styles.cap}>
        The first heat dome, 20–29 June: the hottest edge moves from Iberia to
        Central Europe.
      </p>
      <div className={styles.scale}>
        <span>0°C</span>
        <span className={styles.grad} />
        <span>+12°C above normal</span>
      </div>

      <div className={styles.lead}>
        <div className={styles.prose}>
          <p>
            Through the first half of June, temperatures across Western and
            Central Europe were close to the 1991–2020 average, and below it on
            several days. From 16 June the heat built quickly. By 26 June, the
            average across 15 major European cities was <strong>9.0°C</strong>{" "}
            above the June norm.
          </p>
          <p>
            The first spell was a single heat dome that moved. Its centre tracked
            from the southwest to the northeast over about ten days: Iberia
            around 20–22 June, France around 23–25, Central Europe and Italy
            around 27–29. It faded at the end of the month, ahead of a second
            spell in early July.
          </p>
        </div>
        <div className={styles.stats}>
          <div className={styles.stat}>
            <span className={styles.num}>
              +13.9<span className={styles.unit}>°C</span>
            </span>
            <span className={styles.lab}>
              Paris, 23–25 June, above the June norm
            </span>
          </div>
          <div className={styles.stat}>
            <span className={styles.num}>
              +9.0<span className={styles.unit}>°C</span>
            </span>
            <span className={styles.lab}>Europe-wide daily peak, 26 June</span>
          </div>
          <div className={styles.stat}>
            <span className={styles.num}>
              +6.8<span className={styles.unit}>°C</span>
            </span>
            <span className={styles.lab}>
              Paris again, 6–10 July, above the July norm
            </span>
          </div>
        </div>
      </div>

      <section
        className={styles.triptych}
        aria-label="Three snapshots of the first heat dome"
      >
        <h2>A moving dome: 17–30 June</h2>
        <p className={styles.secNote}>
          Mean anomaly over each three-day window. The centre of the dome shifts
          from the southwest to the northeast of the continent.
        </p>
        <div className={styles.maps}>
          {WINDOWS.map((def) => {
            const texture = textureFor(def.layerId);
            return texture ? (
              <MapFigure key={def.layerId} texture={texture} def={def} />
            ) : (
              <figure key={def.layerId}>
                <div className={styles.mapCanvas} style={{ aspectRatio: String(MAP_ASPECT) }} />
                <figcaption>
                  <span className={styles.dates}>{def.dates}</span>
                  <span className={styles.place}>{def.place}</span>
                  <span className={styles.pk}>{def.peak}</span>
                </figcaption>
              </figure>
            );
          })}
        </div>
        <span className={styles.swipeHint}>
          ← swipe through the three windows →
        </span>
        <div className={styles.scale} style={{ marginTop: 18 }}>
          <span>0°C</span>
          <span className={styles.grad} />
          <span>+12°C above the June norm</span>
        </div>
      </section>

      <section
        className={styles.dome2}
        aria-label="A second heat episode over the southwest in early July"
      >
        {(() => {
          const texture = textureFor(DOME2.layerId);
          return texture ? (
            <MapFigure texture={texture} def={DOME2} height={760} />
          ) : (
            <figure>
              <div
                className={styles.mapCanvas}
                style={{ aspectRatio: String(MAP_ASPECT) }}
              />
            </figure>
          );
        })()}
        <div className={styles.dome2Txt}>
          <h2>A second episode over the southwest</h2>
          <p>
            After a two-day lull, a second build-up formed over France and Iberia
            in early July, but not over Central Europe, which had cooled. Across
            6–10 July Paris ran <strong>6.8°C</strong> above the July norm, and
            the heat kept building after that.
          </p>
          <p>
            This second episode was not the tail of the first. It was a distinct
            spell over the southwest, and it crested on 12 July, when Paris
            reached <strong>9.2°C</strong> above the July norm, before easing the
            next day.
          </p>
        </div>
      </section>

      <section className={styles.globe}>
        <h2>Explore it on the globe</h2>
        <p className={styles.secNote}>
          Spin the globe, step through the windows, and select any location to
          see its own record.
        </p>
        {globeReady ? (
          <GlobeBoundary>
            <StoryGlobe
              layerOptions={globeLayerOptions}
              steps={GLOBE_STEPS}
              initialLayerId="heatwave_2026_w2"
              flyToBbox={GLOBE_BBOX}
              apiBase={apiBase}
              release={sessionRelease ?? requestedRelease}
              panelFromDate="2026-01-01"
              panelPeriodLabel="2026"
            />
          </GlobeBoundary>
        ) : (
          <div className={styles.globeStage}>
            <div className={styles.globeCanvasWrap} />
          </div>
        )}
      </section>

      <section className={styles.chartSec}>
        <h2>Daily anomaly, June–July 2026</h2>
        <p className={styles.secNote}>
          Mean daily temperature across 15 major Western and Central European
          cities, each day against its own 1991–2020 monthly average. Two spells
          stand out, separated by an early-July lull.
        </p>
        <HeatwaveChart
          title="Daily temperature anomaly · June–July 2026"
          sourceText="Source: ECMWF ERA5 · 15-city mean vs 1991–2020"
        />
        <p className={styles.cities}>
          <b>Cities included:</b> Paris, London, Madrid, Barcelona, Lisbon,
          Bordeaux, Lyon, Milan, Rome, Frankfurt, Munich, Amsterdam, Brussels,
          Vienna, Prague.
        </p>
      </section>

      <aside className={styles.callout}>
        <h3>Monthly averages hide short events</h3>
        <p>
          Averaged over the whole of June, Europe was <strong>+1.7°C</strong>{" "}
          above normal: the cool first half offsets the second. The maps on this
          page are therefore built from daily windows around each spell, not from
          a monthly mean.
        </p>
      </aside>

      <footer className={styles.methods}>
        <p>
          <strong>How this page was made.</strong> 2&#8202;m air temperature from
          the Copernicus ERA5 climate record at 0.25° resolution. ERA5 is the
          ECMWF reanalysis, a physically consistent reconstruction of past
          weather; the most recent days use its preliminary near-real-time
          release, ERA5T. The data is ingested and tiled by the{" "}
          <a href="https://github.com/climate-you/climate">
            open-source pipeline
          </a>{" "}
          that powers <a href="https://climate.you">climate.you</a>, the same
          dataset behind the interactive globe. Each map shows the mean over its
          time window minus that grid cell&apos;s 1991–2020 average for the same
          month. The daily line is the mean across 15 major Western and Central
          European cities. Data runs through 13 July 2026.
        </p>
      </footer>
    </article>
  );
}
