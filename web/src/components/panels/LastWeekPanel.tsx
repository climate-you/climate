"use client";

import Caption from "@/components/Caption";
import PanelFigure, { PanelFigureStyles } from "@/components/PanelFigure";
import { useLiveAsof } from "@/hooks/useLiveAsof";
import { useLivePanel } from "@/hooks/useLivePanel";

export default function LastWeekPanel(props: {
  slug: string;
  unit: "C" | "F";
}) {
  const { slug, unit } = props;

  const { asof, error: asofErr } = useLiveAsof(slug, true);
  const { svg, caption, error } = useLivePanel({
    slug,
    unit,
    asof,
    panel: "last_week",
    enabled: true,
  });

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-10">
      <h2 className="text-xl font-semibold tracking-tight">
        Last week - the daily cycle
      </h2>

      {asofErr && <p className="mt-4 text-sm text-red-600">{asofErr}</p>}

      {svg ? (
        <div
          className="mt-5 rounded-2xl border border-neutral-200 bg-white/70 p-4
                        dark:border-neutral-800 dark:bg-[#171717]"
        >
          <PanelFigure svg={svg} animate="draw" replayOnEnter />
          <PanelFigureStyles />
        </div>
      ) : (
        <p className="mt-4 text-sm text-neutral-500">
          Loading last week’s chart…
        </p>
      )}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {caption && (
        <div className="mt-4 text-neutral-700">
          <Caption md={caption} reveal="sentences" />
        </div>
      )}
    </section>
  );
}
