"use client";

import Caption from "@/components/Caption";
import PanelFigure, { PanelFigureStyles } from "@/components/PanelFigure";
import { useLiveAsof } from "@/hooks/useLiveAsof";
import { useLivePanel } from "@/hooks/useLivePanel";
// import { useState } from "react";


export default function LastMonthPanel(props: { slug: string; unit: "C" | "F" }) {
  const { slug, unit } = props;

  const { asof, error: asofErr } = useLiveAsof(slug, true);
  const { svg, caption, error } = useLivePanel({
    slug,
    unit,
    asof,
    panel: "last_month",
    enabled: true,
  });
  // const [figureDone, setFigureDone] = useState(false);

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-10">
      <h2 className="text-xl font-semibold tracking-tight">Last month - daily temperatures</h2>

      {asofErr && <p className="mt-4 text-sm text-red-600">{asofErr}</p>}

      {svg ? (
        <div className="mt-4 rounded-2xl border border-neutral-200 bg-white p-3">
          <PanelFigure
            svg={svg}
            animate="draw"
            replayOnEnter
            // onDrawComplete={() => setFigureDone(true)}
          />
          <PanelFigureStyles />
        </div>
      ) : (
        <p className="mt-4 text-sm text-neutral-500">Loading last month’s chart…</p>
      )}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {/*figureDone && */ caption && (
        <div className="mt-4 text-neutral-700">
          <Caption md={caption} reveal="sentences" />
        </div>
      )}
    </section>
  );
}
