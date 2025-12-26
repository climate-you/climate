"use client";

import { useEffect, useState } from "react";

function cacheBustDev(url: string) {
  if (process.env.NODE_ENV === "development") {
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}v=${Date.now()}`;
  }
  return url;
}

export type StoryPanelName = "last_year" | "five_year" | "fifty_year" | "twenty_five_years";

export function useStoryPanel(args: {
  slug: string;
  unit: "C" | "F";
  panel: StoryPanelName;
  enabled: boolean;
}) {
  const { slug, unit, panel, enabled } = args;

  const [svg, setSvg] = useState<string | null>(null);
  const [caption, setCaption] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    if (!slug || slug === "auto") return;

    let cancelled = false;
    setSvg(null);
    setCaption(null);
    setError(null);

    (async () => {
      try {
        const base = `/data/story/${slug}/panels`;
        const svgUrl = cacheBustDev(`${base}/${panel}.${unit}.svg`);
        const capUrl = cacheBustDev(`${base}/${panel}.${unit}.caption.md`);

        const [svgRes, capRes] = await Promise.all([
          fetch(svgUrl, { cache: "no-store" }),
          fetch(capUrl, { cache: "no-store" }),
        ]);

        if (!svgRes.ok) throw new Error(`Failed to load ${panel} SVG: ${svgRes.status}`);
        if (!capRes.ok) throw new Error(`Failed to load ${panel} caption: ${capRes.status}`);

        const [svgText, capText] = await Promise.all([svgRes.text(), capRes.text()]);
        if (cancelled) return;

        setSvg(svgText);
        setCaption(capText);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [slug, unit, panel, enabled]);

  return { svg, caption, error };
}
