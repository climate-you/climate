"use client";

import { useEffect, useState } from "react";
import PanelFigure from "@/components/PanelFigure";
import Caption from "@/components/Caption";

async function fetchText(url: string) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return await r.text();
}

export default function YouVsWorldPanel({ slug, unit }: { slug: string; unit: "C" | "F" }) {
  const [svgLocal, setSvgLocal] = useState<string | null>(null);
  const [svgGlobal, setSvgGlobal] = useState<string | null>(null);
  const [md, setMd] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setErr(null);
    setSvgLocal(null);
    setSvgGlobal(null);
    setMd(null);

    const base = `/data/story/${slug}/panels`;
    Promise.all([
      fetchText(`${base}/you_vs_world_local.${unit}.svg`),
      fetchText(`${base}/you_vs_world_global.${unit}.svg`),
      fetchText(`${base}/you_vs_world.${unit}.caption.md`),
    ])
      .then(([a, b, c]) => {
        if (cancelled) return;
        setSvgLocal(a);
        setSvgGlobal(b);
        setMd(c);
      })
      .catch((e) => {
        if (cancelled) return;
        setErr(String(e?.message ?? e));
      });

    return () => {
      cancelled = true;
    };
  }, [slug, unit]);

  if (err) return <div className="text-sm text-neutral-500">World comparison panel unavailable.</div>;

  return (
    <div className="mx-auto max-w-6xl px-4 pb-24">
      <h2 className="text-2xl font-semibold tracking-tight">Your warming vs global warming</h2>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-neutral-200 bg-white/70 p-4 dark:border-neutral-800 dark:bg-[#171717]">
          <PanelFigure svg={svgLocal} animate="draw" sequence="traces" drawMs={2200} replayOnEnter />
        </div>
        <div className="rounded-2xl border border-neutral-200 bg-white/70 p-4 dark:border-neutral-800 dark:bg-[#171717]">
          <PanelFigure svg={svgGlobal} animate="draw" sequence="traces" drawMs={2200} replayOnEnter />
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
