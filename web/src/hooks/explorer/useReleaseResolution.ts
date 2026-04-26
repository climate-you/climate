import { useCallback, useEffect, useState } from "react";

export type ReleaseLayer = {
  id: string;
  label: string;
  enable?: boolean | null;
  unit?: "temperature" | "score" | null;
  map_id: string;
  asset_path: string;
  mobile_asset_path?: string | null;
  asset_width?: number | null;
  asset_height?: number | null;
  mobile_asset_width?: number | null;
  mobile_asset_height?: number | null;
  description?: string | null;
  icon?: string | null;
  opacity?: number | null;
  resampling?: "linear" | "nearest" | null;
  legend?: Record<string, unknown> | null;
  projection_bounds?: {
    lat_min: number;
    lat_max: number;
    lon_min: number;
    lon_max: number;
  } | null;
};

type ReleaseResolveResponse = {
  requested_release: string;
  release: string;
  version?: {
    app_version: string;
    app_tag?: string | null;
    app_commit?: string | null;
    assets_release: string;
  } | null;
  layers: ReleaseLayer[];
};

function normalizeRequestedRelease(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "latest";
  return trimmed.toLowerCase() === "latest" ? "latest" : trimmed;
}

export function useReleaseResolution(
  apiBase: string,
  envDefaultReleaseRaw: string | undefined,
) {
  const [requestedRelease, setRequestedRelease] = useState<string>(() =>
    normalizeRequestedRelease(envDefaultReleaseRaw ?? "latest"),
  );
  const [sessionRelease, setSessionRelease] = useState<string | null>(null);
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const [assetsRelease, setAssetsRelease] = useState<string | null>(null);
  const [releaseLayers, setReleaseLayers] = useState<ReleaseLayer[]>([]);

  const pinSessionRelease = useCallback(
    (releaseValue: string | null | undefined) => {
      if (!releaseValue) return;
      setSessionRelease((prev) => prev ?? releaseValue);
    },
    [],
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const qp = new URLSearchParams(window.location.search).get("release");
    if (!qp) return;
    setRequestedRelease(normalizeRequestedRelease(qp));
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function resolveRelease() {
      try {
        const url = `${apiBase}/api/v/${encodeURIComponent(requestedRelease)}/release`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const data = (await r.json()) as ReleaseResolveResponse;
        if (cancelled) return;
        setSessionRelease(data.release);
        setAppVersion(data.version?.app_version ?? null);
        setAssetsRelease(data.version?.assets_release ?? data.release ?? null);
        setReleaseLayers(Array.isArray(data.layers) ? data.layers : []);
      } catch {
        if (cancelled) return;
        setSessionRelease(requestedRelease);
        setAppVersion(null);
        setAssetsRelease(requestedRelease);
        setReleaseLayers([]);
      }
    }

    void resolveRelease();
    return () => {
      cancelled = true;
    };
  }, [apiBase, requestedRelease]);

  return {
    requestedRelease,
    sessionRelease,
    appVersion,
    assetsRelease,
    releaseLayers,
    pinSessionRelease,
  };
}
