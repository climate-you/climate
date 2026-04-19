"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import type { FeatureCollection, Polygon } from "geojson";
import {
  AUTO_ROTATE_DEG_PER_SEC,
  BACKDROP_BLUE,
  BACKDROP_DARK_MODE,
  BACKDROP_WHITE,
  CHAT_DRAWER_BREAKPOINT_PX,
  CHAT_DRAWER_DESKTOP_RIGHT_PX,
  CHAT_DRAWER_MOBILE_BOTTOM_PX,
  CHAT_DRAWER_MOBILE_HEIGHT_MAX_PX,
  CHAT_DRAWER_MOBILE_HEIGHT_RATIO,
  CITY_SNAP_LAYER_IDS,
  CITY_SNAP_MAX_ZOOM,
  CITY_SNAP_RADIUS_PX,
  DATELINE_OVERDRAW_DEG,
  DEBUG_BBOX_FILL_LAYER_ID,
  DEBUG_BBOX_LAYER_ID,
  DEBUG_BBOX_SOURCE_ID,
  DEFAULT_BASE_ZOOM,
  DESKTOP_PANEL_WIDTH_RATIO,
  FOCUS_FLY_DURATION_MS,
  FOCUS_LOCATION_ZOOM,
  FOCUS_RECENTER_DURATION_MS,
  HOME_FLY_DURATION_MS,
  LAYER_MENU_AUTO_CLOSE_MS,
  LAYER_MENU_FADE_MS,
  MARKER_COLOR,
  MERCATOR_MAX_LAT,
  MOBILE_PANEL_HEIGHT_RATIO,
  MOBILE_TEXTURE_FALLBACK_LIMIT,
  PANEL_BREAKPOINT_PX,
  PANEL_TRANSITION_MS,
  TEXTURE_LAYER_ID,
  TEXTURE_SOURCE_ID,
} from "@/lib/explorer/constants";

type LngLat = { lat: number; lon: number };
export type MapLayerOption = {
  id: string;
  label: string;
  imageUrl?: string;
  imageWidth?: number;
  imageHeight?: number;
  mobileImageUrl?: string;
  mobileImageWidth?: number;
  mobileImageHeight?: number;
  projectionBounds?: {
    lat_min: number;
    lat_max: number;
    lon_min: number;
    lon_max: number;
  };
  opacity?: number;
  resampling?: "linear" | "nearest";
};

export type TextureDebugInfo = {
  filename: string;
  width: number | null;
  height: number | null;
  variant: "full" | "mobile";
  maxTextureSize: number | null;
};

export type TextureVariantOverride = "auto" | "mobile" | "full";

type Props = {
  panelOpen: boolean;
  focusLocation: LngLat | null;
  layerOptions: MapLayerOption[];
  activeLayerId: string | null;
  onLayerChange: (layerId: string) => void;
  onLayerMenuOpen?: () => void;
  onPick: (lat: number, lon: number) => void;
  onHome: () => void;
  showControls?: boolean;
  enablePick?: boolean;
  warmingLayerVisible?: boolean;
  showDebugOverlay?: boolean;
  debugBbox?: {
    lat_min: number;
    lat_max: number;
    lon_min: number;
    lon_max: number;
  } | null;
  debugBboxGridId?: string | null;
  textureVariantOverride?: TextureVariantOverride;
  onTextureDebugInfoChange?: (info: TextureDebugInfo | null) => void;
  autoRotate?: boolean;
  chatLocations?: Array<{ label: string; rank?: number; lat: number; lon: number }> | null;
  chatFlyToBbox?: [number, number, number, number] | null;
  onPickChatMarker?: (lat: number, lon: number) => void;
  backgroundImageUrl?: string;
};

const initialView = {
  center: [0, 0] as [number, number],
  pitch: 0,
  bearing: 0,
};

function baseZoomForViewportWidth(width: number) {
  if (width <= 480) return 1.0;
  if (width <= PANEL_BREAKPOINT_PX) return 2.0;
  return DEFAULT_BASE_ZOOM;
}

function responsiveBaseZoom() {
  return baseZoomForViewportWidth(window.innerWidth);
}

function cubicOut(t: number) {
  return 1 - Math.pow(1 - t, 3);
}

function panelPaddingForViewport(map: maplibregl.Map, panelOpen: boolean) {
  if (!panelOpen) return { top: 0, right: 0, bottom: 0, left: 0 };

  const mapRect = map.getContainer().getBoundingClientRect();
  const isMobile = window.matchMedia(
    `(max-width: ${PANEL_BREAKPOINT_PX}px)`,
  ).matches;

  if (isMobile) {
    return {
      top: 0,
      right: 0,
      bottom: Math.round(mapRect.height * MOBILE_PANEL_HEIGHT_RATIO),
      left: 0,
    };
  }

  return {
    top: 0,
    right: Math.round(mapRect.width * DESKTOP_PANEL_WIDTH_RATIO),
    bottom: 0,
    left: 0,
  };
}

function chatDrawerPaddingForViewport(map: maplibregl.Map) {
  const BASE_PAD = 80;
  const mapRect = map.getContainer().getBoundingClientRect();
  const isMobile = window.matchMedia(
    `(max-width: ${CHAT_DRAWER_BREAKPOINT_PX}px)`,
  ).matches;
  if (isMobile) {
    const drawerH =
      Math.min(window.innerHeight * CHAT_DRAWER_MOBILE_HEIGHT_RATIO, CHAT_DRAWER_MOBILE_HEIGHT_MAX_PX) +
      CHAT_DRAWER_MOBILE_BOTTOM_PX;
    const bottomPad = Math.min(BASE_PAD + drawerH, mapRect.height * 0.85);
    return { top: BASE_PAD, bottom: bottomPad, left: BASE_PAD, right: BASE_PAD };
  }
  const rightPad = Math.min(BASE_PAD + CHAT_DRAWER_DESKTOP_RIGHT_PX, mapRect.width * 0.6);
  return { top: BASE_PAD, bottom: BASE_PAD, left: BASE_PAD, right: rightPad };
}

function setBackdropColor(map: maplibregl.Map, color: string) {
  map.getContainer().style.backgroundColor = color;
  map.getCanvas().style.backgroundColor = color;
}

function textureCoordinates(
  layer?: MapLayerOption | null,
): [[number, number], [number, number], [number, number], [number, number]] {
  const bounds = layer?.projectionBounds;
  const lonMin = typeof bounds?.lon_min === "number" ? bounds.lon_min : -180;
  const lonMax = typeof bounds?.lon_max === "number" ? bounds.lon_max : 180;
  const latMin =
    typeof bounds?.lat_min === "number" ? bounds.lat_min : -MERCATOR_MAX_LAT;
  const latMax =
    typeof bounds?.lat_max === "number" ? bounds.lat_max : MERCATOR_MAX_LAT;
  return [
    [lonMin - DATELINE_OVERDRAW_DEG, latMax],
    [lonMax + DATELINE_OVERDRAW_DEG, latMax],
    [lonMax + DATELINE_OVERDRAW_DEG, latMin],
    [lonMin - DATELINE_OVERDRAW_DEG, latMin],
  ];
}

function textureLayerBeforeId(map: maplibregl.Map): string | undefined {
  const preferredForegroundLayers = [
    "coast",
    "boundary_3",
    "boundary_2",
    "boundary_disputed",
    "label_country_3",
    "label_country_2",
    "label_country_1",
    "label_city",
    "label_city_capital",
  ];
  for (const layerId of preferredForegroundLayers) {
    if (map.getLayer(layerId)) return layerId;
  }

  const styleLayers = map.getStyle()?.layers ?? [];
  const firstSymbol = styleLayers.find((layer) => layer.type === "symbol");
  return firstSymbol?.id;
}

function focusZoomTarget(map: maplibregl.Map): number {
  return Math.max(map.getZoom(), FOCUS_LOCATION_ZOOM);
}

function getMaxTextureSize(): number | null {
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl");
    if (!gl) return null;
    const max = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    return typeof max === "number" && Number.isFinite(max) && max > 0
      ? max
      : null;
  } catch {
    return null;
  }
}

function textureFilenameFromUrl(url: string): string {
  const parts = url.split("/");
  const raw = parts[parts.length - 1] ?? "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function selectTextureVariant(
  layer: MapLayerOption,
  maxTextureSize: number | null,
  variantOverride: TextureVariantOverride,
): {
  imageUrl: string;
  width: number | null;
  height: number | null;
  variant: "full" | "mobile";
} | null {
  const fullUrl = layer.imageUrl;
  if (!fullUrl) return null;
  const fullWidth = layer.imageWidth ?? null;
  const fullHeight = layer.imageHeight ?? null;
  const mobileUrl = layer.mobileImageUrl;
  if (variantOverride === "full") {
    return {
      imageUrl: fullUrl,
      width: fullWidth,
      height: fullHeight,
      variant: "full",
    };
  }
  if (variantOverride === "mobile" && mobileUrl) {
    return {
      imageUrl: mobileUrl,
      width: layer.mobileImageWidth ?? null,
      height: layer.mobileImageHeight ?? null,
      variant: "mobile",
    };
  }
  if (!mobileUrl) {
    return {
      imageUrl: fullUrl,
      width: fullWidth,
      height: fullHeight,
      variant: "full",
    };
  }
  if (maxTextureSize === null) {
    return {
      imageUrl: mobileUrl,
      width: layer.mobileImageWidth ?? null,
      height: layer.mobileImageHeight ?? null,
      variant: "mobile",
    };
  }
  if (
    (fullWidth !== null && fullWidth > maxTextureSize) ||
    (fullHeight !== null && fullHeight > maxTextureSize) ||
    (fullWidth === null &&
      fullHeight === null &&
      maxTextureSize <= MOBILE_TEXTURE_FALLBACK_LIMIT)
  ) {
    return {
      imageUrl: mobileUrl,
      width: layer.mobileImageWidth ?? null,
      height: layer.mobileImageHeight ?? null,
      variant: "mobile",
    };
  }
  return {
    imageUrl: fullUrl,
    width: fullWidth,
    height: fullHeight,
    variant: "full",
  };
}

function cityFeatureCoordinates(
  feature: maplibregl.MapGeoJSONFeature,
): [number, number] | null {
  if (feature.geometry.type !== "Point") return null;
  const coords = feature.geometry.coordinates;
  if (!Array.isArray(coords) || coords.length < 2) return null;
  const lng = Number(coords[0]);
  const lat = Number(coords[1]);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  return [lng, lat];
}

function snapTargetAtLowZoom(
  map: maplibregl.Map,
  event: maplibregl.MapMouseEvent,
): [number, number] | null {
  if (map.getZoom() > CITY_SNAP_MAX_ZOOM) return null;
  const layers = CITY_SNAP_LAYER_IDS.filter((id) => Boolean(map.getLayer(id)));
  if (!layers.length) return null;

  const { x, y } = event.point;
  const radius = CITY_SNAP_RADIUS_PX;
  const features = map.queryRenderedFeatures(
    [
      [x - radius, y - radius],
      [x + radius, y + radius],
    ],
    { layers },
  );
  if (!features.length) return null;

  let best: [number, number] | null = null;
  let bestDistanceSq = Number.POSITIVE_INFINITY;
  for (const feature of features) {
    const coords = cityFeatureCoordinates(feature);
    if (!coords) continue;
    const projected = map.project({ lng: coords[0], lat: coords[1] });
    const dx = projected.x - x;
    const dy = projected.y - y;
    const distanceSq = dx * dx + dy * dy;
    if (distanceSq < bestDistanceSq) {
      bestDistanceSq = distanceSq;
      best = coords;
    }
  }
  return best;
}

export default function MapLibreGlobe({
  panelOpen,
  focusLocation,
  layerOptions,
  activeLayerId,
  onLayerChange,
  onLayerMenuOpen,
  onPick,
  onHome,
  showControls = true,
  enablePick = true,
  warmingLayerVisible = false,
  showDebugOverlay = false,
  debugBbox = null,
  debugBboxGridId = null,
  textureVariantOverride = "auto",
  onTextureDebugInfoChange,
  autoRotate = false,
  chatLocations = null,
  chatFlyToBbox = null,
  onPickChatMarker,
  backgroundImageUrl,
}: Props) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const layerControlRef = useRef<{ refresh: () => void } | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const chatMarkersRef = useRef<maplibregl.Marker[]>([]);
  const onPickRef = useRef(onPick);
  const onPickChatMarkerRef = useRef(onPickChatMarker);
  const onHomeRef = useRef(onHome);
  const onLayerChangeRef = useRef(onLayerChange);
  const onLayerMenuOpenRef = useRef(onLayerMenuOpen);
  const panelOpenRef = useRef(panelOpen);
  const focusLocationRef = useRef(focusLocation);
  const layerOptionsRef = useRef(layerOptions);
  const activeLayerIdRef = useRef(activeLayerId);
  const showControlsRef = useRef(showControls);
  const enablePickRef = useRef(enablePick);
  const showDebugOverlayRef = useRef(showDebugOverlay);
  const debugBboxRef = useRef(debugBbox);
  const debugBboxGridIdRef = useRef(debugBboxGridId);
  const textureVariantOverrideRef = useRef(textureVariantOverride);
  const onTextureDebugInfoChangeRef = useRef(onTextureDebugInfoChange);
  const autoRotateRef = useRef(autoRotate);
  const backgroundImageUrlRef = useRef(backgroundImageUrl);
  const applyGlobeBackgroundRef = useRef<(() => void) | null>(null);
  const maxTextureSizeRef = useRef<number | null>(null);
  const textureBackdropRef = useRef<string>(BACKDROP_WHITE);
  const styleReadyRef = useRef(false);
  const [prefersDarkMode, setPrefersDarkMode] = useState(false);

  const textureBackdrop =
    prefersDarkMode && warmingLayerVisible
      ? BACKDROP_DARK_MODE
      : BACKDROP_WHITE;

  useEffect(() => {
    onPickRef.current = onPick;
  }, [onPick]);

  useEffect(() => {
    onPickChatMarkerRef.current = onPickChatMarker;
  }, [onPickChatMarker]);

  useEffect(() => {
    onHomeRef.current = onHome;
  }, [onHome]);

  useEffect(() => {
    onLayerChangeRef.current = onLayerChange;
  }, [onLayerChange]);

  useEffect(() => {
    onLayerMenuOpenRef.current = onLayerMenuOpen;
  }, [onLayerMenuOpen]);

  useEffect(() => {
    panelOpenRef.current = panelOpen;
  }, [panelOpen]);

  useEffect(() => {
    focusLocationRef.current = focusLocation;
  }, [focusLocation]);

  useEffect(() => {
    layerOptionsRef.current = layerOptions;
  }, [layerOptions]);

  useEffect(() => {
    activeLayerIdRef.current = activeLayerId;
  }, [activeLayerId]);

  useEffect(() => {
    showControlsRef.current = showControls;
  }, [showControls]);

  useEffect(() => {
    enablePickRef.current = enablePick;
  }, [enablePick]);

  useEffect(() => {
    showDebugOverlayRef.current = showDebugOverlay;
  }, [showDebugOverlay]);

  useEffect(() => {
    debugBboxRef.current = debugBbox;
  }, [debugBbox]);

  useEffect(() => {
    debugBboxGridIdRef.current = debugBboxGridId;
  }, [debugBboxGridId]);

  useEffect(() => {
    textureVariantOverrideRef.current = textureVariantOverride;
  }, [textureVariantOverride]);

  useEffect(() => {
    onTextureDebugInfoChangeRef.current = onTextureDebugInfoChange;
  }, [onTextureDebugInfoChange]);

  useEffect(() => {
    autoRotateRef.current = autoRotate;
  }, [autoRotate]);

  useEffect(() => {
    backgroundImageUrlRef.current = backgroundImageUrl;
    applyGlobeBackgroundRef.current?.();
  }, [backgroundImageUrl]);

  useEffect(() => {
    textureBackdropRef.current = textureBackdrop;
  }, [textureBackdrop]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setPrefersDarkMode(media.matches);
    sync();
    media.addEventListener?.("change", sync);
    return () => media.removeEventListener?.("change", sync);
  }, []);

  useEffect(() => {
    if (!mapContainerRef.current) return;
    maxTextureSizeRef.current = getMaxTextureSize();

    const baseZoom = responsiveBaseZoom();
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: "/custom_map.json",
      center: initialView.center,
      zoom: baseZoom,
      minZoom: baseZoom,
      maxZoom: 10,
      pitch: initialView.pitch,
      bearing: initialView.bearing,
      attributionControl: false,
    });
    mapRef.current = map;

    function applyMapSettings() {
      map.setProjection({ type: "globe" });
      setBackdropColor(map, BACKDROP_BLUE);
    }

    function applyGlobeBackground() {
      const url = backgroundImageUrlRef.current;
      const container = map.getContainer();
      const canvas = map.getCanvas();
      if (url) {
        container.style.backgroundImage = `url('${url}')`;
        container.style.backgroundSize = "cover";
        container.style.backgroundPosition = "center";
        container.style.backgroundColor = "transparent";
        // The WebGL canvas has transparent pixels outside the globe sphere.
        // Setting backgroundColor to transparent lets the container image show through.
        canvas.style.backgroundColor = "transparent";
      } else {
        container.style.backgroundImage = "";
        container.style.backgroundColor = BACKDROP_BLUE;
        canvas.style.backgroundColor = BACKDROP_BLUE;
      }
    }
    applyGlobeBackgroundRef.current = applyGlobeBackground;

    function applyTextureLayer() {
      const selected = layerOptionsRef.current.find(
        (layer) => layer.id === activeLayerIdRef.current,
      );
      if (!selected) {
        setBackdropColor(map, BACKDROP_BLUE);
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        onTextureDebugInfoChangeRef.current?.(null);
        return;
      }
      const selectedTexture = selectTextureVariant(
        selected,
        maxTextureSizeRef.current,
        textureVariantOverrideRef.current,
      );
      if (!selectedTexture) {
        setBackdropColor(map, BACKDROP_BLUE);
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        onTextureDebugInfoChangeRef.current?.(null);
        return;
      }
      setBackdropColor(map, textureBackdropRef.current);
      onTextureDebugInfoChangeRef.current?.({
        filename: textureFilenameFromUrl(selectedTexture.imageUrl),
        width: selectedTexture.width,
        height: selectedTexture.height,
        variant: selectedTexture.variant,
        maxTextureSize: maxTextureSizeRef.current,
      });

      const coordinates = textureCoordinates(selected);
      const existingSource = map.getSource(TEXTURE_SOURCE_ID) as
        | (maplibregl.ImageSource & {
            updateImage?: (args: {
              url: string;
              coordinates: [
                [number, number],
                [number, number],
                [number, number],
                [number, number],
              ];
            }) => void;
          })
        | undefined;

      if (existingSource && typeof existingSource.updateImage === "function") {
        existingSource.updateImage({
          url: selectedTexture.imageUrl,
          coordinates,
        });
      } else {
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        map.addSource(TEXTURE_SOURCE_ID, {
          type: "image",
          url: selectedTexture.imageUrl,
          coordinates,
        });
      }

      if (!map.getLayer(TEXTURE_LAYER_ID)) {
        const beforeId = textureLayerBeforeId(map);
        map.addLayer(
          {
            id: TEXTURE_LAYER_ID,
            type: "raster",
            source: TEXTURE_SOURCE_ID,
            paint: {
              "raster-opacity": selected.opacity ?? 0.72,
              "raster-resampling": selected.resampling ?? "linear",
            },
          },
          beforeId,
        );
      } else {
        map.setPaintProperty(
          TEXTURE_LAYER_ID,
          "raster-opacity",
          selected.opacity ?? 0.72,
        );
      }
      const beforeId = textureLayerBeforeId(map);
      map.moveLayer(TEXTURE_LAYER_ID, beforeId);
    }

    function ensureHillshadeLayer() {
      if (!map.getSource("hillshadeSource")) {
        map.addSource("hillshadeSource", {
          type: "raster-dem",
          tiles: [
            "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
          ],
          encoding: "terrarium",
          tileSize: 256,
          maxzoom: 15,
        });
      }

      if (map.getLayer("hillshade")) return;

      const beforeId = map.getLayer("water") ? "water" : undefined;
      map.addLayer(
        {
          id: "hillshade",
          type: "hillshade",
          source: "hillshadeSource",
          paint: {
            "hillshade-method": "standard",
            "hillshade-illumination-direction": 315,
            "hillshade-shadow-color": "#000000",
            "hillshade-highlight-color": "#FFFFFF",
            "hillshade-accent-color": "#000000",
            "hillshade-exaggeration": 0.5,
          },
        },
        beforeId,
      );
    }

    function applyDebugBboxLayer() {
      const showOverlay = showDebugOverlayRef.current;
      const bbox = debugBboxRef.current;

      if (!showOverlay || !bbox) {
        if (map.getLayer(DEBUG_BBOX_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_LAYER_ID);
        if (map.getLayer(DEBUG_BBOX_FILL_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_FILL_LAYER_ID);
        if (map.getSource(DEBUG_BBOX_SOURCE_ID))
          map.removeSource(DEBUG_BBOX_SOURCE_ID);
        return;
      }

      const coordinates = [
        [bbox.lon_min, bbox.lat_min],
        [bbox.lon_max, bbox.lat_min],
        [bbox.lon_max, bbox.lat_max],
        [bbox.lon_min, bbox.lat_max],
        [bbox.lon_min, bbox.lat_min],
      ];
      const data: FeatureCollection<Polygon> = {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {},
            geometry: { type: "Polygon", coordinates: [coordinates] },
          },
        ],
      };

      const source = map.getSource(DEBUG_BBOX_SOURCE_ID) as
        | (maplibregl.GeoJSONSource & { setData?: (d: unknown) => void })
        | undefined;
      if (source && typeof source.setData === "function") {
        source.setData(data);
      } else {
        if (map.getLayer(DEBUG_BBOX_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_LAYER_ID);
        if (map.getLayer(DEBUG_BBOX_FILL_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_FILL_LAYER_ID);
        if (map.getSource(DEBUG_BBOX_SOURCE_ID))
          map.removeSource(DEBUG_BBOX_SOURCE_ID);
        map.addSource(DEBUG_BBOX_SOURCE_ID, {
          type: "geojson",
          data,
        });
      }

      const lineColor =
        debugBboxGridIdRef.current === "global_0p05" ? "#00c2ff" : "#ff3b30";
      if (!map.getLayer(DEBUG_BBOX_FILL_LAYER_ID)) {
        map.addLayer({
          id: DEBUG_BBOX_FILL_LAYER_ID,
          type: "fill",
          source: DEBUG_BBOX_SOURCE_ID,
          paint: {
            "fill-color": "#fff200",
            "fill-opacity": 0.18,
          },
        });
      }
      if (!map.getLayer(DEBUG_BBOX_LAYER_ID)) {
        map.addLayer({
          id: DEBUG_BBOX_LAYER_ID,
          type: "line",
          source: DEBUG_BBOX_SOURCE_ID,
          paint: {
            "line-color": lineColor,
            "line-width": 4,
            "line-dasharray": [1, 1.5],
          },
        });
      } else {
        map.setPaintProperty(DEBUG_BBOX_LAYER_ID, "line-color", lineColor);
      }
      // Keep debug bbox visible above texture and style layers.
      map.moveLayer(DEBUG_BBOX_FILL_LAYER_ID);
      map.moveLayer(DEBUG_BBOX_LAYER_ID);
    }

    function getPanelPadding() {
      return panelPaddingForViewport(map, panelOpenRef.current);
    }

    function applyCtrlIconStyle(btn: HTMLButtonElement, fontSize: string) {
      btn.style.fontSize = fontSize;
      btn.style.lineHeight = "1";
      btn.style.color = "#111";
    }

    function createHomeControl(): maplibregl.IControl {
      let mapInstance: maplibregl.Map | undefined;
      let container: HTMLDivElement | undefined;
      let button: HTMLButtonElement | undefined;
      const onClick = () => {
        markerRef.current?.remove();
        markerRef.current = null;
        onHomeRef.current();
        const nextBaseZoom = responsiveBaseZoom();
        mapInstance?.setMinZoom(nextBaseZoom);
        mapInstance?.flyTo({
          center: initialView.center,
          zoom: nextBaseZoom,
          pitch: initialView.pitch,
          bearing: initialView.bearing,
          padding: { top: 0, right: 0, bottom: 0, left: 0 },
          duration: HOME_FLY_DURATION_MS,
          essential: true,
        });
      };
      return {
        onAdd(mapArg: maplibregl.Map) {
          mapInstance = mapArg;
          container = document.createElement("div");
          container.className = "maplibregl-ctrl maplibregl-ctrl-group";

          button = document.createElement("button");
          button.type = "button";
          button.className = "maplibregl-ctrl-icon";
          button.ariaLabel = "Return to initial globe position";
          button.title = "Home";
          button.textContent = "⌂";
          applyCtrlIconStyle(button, "26px");
          button.addEventListener("click", onClick);

          container.appendChild(button);
          return container;
        },
        onRemove() {
          button?.removeEventListener("click", onClick);
          container?.remove();
        },
      };
    }

    function createLayerControl(): maplibregl.IControl & {
      refresh: () => void;
    } {
      let container: HTMLDivElement | undefined;
      let button: HTMLButtonElement | undefined;
      let menu: HTMLDivElement | undefined;
      let isOpen = false;
      let autoCloseTimeoutId: number | undefined;
      let hideTimeoutId: number | undefined;
      const isDarkMode = () =>
        window.matchMedia("(prefers-color-scheme: dark)").matches;
      const applyMenuTheme = () => {
        if (!menu) return;
        const dark = isDarkMode();
        menu.style.background = dark ? "#2a2a2a" : "#fff";
        menu.style.border = dark
          ? "1px solid rgba(255, 255, 255, 0.28)"
          : "1px solid rgba(0, 0, 0, 0.18)";
      };
      const isCoarsePointerMode = () =>
        window.matchMedia("(pointer: coarse)").matches ||
        window.matchMedia("(hover: none)").matches;
      const clearAutoCloseTimer = () => {
        if (autoCloseTimeoutId === undefined) return;
        window.clearTimeout(autoCloseTimeoutId);
        autoCloseTimeoutId = undefined;
      };
      const clearHideTimer = () => {
        if (hideTimeoutId === undefined) return;
        window.clearTimeout(hideTimeoutId);
        hideTimeoutId = undefined;
      };
      const scheduleAutoClose = () => {
        clearAutoCloseTimer();
        autoCloseTimeoutId = window.setTimeout(() => {
          closeMenu();
        }, LAYER_MENU_AUTO_CLOSE_MS);
      };
      const closeMenu = () => {
        isOpen = false;
        clearAutoCloseTimer();
        clearHideTimer();
        const controlSlot = container?.parentElement;
        if (controlSlot) {
          controlSlot.style.zIndex = "2";
        }
        if (container) {
          container.style.zIndex = "2";
        }
        if (!menu) return;
        menu.style.opacity = "0";
        menu.style.pointerEvents = "none";
        hideTimeoutId = window.setTimeout(() => {
          if (!menu || isOpen) return;
          menu.style.visibility = "hidden";
        }, LAYER_MENU_FADE_MS);
      };
      const renderMenuOptions = () => {
        if (!menu) return;
        const dark = isDarkMode();
        menu.innerHTML = "";
        for (const option of layerOptionsRef.current) {
          const item = document.createElement("button");
          const active = option.id === activeLayerIdRef.current;
          item.type = "button";
          item.textContent = active ? `✓ ${option.label}` : option.label;
          item.style.display = "block";
          item.style.width = "100%";
          item.style.textAlign = "left";
          item.style.padding = "6px 8px";
          item.style.border = "0";
          item.style.borderRadius = "6px";
          item.style.cursor = "pointer";
          item.style.background = active
            ? dark
              ? "rgba(255, 255, 255, 0.18)"
              : "rgba(17, 17, 17, 0.08)"
            : "transparent";
          item.style.color = dark ? "#fff" : "#111";
          item.style.fontSize = "12px";
          item.style.whiteSpace = "nowrap";
          item.addEventListener("click", () => {
            onLayerChangeRef.current(option.id);
            if (isCoarsePointerMode()) {
              closeMenu();
            }
          });
          menu.appendChild(item);
        }
      };
      const openMenu = () => {
        if (!menu) return;
        if (isOpen) {
          clearAutoCloseTimer();
          return;
        }
        isOpen = true;
        clearAutoCloseTimer();
        clearHideTimer();
        const controlSlot = container?.parentElement;
        if (controlSlot) {
          // Raise parent slot so the menu can overlay the location panel.
          controlSlot.style.zIndex = "7";
        }
        if (container) {
          container.style.zIndex = "7";
        }
        onLayerMenuOpenRef.current?.();
        applyMenuTheme();
        menu.style.visibility = "visible";
        menu.style.pointerEvents = "auto";
        // Force a new frame so opacity transition runs when reopening.
        void menu.offsetWidth;
        menu.style.opacity = "1";
        renderMenuOptions();
      };
      const onDocumentKeyDown = (event: KeyboardEvent) => {
        if (!isOpen) return;
        if (event.key === "Escape") closeMenu();
      };
      const onControlPointerEnter = () => {
        if (!isOpen) return;
        if (isCoarsePointerMode()) return;
        clearAutoCloseTimer();
      };
      const onControlPointerLeave = (event: PointerEvent) => {
        if (!isOpen) return;
        if (isCoarsePointerMode() || event.pointerType === "touch") return;
        scheduleAutoClose();
      };
      const onButtonPointerEnter = (event: PointerEvent) => {
        if (isCoarsePointerMode() || event.pointerType === "touch") return;
        openMenu();
      };
      const onButtonClick = (event: MouseEvent) => {
        event.preventDefault();
        event.stopPropagation();
        if (isCoarsePointerMode()) {
          if (isOpen) {
            closeMenu();
            return;
          }
          openMenu();
          return;
        }
        openMenu();
      };
      const onDocumentPointerDown = (event: PointerEvent) => {
        if (!isOpen || !isCoarsePointerMode()) return;
        const target = event.target;
        if (target instanceof Node && container?.contains(target)) return;
        closeMenu();
      };
      return {
        onAdd() {
          container = document.createElement("div");
          container.className = "maplibregl-ctrl maplibregl-ctrl-group";
          container.style.position = "relative";
          container.style.zIndex = "2";
          container.addEventListener("pointerenter", onControlPointerEnter);
          container.addEventListener("pointerleave", onControlPointerLeave);

          button = document.createElement("button");
          button.type = "button";
          button.className = "maplibregl-ctrl-icon";
          button.ariaLabel = "Select map layer";
          button.title = "Layers";
          button.textContent = "◫";
          applyCtrlIconStyle(button, "24px");
          button.addEventListener("pointerenter", onButtonPointerEnter);
          button.addEventListener("click", onButtonClick);

          menu = document.createElement("div");
          menu.style.position = "absolute";
          menu.style.left = "100%";
          menu.style.top = "0";
          menu.style.marginLeft = "8px";
          menu.style.minWidth = "220px";
          applyMenuTheme();
          menu.style.borderRadius = "8px";
          menu.style.boxShadow = "0 6px 18px rgba(0, 0, 0, 0.2)";
          menu.style.padding = "6px";
          menu.style.maxHeight = "40vh";
          menu.style.overflowY = "auto";
          menu.style.opacity = "0";
          menu.style.visibility = "hidden";
          menu.style.pointerEvents = "none";
          menu.style.zIndex = "8";
          menu.style.transition = `opacity ${LAYER_MENU_FADE_MS}ms ease`;
          renderMenuOptions();

          document.addEventListener("keydown", onDocumentKeyDown);
          document.addEventListener("pointerdown", onDocumentPointerDown, true);

          container.appendChild(button);
          container.appendChild(menu);
          return container;
        },
        onRemove() {
          clearAutoCloseTimer();
          clearHideTimer();
          const controlSlot = container?.parentElement;
          if (controlSlot) {
            controlSlot.style.zIndex = "2";
          }
          container?.removeEventListener("pointerenter", onControlPointerEnter);
          container?.removeEventListener("pointerleave", onControlPointerLeave);
          document.removeEventListener("keydown", onDocumentKeyDown);
          document.removeEventListener(
            "pointerdown",
            onDocumentPointerDown,
            true,
          );
          button?.removeEventListener("pointerenter", onButtonPointerEnter);
          button?.removeEventListener("click", onButtonClick);
          container?.remove();
        },
        refresh() {
          renderMenuOptions();
        },
      };
    }

    const onStyleLoad = () => {
      styleReadyRef.current = true;
    };

    map.on("style.load", onStyleLoad);
    map.on("style.load", applyMapSettings);
    map.on("style.load", applyTextureLayer);
    map.on("style.load", ensureHillshadeLayer);
    map.on("style.load", applyDebugBboxLayer);
    map.on("style.load", applyGlobeBackground);
    map.on("load", applyMapSettings);
    map.on("load", applyTextureLayer);
    map.on("load", applyDebugBboxLayer);
    map.on("load", applyGlobeBackground);
    if (showControlsRef.current) {
      map.addControl(createHomeControl(), "top-left");
      map.addControl(new maplibregl.NavigationControl(), "top-left");
      const layerControl = createLayerControl();
      layerControlRef.current = layerControl;
      map.addControl(layerControl, "top-left");
    }

    const onResize = () => {
      const previousMinZoom = map.getMinZoom();
      const nextMinZoom = responsiveBaseZoom();
      map.setMinZoom(nextMinZoom);

      // Keep the base/home view responsive across viewport sizes.
      const currentZoom = map.getZoom();
      const isAtBaseZoom = Math.abs(currentZoom - previousMinZoom) < 0.05;
      if (!focusLocationRef.current && isAtBaseZoom) {
        map.easeTo({
          zoom: nextMinZoom,
          duration: PANEL_TRANSITION_MS,
          essential: true,
        });
      }
    };
    window.addEventListener("resize", onResize);

    const onMapClick = (event: maplibregl.MapMouseEvent) => {
      if (!enablePickRef.current) return;
      if (!map.transform.isPointOnMapSurface(event.point)) return;
      const { lng, lat } = event.lngLat;
      const snapped = snapTargetAtLowZoom(map, event);
      const targetLng = snapped?.[0] ?? lng;
      const targetLat = snapped?.[1] ?? lat;

      if (!markerRef.current) {
        markerRef.current = new maplibregl.Marker({ color: MARKER_COLOR })
          .setLngLat([targetLng, targetLat])
          .addTo(map);
      } else {
        markerRef.current.setLngLat([targetLng, targetLat]);
      }

      onPickRef.current(targetLat, targetLng);
      map.flyTo({
        center: [targetLng, targetLat],
        zoom: focusZoomTarget(map),
        pitch: 0,
        bearing: 0,
        padding: getPanelPadding(),
        duration: FOCUS_FLY_DURATION_MS,
        easing: cubicOut,
        essential: true,
      });
    };
    map.on("click", onMapClick);

    return () => {
      window.removeEventListener("resize", onResize);
      map.off("click", onMapClick);
      markerRef.current?.remove();
      markerRef.current = null;
      layerControlRef.current = null;
      styleReadyRef.current = false;
      applyGlobeBackgroundRef.current = null;
      onTextureDebugInfoChangeRef.current?.(null);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      const selected = layerOptions.find((layer) => layer.id === activeLayerId);
      if (!selected) {
        applyGlobeBackgroundRef.current?.();
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        onTextureDebugInfoChangeRef.current?.(null);
        layerControlRef.current?.refresh();
        return;
      }
      const selectedTexture = selectTextureVariant(
        selected,
        maxTextureSizeRef.current,
        textureVariantOverrideRef.current,
      );
      if (!selectedTexture) {
        applyGlobeBackgroundRef.current?.();
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        onTextureDebugInfoChangeRef.current?.(null);
        layerControlRef.current?.refresh();
        return;
      }
      setBackdropColor(map, textureBackdrop);
      onTextureDebugInfoChangeRef.current?.({
        filename: textureFilenameFromUrl(selectedTexture.imageUrl),
        width: selectedTexture.width,
        height: selectedTexture.height,
        variant: selectedTexture.variant,
        maxTextureSize: maxTextureSizeRef.current,
      });
      const source = map.getSource(TEXTURE_SOURCE_ID) as
        | (maplibregl.ImageSource & {
            updateImage?: (args: {
              url: string;
              coordinates: [
                [number, number],
                [number, number],
                [number, number],
                [number, number],
              ];
            }) => void;
          })
        | undefined;
      const coordinates = textureCoordinates(selected);
      if (source && typeof source.updateImage === "function") {
        source.updateImage({ url: selectedTexture.imageUrl, coordinates });
      } else {
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        map.addSource(TEXTURE_SOURCE_ID, {
          type: "image",
          url: selectedTexture.imageUrl,
          coordinates,
        });
      }
      if (!map.getLayer(TEXTURE_LAYER_ID)) {
        const beforeId = textureLayerBeforeId(map);
        map.addLayer(
          {
            id: TEXTURE_LAYER_ID,
            type: "raster",
            source: TEXTURE_SOURCE_ID,
            paint: {
              "raster-opacity": selected.opacity ?? 0.72,
              "raster-resampling": selected.resampling ?? "linear",
            },
          },
          beforeId,
        );
      }
      map.setPaintProperty(
        TEXTURE_LAYER_ID,
        "raster-opacity",
        selected.opacity ?? 0.72,
      );
      const beforeId = textureLayerBeforeId(map);
      map.moveLayer(TEXTURE_LAYER_ID, beforeId);
      layerControlRef.current?.refresh();
    };

    if (styleReadyRef.current || map.isStyleLoaded()) {
      styleReadyRef.current = true;
      apply();
      return;
    }

    const applyAfterStyleReady = () => {
      styleReadyRef.current = true;
      apply();
    };
    map.once("style.load", applyAfterStyleReady);
    return () => {
      map.off("style.load", applyAfterStyleReady);
    };
  }, [activeLayerId, layerOptions, textureBackdrop, textureVariantOverride]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!showDebugOverlay || !debugBbox) {
        if (map.getLayer(DEBUG_BBOX_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_LAYER_ID);
        if (map.getLayer(DEBUG_BBOX_FILL_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_FILL_LAYER_ID);
        if (map.getSource(DEBUG_BBOX_SOURCE_ID))
          map.removeSource(DEBUG_BBOX_SOURCE_ID);
        return;
      }

      const coordinates = [
        [debugBbox.lon_min, debugBbox.lat_min],
        [debugBbox.lon_max, debugBbox.lat_min],
        [debugBbox.lon_max, debugBbox.lat_max],
        [debugBbox.lon_min, debugBbox.lat_max],
        [debugBbox.lon_min, debugBbox.lat_min],
      ];
      const data: FeatureCollection<Polygon> = {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: {},
            geometry: { type: "Polygon", coordinates: [coordinates] },
          },
        ],
      };

      const source = map.getSource(DEBUG_BBOX_SOURCE_ID) as
        | (maplibregl.GeoJSONSource & { setData?: (d: unknown) => void })
        | undefined;
      if (source && typeof source.setData === "function") {
        source.setData(data);
      } else {
        if (map.getLayer(DEBUG_BBOX_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_LAYER_ID);
        if (map.getLayer(DEBUG_BBOX_FILL_LAYER_ID))
          map.removeLayer(DEBUG_BBOX_FILL_LAYER_ID);
        if (map.getSource(DEBUG_BBOX_SOURCE_ID))
          map.removeSource(DEBUG_BBOX_SOURCE_ID);
        map.addSource(DEBUG_BBOX_SOURCE_ID, { type: "geojson", data });
      }

      const lineColor =
        debugBboxGridId === "global_0p05" ? "#00c2ff" : "#ff3b30";
      if (!map.getLayer(DEBUG_BBOX_FILL_LAYER_ID)) {
        map.addLayer({
          id: DEBUG_BBOX_FILL_LAYER_ID,
          type: "fill",
          source: DEBUG_BBOX_SOURCE_ID,
          paint: {
            "fill-color": "#fff200",
            "fill-opacity": 0.18,
          },
        });
      }
      if (!map.getLayer(DEBUG_BBOX_LAYER_ID)) {
        map.addLayer({
          id: DEBUG_BBOX_LAYER_ID,
          type: "line",
          source: DEBUG_BBOX_SOURCE_ID,
          paint: {
            "line-color": lineColor,
            "line-width": 4,
            "line-dasharray": [1, 1.5],
          },
        });
      } else {
        map.setPaintProperty(DEBUG_BBOX_LAYER_ID, "line-color", lineColor);
      }
      // Keep debug bbox visible above texture and style layers.
      map.moveLayer(DEBUG_BBOX_FILL_LAYER_ID);
      map.moveLayer(DEBUG_BBOX_LAYER_ID);
    };

    if (styleReadyRef.current || map.isStyleLoaded()) {
      styleReadyRef.current = true;
      apply();
      return;
    }

    const applyAfterStyleReady = () => {
      styleReadyRef.current = true;
      apply();
    };
    map.once("style.load", applyAfterStyleReady);
    return () => {
      map.off("style.load", applyAfterStyleReady);
    };
  }, [showDebugOverlay, debugBbox, debugBboxGridId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!focusLocation) return;

    const { lat, lon } = focusLocation;
    if (!markerRef.current) {
      markerRef.current = new maplibregl.Marker({ color: MARKER_COLOR })
        .setLngLat([lon, lat])
        .addTo(map);
    } else {
      markerRef.current.setLngLat([lon, lat]);
    }

    map.flyTo({
      center: [lon, lat],
      zoom: focusZoomTarget(map),
      pitch: 0,
      bearing: 0,
      padding: panelPaddingForViewport(map, panelOpen),
      duration: FOCUS_FLY_DURATION_MS,
      easing: cubicOut,
      essential: true,
    });
  }, [focusLocation, panelOpen]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!panelOpen) return;
    if (!focusLocation) return;

    const { lat, lon } = focusLocation;
    let rafId: number | null = null;
    let timerId: number | null = null;
    const recenterToVisibleArea = () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        map.easeTo({
          center: [lon, lat],
          zoom: focusZoomTarget(map),
          padding: panelPaddingForViewport(map, true),
          duration: FOCUS_RECENTER_DURATION_MS,
          easing: cubicOut,
          essential: true,
        });
      });
    };

    const media = window.matchMedia(`(max-width: ${PANEL_BREAKPOINT_PX}px)`);
    timerId = window.setTimeout(recenterToVisibleArea, PANEL_TRANSITION_MS);
    window.addEventListener("resize", recenterToVisibleArea);
    media.addEventListener?.("change", recenterToVisibleArea);

    return () => {
      if (timerId !== null) window.clearTimeout(timerId);
      if (rafId !== null) cancelAnimationFrame(rafId);
      window.removeEventListener("resize", recenterToVisibleArea);
      media.removeEventListener?.("change", recenterToVisibleArea);
    };
  }, [panelOpen, focusLocation]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (panelOpen) return;
    if (!focusLocationRef.current) return;
    map.easeTo({
      padding: { top: 0, right: 0, bottom: 0, left: 0 },
      duration: PANEL_TRANSITION_MS,
      essential: true,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelOpen]);

  useEffect(() => {
    const map = mapRef.current;
    chatMarkersRef.current.forEach((m) => m.remove());
    chatMarkersRef.current = [];
    if (!map || !chatLocations || chatLocations.length === 0) return;
    // Geographic threshold for collision detection (~50km)
    const GEO_THRESHOLD = 0.5;
    chatLocations.forEach((loc, i) => {
      // Place label above pin if a nearby city exists to the south, to avoid overlap
      const labelAbove = chatLocations.some(
        (other, j) =>
          i !== j &&
          Math.abs(loc.lat - other.lat) < GEO_THRESHOLD &&
          Math.abs(loc.lon - other.lon) < GEO_THRESHOLD &&
          loc.lat > other.lat,
      );
      const cityName = loc.label.split(",")[0].trim();
      const displayName = loc.rank !== undefined ? `${loc.rank}. ${cityName}` : cityName;
      const el = document.createElement("div");
      el.style.cssText = "display:flex;flex-direction:column;align-items:center;gap:2px;cursor:pointer";
      const pin = document.createElement("div");
      pin.style.cssText = `width:12px;height:12px;border-radius:50%;background:${MARKER_COLOR};border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.5);flex-shrink:0`;
      const labelEl = document.createElement("span");
      labelEl.textContent = displayName;
      labelEl.style.cssText = "background:rgba(0,0,0,0.65);color:white;font-size:11px;font-weight:600;padding:1px 5px;border-radius:3px;white-space:nowrap";
      if (labelAbove) {
        el.appendChild(labelEl);
        el.appendChild(pin);
      } else {
        el.appendChild(pin);
        el.appendChild(labelEl);
      }
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!markerRef.current) {
          markerRef.current = new maplibregl.Marker({ color: MARKER_COLOR })
            .setLngLat([loc.lon, loc.lat])
            .addTo(map);
        } else {
          markerRef.current.setLngLat([loc.lon, loc.lat]);
        }
        (onPickChatMarkerRef.current ?? onPickRef.current)(loc.lat, loc.lon);
        map.flyTo({
          center: [loc.lon, loc.lat],
          zoom: focusZoomTarget(map),
          pitch: 0,
          bearing: 0,
          padding: panelPaddingForViewport(map, panelOpenRef.current),
          duration: FOCUS_FLY_DURATION_MS,
          easing: cubicOut,
          essential: true,
        });
      });
      chatMarkersRef.current.push(
        new maplibregl.Marker({ element: el, anchor: labelAbove ? "bottom" : "top" })
          .setLngLat([loc.lon, loc.lat])
          .addTo(map),
      );
    });
    const lons = chatLocations.map((l) => l.lon);
    const lats = chatLocations.map((l) => l.lat);
    if (chatLocations.length === 1) {
      map.flyTo({
        center: [lons[0], lats[0]],
        zoom: focusZoomTarget(map),
        pitch: 0,
        bearing: 0,
        padding: chatDrawerPaddingForViewport(map),
        duration: FOCUS_FLY_DURATION_MS,
        easing: cubicOut,
        essential: true,
      });
    } else {
      map.fitBounds(
        new maplibregl.LngLatBounds(
          [Math.min(...lons), Math.min(...lats)],
          [Math.max(...lons), Math.max(...lats)],
        ),
        { padding: chatDrawerPaddingForViewport(map), duration: FOCUS_FLY_DURATION_MS, essential: true },
      );
    }
  }, [chatLocations]);

  // Fly to a continent bounding box when the chat answer is about a single region.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !chatFlyToBbox) return;
    const [west, south, east, north] = chatFlyToBbox;
    map.fitBounds(
      new maplibregl.LngLatBounds([west, south], [east, north]),
      { padding: chatDrawerPaddingForViewport(map), duration: FOCUS_FLY_DURATION_MS, essential: true },
    );
  }, [chatFlyToBbox]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !autoRotate) return;
    if (focusLocation) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let rafId: number | null = null;
    let previousTimestamp: number | null = null;

    const tick = (timestamp: number) => {
      if (!autoRotateRef.current) return;
      if (focusLocationRef.current) return;

      if (previousTimestamp === null) {
        previousTimestamp = timestamp;
        rafId = window.requestAnimationFrame(tick);
        return;
      }

      const elapsedSeconds = Math.min(
        (timestamp - previousTimestamp) / 1000,
        0.05,
      );
      previousTimestamp = timestamp;
      const center = map.getCenter();
      const nextLon =
        ((((center.lng + elapsedSeconds * AUTO_ROTATE_DEG_PER_SEC + 180) %
          360) +
          360) %
          360) -
        180;
      map.jumpTo({ center: [nextLon, center.lat], bearing: 0 });
      rafId = window.requestAnimationFrame(tick);
    };

    rafId = window.requestAnimationFrame(tick);
    return () => {
      if (rafId !== null) window.cancelAnimationFrame(rafId);
    };
  }, [autoRotate, focusLocation]);

  return (
    <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
  );
}
