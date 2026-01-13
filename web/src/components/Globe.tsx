import { useEffect, useRef } from "react";
import { GlobeEngine } from "./GlobeEngine";

function applyGlobeTheme(engine: GlobeEngine) {
  const isDark = document.documentElement.classList.contains("dark");

  engine.setPalette({
    // tweak to taste
    ocean: isDark ? "#2a2d33" : "#e0e0e0",
    // optional: also tweak grid/borders slightly in dark
    grid:  isDark ? "#8a8a8d" : "#49494b",
    border: isDark ? "#101010" : "#ffffff",
  });
}

export function Globe({
  targetLatLon,
  phase = "arrived",
  onArrive,
  variant = "hero",
  active = true,
  warmingConfig,
  initialSnapshot,
  onSnapshot,
}: {
  targetLatLon: { lat: number; lon: number } | null;
  phase?: "landing" | "flying" | "arrived";
  onArrive?: () => void;
  variant?: "hero" | "mini" | "warming";
  active?: boolean;
  warmingConfig?: {
    revealDelayMs?: number;
    revealFadeMs?: number;
    spinDelayMs?: number;
  };
  initialSnapshot?: any; // you can type this later
  onSnapshot?: (s: any) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const washRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<GlobeEngine | null>(null);
  const onArriveRef = useRef(onArrive);

  useEffect(() => {
    onArriveRef.current = onArrive;
  }, [onArrive]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // prevents accidental double-create
    if (engineRef.current) return;

    const engine = new GlobeEngine({
      canvas,
      assets: { basePath: "/data/textures", markerFile: "marker.png", emptyFile: "empty.png" },
      enableBorders: true,
      enableData: true,
      enableClouds: variant !== "warming",
      onArrive: () => onArriveRef.current?.(),
      timings: {
        globeFadeMs: 3500,
        cloudsDelayAfterGlobeMs: 500,
        cloudsFadeMs: 2000,
        dataDelayAfterGlobeMs: 2000,
      },
    });
    engineRef.current = engine;

    let ro: ResizeObserver | null = null;
    let obs: MutationObserver | null = null;
    let cancelled = false;

    (async () => {
      await engine.init();
      if (cancelled) return;

      engine.resize();
      engine.start();
      engine.warmup();

      // apply snapshot once (for mini handoff)
      if (initialSnapshot) {
        await engine.ready;
        engine.applySnapshot?.(initialSnapshot);
      }

      requestAnimationFrame(() => {
        washRef.current?.classList.add("is-visible");
      });

      if (variant === "hero") {
        engine.setAutorotate(true);
        engine.runIntroSequence(); // delayed clouds + delayed data
        // REMOVE this: engine.requestCloudsReveal(); (it fights the intro)
      } else if (variant === "warming") {
        engine.setAutorotate(false);
        engine.stopDataRevealCycle?.();
        engine.setDataOpacity(0, 0);
      } else {
        // mini defaults
        engine.setAutorotate(false);
        engine.requestCloudsReveal(); // instant clouds
        if (targetLatLon) engine.ready.then(() => engine.setFixedLocation(targetLatLon.lat, targetLatLon.lon));
        // do NOT call runIntroSequence in mini
      }
    
      applyGlobeTheme(engine);
      obs = new MutationObserver(() => applyGlobeTheme(engine));
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

      ro = new ResizeObserver(() => engine.resize());
      ro.observe(canvas);
    })();

    return () => {
      cancelled = true;
      ro?.disconnect();
      engine.destroy();
      engineRef.current = null;
      obs?.disconnect();
    };
  }, []); // ✅ important: empty deps

  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    if (variant !== "hero") return;

    if (phase === "landing") {
      eng.setAutorotate(true);
    }

    if (phase === "flying" && targetLatLon) {
      eng.ready.then(() => eng.flyTo(targetLatLon.lat, targetLatLon.lon));
    }

    if (phase === "arrived") eng.setAutorotate(false);
  }, [variant, phase, targetLatLon]);

  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    if (variant !== "mini") return;
    if (!targetLatLon) return;

    eng.ready.then(() => eng.setFixedLocation(targetLatLon.lat, targetLatLon.lon));
  }, [variant, targetLatLon?.lat, targetLatLon?.lon]);

  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    if (variant !== "warming") return;
    if (!targetLatLon) return;

    if (!active) {
      // reset so re-enter replays
      eng.ready.then(() => {
        eng.setAutorotate(false);
        eng.stopDataRevealCycle?.();
        eng.setDataOpacity(0, 0);
        eng.setFixedLocation(targetLatLon.lat, targetLatLon.lon);
      });
      return;
    }

    eng.ready.then(() => {
      eng.runWarmingSequence?.({
        lat: targetLatLon.lat,
        lon: targetLatLon.lon,
        revealDelayMs: warmingConfig?.revealDelayMs ?? 700,
        revealFadeMs: warmingConfig?.revealFadeMs ?? 2200,
        spinDelayMs: warmingConfig?.spinDelayMs ?? 500,
      });
    });
  }, [
    variant,
    active,
    targetLatLon?.lat,
    targetLatLon?.lon,
    warmingConfig?.revealDelayMs,
    warmingConfig?.revealFadeMs,
    warmingConfig?.spinDelayMs,
  ]);

  return (
    <div className="relative w-full h-full">
      <canvas ref={canvasRef} className="w-full h-full globe-canvas" />
      <div ref={washRef} className="globe-wash" aria-hidden />
    </div>
  );
}


