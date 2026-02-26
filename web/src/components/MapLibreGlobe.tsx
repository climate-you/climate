"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";

type LngLat = { lat: number; lon: number };
export type MapLayerOption = {
  id: string;
  label: string;
  imageUrl?: string;
  opacity?: number;
  resampling?: "linear" | "nearest";
};

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
};

const initialView = {
  center: [0, 0] as [number, number],
  pitch: 0,
  bearing: 0,
};

const PANEL_BREAKPOINT_PX = 900;
const DESKTOP_PANEL_WIDTH_RATIO = 0.62;
const MOBILE_PANEL_HEIGHT_RATIO = 0.6;
const FOCUS_LOCATION_ZOOM = 5.5;
const FOCUS_FLY_DURATION_MS = 1900;
const FOCUS_RECENTER_DURATION_MS = 650;
const PANEL_TRANSITION_MS = 300;
const DEFAULT_BASE_ZOOM = 2.5;
const MERCATOR_MAX_LAT = 85.05112878;
const DATELINE_OVERDRAW_DEG = 0.05;
const TEXTURE_SOURCE_ID = "climateTextureSource";
const TEXTURE_LAYER_ID = "climateTextureLayer";
const BACKDROP_BLUE = "#0000ff";
const BACKDROP_WHITE = "#ffffff";
const BACKDROP_DARK_MODE = "#181818";
const CITY_SNAP_MAX_ZOOM = 6;
const CITY_SNAP_RADIUS_PX = 28;
const CITY_SNAP_LAYER_IDS = ["label_city_capital", "label_city"] as const;
const LAYER_MENU_AUTO_CLOSE_MS = 800;
const LAYER_MENU_FADE_MS = 500;

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

function setBackdropColor(map: maplibregl.Map, color: string) {
  map.getContainer().style.backgroundColor = color;
  map.getCanvas().style.backgroundColor = color;
}

function textureCoordinates(): [
  [number, number],
  [number, number],
  [number, number],
  [number, number],
] {
  return [
    [-180 - DATELINE_OVERDRAW_DEG, MERCATOR_MAX_LAT],
    [180 + DATELINE_OVERDRAW_DEG, MERCATOR_MAX_LAT],
    [180 + DATELINE_OVERDRAW_DEG, -MERCATOR_MAX_LAT],
    [-180 - DATELINE_OVERDRAW_DEG, -MERCATOR_MAX_LAT],
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
}: Props) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const layerControlRef = useRef<{ refresh: () => void } | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const onPickRef = useRef(onPick);
  const onHomeRef = useRef(onHome);
  const onLayerChangeRef = useRef(onLayerChange);
  const onLayerMenuOpenRef = useRef(onLayerMenuOpen);
  const panelOpenRef = useRef(panelOpen);
  const focusLocationRef = useRef(focusLocation);
  const layerOptionsRef = useRef(layerOptions);
  const activeLayerIdRef = useRef(activeLayerId);
  const showControlsRef = useRef(showControls);
  const enablePickRef = useRef(enablePick);
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

    function applyTextureLayer() {
      const selected = layerOptionsRef.current.find(
        (layer) => layer.id === activeLayerIdRef.current,
      );
      if (!selected || !selected.imageUrl) {
        setBackdropColor(map, BACKDROP_BLUE);
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        return;
      }
      setBackdropColor(map, textureBackdropRef.current);

      const coordinates = textureCoordinates();
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
          url: selected.imageUrl,
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
          url: selected.imageUrl,
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

    function getPanelPadding() {
      return panelPaddingForViewport(map, panelOpenRef.current);
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
          duration: 1200,
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
          button.style.fontSize = "26px";
          button.style.lineHeight = "1";
          button.style.color = "#111";
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
          button.style.fontSize = "24px";
          button.style.lineHeight = "1";
          button.style.color = "#111";
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
    map.on("load", applyMapSettings);
    map.on("load", applyTextureLayer);
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
          duration: 300,
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
        markerRef.current = new maplibregl.Marker({ color: "#ff0000" })
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
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      const selected = layerOptions.find((layer) => layer.id === activeLayerId);
      if (!selected || !selected.imageUrl) {
        setBackdropColor(map, BACKDROP_BLUE);
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        layerControlRef.current?.refresh();
        return;
      }
      setBackdropColor(map, textureBackdrop);
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
      const coordinates = textureCoordinates();
      if (source && typeof source.updateImage === "function") {
        source.updateImage({ url: selected.imageUrl, coordinates });
      } else {
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        map.addSource(TEXTURE_SOURCE_ID, {
          type: "image",
          url: selected.imageUrl,
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
  }, [activeLayerId, layerOptions, textureBackdrop]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!focusLocation) return;

    const { lat, lon } = focusLocation;
    if (!markerRef.current) {
      markerRef.current = new maplibregl.Marker({ color: "#ff0000" })
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
    if (!focusLocation) return;
    map.easeTo({
      padding: { top: 0, right: 0, bottom: 0, left: 0 },
      duration: 300,
      essential: true,
    });
  }, [panelOpen, focusLocation]);

  return (
    <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
  );
}
