"use client";

import { useEffect, useState } from "react";

function cacheBustDev(url: string) {
  if (process.env.NODE_ENV === "development") {
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}v=${Date.now()}`;
  }
  return url;
}

export function useIntroCaption(args: {
  slug: string;
  unit: "C" | "F";
  enabled: boolean;
}) {
  const { slug, unit, enabled } = args;

  const [caption, setCaption] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    if (!slug || slug === "auto") return;

    let cancelled = false;
    setCaption(null);
    setError(null);

    (async () => {
      try {
        const url = cacheBustDev(
          `/data/story/${slug}/panels/intro.${unit}.caption.md`,
        );
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok)
          throw new Error(`Failed to load intro caption: ${res.status}`);
        const md = await res.text();
        if (!cancelled) setCaption(md);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [slug, unit, enabled]);

  return { caption, error };
}
