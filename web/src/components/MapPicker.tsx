"use client";

import React, { useEffect } from "react";
import {
  CircleMarker,
  MapContainer,
  Rectangle,
  TileLayer,
  useMapEvents,
  useMap,
} from "react-leaflet";

type PickPoint = { lat: number; lon: number };

type DataCell = {
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
};

function ClickHandler({
  onPick,
  onZoomChange,
}: {
  onPick: (lat: number, lon: number) => void;
  onZoomChange?: (zoom: number) => void;
}) {
  const map = useMap();
  useMapEvents({
    click(e) {
      const wrapped = map.wrapLatLng(e.latlng);
      onPick(wrapped.lat, wrapped.lng);
    },
    zoomend(e) {
      if (onZoomChange) {
        onZoomChange(e.target.getZoom());
      }
    },
  });
  return null;
}

function ViewUpdater({
  center,
  zoom,
}: {
  center?: [number, number];
  zoom?: number;
}) {
  const map = useMap();
  useEffect(() => {
    if (center && typeof zoom === "number") {
      map.setView(center, zoom, { animate: true });
    } else if (center) {
      map.setView(center, map.getZoom(), { animate: true });
    } else if (typeof zoom === "number") {
      map.setZoom(zoom, { animate: true });
    }
  }, [center?.[0], center?.[1], zoom, map]);
  return null;
}

function cellBoundsParts(
  cell: DataCell,
): Array<[[number, number], [number, number]]> {
  // Leaflet bounds are [[southWest],[northEast]]
  const swLat = cell.lat_min;
  const neLat = cell.lat_max;

  // Normal case
  if (cell.lon_min <= cell.lon_max) {
    return [
      [
        [swLat, cell.lon_min],
        [neLat, cell.lon_max],
      ],
    ];
  }

  // Antimeridian wrap: split into two rectangles
  return [
    [
      [
        [swLat, cell.lon_min],
        [neLat, 180],
      ],
    ],
    [
      [
        [swLat, -180],
        [neLat, cell.lon_max],
      ],
    ],
  ].map((b) => b[0]);
}

export default function MapPicker({
  onPick,
  onZoomChange,
  center = [20, 0],
  zoom = 2,
  picked,
  cell,
  cellCenter,
}: {
  onPick: (lat: number, lon: number) => void;
  onZoomChange?: (zoom: number) => void;
  center?: [number, number];
  zoom?: number;
  picked?: PickPoint | null;
  cell?: DataCell | null;
  cellCenter?: PickPoint | null;
}) {
  const rects = cell ? cellBoundsParts(cell) : [];

  return (
    <div
      style={{
        height: 360,
        width: "100%",
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <MapContainer
        center={center}
        zoom={zoom}
        scrollWheelZoom
        style={{ height: "100%", width: "100%", position: "relative", zIndex: 1 }}
      >
        <ViewUpdater center={center} zoom={zoom} />
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Cell boundary (dotted rectangle) */}
        {rects.map((b, idx) => (
          <Rectangle
            key={idx}
            bounds={b}
            pathOptions={{
              color: "black",
              weight: 1,
              dashArray: "3 3",
              fillOpacity: 0,
            }}
          />
        ))}

        {/* Picked point (hollow circle) */}
        {picked ? (
          <CircleMarker
            center={[picked.lat, picked.lon]}
            radius={6}
            pathOptions={{ color: "black", weight: 2, fillOpacity: 0 }}
          />
        ) : null}

        {/* Cell center (filled dot) */}
        {cellCenter ? (
          <CircleMarker
            center={[cellCenter.lat, cellCenter.lon]}
            radius={4}
            pathOptions={{ color: "black", weight: 1, fillOpacity: 1 }}
          />
        ) : null}

        <ClickHandler onPick={onPick} onZoomChange={onZoomChange} />
      </MapContainer>
    </div>
  );
}
