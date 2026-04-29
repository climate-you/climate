"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as echarts from "echarts";
import MapLibreGlobe from "@/components/MapLibreGlobe";
import type {
  MapLayerOption,
  TextureDebugInfo,
} from "@/components/MapLibreGlobe";
import AboutOverlay from "@/components/AboutOverlay";
import GraphCard from "@/components/explorer/GraphCard";
import InfoBubble from "@/components/explorer/InfoBubble";
import ColdOpenOverlay from "@/components/explorer/ColdOpenOverlay";
import SearchOverlay from "@/components/explorer/SearchOverlay";
import type { AutocompleteItem } from "@/components/explorer/SearchOverlay";
import SourcesOverlay from "@/components/SourcesOverlay";
import ChatDrawer from "@/components/chat/ChatDrawer";
import { useChatFeatureFlag } from "@/hooks/explorer/useChatFeatureFlag";
import { useDebugTextureSync } from "@/hooks/explorer/useDebugTextureSync";
import { useOverlayRouteSync } from "@/hooks/explorer/useOverlayRouteSync";
import { useReleaseResolution } from "@/hooks/explorer/useReleaseResolution";
import {
  CLIMATE_DATA_LOAD_ERROR,
  DEFAULT_OVERLAY_BASE_PATH,
  MIN_PANEL_VIEWPORT_HEIGHT_FOR_TWO_GRAPHS,
  TOUCH_CLOSE_PANEL_THRESHOLD_PX,
  TOUCH_PANEL_LIFT_MAX_PX,
  TOUCH_PANEL_PULL_MAX_PX,
  TOUCH_SWIPE_MIN_VELOCITY_PX_MS,
  TOUCH_SWIPE_THRESHOLD_PX,
  WHEEL_GESTURE_GAP_MS,
  WHEEL_REPEAT_KICK_THRESHOLD,
  WHEEL_STEP_THRESHOLD,
  WHEEL_SUSTAIN_REPEAT_MS,
} from "@/lib/explorer/constants";
import {
  formatHeadlineDelta,
  formatPopulation,
  inBbox,
  legendForLayer,
  mergeSeries,
} from "@/lib/explorer/chartData";
import { isMobileViewport } from "@/lib/explorer/chartOptions";
import { defaultTemperatureUnitForLocale } from "@/lib/temperatureUnit";
import styles from "./page.module.css";

const CORAL_REEF_CENTERS: [number, number][] = [
  [-18, 147], // Great Barrier Reef
  [0, 122], // Coral Triangle (SE Asia)
  [20, 38], // Red Sea
  [4, 73], // Maldives / Indian Ocean
  [15, -70], // Caribbean
  [21, -157], // Hawaii
  [-17, 178], // Pacific (Fiji)
  [25, -81], // Florida Keys
];

function nearestCoralBbox(lat: number, lon: number): [number, number, number, number] {
  let best = CORAL_REEF_CENTERS[0];
  let bestDist = Infinity;
  for (const center of CORAL_REEF_CENTERS) {
    const dLat = center[0] - lat;
    const dLon = ((center[1] - lon + 540) % 360) - 180;
    const dist = dLat * dLat + dLon * dLon;
    if (dist < bestDist) {
      bestDist = dist;
      best = center;
    }
  }
  const [cLat, cLon] = best;
  return [cLon - 20, cLat - 12, cLon + 20, cLat + 12];
}

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
  shortLabel?: string | null;
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
    panel_bbox_grid_id?: string | null;
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
    baseline_value?: number | null;
    unit: string;
    baseline?: string | null;
    period?: string | null;
    method?: string | null;
  }>;
  layer_overrides?: Record<string, { default_graph_ids: string[] }>;
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
  available: boolean;
};

type GlobeBackground = { src: string; accentColor: string };

const GLOBE_BACKGROUNDS: GlobeBackground[] = [
  { src: "/bg1.webp", accentColor: "#ff0000" },
  { src: "/bg2.webp", accentColor: "#0000ff" },
  { src: "/bg3.webp", accentColor: "#0000ff" },
  { src: "/bg4.webp", accentColor: "#0000ff" },
  { src: "/bg5.webp", accentColor: "#ff0000" },
];

function pickGlobeBackground(): GlobeBackground {
  const entry =
    GLOBE_BACKGROUNDS[Math.floor(Math.random() * GLOBE_BACKGROUNDS.length)];
  if (isMobileViewport()) {
    return { ...entry, src: entry.src.replace(".webp", "_mobile.webp") };
  }
  return entry;
}

const FIXED_GRAPH_ORDER = [
  "t2m_annual",
  "t2m_hot_days",
  "sst_annual",
  "sst_hot_days",
  "tp_annual",
  "tp_cdd",
  "dhw_risk_days",
] as const;

const GRAPH_PANEL_ID: Record<string, string> = {
  t2m_annual: "air_temperature",
  t2m_hot_days: "air_temperature",
  sst_annual: "sea_temperature",
  sst_hot_days: "sea_temperature",
  tp_annual: "precipitation",
  tp_cdd: "precipitation",
  dhw_risk_days: "coral_reef_dhw",
};

const GRAPH_TITLES: Record<string, string> = {
  t2m_annual: "Annual air temperature",
  t2m_hot_days: "Number of hot days",
  sst_annual: "Annual sea surface temperature",
  sst_hot_days: "Number of sea surface hot days",
  tp_annual: "Annual total precipitation",
  tp_cdd: "Consecutive dry days",
  dhw_risk_days: "Coral reef DHW risk days",
};

const GRAPH_INFO_TEXT: Record<string, string> = {
  t2m_annual: "Annual air temperature is derived from daily air temperature at 2 meters above the surface, aggregated into monthly and yearly averages for 1979-2025. We show a zoomed-in version of the daily and monthly temperatures over 5 years (2021-2025) that reflects seasonal changes. Source: CDS.",
  t2m_hot_days: "Number of hot days per year are counted as days warmer than the top 10% warmest days in a 10-year baseline starting in 1979, for 1979-2025. Source: CDS.",
  sst_annual: "Annual sea surface temperature is derived from daily sea surface temperature, aggregated into yearly averages for 1982-2025. Source: ERDDAP.",
  sst_hot_days: "Number of sea surface hot days per year are counted as days where the sea surface temperature is warmer than the top 10% warmest days in a 10-year baseline starting in 1982, for 1982-2025. Source: ERDDAP.",
  tp_annual: "Annual total precipitation is derived from daily ERA5 total precipitation, summed into yearly totals for 1979-2025. Source: CDS.",
  tp_cdd: "Maximum number of consecutive dry days (daily precipitation < 1 mm) per year for 1979-2025. Source: CDS.",
  dhw_risk_days: "This graph shows the number of days per year that coral reefs experienced each DHW (Degree Heating Weeks) heat-stress level for 1985-2025: no risk (DHW < 4), moderate risk (4 ≤ DHW < 8), and severe risk (DHW ≥ 8). DHW measures accumulated ocean heat stress over the previous 12 weeks; more days in higher DHW categories indicate greater bleaching risk. Source: ERDDAP.",
};

type PanelStepIconProps = {
  panelId: string;
  active: boolean;
  label: string;
  onClick: () => void;
};

function PanelStepIcon({ panelId, active, label, onClick }: PanelStepIconProps) {
  let icon: React.ReactNode;
  if (panelId === "precipitation") {
    icon = <path d="M12 2C8.5 7.5 5 12 5 15.5a7 7 0 0 0 14 0C19 12 15.5 7.5 12 2z" />;
  } else if (panelId === "sea_temperature") {
    icon = (
      <>
        <path d="M2 10c2-4 4-4 6 0s4 4 6 0 4-4 6 0" />
        <path d="M2 16c2-4 4-4 6 0s4 4 6 0 4-4 6 0" />
      </>
    );
  } else if (panelId === "coral_reef_dhw") {
    return (
      <button
        type="button"
        role="tab"
        aria-label={label}
        aria-selected={active}
        onClick={onClick}
        className={`${styles.panelStepIcon} ${active ? styles.panelStepIconActive : ""}`}
      >
        <img
          src="/coral_icon.png"
          alt=""
          aria-hidden="true"
          className={`${styles.panelStepIconImg} ${active ? styles.panelStepIconImgActive : ""}`}
        />
      </button>
    );
  } else {
    icon = <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z" />;
  }
  return (
    <button
      type="button"
      role="tab"
      aria-label={label}
      aria-selected={active}
      onClick={onClick}
      className={`${styles.panelStepIcon} ${active ? styles.panelStepIconActive : ""}`}
    >
      <svg className={styles.panelStepIconSvg} viewBox="0 0 24 24" aria-hidden="true">
        {icon}
      </svg>
    </button>
  );
}

type ExplorerPageProps = {
  coldOpen?: boolean;
  initialOverlay?: "about" | "sources" | null;
  initialOverlayBasePath?: string;
};

export default function ExplorerPage({
  coldOpen = false,
  initialOverlay = null,
  initialOverlayBasePath = DEFAULT_OVERLAY_BASE_PATH,
}: ExplorerPageProps) {
  const debugAllowed = process.env.NODE_ENV !== "production";
  const envDefaultReleaseRaw = process.env.NEXT_PUBLIC_RELEASE;
  const [lat, setLat] = useState<number>(-20.32556);
  const [lon, setLon] = useState<number>(57.37056);
  const [unit, setUnit] = useState<"C" | "F">("C");
  const [resp, setResp] = useState<PanelResponse | null>(null);
  const [locationError, setLocationError] = useState<string | null>(null);
  const [panelLoadError, setPanelLoadError] = useState<string | null>(null);
  const [panelLoading, setPanelLoading] = useState<boolean>(false);
  const [panelRetrying, setPanelRetrying] = useState<boolean>(false);
  const [panelOpen, setPanelOpen] = useState<boolean>(false);
  const [panelTab, setPanelTab] = useState<"graph" | "chat">("graph");
  const [panelDragOffsetPx, setPanelDragOffsetPx] = useState(0);
  const [panelDragActive, setPanelDragActive] = useState(false);
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(
    null,
  );
  const [chatLocations, setChatLocations] = useState<Array<{
    label: string;
    rank?: number;
    lat: number;
    lon: number;
  }> | null>(null);
  const [chatFlyToBbox, setChatFlyToBbox] = useState<
    [number, number, number, number] | null
  >(null);
  const [selectedLocation, setSelectedLocation] =
    useState<SelectedLocationMeta | null>(null);
  const [selectedGeonameidForPanel, setSelectedGeonameidForPanel] = useState<
    number | null
  >(null);
  const wheelAccumRef = useRef(0);
  const wheelLastEventTsRef = useRef(0);
  const wheelGestureConsumedRef = useRef(false);
  const wheelGestureConsumedAtRef = useRef(0);
  const wheelGestureResetTimerRef = useRef<number | null>(null);
  const touchStartYRef = useRef<number | null>(null);
  const touchStartXRef = useRef<number | null>(null);
  const touchStartTimeRef = useRef<number | null>(null);
  const touchGestureAxisRef = useRef<"x" | "y" | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const panelViewportRef = useRef<HTMLDivElement | null>(null);
  const [panelViewportEl, setPanelViewportEl] = useState<HTMLDivElement | null>(
    null,
  );
  const panelViewportCallbackRef = useCallback((el: HTMLDivElement | null) => {
    panelViewportRef.current = el;
    setPanelViewportEl(el);
  }, []);
  const prevActiveLayerIdRef = useRef<string>("");
  const lastGraphViewFingerprintRef = useRef<string | null>(null);
  const lastTrackedLayerIdRef = useRef<string | null>(null);
  const [graphsPerPage, setGraphsPerPage] = useState(2);
  const prevGraphsPerPageRef = useRef(2);
  const [graphPage, setGraphPage] = useState(0);
  const [graphStepById, setGraphStepById] = useState<Record<string, number>>(
    {},
  );
  const [introActive, setIntroActive] = useState(coldOpen);
  const [introShowMap, setIntroShowMap] = useState(!coldOpen);
  const [coldOpenAutoRotate, setColdOpenAutoRotate] = useState(false);
  const [globeBackground, setGlobeBackground] = useState<GlobeBackground>(
    GLOBE_BACKGROUNDS[0],
  );
  useEffect(() => {
    setGlobeBackground(pickGlobeBackground());
  }, []);
  useEffect(() => {
    const img = new Image();
    img.src = globeBackground.src;
  }, [globeBackground]);
  const { aboutOpen, sourcesOpen, setOverlayOpenWithUrl } = useOverlayRouteSync(
    {
      initialOverlay,
      initialOverlayBasePath,
    },
  );
  const { debugMode, textureVariantOverride } =
    useDebugTextureSync(debugAllowed);
  const chatEnabled = useChatFeatureFlag();
  const [textureDebugInfo, setTextureDebugInfo] =
    useState<TextureDebugInfo | null>(null);
  const DEFAULT_API_PORT = 8001;
  const apiBase = useMemo(() => {
    if (process.env.NEXT_PUBLIC_CLIMATE_API_BASE) {
      return process.env.NEXT_PUBLIC_CLIMATE_API_BASE.replace(/\/+$/, "");
    }
    if (typeof window === "undefined")
      return `http://localhost:${DEFAULT_API_PORT}`;
    return `http://${window.location.hostname}:${DEFAULT_API_PORT}`;
  }, []);
  const mapAssetBase = useMemo(() => {
    if (process.env.NEXT_PUBLIC_MAP_ASSET_BASE) {
      return process.env.NEXT_PUBLIC_MAP_ASSET_BASE.replace(/\/+$/, "");
    }
    return apiBase;
  }, [apiBase]);
  const {
    requestedRelease,
    sessionRelease,
    appVersion,
    assetsRelease,
    releaseLayers,
    pinSessionRelease,
  } = useReleaseResolution(apiBase, envDefaultReleaseRaw);
  const releaseForSession = sessionRelease ?? requestedRelease;
  const encodedRelease = encodeURIComponent(releaseForSession);
  const mapLayers = useMemo<MapLayerOption[]>(() => {
    const configuredLayers = releaseLayers
      .filter((layer) => {
        const isEnabled = layer.enable !== false;
        return debugMode || isEnabled;
      })
      .map((layer) => {
        const isEnabled = layer.enable !== false;
        return {
          id: layer.id,
          label: isEnabled ? layer.label : `${layer.label} [disabled]`,
          imageUrl: `${mapAssetBase}/assets/v/${encodedRelease}/${layer.asset_path}`,
          imageWidth:
            typeof layer.asset_width === "number"
              ? layer.asset_width
              : undefined,
          imageHeight:
            typeof layer.asset_height === "number"
              ? layer.asset_height
              : undefined,
          mobileImageUrl:
            typeof layer.mobile_asset_path === "string" &&
            layer.mobile_asset_path
              ? `${mapAssetBase}/assets/v/${encodedRelease}/${layer.mobile_asset_path}`
              : undefined,
          mobileImageWidth:
            typeof layer.mobile_asset_width === "number"
              ? layer.mobile_asset_width
              : undefined,
          mobileImageHeight:
            typeof layer.mobile_asset_height === "number"
              ? layer.mobile_asset_height
              : undefined,
          projectionBounds:
            layer.projection_bounds &&
            typeof layer.projection_bounds.lat_min === "number" &&
            typeof layer.projection_bounds.lat_max === "number" &&
            typeof layer.projection_bounds.lon_min === "number" &&
            typeof layer.projection_bounds.lon_max === "number"
              ? layer.projection_bounds
              : undefined,
          opacity: typeof layer.opacity === "number" ? layer.opacity : 0.72,
          resampling:
            layer.resampling === "linear" || layer.resampling === "nearest"
              ? layer.resampling
              : ("nearest" as const),
        };
      });
    return [{ id: "none", label: "None" }, ...configuredLayers];
  }, [debugMode, encodedRelease, mapAssetBase, releaseLayers]);
  const [activeLayerId, setActiveLayerId] = useState<string>(
    mapLayers[0]?.id ?? "",
  );
  const activeLayer = useMemo(
    () =>
      releaseLayers.find((layer) => layer.id === (activeLayerId || "")) ?? null,
    [activeLayerId, releaseLayers],
  );
  const activeLayerLegend = useMemo(
    () => legendForLayer(activeLayer, unit),
    [activeLayer, unit],
  );
  const activeLayerDescription = useMemo(() => {
    if (typeof activeLayer?.description !== "string") return "";
    return activeLayer.description.trim();
  }, [activeLayer]);
  const darkBackdropLayerActive = useMemo(
    () => activeLayerId !== "" && activeLayerId !== "none",
    [activeLayerId],
  );
  const activeLayerOverride = useMemo(() => {
    if (!resp?.layer_overrides) return null;
    if (!activeLayerId || activeLayerId === "none") return null;
    const spec = resp.layer_overrides[activeLayerId];
    return spec ?? null;
  }, [activeLayerId, resp?.layer_overrides]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (
      params.get("unit") === "F" ||
      defaultTemperatureUnitForLocale() === "F"
    ) {
      setUnit("F");
    }
  }, []);

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

  const pagedGraphs = useMemo<PagedGraphItem[]>(() => {
    const graphLookup = new Map<string, PagedGraphItem>();
    panelData.forEach(({ panel, graphs }) => {
      graphs.forEach(({ graph, data }) => {
        graphLookup.set(graph.id, {
          panelId: panel.id,
          graph,
          data,
          available: true,
        });
      });
    });
    return FIXED_GRAPH_ORDER.map((graphId) => {
      return (
        graphLookup.get(graphId) ?? {
          panelId: GRAPH_PANEL_ID[graphId] ?? "",
          graph: {
            id: graphId,
            title: GRAPH_TITLES[graphId] ?? graphId,
            series_keys: [],
            ui: { info_text: GRAPH_INFO_TEXT[graphId] ?? null },
          },
          data: [],
          available: resp === null,
        }
      );
    });
  }, [panelData, resp]);
  const maxGraphPage = Math.max(
    0,
    Math.ceil(pagedGraphs.length / graphsPerPage) - 1,
  );
  const stepCount = maxGraphPage + 1;
  const pageStart = graphPage * graphsPerPage;
  const visibleGraphs = pagedGraphs.slice(pageStart, pageStart + graphsPerPage);

  const panelHeadline = useMemo(() => {
    if (!resp) return null;
    const headlines = resp.headlines ?? [];
    const h = (key: string) => headlines.find((hd) => hd.key === key) ?? null;
    const graphId = visibleGraphs[0]?.graph.id ?? null;
    const isGlobal = resp.location.place.geonameid === 0;
    const trendDir = (hd: { value: number | null; baseline_value?: number | null }) =>
      typeof hd.value === "number" && typeof hd.baseline_value === "number"
        ? hd.value >= hd.baseline_value ? "risen" : "fallen"
        : "risen";

    switch (graphId) {
      case "t2m_annual": {
        const pi = h(isGlobal ? "t2m_vs_preindustrial_global" : "t2m_vs_preindustrial_local");
        const recent = h(isGlobal ? "t2m_recent_global" : "t2m_recent_local");
        const piVal = typeof pi?.value === "number" && Number.isFinite(pi.value) ? pi.value : null;
        if (piVal === null) return null;
        const recentVal =
          typeof recent?.value === "number" && Number.isFinite(recent.value) && recent.value >= 0.05
            ? recent.value : null;
        return { type: "air_temp", warming: piVal > 0, preindustrial: piVal, recent: recentVal } as const;
      }
      case "t2m_hot_days": {
        const hd = h(isGlobal ? "t2m_hotdays_global" : "t2m_hotdays_local");
        if (typeof hd?.value !== "number" || !Number.isFinite(hd.value)) return null;
        return { type: "trend", direction: trendDir(hd), label: "the number of hot days has", value: hd.value, suffix: " days since 1979" } as const;
      }
      case "sst_annual": {
        const sst = h(isGlobal ? "sst_recent_global" : "sst_recent_local");
        const sstVal = typeof sst?.value === "number" && Number.isFinite(sst.value) ? sst.value : null;
        if (sstVal !== null) {
          return sstVal > 0
            ? { type: "temp_delta", action: "the sea has warmed by", value: sstVal, suffix: "since 1982" } as const
            : { type: "no_warming", text: "the sea has not warmed since 1982." } as const;
        }
        if (!isGlobal) {
          const globalSst = h("sst_recent_global");
          const globalDelta = typeof globalSst?.value === "number" && Number.isFinite(globalSst.value) ? globalSst.value : null;
          return { type: "sst_unavailable", globalDelta } as const;
        }
        return null;
      }
      case "sst_hot_days": {
        const hd = h(isGlobal ? "sst_hotdays_global" : "sst_hotdays_local");
        if (typeof hd?.value === "number" && Number.isFinite(hd.value)) {
          return { type: "trend", direction: trendDir(hd), label: "the number of sea hot days has", value: hd.value, suffix: " days since 1982" } as const;
        }
        if (!isGlobal) {
          const globalSst = h("sst_recent_global");
          const globalDelta = typeof globalSst?.value === "number" && Number.isFinite(globalSst.value) ? globalSst.value : null;
          return { type: "sst_unavailable", globalDelta } as const;
        }
        return null;
      }
      case "tp_annual": {
        const hd = h(isGlobal ? "precip_global" : "precip_local");
        if (typeof hd?.value !== "number" || !Number.isFinite(hd.value)) return null;
        return { type: "trend", direction: trendDir(hd), label: "the precipitation level has", value: hd.value, suffix: " mm since 1979" } as const;
      }
      case "tp_cdd": {
        const hd = h(isGlobal ? "cdd_global" : "cdd_local");
        if (typeof hd?.value !== "number" || !Number.isFinite(hd.value)) return null;
        return { type: "trend", direction: trendDir(hd), label: "the number of consecutive dry days has", value: hd.value, suffix: " days since 1979" } as const;
      }
      case "dhw_risk_days": {
        if (isGlobal) {
          const hd = h("dhw_severe_global");
          if (typeof hd?.value !== "number" || !Number.isFinite(hd.value)) return null;
          return { type: "coral_absolute", days: hd.value } as const;
        }
        const factor = h("dhw_factor_local");
        const severe = h("dhw_severe_local");
        const factorVal = typeof factor?.value === "number" && Number.isFinite(factor.value) ? factor.value : null;
        const severeVal = typeof severe?.value === "number" && Number.isFinite(severe.value) ? severe.value : null;
        if (severeVal === null) {
          const globalCoral = h("dhw_severe_global");
          const globalDays = typeof globalCoral?.value === "number" && Number.isFinite(globalCoral.value) ? globalCoral.value : null;
          return { type: "coral_unavailable", globalDays } as const;
        }
        if (factorVal === 0 || severeVal === 0) return { type: "coral_no_days" } as const;
        if (factorVal !== null && factorVal > 1.2) return { type: "coral_factor", factor: factorVal } as const;
        if (factorVal !== null && factorVal >= 0.8) return { type: "coral_stable" } as const;
        return { type: "coral_absolute", days: severeVal } as const;
      }
      default:
        return null;
    }
  }, [resp, visibleGraphs]);

  const graphSlots = useMemo(
    () =>
      Array.from(
        { length: graphsPerPage },
        (_, index) => visibleGraphs[index] ?? null,
      ),
    [graphsPerPage, visibleGraphs],
  );

  const trackGoatEvent = useCallback((path: string, title: string) => {
    if (typeof window === "undefined") return;
    const goatcounter = (
      window as Window & {
        goatcounter?: { count?: (payload: Record<string, unknown>) => void };
      }
    ).goatcounter;
    goatcounter?.count?.({
      path,
      title,
      event: true,
    });
  }, []);

  useEffect(() => {
    if (!panelOpen) return;
    const locationKey = String(
      selectedGeonameidForPanel ??
        selectedLocation?.geonameid ??
        resp?.location.place.geonameid ??
        "unknown",
    );
    const visibleIds = visibleGraphs
      .map((entry) => entry?.graph.id ?? "none")
      .join("|");
    const fingerprint = `${locationKey}:${graphPage}:${visibleIds}`;
    if (lastGraphViewFingerprintRef.current === fingerprint) return;
    lastGraphViewFingerprintRef.current = fingerprint;
    visibleGraphs.forEach((entry) => {
      if (!entry) return;
      const graphId = entry.graph.id;
      if (!graphId) return;
      trackGoatEvent(
        `/view/graph/${encodeURIComponent(graphId)}`,
        `Graph viewed: ${entry.graph.title} @${locationKey}`,
      );
    });
  }, [
    graphPage,
    panelOpen,
    resp?.location.place.geonameid,
    selectedGeonameidForPanel,
    selectedLocation?.geonameid,
    trackGoatEvent,
    visibleGraphs,
  ]);

  useEffect(() => {
    if (!activeLayerId || activeLayerId === "none") return;
    if (lastTrackedLayerIdRef.current === activeLayerId) return;
    lastTrackedLayerIdRef.current = activeLayerId;
    trackGoatEvent(
      `/view/layer/${encodeURIComponent(activeLayerId)}`,
      `Layer viewed: ${activeLayer?.label ?? activeLayerId}`,
    );
  }, [activeLayer?.label, activeLayerId, trackGoatEvent]);

  useEffect(() => {
    if (sessionStorage.getItem("session_reported")) return;
    sessionStorage.setItem("session_reported", "1");
    fetch(`${apiBase}/api/events/session`, { method: "POST" }).catch(() => {});
  }, [apiBase]);

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

  useEffect(() => {
    const prevLayerId = prevActiveLayerIdRef.current;
    prevActiveLayerIdRef.current = activeLayerId;
    if (prevLayerId === activeLayerId) return;
    if (!activeLayerId || activeLayerId === "none") {
      setGraphPage(0);
      return;
    }
    const firstGraphId = activeLayerOverride?.default_graph_ids?.[0];
    if (!firstGraphId) return;
    const graphIndex = (FIXED_GRAPH_ORDER as readonly string[]).indexOf(firstGraphId);
    if (graphIndex < 0) return;
    setGraphPage(Math.floor(graphIndex / Math.max(1, graphsPerPage)));
  }, [activeLayerId, activeLayerOverride, graphsPerPage]);

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
      setResp(null);
      setSelectedLocation((prev) =>
        prev ? { ...prev, population: null } : prev,
      );
      setPanelLoadError(CLIMATE_DATA_LOAD_ERROR);
      return null;
    } finally {
      setPanelLoading(false);
    }
  }

  async function loadGlobalPanel(nextUnit = unit) {
    setChatLocations(null);
    setChatFlyToBbox(null);
    setPicked(null);
    setSelectedGeonameidForPanel(null);
    setSelectedLocation({
      geonameid: 0,
      label: "Global",
      countryCode: "",
      population: null,
    });
    setPanelTab("graph");
    setPanelOpen(true);
    setPanelLoading(true);
    setPanelLoadError(null);
    try {
      const url = `${apiBase}/api/v/${encodeURIComponent(releaseForSession)}/panel/global?unit=${nextUnit}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as PanelResponse;
      pinSessionRelease(data.release);
      setResp(data);
      setPanelLoadError(null);
    } catch {
      setResp(null);
      setPanelLoadError(CLIMATE_DATA_LOAD_ERROR);
    } finally {
      setPanelLoading(false);
    }
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
    fetch(`${apiBase}/api/events/click`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: item.lat, lon: item.lon }),
    }).catch(() => {});
    setLat(item.lat);
    setLon(item.lon);
    setPicked({ lat: item.lat, lon: item.lon });
    setChatLocations(null);
    setChatFlyToBbox(null);
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

  async function handlePick(
    la: number,
    lo: number,
    keepChatLocations = false,
    openPanel = true,
  ) {
    fetch(`${apiBase}/api/events/click`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: la, lon: lo }),
    }).catch(() => {});
    setLat(la);
    setLon(lo);
    setPicked({ lat: la, lon: lo });
    if (!keepChatLocations) {
      setChatLocations(null);
      setChatFlyToBbox(null);
    }
    setSelectedGeonameidForPanel(null);
    if (openPanel) setPanelOpen(true);

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
      setPanelLoadError(CLIMATE_DATA_LOAD_ERROR);
      setLocationError(
        err instanceof Error ? err.message : "Failed to load location data",
      );
    }
  }

  useEffect(() => {
    if (!mapLayers.length) return;
    if (mapLayers.some((layer) => layer.id === activeLayerId)) return;
    setActiveLayerId(mapLayers[0].id);
  }, [activeLayerId, mapLayers]);

  useEffect(() => {
    if (!panelViewportEl) return;
    const updateGraphsPerPage = () => {
      const next =
        panelViewportEl.clientHeight < MIN_PANEL_VIEWPORT_HEIGHT_FOR_TWO_GRAPHS
          ? 1
          : 2;
      setGraphsPerPage((prev) => (prev === next ? prev : next));
    };
    updateGraphsPerPage();
    const observer = new ResizeObserver(updateGraphsPerPage);
    observer.observe(panelViewportEl);
    window.addEventListener("resize", updateGraphsPerPage);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateGraphsPerPage);
    };
  }, [panelViewportEl]);

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

  useEffect(() => {
    if (panelOpen) return;
    setGraphPage(0);
    setPanelDragOffsetPx(0);
    setPanelDragActive(false);
    touchGestureAxisRef.current = null;
  }, [panelOpen]);

  const keepPanelFocused = useCallback(() => {
    if (!panelOpen || introActive) return;
    window.requestAnimationFrame(() => {
      panelRef.current?.focus({ preventScroll: true });
    });
  }, [introActive, panelOpen]);

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
      if (now - wheelLastEventTsRef.current > WHEEL_GESTURE_GAP_MS) {
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
      }, WHEEL_GESTURE_GAP_MS);
      if (wheelGestureConsumedRef.current) {
        if (now - wheelGestureConsumedAtRef.current < WHEEL_SUSTAIN_REPEAT_MS) {
          return;
        }
        // Allow another step only on a fresh strong impulse.
        // This blocks trackpad momentum from cascading through many pages.
        if (Math.abs(e.deltaY) < WHEEL_REPEAT_KICK_THRESHOLD) {
          return;
        }
        wheelGestureConsumedRef.current = false;
        wheelAccumRef.current = 0;
      }
      wheelAccumRef.current += e.deltaY;
      if (Math.abs(wheelAccumRef.current) < WHEEL_STEP_THRESHOLD) return;
      const changed = goGraphPage(wheelAccumRef.current > 0 ? 1 : -1);
      wheelAccumRef.current = 0;
      if (changed) {
        wheelGestureConsumedRef.current = true;
        wheelGestureConsumedAtRef.current = now;
      }
    },
    [
      goGraphPage,
      WHEEL_GESTURE_GAP_MS,
      WHEEL_REPEAT_KICK_THRESHOLD,
      WHEEL_STEP_THRESHOLD,
      WHEEL_SUSTAIN_REPEAT_MS,
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
      } else if (e.key === "Escape") {
        e.preventDefault();
        setPanelOpen(false);
      }
    },
    [goGraphPage],
  );

  const handlePanelTouchStart = useCallback(
    (e: React.TouchEvent<HTMLElement>) => {
      if (e.touches.length !== 1) {
        touchStartYRef.current = null;
        touchStartXRef.current = null;
        touchGestureAxisRef.current = null;
        return;
      }
      touchStartYRef.current = e.touches[0].clientY;
      touchStartXRef.current = e.touches[0].clientX;
      touchStartTimeRef.current = Date.now();
      touchGestureAxisRef.current = null;
      setPanelDragActive(false);
      setPanelDragOffsetPx(0);
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
      const absDeltaY = Math.abs(deltaY);
      const absDeltaX = Math.abs(deltaX);
      if (
        touchGestureAxisRef.current === null &&
        (absDeltaY > 6 || absDeltaX > 6)
      ) {
        touchGestureAxisRef.current = absDeltaY >= absDeltaX ? "y" : "x";
      }
      if (touchGestureAxisRef.current === "y") {
        // Block native pull-to-refresh / page overscroll while panel drag
        // gestures are active on mobile, and follow the finger.
        e.preventDefault();
        setPanelDragActive(true);
        const nextOffset = Math.max(
          -TOUCH_PANEL_LIFT_MAX_PX,
          Math.min(TOUCH_PANEL_PULL_MAX_PX, deltaY),
        );
        setPanelDragOffsetPx(nextOffset);
        return;
      }
      if (touchGestureAxisRef.current === "x" && absDeltaX > 8) {
        // Prevent native scrolling while a horizontal swipe gesture is in progress.
        e.preventDefault();
      }
    },
    [TOUCH_PANEL_LIFT_MAX_PX, TOUCH_PANEL_PULL_MAX_PX],
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
      const axis = touchGestureAxisRef.current;
      touchGestureAxisRef.current = null;
      setPanelDragActive(false);
      setPanelDragOffsetPx(0);
      if (
        typeof window !== "undefined" &&
        !window.matchMedia("(max-width: 900px)").matches
      ) {
        return;
      }
      if (axis === "y" && deltaY > 0 && Math.abs(deltaY) > Math.abs(deltaX)) {
        if (deltaY >= TOUCH_CLOSE_PANEL_THRESHOLD_PX) {
          setPanelOpen(false);
        }
        return;
      }
      if (axis === "y") return;
      if (Math.abs(deltaX) < TOUCH_SWIPE_THRESHOLD_PX) return;
      if (Math.abs(deltaX) <= Math.abs(deltaY)) return;
      const duration =
        touchStartTimeRef.current !== null
          ? Date.now() - touchStartTimeRef.current
          : 0;
      if (
        duration > 0 &&
        Math.abs(deltaX) / duration < TOUCH_SWIPE_MIN_VELOCITY_PX_MS
      )
        return;
      goGraphPage(deltaX < 0 ? 1 : -1);
    },
    [
      goGraphPage,
      TOUCH_CLOSE_PANEL_THRESHOLD_PX,
      TOUCH_SWIPE_THRESHOLD_PX,
      TOUCH_SWIPE_MIN_VELOCITY_PX_MS,
    ],
  );

  const handlePanelTouchCancel = useCallback(() => {
    touchStartYRef.current = null;
    touchStartXRef.current = null;
    touchGestureAxisRef.current = null;
    setPanelDragActive(false);
    setPanelDragOffsetPx(0);
  }, []);

  const locationLabel =
    selectedLocation?.label ?? resp?.location.place.label ?? "";
  const titleLocationLabel = locationLabel || "this location";
  const panelTitleInfoText =
    "Headline values are derived from local climate trend data. See the chart below for the full time series.";
  const populationText = formatPopulation(selectedLocation?.population);
  const debugBbox = resp?.location?.panel_valid_bbox ?? null;
  const debugInBbox = inBbox(lat, lon, debugBbox);
  const isMobile = isMobileViewport();
  const panelDragTransform =
    isMobile && panelOpen
      ? `translateY(${Math.round(panelDragOffsetPx)}px)`
      : undefined;
  return (
    <main
      className={`${styles.app} ${introActive ? styles.appIntro : styles.appReady}`}
    >
      <div
        className={`${styles.map} ${introShowMap ? styles.mapVisible : styles.mapHidden}`}
        onPointerDownCapture={keepPanelFocused}
      >
        <MapLibreGlobe
          panelOpen={panelOpen}
          focusLocation={picked}
          showDebugOverlay={debugMode}
          debugBbox={
            debugMode ? (resp?.location.panel_valid_bbox ?? null) : null
          }
          debugBboxGridId={
            debugMode ? (resp?.location.panel_bbox_grid_id ?? null) : null
          }
          textureVariantOverride={textureVariantOverride}
          onTextureDebugInfoChange={setTextureDebugInfo}
          layerOptions={mapLayers}
          activeLayerId={activeLayerId || null}
          warmingLayerVisible={darkBackdropLayerActive}
          onLayerChange={(layerId) => setActiveLayerId(layerId)}
          onLayerMenuOpen={() => {}}
          onPick={(la, lo) => {
            void handlePick(la, lo);
          }}
          onHome={() => {
            setPanelOpen(false);
            setPicked(null);
            setChatLocations(null);
            setChatFlyToBbox(null);
            setSelectedLocation(null);
            setGlobeBackground(pickGlobeBackground());
          }}
          enablePick={!introActive}
          autoRotate={coldOpenAutoRotate}
          chatLocations={chatLocations}
          chatFlyToBbox={chatFlyToBbox}
          onPickChatMarker={(la, lo) => void handlePick(la, lo, true)}
          backgroundImageUrl={globeBackground.src}
          onGraphOpen={() => {
            if (panelOpen && panelTab === "graph") {
              setPanelOpen(false);
            } else if (selectedLocation !== null) {
              setPanelTab("graph");
              setPanelOpen(true);
            } else {
              void loadGlobalPanel();
            }
          }}
          chatEnabled={chatEnabled}
          onChatOpen={() => {
            if (panelOpen && panelTab === "chat") {
              setPanelOpen(false);
            } else {
              setPanelTab("chat");
              setPanelOpen(true);
            }
          }}
        />
        {activeLayerLegend ? (
          <aside
            className={`${styles.globeLegend} maplibregl-ctrl maplibregl-ctrl-group`}
            aria-label="Map legend"
          >
            <div className={styles.globeLegendScale}>
              <div
                className={styles.globeLegendBar}
                style={{
                  background: `linear-gradient(to top, ${activeLayerLegend.colors.join(", ")})`,
                }}
              />
              <div className={styles.globeLegendTicks}>
                {activeLayerLegend.ticks.map((tick) => (
                  <div key={tick} className={styles.globeLegendTick}>
                    {tick}
                  </div>
                ))}
              </div>
            </div>
            {activeLayerLegend.showTemperatureUnitToggle ? (
              <button
                type="button"
                className={styles.globeLegendUnitSwitch}
                aria-label={`Switch to ${unit === "C" ? "°F" : "°C"}`}
                onClick={() => {
                  const nextUnit: "C" | "F" = unit === "C" ? "F" : "C";
                  setUnit(nextUnit);
                  if (selectedLocation?.geonameid === 0) {
                    void loadGlobalPanel(nextUnit);
                  } else {
                    void loadPanel(lat, lon, nextUnit);
                  }
                }}
              >
                {unit === "C" ? "°C" : "°F"}
              </button>
            ) : null}
            {activeLayerDescription ? (
              <InfoBubble
                className={styles.globeLegendInfoBubble}
                label={`Layer description for ${activeLayer?.label ?? "active layer"}`}
                text={activeLayerDescription}
                preferAboveOnMobile
              />
            ) : null}
          </aside>
        ) : null}
        {debugMode ? (
          <aside className={styles.debugHud} aria-label="Debug panel bbox info">
            <div>debug=on</div>
            <div>
              query: lat={lat.toFixed(5)} lon={lon.toFixed(5)}
            </div>
            <div>bbox_grid: {resp?.location?.panel_bbox_grid_id ?? "null"}</div>
            <div>in_bbox: {debugInBbox ? "true" : "false"}</div>
            <div>
              bbox:
              {debugBbox
                ? ` [${debugBbox.lat_min.toFixed(5)}, ${debugBbox.lat_max.toFixed(5)}] x [${debugBbox.lon_min.toFixed(5)}, ${debugBbox.lon_max.toFixed(5)}]`
                : " null"}
            </div>
            <div>
              map:
              {textureDebugInfo
                ? ` ${textureDebugInfo.filename} (${textureDebugInfo.width ?? "?"}x${textureDebugInfo.height ?? "?"}) variant=${textureDebugInfo.variant} max_texture=${textureDebugInfo.maxTextureSize ?? "unknown"} override=${textureVariantOverride}`
                : " none"}
            </div>
          </aside>
        ) : null}
      </div>

      <ColdOpenOverlay
        active={coldOpen}
        paused={aboutOpen || sourcesOpen}
        onVisibleChange={setIntroActive}
        onShowMapChange={setIntroShowMap}
        onAutoRotateChange={setColdOpenAutoRotate}
        accentColor={globeBackground.accentColor}
      />

      <SearchOverlay
        className={styles.searchOverlay}
        apiBase={apiBase}
        releaseForSession={releaseForSession}
        onLocationSelect={applyLocation}
        externalError={locationError}
      />
      {!introActive ? (
        <div className={styles.sourcesLinkDock}>
          <button
            type="button"
            className={styles.searchMetaLink}
            onClick={() => setOverlayOpenWithUrl("about")}
          >
            About
          </button>
          <button
            type="button"
            className={styles.searchMetaLink}
            onClick={() => setOverlayOpenWithUrl("sources")}
          >
            Sources
          </button>
        </div>
      ) : null}

      {aboutOpen ? (
        <AboutOverlay
          onClose={() => setOverlayOpenWithUrl(null)}
          appVersion={appVersion}
          assetsRelease={assetsRelease ?? sessionRelease ?? requestedRelease}
        />
      ) : null}

      {sourcesOpen ? (
        <SourcesOverlay onClose={() => setOverlayOpenWithUrl(null)} />
      ) : null}

      <aside
        ref={panelRef}
        className={`${styles.locationPanel} ${panelOpen ? styles.locationPanelOpen : ""} ${panelDragActive ? styles.locationPanelDragging : ""}`}
        aria-live="polite"
        tabIndex={0}
        style={
          panelDragTransform ? { transform: panelDragTransform } : undefined
        }
        onWheel={handlePanelWheel}
        onKeyDown={handlePanelKeyDown}
        onTouchStart={handlePanelTouchStart}
        onTouchMove={handlePanelTouchMove}
        onTouchEnd={handlePanelTouchEnd}
        onTouchCancel={handlePanelTouchCancel}
      >
        {panelTab === "graph" && stepCount >= 2 ? (
          <div
            className={styles.panelSteps}
            role="tablist"
            aria-label="Graph steps"
          >
            {Array.from({ length: stepCount }, (_, idx) => {
              const handleStepClick = () => {
                const changed = goToGraphPage(idx);
                if (!changed) return;
                wheelAccumRef.current = 0;
                wheelGestureConsumedRef.current = false;
                wheelGestureConsumedAtRef.current = 0;
              };
              const panelId =
                pagedGraphs[idx * graphsPerPage]?.panelId ?? "";
              return (
                <PanelStepIcon
                  key={`step-icon-${idx}`}
                  panelId={panelId}
                  active={idx === graphPage}
                  label={`Go to step ${idx + 1} of ${stepCount}`}
                  onClick={handleStepClick}
                />
              );
            })}
          </div>
        ) : null}

        <div className={styles.panelActions}>
          <div className={styles.panelTopRow}>
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
                      {CLIMATE_DATA_LOAD_ERROR}
                    </span>
                  ) : panelLoading ? (
                    <span>Loading climate data...</span>
                  ) : panelHeadline?.type === "air_temp" ? (
                    <>
                      {resp?.location.place.geonameid === 0 ? (
                        <>Globally,{" "}</>
                      ) : (
                        <><span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}</>
                      )}
                      {panelHeadline.warming ? (
                        <>
                          <span className={styles.panelTitleSmall}>the air has warmed by </span>
                          <span className={styles.panelTitleTempAccent}>
                            {formatHeadlineDelta(panelHeadline.preindustrial, unit)}
                          </span>
                          <span className={styles.panelTitleSmall}>
                            {" "}since the pre-industrial era (1850–1900)
                            {panelHeadline.recent !== null
                              ? `, of which ${formatHeadlineDelta(panelHeadline.recent, unit)} since 1979`
                              : ""}.
                          </span>
                        </>
                      ) : panelHeadline.recent !== null ? (
                        <>
                          <span className={styles.panelTitleSmall}>the air has warmed by </span>
                          <span className={styles.panelTitleTempAccent}>
                            {formatHeadlineDelta(panelHeadline.recent, unit)}
                          </span>
                          <span className={styles.panelTitleSmall}> since 1979.</span>
                        </>
                      ) : (
                        <span className={styles.panelTitleSmall}>
                          the air has not warmed since the pre-industrial era (1850–1900).
                        </span>
                      )}
                    </>
                  ) : panelHeadline?.type === "temp_delta" ? (
                    <>
                      {resp?.location.place.geonameid === 0 ? (
                        <>Globally,{" "}</>
                      ) : (
                        <><span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}</>
                      )}
                      <span className={styles.panelTitleSmall}>{panelHeadline.action} </span>
                      <span className={styles.panelTitleTempAccent}>
                        {formatHeadlineDelta(panelHeadline.value, unit)}
                      </span>
                      <span className={styles.panelTitleSmall}> {panelHeadline.suffix}.</span>
                    </>
                  ) : panelHeadline?.type === "no_warming" ? (
                    <>
                      {resp?.location.place.geonameid === 0 ? (
                        <>Globally,{" "}</>
                      ) : (
                        <><span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}</>
                      )}
                      <span className={styles.panelTitleSmall}>{panelHeadline.text}</span>
                    </>
                  ) : panelHeadline?.type === "trend" ? (
                    <>
                      {resp?.location.place.geonameid === 0 ? (
                        <>Globally,{" "}</>
                      ) : (
                        <><span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}</>
                      )}
                      <span className={styles.panelTitleSmall}>{panelHeadline.label} {panelHeadline.direction} to </span>
                      <span className={styles.panelTitleTempAccent}>
                        {panelHeadline.value >= 0 ? "+" : ""}{Math.round(panelHeadline.value)}
                      </span>
                      <span className={styles.panelTitleSmall}>{panelHeadline.suffix}.</span>
                    </>
                  ) : panelHeadline?.type === "coral_factor" ? (
                    <>
                      <span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}
                      <span className={styles.panelTitleSmall}>the number of days of severe coral heat stress has multiplied by </span>
                      <span className={styles.panelTitleTempAccent}>{panelHeadline.factor.toFixed(1)}×</span>
                      <span className={styles.panelTitleSmall}> since 1985.</span>
                    </>
                  ) : panelHeadline?.type === "coral_stable" ? (
                    <>
                      <span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}
                      <span className={styles.panelTitleSmall}>the number of days of severe coral heat stress has remained stable since 1985.</span>
                    </>
                  ) : panelHeadline?.type === "coral_no_days" ? (
                    <>
                      <span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}
                      <span className={styles.panelTitleSmall}>no days of severe coral heat stress have been recorded in recent years.</span>
                    </>
                  ) : panelHeadline?.type === "coral_absolute" ? (
                    <>
                      {resp?.location.place.geonameid === 0 ? (
                        <>Globally,{" "}</>
                      ) : (
                        <><span className={styles.panelTitleSmall}>In</span>{" "}{titleLocationLabel},{" "}</>
                      )}
                      <span className={styles.panelTitleSmall}>there are now </span>
                      <span className={styles.panelTitleTempAccent}>+{Math.round(panelHeadline.days)}</span>
                      <span className={styles.panelTitleSmall}> days of severe coral heat stress per year.</span>
                    </>
                  ) : panelHeadline?.type === "sst_unavailable" ? (
                    <>
                      <span className={styles.panelTitleSmall}>Sea temperature data not available in</span>{" "}
                      {titleLocationLabel}.{" "}
                      {panelHeadline.globalDelta !== null ? (
                        <>
                          <span className={styles.panelTitleSmall}>Globally, the sea has warmed of </span>
                          <span className={styles.panelTitleTempAccent}>{formatHeadlineDelta(panelHeadline.globalDelta, unit)}</span>
                          <span className={styles.panelTitleSmall}> since 1982.</span>
                        </>
                      ) : null}
                    </>
                  ) : panelHeadline?.type === "coral_unavailable" ? (
                    <>
                      <span className={styles.panelTitleSmall}>Coral stress data not available in</span>{" "}
                      {titleLocationLabel}.{" "}
                      {panelHeadline.globalDays !== null ? (
                        <>
                          <span className={styles.panelTitleSmall}>Globally, there are now </span>
                          <span className={styles.panelTitleTempAccent}>+{Math.round(panelHeadline.globalDays)}</span>
                          <span className={styles.panelTitleSmall}> days of severe coral heat stress per year.</span>
                        </>
                      ) : null}
                    </>
                  ) : resp ? (
                    <span>{titleLocationLabel}</span>
                  ) : (
                    <span>Pick a location to load climate data.</span>
                  )}
                  {!panelLoadError ? (
                    <InfoBubble
                      label="Panel title information"
                      text={panelTitleInfoText}
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

        {panelTab === "graph" ? (
          <>
            <div
              ref={panelViewportCallbackRef}
              className={styles.panelViewport}
            >
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
                    available={entry.available}
                    onSelectLayer={
                      entry.graph.id === "dhw_risk_days"
                        ? () => {
                            setActiveLayerId("reef_stress");
                            const bbox = nearestCoralBbox(
                              picked?.lat ?? 0,
                              picked?.lon ?? 0,
                            );
                            setChatFlyToBbox(bbox);
                          }
                        : undefined
                    }
                  />
                ) : null,
              )}
            </div>
            {stepCount >= 2 ? (
              <div className={styles.panelScrollNav}>
                <button
                  type="button"
                  className={`${styles.panelScrollArrow} ${styles.panelScrollArrowPrev}`}
                  aria-label="Previous graphs"
                  onClick={() => {
                    const next = graphPage > 0 ? graphPage - 1 : maxGraphPage;
                    goToGraphPage(next);
                    wheelAccumRef.current = 0;
                    wheelGestureConsumedRef.current = false;
                    wheelGestureConsumedAtRef.current = 0;
                  }}
                >
                  <svg
                    viewBox="0 0 14.51 35.1"
                    width="14"
                    height="35"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <polygon points="0,7.91 6.94,0.34 7.26,0 7.57,0.34 14.51,7.91 14.04,8.35 7.57,1.3 7.57,35.1 6.94,35.1 6.94,1.3 0.47,8.35" />
                  </svg>
                </button>
                <button
                  type="button"
                  className={`${styles.panelScrollArrow} ${styles.panelScrollArrowNext}`}
                  aria-label="Next graphs"
                  onClick={() => {
                    const next = graphPage < maxGraphPage ? graphPage + 1 : 0;
                    goToGraphPage(next);
                    wheelAccumRef.current = 0;
                    wheelGestureConsumedRef.current = false;
                    wheelGestureConsumedAtRef.current = 0;
                  }}
                >
                  <svg
                    viewBox="0 0 14.51 35.1"
                    width="14"
                    height="35"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <polygon points="0,7.91 6.94,0.34 7.26,0 7.57,0.34 14.51,7.91 14.04,8.35 7.57,1.3 7.57,35.1 6.94,35.1 6.94,1.3 0.47,8.35" />
                  </svg>
                </button>
              </div>
            ) : null}
          </>
        ) : null}

        {chatEnabled ? (
          <ChatDrawer
            embedded
            embeddedVisible={panelTab === "chat"}
            apiBase={apiBase}
            mapContext={
              selectedLocation
                ? {
                    lat,
                    lon,
                    label: selectedLocation.label,
                    countryCode: selectedLocation.countryCode,
                  }
                : null
            }
            unit={unit}
            devMode={debugMode}
            debugMode={debugMode}
            onLocations={(locs) => {
              setChatLocations(locs && locs.length > 0 ? [...locs] : null);
              setChatFlyToBbox(null);
            }}
            onPickLocation={(la, lo) => void handlePick(la, lo, true, false)}
            onFlyToBbox={(bbox) => {
              setChatFlyToBbox(bbox);
              setChatLocations(null);
            }}
            onClose={() => setPanelOpen(false)}
            onSwitchToGraph={() => setPanelTab("graph")}
          />
        ) : null}

        <div className={styles.panelBottomBar}>
          {panelTab === "graph" ? (
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
                  if (selectedLocation?.geonameid === 0) {
                    void loadGlobalPanel("C");
                  } else {
                    void loadPanel(lat, lon, "C");
                  }
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
                  if (selectedLocation?.geonameid === 0) {
                    void loadGlobalPanel("F");
                  } else {
                    void loadPanel(lat, lon, "F");
                  }
                }}
              >
                °F
              </button>
            </div>
          ) : null}
        </div>
      </aside>

      <button
        className={`${styles.panelOpenTab} ${!panelOpen && selectedLocation !== null ? styles.panelOpenTabVisible : ""}`}
        type="button"
        aria-label={`Open ${selectedLocation?.label ?? ""} location panel`}
        onClick={() => setPanelOpen(true)}
      >
        <svg
          className={styles.panelOpenTabIcon}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M15 18L9 12L15 6" />
        </svg>
        <span className={styles.panelOpenTabLabel}>
          {selectedLocation?.label ?? ""}
        </span>
      </button>
    </main>
  );
}
