import React, { useMemo, useState } from "react";
import PanelFigure, { PanelFigureStyles } from "@/components/PanelFigure";
import Caption from "@/components/Caption";
import { useStoryPanel } from "@/hooks/useStoryPanel";
import { TrendingUp, Grid3x3 } from "lucide-react";

export type ManifestFigureVariant = {
  panel: string;
  kind: "svg" | "webp";
  icon?: "curve" | "heatmap";
};

export type ManifestFigure = {
  panel: string;
  kind?: "svg" | "webp";
  animate?: boolean;
  slot?: "left" | "right";
  variants?: ManifestFigureVariant[];
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

function panelAssetUrl(
  slug: string,
  unit: "C" | "F",
  panel: string,
  kind: "svg" | "webp",
) {
  // Matches the Python exporter convention: public/data/story/<slug>/panels/<panel>.<unit>.<ext>
  const ext = kind === "svg" ? "svg" : "webp";
  return `/data/story/${slug}/panels/${panel}.${unit}.${ext}`;
}

function VariantIcon({ icon }: { icon?: "curve" | "heatmap" }) {
  const cls = "h-5 w-5";
  if (icon === "curve")
    return <TrendingUp className={cls} aria-hidden="true" />;
  if (icon === "heatmap") return <Grid3x3 className={cls} aria-hidden="true" />;
  return null;
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

  const [sel, setSel] = useState<[number, number]>([0, 0]);

  // Caption is its own “panel” (caption-only fetch)
  const cap = useStoryPanel({
    slug,
    unit,
    panel: slide.caption_panel,
    loadSvg: false,
    loadCaption: true,
  });

  const figDef1 = slide.figures[0];
  const figDef2 = slide.figures[1];

  const choices1 = useMemo(() => {
    if (!figDef1) return [];
    const baseKind = (figDef1.kind ?? "svg") as "svg" | "webp";
    const base = { panel: figDef1.panel, kind: baseKind, icon: undefined };
    const vars = (figDef1.variants ?? []).map((v) => ({
      panel: v.panel,
      kind: v.kind,
      icon: v.icon,
    }));
    return [base, ...vars];
  }, [figDef1]);

  const choices2 = useMemo(() => {
    if (!figDef2) return [];
    const baseKind = (figDef2.kind ?? "svg") as "svg" | "webp";
    const base = { panel: figDef2.panel, kind: baseKind, icon: undefined };
    const vars = (figDef2.variants ?? []).map((v) => ({
      panel: v.panel,
      kind: v.kind,
      icon: v.icon,
    }));
    return [base, ...vars];
  }, [figDef2]);

  const active1 = choices1[sel[0]] ?? choices1[0];
  const active2 = choices2[sel[1]] ?? choices2[0];

  // Load SVG only when active kind is svg
  const fig1 = useStoryPanel({
    slug,
    unit,
    panel: active1?.panel ?? "",
    enabled: !!active1?.panel && active1?.kind === "svg",
    loadSvg: active1?.kind === "svg",
    loadCaption: false,
  });

  const fig2 = useStoryPanel({
    slug,
    unit,
    panel: active2?.panel ?? "",
    enabled: !!active2?.panel && active2?.kind === "svg",
    loadSvg: active2?.kind === "svg",
    loadCaption: false,
  });

  const anyLoading = cap.loading || fig1.loading || fig2.loading;
  const anyError = cap.error || fig1.error || fig2.error;

  // Layout
  function VariantButtons(props: {
    idx: 0 | 1;
    choices: Array<{ panel: string; kind: "svg" | "webp"; icon?: any }>;
    value: number;
    onChange: (n: number) => void;
  }) {
    const { choices, value, onChange } = props;
    if (!choices || choices.length <= 1) return null;

    // We only show buttons for variants (skip base at index 0)
    return (
      <div className="absolute right-3 top-3 flex gap-1 rounded-xl border border-neutral-200 bg-white/80 p-1 text-sm shadow-sm backdrop-blur dark:border-neutral-800 dark:bg-neutral-900/70">
        {choices.map((c, i) => {
          if (i === 0) return null;
          const active = i === value;
          return (
            <button
              key={`${c.panel}-${i}`}
              onClick={() => onChange(i)}
              className={[
                "h-8 w-9 rounded-lg border p-0",
                "inline-flex items-center justify-center", // ✅ center the icon
                active
                  ? "border-neutral-400 bg-white dark:border-neutral-500 dark:bg-neutral-800"
                  : "border-transparent hover:border-neutral-300 hover:bg-white/70 dark:hover:border-neutral-700 dark:hover:bg-neutral-800/70",
              ].join(" ")}
              title={
                c.icon === "curve"
                  ? "Trend"
                  : c.icon === "heatmap"
                    ? "Heatmap"
                    : "Variant"
              }
              aria-label={
                c.icon === "curve"
                  ? "Trend"
                  : c.icon === "heatmap"
                    ? "Heatmap"
                    : "Variant"
              }
            >
              <VariantIcon icon={c.icon} />
            </button>
          );
        })}
        {/* Reset to base */}
        <button
          onClick={() => onChange(0)}
          className={[
            "ml-1 h-8 rounded-lg border px-2 text-xs",
            value === 0
              ? "border-neutral-400 bg-white dark:border-neutral-500 dark:bg-neutral-800"
              : "border-transparent hover:border-neutral-300 hover:bg-white/70 dark:hover:border-neutral-700 dark:hover:bg-neutral-800/70",
          ].join(" ")}
          title="Default"
        >
          reset
        </button>
      </div>
    );
  }

  const renderFigure = (
    which: 1 | 2,
    active: { panel: string; kind: "svg" | "webp" } | undefined,
    svg: string | null,
    animate?: boolean,
    buttons?: React.ReactNode,
  ) => {
    if (!active) return null;
    return (
      <div className="relative">
        {buttons}
        {active.kind === "svg" ? (
          animate ? (
            <PanelFigure svg={svg} animate="draw" replayOnEnter />
          ) : (
            <PanelFigure svg={svg} />
          )
        ) : (
          <PanelFigure
            imgSrc={panelAssetUrl(slug, unit, active.panel, active.kind)}
            imgAlt={`${slide.id} ${active.panel}`}
          />
        )}
      </div>
    );
  };

  const body =
    slide.layout === "none" ? null : slide.layout === "single" ? (
      <div className="mt-4">
        {renderFigure(
          1,
          active1,
          fig1.svg,
          (figDef1?.animate ?? true) && active1?.kind === "svg",
          <VariantButtons
            idx={0}
            choices={choices1}
            value={sel[0]}
            onChange={(n) => setSel(([_, b]) => [n, b])}
          />,
        )}
      </div>
    ) : (
      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {renderFigure(
          1,
          active1,
          fig1.svg,
          (figDef1?.animate ?? true) && active1?.kind === "svg",
          <VariantButtons
            idx={0}
            choices={choices1}
            value={sel[0]}
            onChange={(n) => setSel(([_, b]) => [n, b])}
          />,
        )}
        {renderFigure(
          2,
          active2,
          fig2.svg,
          (figDef2?.animate ?? true) && active2?.kind === "svg",
          <VariantButtons
            idx={1}
            choices={choices2}
            value={sel[1]}
            onChange={(n) => setSel(([a, _]) => [a, n])}
          />,
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
