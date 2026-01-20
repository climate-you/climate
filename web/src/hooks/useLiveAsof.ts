"use client";

import { useEffect, useState } from "react";

type LatestMap = Record<string, string>;

function cacheBustDev(url: string) {
  if (process.env.NODE_ENV === "development") {
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}v=${Date.now()}`;
  }
  return url;
}

export function useLiveAsof(slug: string, enabled: boolean) {
  const [asof, setAsof] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    if (!slug || slug === "auto") return;

    let cancelled = false;
    setAsof(null);
    setError(null);

    (async () => {
      try {
        const url = cacheBustDev("/data/live/latest.json");
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok)
          throw new Error(`Failed to load live/latest.json: ${res.status}`);
        const latest = (await res.json()) as LatestMap;
        const v = latest[slug] ?? null;
        if (!cancelled) setAsof(v);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [slug, enabled]);

  return { asof, error };
}
