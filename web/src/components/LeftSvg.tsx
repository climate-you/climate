"use client";

import { useEffect, useMemo, useState } from "react";
import PanelFigure from "@/components/PanelFigure";

function cacheBustDev(url: string) {
  if (process.env.NODE_ENV !== "development") return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}_ts=${Date.now()}`;
}

// Simple in-memory cache so revisiting slides is instant.
const SVG_CACHE = new Map<string, string>();

export default function LeftSvg(props: {
  slug: string;
  unit: "C" | "F";
  src: string; // relative to /data/story/<slug>/
}) {
  const { slug, unit, src } = props;

  const [svg, setSvg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Resolve {unit} once per prop change.
  const resolved = useMemo(() => {
    if (!src) return "";
    return src.includes("{unit}") ? src.replace("{unit}", unit) : src;
  }, [src, unit]);

  useEffect(() => {
    if (!slug || !resolved) return;

    let cancelled = false;
    setErr(null);

    // Cache key should NOT include dev cache-bust query params.
    const baseUrl = `/data/story/${slug}/${resolved}`;

    // If we have it, show immediately (prevents “pill first, SVG later” on revisit).
    const cached = SVG_CACHE.get(baseUrl);
    if (cached) {
      setSvg(cached);
      return () => {
        cancelled = true;
      };
    }

    // Otherwise, hide content until loaded (so pill doesn't appear alone).
    setSvg(null);

    const fetchUrl = cacheBustDev(baseUrl);

    const fetchOpts: RequestInit =
      process.env.NODE_ENV === "development"
        ? { cache: "no-store" }
        : { cache: "force-cache" };

    (async () => {
      const r = await fetch(fetchUrl, fetchOpts);

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

      SVG_CACHE.set(baseUrl, text);
      setSvg(text);
    })().catch((e) => {
      if (cancelled) return;
      setErr(e instanceof Error ? e.message : String(e));
    });

    return () => {
      cancelled = true;
    };
  }, [slug, resolved]);

  if (err) {
    return (
      <div className="aspect-square w-full max-w-[420px] flex items-center justify-center rounded-xl border border-white/10 text-xs opacity-60">
        (map unavailable)
      </div>
    );
  }

  return (
    <div className="aspect-square w-full max-w-[420px]">
      {/* “Streamlit-like” pill: centers content + prevents overflow */}
      <div
        className={[
          "h-full w-full rounded-[28px] bg-white/95 dark:bg-white/90",
          "shadow-[0_20px_70px_rgba(0,0,0,0.35)]",
          "p-6 overflow-hidden",
          "flex items-center justify-center",
          "transition-opacity duration-300",
          svg ? "opacity-100" : "opacity-0",
        ].join(" ")}
      >
        {/* Force any injected SVG to fit the square nicely */}
        <div className="h-full w-full flex items-center justify-center [&_svg]:block [&_svg]:max-w-full [&_svg]:max-h-full [&_svg]:w-full [&_svg]:h-full">
          <PanelFigure svg={svg} />
        </div>
      </div>
    </div>
  );
}
