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
  zoom: 2.5,
  pitch: 0,
  bearing: 0,
};

const LOCATION_LABELS_MIN_ZOOM = 3.8;
const LOCATION_LABELS_MAX_ZOOM = 10;
const LOCATION_LABEL_KEYWORDS = [
  "place",
  "settlement",
  "city",
  "town",
  "village",
  "country",
  "state",
  "province",
  "continent",
];

function isEarthLocationLabelLayer(layer: {
  type?: string;
  id?: string;
  layout?: Record<string, unknown>;
}) {
  if (!layer || layer.type !== "symbol") return false;
  if (!layer.layout?.["text-field"]) return false;
  const id = (layer.id || "").toLowerCase();
  return LOCATION_LABEL_KEYWORDS.some((keyword) => id.includes(keyword));
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
    if (!mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: "/custom_map.json",
      projection: { type: "globe" },
      center: initialView.center,
      zoom: initialView.zoom,
      minZoom: initialView.zoom,
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

    function updateEarthLocationLabelVisibility() {
      const zoom = map.getZoom();
      const visible =
        zoom >= LOCATION_LABELS_MIN_ZOOM && zoom <= LOCATION_LABELS_MAX_ZOOM;
      const visibility = visible ? "visible" : "none";
      const layers = map.getStyle()?.layers || [];

      for (const layer of layers) {
        if (!isEarthLocationLabelLayer(layer)) continue;
        map.setLayoutProperty(layer.id, "visibility", visibility);
      }
    }

    function getPanelPadding() {
      if (!panelOpenRef.current || window.matchMedia("(max-width: 900px)").matches) {
        return { top: 0, right: 0, bottom: 0, left: 0 };
      }
      const mapRect = map.getContainer().getBoundingClientRect();
      const rightPadding = Math.round(mapRect.width * 0.62);
      return { top: 0, right: rightPadding, bottom: 0, left: 0 };
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
        onHomeRef.current();
        this.map?.flyTo({
          center: initialView.center,
          zoom: initialView.zoom,
          pitch: initialView.pitch,
          bearing: initialView.bearing,
          padding: { top: 0, right: 0, bottom: 0, left: 0 },
          duration: 1200,
          essential: true,
        });
      };
    }

    map.on("style.load", applyGlobeSettings);
    map.on("style.load", ensureHillshadeLayer);
    map.on("load", applyGlobeSettings);
    map.on("load", updateEarthLocationLabelVisibility);
    map.on("zoom", updateEarthLocationLabelVisibility);
    map.addControl(new HomeControl(), "top-left");
    map.addControl(new maplibregl.NavigationControl(), "top-left");

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
        zoom: 5.5,
        pitch: 0,
        bearing: 0,
        padding: getPanelPadding(),
        duration: 1500,
        essential: true,
      });
    });

    return () => {
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
      zoom: 5.5,
      pitch: 0,
      bearing: 0,
      padding:
        panelOpen && !window.matchMedia("(max-width: 900px)").matches
          ? {
              top: 0,
              right: Math.round(map.getContainer().getBoundingClientRect().width * 0.62),
              bottom: 0,
              left: 0,
            }
          : { top: 0, right: 0, bottom: 0, left: 0 },
      duration: 1500,
      essential: true,
    });
  }, [focusLocation, panelOpen]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (panelOpen) return;
    map.easeTo({
      padding: { top: 0, right: 0, bottom: 0, left: 0 },
      duration: 300,
      essential: true,
    });
  }, [panelOpen]);

  return <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />;
}
