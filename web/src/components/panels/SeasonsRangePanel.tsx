"use client";

import { useEffect, useState } from "react";
import PanelFigure from "@/components/PanelFigure";
import Caption from "@/components/Caption";

async function fetchText(url: string) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return await r.text();
}

export default function SeasonsRangePanel({
  slug,
  unit,
}: {
  slug: string;
  unit: "C" | "F";
}) {
  const [svgPast, setSvgPast] = useState<string | null>(null);
  const [svgRecent, setSvgRecent] = useState<string | null>(null);
  const [md, setMd] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setErr(null);
    setSvgPast(null);
    setSvgRecent(null);
    setMd(null);

    const base = `/data/story/${slug}/panels`;
    Promise.all([
      fetchText(`${base}/seasons_range_earlier.${unit}.svg`),
      fetchText(`${base}/seasons_range_recent.${unit}.svg`),
      fetchText(`${base}/seasons_range.${unit}.caption.md`),
    ])
      .then(([p, r, m]) => {
        if (cancelled) return;
        setSvgPast(p);
        setSvgRecent(r);
        setMd(m);
      })
      .catch((e) => {
        if (cancelled) return;
        setErr(String(e?.message ?? e));
      });

    return () => {
      cancelled = true;
    };
  }, [slug, unit]);

  if (err)
    return (
      <div className="text-sm text-neutral-500">
        Seasons range panel unavailable.
      </div>
    );

  return (
    <div className="mx-auto max-w-6xl px-4 pb-24">
      <h2 className="text-2xl font-semibold tracking-tight">
        How the range of monthly temperatures has changed
      </h2>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-neutral-200 bg-white/70 p-4 dark:border-neutral-800 dark:bg-[#171717]">
          <PanelFigure
            svg={svgPast}
            animate="draw"
            sequence="traces"
            drawMs={2000}
            replayOnEnter
          />
        </div>
        <div className="rounded-2xl border border-neutral-200 bg-white/70 p-4 dark:border-neutral-800 dark:bg-[#171717]">
          <PanelFigure
            svg={svgRecent}
            animate="draw"
            sequence="traces"
            drawMs={2000}
            replayOnEnter
          />
        </div>
      </div>

      {md && (
        <div className="mt-6 text-neutral-700 dark:text-neutral-200">
          <Caption md={md} reveal="sentences" />
        </div>
      )}
    </div>
  );
}
