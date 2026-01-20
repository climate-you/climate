import { useEffect, useState } from "react";

export type StoryPanelName = string;

function cacheBustDev(url: string) {
  if (process.env.NODE_ENV !== "development") return url;
  const u = new URL(url, window.location.origin);
  u.searchParams.set("_ts", String(Date.now()));
  return u.pathname + u.search;
}

type Args = {
  slug: string;
  unit: "C" | "F";
  panel: StoryPanelName;
  enabled?: boolean;

  // New: allow fetching only what we need
  loadSvg?: boolean; // default true
  loadCaption?: boolean; // default true
  captionPanel?: string; // default = panel
};

export function useStoryPanel({
  slug,
  unit,
  panel,
  enabled = true,
  loadSvg = true,
  loadCaption = true,
  captionPanel,
}: Args) {
  const [svg, setSvg] = useState<string | null>(null);
  const [caption, setCaption] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setSvg(null);
    setCaption(null);

    const capName = captionPanel ?? panel;

    const svgUrl = loadSvg
      ? cacheBustDev(`/data/story/${slug}/panels/${panel}.${unit}.svg`)
      : null;

    const capUrl = loadCaption
      ? cacheBustDev(`/data/story/${slug}/panels/${capName}.${unit}.caption.md`)
      : null;

    const fetchSvg = async () => {
      if (!svgUrl) return null;
      const r = await fetch(svgUrl, { cache: "no-store" });
      if (!r.ok) throw new Error(`Failed to load SVG: ${panel} (${r.status})`);
      return await r.text();
    };

    const fetchCaption = async () => {
      if (!capUrl) return null;
      const r = await fetch(capUrl, { cache: "no-store" });
      if (!r.ok)
        throw new Error(`Failed to load caption: ${capName} (${r.status})`);
      return await r.text();
    };

    Promise.all([fetchSvg(), fetchCaption()])
      .then(([svgText, capText]) => {
        if (cancelled) return;
        if (svgText != null) setSvg(svgText);
        if (capText != null) setCaption(capText);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [slug, unit, panel, enabled, loadSvg, loadCaption, captionPanel]);

  return { svg, caption, loading, error };
}
