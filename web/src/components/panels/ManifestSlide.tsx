import React, { useMemo } from "react";
import PanelFigure, { PanelFigureStyles } from "@/components/PanelFigure";
import Caption from "@/components/Caption";
import { useStoryPanel } from "@/hooks/useStoryPanel";

export type ManifestFigure = {
  panel: string;
  kind?: "svg";
  animate?: boolean;
  slot?: "left" | "right";
};

export type ManifestLeft =
  | { kind: "globe" }
  | { kind: "svg"; asset: string }
  | { kind: "none" };

export type ManifestSlideDef = {
  id: string;
  layout: "none" | "single" | "two_up";
  figures: ManifestFigure[];
  caption_panel: string;
  left?: ManifestLeft;
};

function titleFromId(id: string) {
  return id.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

export default function ManifestSlide({
  slug,
  unit,
  slide,
}: {
  slug: string;
  unit: "C" | "F";
  slide: ManifestSlideDef;
}) {
  const title = useMemo(() => titleFromId(slide.id), [slide.id]);

  // Caption is its own “panel” (caption-only fetch)
  const cap = useStoryPanel({
    slug,
    unit,
    panel: slide.caption_panel,
    loadSvg: false,
    loadCaption: true,
  });

  // Figure SVGs (svg-only fetch)
  const one = slide.figures[0]?.panel;
  const two = slide.figures[1]?.panel;

  const fig1 = useStoryPanel({
    slug,
    unit,
    panel: one ?? "",
    enabled: !!one,
    loadSvg: true,
    loadCaption: false,
  });

  const fig2 = useStoryPanel({
    slug,
    unit,
    panel: two ?? "",
    enabled: !!two,
    loadSvg: true,
    loadCaption: false,
  });

  const anyLoading = cap.loading || fig1.loading || fig2.loading;
  const anyError = cap.error || fig1.error || fig2.error;

  // Layout
  const body =
    slide.layout === "none" ? null : slide.layout === "single" ? (
      <div className="mt-4">
        {(slide.figures[0]?.animate ?? true) ? (
          <PanelFigure svg={fig1.svg} animate="draw" replayOnEnter />
        ) : (
          <PanelFigure svg={fig1.svg} />
        )}
      </div>
    ) : (
      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {(slide.figures[0]?.animate ?? true) ? (
          <PanelFigure svg={fig1.svg} animate="draw" replayOnEnter />
        ) : (
          <PanelFigure svg={fig1.svg} />
        )}
        {(slide.figures[1]?.animate ?? true) ? (
          <PanelFigure svg={fig2.svg} animate="draw" replayOnEnter />
        ) : (
          <PanelFigure svg={fig2.svg} />
        )}
      </div>
    );

  return (
    <div className="pt-10 pb-8">
      <div className="flex items-end justify-between">
        <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
        {anyLoading && (
          <div className="text-sm text-neutral-500 dark:text-neutral-400">
            Loading…
          </div>
        )}
      </div>

      {anyError && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-200">
          {anyError}
        </div>
      )}

      {body}

      {cap.caption && (
        <div className="mt-6 text-neutral-700 dark:text-neutral-200">
          <Caption md={cap.caption} reveal="sentences" />
        </div>
      )}

      <PanelFigureStyles />
    </div>
  );
}
