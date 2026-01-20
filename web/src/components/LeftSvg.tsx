"use client";

import { useEffect, useState } from "react";
import PanelFigure from "@/components/PanelFigure";

function cacheBustDev(url: string) {
  if (process.env.NODE_ENV !== "development") return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}_ts=${Date.now()}`;
}

export default function LeftSvg(props: {
  slug: string;
  unit: "C" | "F";
  src: string; // relative to /data/story/<slug>/
}) {
  const { slug, unit, src } = props;

  const [svg, setSvg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!slug || !src) return;

    let cancelled = false;
    setSvg(null);
    setErr(null);

    // Allow optional "{unit}" token in story.json (nice for future unit-specific assets)
    const resolved = src.includes("{unit}") ? src.replace("{unit}", unit) : src;

    const url = cacheBustDev(`/data/story/${slug}/${resolved}`);

    (async () => {
      const r = await fetch(url, { cache: "no-store" });

      // Soft-fail on missing assets (common while a map hasn't been exported yet)
      if (r.status === 404) {
        if (cancelled) return;
        setSvg(null);
        setErr(null);
        return;
      }

      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(
          `Failed to load left SVG (${r.status}): ${resolved} ${t}`,
        );
      }

      const text = await r.text();
      if (cancelled) return;
      setSvg(text);
    })().catch((e) => {
      if (cancelled) return;
      setErr(e instanceof Error ? e.message : String(e));
    });

    return () => {
      cancelled = true;
    };
  }, [slug, unit, src]);

  if (err) {
    return (
      <div className="aspect-square w-full max-w-[420px] flex items-center justify-center rounded-xl border border-white/10 text-xs opacity-60">
        (map unavailable)
      </div>
    );
  }

  return (
    <div className="aspect-square w-full max-w-[420px]">
      <PanelFigure svg={svg} />
    </div>
  );
}
