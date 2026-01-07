import { useEffect, useRef } from "react";
import { GlobeEngine } from "./GlobeEngine";

export function Globe({
  targetLatLon,
  phase,
  onArrive,
  variant = "hero",
  initialSnapshot,
  onSnapshot,
}: {
  targetLatLon: { lat: number; lon: number } | null;
  phase: "landing" | "flying" | "arrived";
  onArrive?: () => void;
  variant?: "hero" | "mini";
  initialSnapshot?: any; // you can type this later
  onSnapshot?: (s: any) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
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
      onArrive: () => onArriveRef.current?.(),
      timings: {
        globeFadeMs: 2000,
        cloudsDelayAfterGlobeMs: 0,
        cloudsFadeMs: 1000,
        dataDelayAfterGlobeMs: 2000,
      },
    });
    engineRef.current = engine;

    let ro: ResizeObserver | null = null;
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
        canvas.classList.add("is-visible");
      });

      if (variant === "hero") {
        engine.setAutorotate(true);
        engine.runIntroSequence(); // delayed clouds + delayed data
        // REMOVE this: engine.requestCloudsReveal(); (it fights the intro)
      } else {
        // mini defaults
        engine.setAutorotate(false);
        engine.requestCloudsReveal(); // instant clouds
        if (targetLatLon) engine.ready.then(() => engine.setFixedLocation(targetLatLon.lat, targetLatLon.lon));
        // do NOT call runIntroSequence in mini
      }
    
      ro = new ResizeObserver(() => engine.resize());
      ro.observe(canvas);
    })();

    return () => {
      cancelled = true;
      ro?.disconnect();
      engine.destroy();
      engineRef.current = null;
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

  return <canvas ref={canvasRef} className="w-full h-full globe-canvas" />;
}


