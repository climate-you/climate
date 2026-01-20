"use client";

import { useEffect, useState } from "react";
import type { CityIndexEntry } from "@/lib/cities";

function cacheBustDev(url: string) {
  if (process.env.NODE_ENV === "development") {
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}v=${Date.now()}`;
  }
  return url;
}

export function useCitiesIndex() {
  const [cities, setCities] = useState<CityIndexEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setError(null);
        const url = cacheBustDev("/data/cities_index.json");
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok)
          throw new Error(`Failed to load cities_index.json: ${res.status}`);
        const data = (await res.json()) as CityIndexEntry[];
        if (!cancelled) setCities(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return { cities, error };
}
