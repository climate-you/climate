"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Globe } from "@/components/Globe";
import Caption from "@/components/Caption";

function WarmingLegend({ unit }: { unit: "C" | "F" }) {
  const ticks = unit === "C"
    ? [-1, 0, 1, 2, 3, 4]
    : [-1, 0, 1, 2, 3, 4, 5, 6, 7];

  const gradient = "linear-gradient(to bottom, #ffffcc, #ffeda0, #feb24c, #f03b20, #bd0026)";

  return (
    <div className="flex items-center gap-3">
      <div className="h-56 w-3 rounded-full" style={{ background: gradient }} />
      <div className="flex h-56 flex-col justify-between text-xs text-neutral-600 dark:text-neutral-300">
        {ticks.map((t) => (
          <div key={t} className="flex items-center gap-2">
            <div className="h-px w-3 bg-neutral-400/60 dark:bg-neutral-500/60" />
            <div>
              {t}°{unit}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function WarmingGlobePanel({
  target,
  unit,
  locationLabel,
}: {
  target: { lat: number; lon: number } | null;
  unit: "C" | "F";
  locationLabel: string;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState(false);

  // start/reset animation when this slide is visible within the story scroller
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;

    const scroller = el.closest("[data-story-scroller]") as HTMLElement | null;

    const io = new IntersectionObserver(
      (entries) => {
        const e = entries[0];
        setActive(!!e?.isIntersecting);
      },
      {
        root: scroller ?? null, // fallback to viewport if not found
        threshold: 0.6,
      }
    );

    io.observe(el);
    return () => io.disconnect();
  }, []);

  const md = useMemo(() => {
    return [
      `This globe shows warming in **2016–2025 vs 1979–1988** (ERA5 2m air temperature).`,
      ``,
      `It blends from a neutral Earth view into the **warming map**, then begins a slow rotation.`,
      ``,
      `*Centered on **${locationLabel}**.*`,
    ].join("\n");
  }, [locationLabel]);

  return (
    <div ref={rootRef} className="w-full">
      <div className="relative">
        {/* Big globe (centered in viewport; compensate for the fixed left globe column on lg) */}
        <div className="mx-auto aspect-square w-full max-w-[980px] lg:-translate-x-[210px]">
          <Globe
            variant="warming"
            targetLatLon={target}
            active={active}
            warmingConfig={{ revealDelayMs: 900, revealFadeMs: 2600, spinDelayMs: 600 }}
          />
        </div>

        {/* Legend */}
        <div className="pointer-events-none mt-6 flex justify-center lg:absolute lg:right-0 lg:top-1/2 lg:mt-0 lg:-translate-y-1/2">
          <div className="rounded-2xl border border-neutral-200 bg-white/70 p-3 backdrop-blur dark:border-neutral-800 dark:bg-[#171717]/70">
            <div className="mb-2 text-xs font-medium text-neutral-700 dark:text-neutral-200">
              Warming (°{unit})
            </div>
            <WarmingLegend unit={unit} />
          </div>
        </div>
      </div>

      <div className="mx-auto mt-8 max-w-3xl">
        <Caption md={md} reveal="sentences" />
      </div>
    </div>
  );
}
