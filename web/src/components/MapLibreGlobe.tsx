"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";

type LngLat = { lat: number; lon: number };

type Props = {
  panelOpen: boolean;
  focusLocation: LngLat | null;
  onPick: (lat: number, lon: number) => void;
  onHome: () => void;
};

const initialView = {
  center: [0, 0] as [number, number],
  pitch: 0,
  bearing: 0,
};

const CLOUD_SOURCE_ID = "clouds-overlay-source";
const CLOUD_LAYER_ID = "clouds-overlay-layer";
const CLOUD_TEXTURE_URL = "/data/textures/clouds_4096_mercator_alpha.webp";
const CLOUD_DRIFT_SPEED_RAD_PER_SEC = 0.01;
const CLOUD_DRIFT_SPEED_DEG_PER_SEC =
  CLOUD_DRIFT_SPEED_RAD_PER_SEC * (180 / Math.PI);
const CLOUD_DRIFT_WRAP_DEG = 360;
const CLOUD_DRIFT_MAX_OFFSET_DEG = 359.9999;
const MERCATOR_MAX_LAT = 85.05112878;

const CLOUD_FADE_START_ZOOM = 3.8;
const CLOUD_FADE_END_ZOOM = CLOUD_FADE_START_ZOOM + 1.2;
const CLOUD_MAX_OPACITY = 0.65;
const PANEL_BREAKPOINT_PX = 900;
const DESKTOP_PANEL_WIDTH_RATIO = 0.62;
const MOBILE_PANEL_HEIGHT_RATIO = 0.6;
const FOCUS_LOCATION_ZOOM = 5.5;
const FOCUS_FLY_DURATION_MS = 1900;
const FOCUS_RECENTER_DURATION_MS = 650;
const PANEL_TRANSITION_MS = 300;
const DEFAULT_BASE_ZOOM = 2.5;

function baseZoomForViewportWidth(width: number) {
  if (width <= 480) return 1.5;
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
  onPick,
  onHome,
}: Props) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const onPickRef = useRef(onPick);
  const onHomeRef = useRef(onHome);
  const panelOpenRef = useRef(panelOpen);
  const focusLocationRef = useRef(focusLocation);
  const cloudRafRef = useRef<number | null>(null);
  const cloudStartRef = useRef<number | null>(null);

  useEffect(() => {
    onPickRef.current = onPick;
  }, [onPick]);

  useEffect(() => {
    onHomeRef.current = onHome;
  }, [onHome]);

  useEffect(() => {
    panelOpenRef.current = panelOpen;
  }, [panelOpen]);

  useEffect(() => {
    focusLocationRef.current = focusLocation;
  }, [focusLocation]);

  useEffect(() => {
    if (!mapContainerRef.current) return;

    const baseZoom = responsiveBaseZoom();
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: "/custom_map.json",
      projection: { type: "globe" },
      center: initialView.center,
      zoom: baseZoom,
      minZoom: baseZoom,
      maxZoom: 10,
      pitch: initialView.pitch,
      bearing: initialView.bearing,
    });
    mapRef.current = map;

    function applyGlobeSettings() {
      map.setProjection({ type: "globe" });
      map.getContainer().style.backgroundColor = "#0000ff";
      map.getCanvas().style.backgroundColor = "#0000ff";

      const layers = map.getStyle()?.layers || [];
      for (const layer of layers) {
        if (layer.type === "sky") {
          map.setPaintProperty(layer.id, "sky-opacity", 0);
        }
      }
    }

    function cloudCoordinates(lonOffsetDeg: number): [number, number][] {
      const west = -180 + lonOffsetDeg;
      const east = 180 + lonOffsetDeg;
      return [
        [west, MERCATOR_MAX_LAT],
        [east, MERCATOR_MAX_LAT],
        [east, -MERCATOR_MAX_LAT],
        [west, -MERCATOR_MAX_LAT],
      ];
    }

    function ensureCloudOverlay() {
      if (!map.getSource(CLOUD_SOURCE_ID)) {
        map.addSource(CLOUD_SOURCE_ID, {
          type: "image",
          url: CLOUD_TEXTURE_URL,
          coordinates: cloudCoordinates(0),
        });
      }

      if (!map.getLayer(CLOUD_LAYER_ID)) {
        const firstSymbolLayerId = (map.getStyle()?.layers || []).find(
          (layer) => layer.type === "symbol",
        )?.id;

        map.addLayer(
          {
            id: CLOUD_LAYER_ID,
            type: "raster",
            source: CLOUD_SOURCE_ID,
            paint: {
              "raster-opacity": CLOUD_MAX_OPACITY,
              "raster-fade-duration": 0,
            },
          },
          firstSymbolLayerId,
        );
      }
    }

    function updateCloudOpacity() {
      if (!map.getLayer(CLOUD_LAYER_ID)) return;
      const zoom = map.getZoom();
      if (zoom <= CLOUD_FADE_START_ZOOM) {
        map.setPaintProperty(
          CLOUD_LAYER_ID,
          "raster-opacity",
          CLOUD_MAX_OPACITY,
        );
        return;
      }
      if (zoom >= CLOUD_FADE_END_ZOOM) {
        map.setPaintProperty(CLOUD_LAYER_ID, "raster-opacity", 0);
        return;
      }
      const t =
        (zoom - CLOUD_FADE_START_ZOOM) /
        (CLOUD_FADE_END_ZOOM - CLOUD_FADE_START_ZOOM);
      map.setPaintProperty(
        CLOUD_LAYER_ID,
        "raster-opacity",
        CLOUD_MAX_OPACITY * (1 - t),
      );
    }

    function startCloudDrift() {
      stopCloudDrift();

      const source = map.getSource(CLOUD_SOURCE_ID) as
        | maplibregl.ImageSource
        | undefined;
      if (!source) return;

      cloudStartRef.current = performance.now();
      const tick = (now: number) => {
        const t0 = cloudStartRef.current ?? now;
        const elapsedSec = (now - t0) / 1000;
        const driftOffsetDeg = Math.min(
          (elapsedSec * CLOUD_DRIFT_SPEED_DEG_PER_SEC) % CLOUD_DRIFT_WRAP_DEG,
          CLOUD_DRIFT_MAX_OFFSET_DEG,
        );
        source.setCoordinates(cloudCoordinates(driftOffsetDeg));
        cloudRafRef.current = requestAnimationFrame(tick);
      };
      cloudRafRef.current = requestAnimationFrame(tick);
    }

    function stopCloudDrift() {
      if (cloudRafRef.current !== null) {
        cancelAnimationFrame(cloudRafRef.current);
        cloudRafRef.current = null;
      }
      cloudStartRef.current = null;
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

    function syncZoomDependentLayers() {
      updateCloudOpacity();
      map.triggerRepaint();
    }

    function getPanelPadding() {
      return panelPaddingForViewport(map, panelOpenRef.current);
    }

    class HomeControl {
      map?: maplibregl.Map;
      container?: HTMLDivElement;
      button?: HTMLButtonElement;

      onAdd(mapInstance: maplibregl.Map) {
        this.map = mapInstance;
        this.container = document.createElement("div");
        this.container.className = "maplibregl-ctrl maplibregl-ctrl-group";

        this.button = document.createElement("button");
        this.button.type = "button";
        this.button.className = "maplibregl-ctrl-icon";
        this.button.ariaLabel = "Return to initial globe position";
        this.button.title = "Home";
        this.button.textContent = "⌂";
        this.button.style.fontSize = "18px";
        this.button.style.lineHeight = "29px";
        this.button.style.color = "#111";
        this.button.addEventListener("click", this.onClick);

        this.container.appendChild(this.button);
        return this.container;
      }

      onRemove() {
        this.button?.removeEventListener("click", this.onClick);
        this.container?.remove();
      }

      onClick = () => {
        markerRef.current?.remove();
        markerRef.current = null;
        onHomeRef.current();
        const nextBaseZoom = responsiveBaseZoom();
        this.map?.setMinZoom(nextBaseZoom);
        this.map?.flyTo({
          center: initialView.center,
          zoom: nextBaseZoom,
          pitch: initialView.pitch,
          bearing: initialView.bearing,
          padding: { top: 0, right: 0, bottom: 0, left: 0 },
          duration: 1200,
          essential: true,
        });
      };
    }

    map.on("style.load", applyGlobeSettings);
    map.on("style.load", ensureCloudOverlay);
    map.on("style.load", startCloudDrift);
    map.on("style.load", ensureHillshadeLayer);
    map.on("style.load", syncZoomDependentLayers);
    map.on("styledata", () => {
      if (!map.isStyleLoaded()) return;
      syncZoomDependentLayers();
    });
    map.on("load", applyGlobeSettings);
    map.on("load", ensureCloudOverlay);
    map.on("load", startCloudDrift);
    map.on("load", syncZoomDependentLayers);
    map.once("idle", syncZoomDependentLayers);
    map.on("zoom", updateCloudOpacity);
    map.addControl(new HomeControl(), "top-left");
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
      stopCloudDrift();
      markerRef.current?.remove();
      markerRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, []);

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
