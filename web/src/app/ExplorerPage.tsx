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
import { useDebugTextureSync } from "@/hooks/explorer/useDebugTextureSync";
import { useOverlayRouteSync } from "@/hooks/explorer/useOverlayRouteSync";
import { useReleaseResolution } from "@/hooks/explorer/useReleaseResolution";
import {
  CLIMATE_DATA_LOAD_ERROR,
  DEFAULT_OVERLAY_BASE_PATH,
  DEFAULT_TITLE_ACTION_TEXT,
  MIN_PANEL_VIEWPORT_HEIGHT_FOR_TWO_GRAPHS,
  PANEL_TITLE_INFO_PREINDUSTRIAL,
  PANEL_TITLE_INFO_RECENT,
  PREINDUSTRIAL_TITLE_SUFFIX,
  TOUCH_CLOSE_PANEL_THRESHOLD_PX,
  TOUCH_PANEL_LIFT_MAX_PX,
  TOUCH_PANEL_PULL_MAX_PX,
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
    unit: string;
    baseline?: string | null;
    period?: string | null;
    method?: string | null;
  }>;
  layer_overrides?: Record<
    string,
    {
      default_graph_ids: string[];
      title_mode: "preindustrial" | "recent_trend";
      title_metric_key?: string | null;
      title_suffix?: string | null;
      title_action_text?: string | null;
      title_action_text_non_positive?: string | null;
    }
  >;
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
};

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
  const [panelDragOffsetPx, setPanelDragOffsetPx] = useState(0);
  const [panelDragActive, setPanelDragActive] = useState(false);
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(
    null,
  );
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
  const touchGestureAxisRef = useRef<"x" | "y" | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const panelViewportRef = useRef<HTMLDivElement | null>(null);
  const pendingGraphRestoreIdsRef = useRef<string[] | null>(null);
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
  const { aboutOpen, sourcesOpen, setOverlayOpenWithUrl } = useOverlayRouteSync(
    {
      initialOverlay,
      initialOverlayBasePath,
    },
  );
  const { debugMode, textureVariantOverride } =
    useDebugTextureSync(debugAllowed);
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
  const activeTitleMode = activeLayerOverride?.title_mode ?? "preindustrial";
  const activeTitleMetricKey =
    activeLayerOverride?.title_metric_key ??
    (activeTitleMode === "preindustrial" ? "t2m_vs_preindustrial_local" : null);
  const activeTitleSuffix =
    activeLayerOverride?.title_suffix ??
    (activeTitleMode === "preindustrial" ? PREINDUSTRIAL_TITLE_SUFFIX : "");
  const requestedTitleHeadline = useMemo(() => {
    if (!resp?.headlines?.length || !activeTitleMetricKey) return null;
    return resp.headlines.find((h) => h.key === activeTitleMetricKey) ?? null;
  }, [activeTitleMetricKey, resp]);
  const preindustrialHeadline = useMemo(() => {
    if (!resp?.headlines?.length) return null;
    return (
      resp.headlines.find((h) => h.key === "t2m_vs_preindustrial_local") ?? null
    );
  }, [resp]);
  const shouldFallbackToPreindustrial =
    activeTitleMetricKey === "sst_recent_local" &&
    !(
      typeof requestedTitleHeadline?.value === "number" &&
      Number.isFinite(requestedTitleHeadline.value)
    );
  const effectiveTitleMode = shouldFallbackToPreindustrial
    ? "preindustrial"
    : activeTitleMode;
  const effectiveTitleSuffix = shouldFallbackToPreindustrial
    ? PREINDUSTRIAL_TITLE_SUFFIX
    : activeTitleSuffix;
  const effectiveTitleActionText = shouldFallbackToPreindustrial
    ? DEFAULT_TITLE_ACTION_TEXT
    : (activeLayerOverride?.title_action_text ?? DEFAULT_TITLE_ACTION_TEXT);
  const effectiveTitleActionTextNonPositive = shouldFallbackToPreindustrial
    ? null
    : (activeLayerOverride?.title_action_text_non_positive ?? null);
  const tempHeadline = shouldFallbackToPreindustrial
    ? preindustrialHeadline
    : requestedTitleHeadline;
  const shouldUseNoWarmingWording =
    typeof tempHeadline?.value === "number" &&
    Number.isFinite(tempHeadline.value) &&
    tempHeadline.value <= 0 &&
    typeof effectiveTitleActionTextNonPositive === "string" &&
    effectiveTitleActionTextNonPositive.trim().length > 0;
  const resolvedTitleActionText = shouldUseNoWarmingWording
    ? (effectiveTitleActionTextNonPositive?.trim() ?? effectiveTitleActionText)
    : effectiveTitleActionText;
  useEffect(() => {
    if (defaultTemperatureUnitForLocale() !== "F") return;
    setUnit("F");
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

  const basePagedGraphs = useMemo<PagedGraphItem[]>(
    () =>
      panelData.flatMap(({ panel, graphs }) =>
        graphs.map(({ graph, data }) => ({ panelId: panel.id, graph, data })),
      ),
    [panelData],
  );
  const pagedGraphs = useMemo<PagedGraphItem[]>(() => {
    const orderedIds = activeLayerOverride?.default_graph_ids ?? [];
    if (!orderedIds.length) return basePagedGraphs;
    const picked = new Set<string>();
    const out: PagedGraphItem[] = [];
    orderedIds.forEach((graphId) => {
      const match = basePagedGraphs.find(
        (entry) => entry.graph.id === graphId && !picked.has(entry.graph.id),
      );
      if (!match) return;
      out.push(match);
      picked.add(match.graph.id);
    });
    basePagedGraphs.forEach((entry) => {
      if (picked.has(entry.graph.id)) return;
      out.push(entry);
    });
    return out;
  }, [activeLayerOverride?.default_graph_ids, basePagedGraphs]);
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
    if (!panelOpen) {
      pendingGraphRestoreIdsRef.current = null;
      return;
    }
    const visibleIds = visibleGraphs
      .map((entry) => entry?.graph.id)
      .filter((id): id is string => typeof id === "string" && id.length > 0);
    pendingGraphRestoreIdsRef.current =
      visibleIds.length > 0 ? visibleIds : null;
  }, [panelOpen, visibleGraphs]);

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
    if (pendingGraphRestoreIdsRef.current) return;
    setGraphPage(0);
  }, [activeLayerId]);

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
      setPanelLoadError(CLIMATE_DATA_LOAD_ERROR);
      return null;
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
    queueGraphRestoreFromVisible();
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
    const viewport = panelViewportRef.current;
    if (!viewport) return;
    const updateGraphsPerPage = () => {
      const next =
        viewport.clientHeight < MIN_PANEL_VIEWPORT_HEIGHT_FOR_TWO_GRAPHS
          ? 1
          : 2;
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

  useEffect(() => {
    if (panelOpen) return;
    pendingGraphRestoreIdsRef.current = null;
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
      goGraphPage(deltaX < 0 ? 1 : -1);
    },
    [goGraphPage, TOUCH_CLOSE_PANEL_THRESHOLD_PX, TOUCH_SWIPE_THRESHOLD_PX],
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
    effectiveTitleMode === "preindustrial"
      ? PANEL_TITLE_INFO_PREINDUSTRIAL
      : PANEL_TITLE_INFO_RECENT;
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
          }}
          enablePick={!introActive}
          autoRotate={coldOpenAutoRotate}
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
                  queueGraphRestoreFromVisible();
                  setUnit(nextUnit);
                  void loadPanel(lat, lon, nextUnit);
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
                      {CLIMATE_DATA_LOAD_ERROR}
                    </span>
                  ) : panelLoading ? (
                    <span>Loading climate data...</span>
                  ) : typeof tempHeadline?.value === "number" &&
                    Number.isFinite(tempHeadline.value) ? (
                    <>
                      <span className={styles.panelTitleSmall}>In</span>{" "}
                      {titleLocationLabel},{" "}
                      <span className={styles.panelTitleSmall}>
                        {resolvedTitleActionText}
                        {!shouldUseNoWarmingWording ? " " : ""}
                      </span>
                      {!shouldUseNoWarmingWording ? (
                        <span className={styles.panelTitleTempAccent}>
                          {formatHeadlineDelta(tempHeadline.value, unit)}
                        </span>
                      ) : null}
                      <span className={styles.panelTitleSmall}>
                        {" "}
                        {effectiveTitleSuffix}
                      </span>
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
