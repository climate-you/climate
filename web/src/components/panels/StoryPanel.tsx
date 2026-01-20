"use client";

import Caption from "@/components/Caption";
import PanelFigure, { PanelFigureStyles } from "@/components/PanelFigure";
import { useStoryPanel, type StoryPanelName } from "@/hooks/useStoryPanel";

export default function StoryPanel(props: {
  slug: string;
  unit: "C" | "F";
  panel: StoryPanelName;
  title: string;
}) {
  const { slug, unit, panel, title } = props;

  const { svg, caption, error } = useStoryPanel({
    slug,
    unit,
    panel,
    enabled: true,
  });

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-10">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>

      {svg ? (
        <div
          className="mt-5 rounded-2xl border border-neutral-200 bg-white/70 p-4
                        dark:border-neutral-800 dark:bg-[#171717]"
        >
          <PanelFigure svg={svg} animate="draw" replayOnEnter />
          <PanelFigureStyles />
        </div>
      ) : (
        <p className="mt-4 text-sm text-neutral-500">Loading…</p>
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
