// Resolving a release's map layers into things a story can draw: the texture
// URL and dimensions for <AnomalyMap>, and MapLayerOption entries for the
// globe. Story pages reference layers by id (they are `enable: false` in the
// registry, so they never appear in the public layer list).

import { useMemo } from "react";
import type { MapLayerOption } from "@/components/MapLibreGlobe";
import type { ReleaseLayer } from "@/hooks/explorer/useReleaseResolution";
import { DEFAULT_MERCATOR_LAT_MAX } from "@/lib/story/mercator";

export type TextureInfo = {
  url: string;
  width: number;
  height: number;
  latMax: number;
};

export function useClimateApiBase() {
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

export function toMapLayerOption(
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

export function textureInfo(
  layer: ReleaseLayer | undefined,
  mapAssetBase: string,
  encodedRelease: string,
): TextureInfo | null {
  if (!layer || !layer.asset_width || !layer.asset_height) return null;
  return {
    url: `${mapAssetBase}/assets/v/${encodedRelease}/${layer.asset_path}`,
    width: layer.asset_width,
    height: layer.asset_height,
    latMax: layer.projection_bounds?.lat_max ?? DEFAULT_MERCATOR_LAT_MAX,
  };
}
