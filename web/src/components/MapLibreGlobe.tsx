"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";

type LngLat = { lat: number; lon: number };
export type MapLayerOption = {
  id: string;
  label: string;
  imageUrl?: string;
  opacity?: number;
};

type Props = {
  panelOpen: boolean;
  focusLocation: LngLat | null;
  layerOptions: MapLayerOption[];
  activeLayerId: string | null;
  onLayerChange: (layerId: string) => void;
  onPick: (lat: number, lon: number) => void;
  onHome: () => void;
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
const TEXTURE_SOURCE_ID = "climateTextureSource";
const TEXTURE_LAYER_ID = "climateTextureLayer";

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

export default function MapLibreGlobe({
  panelOpen,
  focusLocation,
  layerOptions,
  activeLayerId,
  onLayerChange,
  onPick,
  onHome,
}: Props) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const layerControlRef = useRef<{ refresh: () => void } | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const onPickRef = useRef(onPick);
  const onHomeRef = useRef(onHome);
  const onLayerChangeRef = useRef(onLayerChange);
  const panelOpenRef = useRef(panelOpen);
  const focusLocationRef = useRef(focusLocation);
  const layerOptionsRef = useRef(layerOptions);
  const activeLayerIdRef = useRef(activeLayerId);

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
    if (!mapContainerRef.current) return;

    const baseZoom = responsiveBaseZoom();
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: "/custom_map.json",
      projection: { type: "mercator" },
      center: initialView.center,
      zoom: baseZoom,
      minZoom: baseZoom,
      maxZoom: 10,
      pitch: initialView.pitch,
      bearing: initialView.bearing,
    });
    mapRef.current = map;

    function applyMapSettings() {
      map.setProjection({ type: "mercator" });
      map.getContainer().style.backgroundColor = "#ffffff";
      map.getCanvas().style.backgroundColor = "#ffffff";

      const layers = map.getStyle()?.layers || [];
      for (const layer of layers) {
        if (layer.type === "sky") {
          map.setPaintProperty(layer.id, "sky-opacity", 0);
        }
      }
    }

    function applyTextureLayer() {
      const selected = layerOptionsRef.current.find(
        (layer) => layer.id === activeLayerIdRef.current,
      );
      if (!selected || !selected.imageUrl) {
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        return;
      }

      const coordinates: [[number, number], [number, number], [number, number], [number, number]] = [
        [-180, MERCATOR_MAX_LAT],
        [180, MERCATOR_MAX_LAT],
        [180, -MERCATOR_MAX_LAT],
        [-180, -MERCATOR_MAX_LAT],
      ];
      const existingSource = map.getSource(TEXTURE_SOURCE_ID) as
        | (maplibregl.ImageSource & {
            updateImage?: (args: {
              url: string;
              coordinates: [[number, number], [number, number], [number, number], [number, number]];
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
        map.addLayer({
          id: TEXTURE_LAYER_ID,
          type: "raster",
          source: TEXTURE_SOURCE_ID,
          paint: {
            "raster-opacity": selected.opacity ?? 0.72,
            "raster-resampling": "linear",
          },
        });
      } else {
        map.setPaintProperty(
          TEXTURE_LAYER_ID,
          "raster-opacity",
          selected.opacity ?? 0.72,
        );
      }
      map.moveLayer(TEXTURE_LAYER_ID);
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
          button.style.fontSize = "18px";
          button.style.lineHeight = "29px";
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

    function createLayerControl(): maplibregl.IControl & { refresh: () => void } {
      let container: HTMLDivElement | undefined;
      let button: HTMLButtonElement | undefined;
      let menu: HTMLDivElement | undefined;
      let isOpen = false;
      const renderMenuOptions = () => {
        if (!menu) return;
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
            ? "rgba(17, 17, 17, 0.08)"
            : "transparent";
          item.style.color = "#111";
          item.style.fontSize = "12px";
          item.style.whiteSpace = "nowrap";
          item.addEventListener("click", () => {
            onLayerChangeRef.current(option.id);
            isOpen = false;
            if (menu) menu.style.display = "none";
          });
          menu.appendChild(item);
        }
      };
      const onToggleMenu = () => {
        isOpen = !isOpen;
        if (menu) {
          menu.style.display = isOpen ? "block" : "none";
        }
        renderMenuOptions();
      };
      return {
        onAdd() {
          container = document.createElement("div");
          container.className = "maplibregl-ctrl maplibregl-ctrl-group";
          container.style.position = "relative";

          button = document.createElement("button");
          button.type = "button";
          button.className = "maplibregl-ctrl-icon";
          button.ariaLabel = "Select map layer";
          button.title = "Layers";
          button.textContent = "◫";
          button.style.fontSize = "16px";
          button.style.lineHeight = "29px";
          button.style.color = "#111";
          button.addEventListener("click", onToggleMenu);

          menu = document.createElement("div");
          menu.style.display = "none";
          menu.style.position = "absolute";
          menu.style.left = "100%";
          menu.style.top = "0";
          menu.style.marginLeft = "8px";
          menu.style.minWidth = "220px";
          menu.style.background = "#fff";
          menu.style.border = "1px solid rgba(0, 0, 0, 0.18)";
          menu.style.borderRadius = "8px";
          menu.style.boxShadow = "0 6px 18px rgba(0, 0, 0, 0.2)";
          menu.style.padding = "6px";
          menu.style.maxHeight = "40vh";
          menu.style.overflowY = "auto";
          renderMenuOptions();

          container.appendChild(button);
          container.appendChild(menu);
          return container;
        },
        onRemove() {
          button?.removeEventListener("click", onToggleMenu);
          container?.remove();
        },
        refresh() {
          renderMenuOptions();
        },
      };
    }

    map.on("style.load", applyMapSettings);
    map.on("style.load", applyTextureLayer);
    map.on("style.load", ensureHillshadeLayer);
    map.on("load", applyMapSettings);
    map.on("load", applyTextureLayer);
    map.addControl(createHomeControl(), "top-left");
    const layerControl = createLayerControl();
    layerControlRef.current = layerControl;
    map.addControl(layerControl, "top-left");
    map.addControl(new maplibregl.NavigationControl(), "top-left");

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

    map.on("click", (event) => {
      const { lng, lat } = event.lngLat;

      if (!markerRef.current) {
        markerRef.current = new maplibregl.Marker({ color: "#ff0000" })
          .setLngLat([lng, lat])
          .addTo(map);
      } else {
        markerRef.current.setLngLat([lng, lat]);
      }

      onPickRef.current(lat, lng);
      map.flyTo({
        center: [lng, lat],
        zoom: FOCUS_LOCATION_ZOOM,
        pitch: 0,
        bearing: 0,
        padding: getPanelPadding(),
        duration: FOCUS_FLY_DURATION_MS,
        easing: cubicOut,
        essential: true,
      });
    });

    return () => {
      window.removeEventListener("resize", onResize);
      markerRef.current?.remove();
      markerRef.current = null;
      layerControlRef.current = null;
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
        if (map.getLayer(TEXTURE_LAYER_ID)) {
          map.removeLayer(TEXTURE_LAYER_ID);
        }
        if (map.getSource(TEXTURE_SOURCE_ID)) {
          map.removeSource(TEXTURE_SOURCE_ID);
        }
        layerControlRef.current?.refresh();
        return;
      }
      const source = map.getSource(TEXTURE_SOURCE_ID) as
        | (maplibregl.ImageSource & {
            updateImage?: (args: {
              url: string;
              coordinates: [[number, number], [number, number], [number, number], [number, number]];
            }) => void;
          })
        | undefined;
      const coordinates: [[number, number], [number, number], [number, number], [number, number]] = [
        [-180, MERCATOR_MAX_LAT],
        [180, MERCATOR_MAX_LAT],
        [180, -MERCATOR_MAX_LAT],
        [-180, -MERCATOR_MAX_LAT],
      ];
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
        map.addLayer({
          id: TEXTURE_LAYER_ID,
          type: "raster",
          source: TEXTURE_SOURCE_ID,
          paint: {
            "raster-opacity": selected.opacity ?? 0.72,
            "raster-resampling": "linear",
          },
        });
      }
      map.setPaintProperty(TEXTURE_LAYER_ID, "raster-opacity", selected.opacity ?? 0.72);
      map.moveLayer(TEXTURE_LAYER_ID);
      layerControlRef.current?.refresh();
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [activeLayerId, layerOptions]);

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
      zoom: FOCUS_LOCATION_ZOOM,
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
          zoom: FOCUS_LOCATION_ZOOM,
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
