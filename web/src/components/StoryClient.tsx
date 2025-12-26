"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Globe from "@/components/Globe";
import type { CityIndexEntry } from "@/lib/cities";
import { nearestCity } from "@/lib/geo";
import { motion as M } from "@/config/motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Caption from "@/components/Caption"

type Phase = "landing" | "flying" | "arrived";

type PendingFlyTo = {
  lat: number;
  lon: number;
  label?: string;
  chosenSlug?: string;
};

const PENDING_KEY = "climateStory.pendingFlyTo.v1";

function cToF(c: number) {
  return (c * 9) / 5 + 32;
}

function readPendingFlyTo(): PendingFlyTo | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writePendingFlyTo(data: PendingFlyTo) {
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(data));
}

function clearPendingFlyTo() {
  sessionStorage.removeItem(PENDING_KEY);
}

async function loadCitiesIndex(): Promise<CityIndexEntry[]> {
  const res = await fetch("/data/cities_index.json", { cache: "force-cache" });
  if (!res.ok) throw new Error(`Failed to load cities_index.json: ${res.status}`);
  return res.json();
}

// Always fetch in Celsius (we convert locally for °F display)
async function fetchCurrentTempC(args: { lat: number; lon: number }) {
  const url = new URL("/api/weather/current", window.location.origin);
  url.searchParams.set("lat", String(args.lat));
  url.searchParams.set("lon", String(args.lon));
  url.searchParams.set("unit", "C");
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`current weather failed: ${res.status}`);

  // Your API currently returns { temperature, unit, ... }
  // We treat temperature as Celsius because we always requested unit=C.
  return res.json() as Promise<{
    temperature: number;
    unit: "C" | "F";
    time: string | null;
    timezone: string | null;
    cached: boolean;
    cacheAgeSeconds: number;
    source: string;
  }>;
}

export default function StoryClient() {
  const params = useParams();
  const slugParam = (params as any)?.slug;
  const slug =
    typeof slugParam === "string" ? slugParam : Array.isArray(slugParam) ? slugParam[0] : "auto";

  const router = useRouter();

  const [phase, setPhase] = useState<Phase>("landing");
  const [unit, setUnit] = useState<"C" | "F">("C");
  
  const [cities, setCities] = useState<CityIndexEntry[] | null>(null);
  const [target, setTarget] = useState<{ lat: number; lon: number } | null>(null);
  const [locationLabel, setLocationLabel] = useState<string>("your location");
  
  const [currentTempC, setCurrentTempC] = useState<number | null>(null);
  const [currentMeta, setCurrentMeta] = useState<{ cached: boolean; age: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const [introCaption, setIntroCaption] = useState<string | null>(null);
  const arrivedOnceRef = useRef(false);

  const [liveAsof, setLiveAsof] = useState<string | null>(null);
  const [lastWeekSvg, setLastWeekSvg] = useState<string | null>(null);
  const [lastWeekCaption, setLastWeekCaption] = useState<string | null>(null);

  // Load cities index once
  useEffect(() => {
    loadCitiesIndex()
      .then(setCities)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Boot logic: resolve slug + choose target; start landing, then fly after hold
  useEffect(() => {
    if (!cities) return;

    // Cleanup any pending fly timer on rerenders
    let flyTimer: number | null = null;

    const scheduleFly = () => {
      setPhase("landing");
      flyTimer = window.setTimeout(() => setPhase("flying"), M.layout.landingHoldMs);
    };

    if (slug !== "auto") {
      const pending = readPendingFlyTo();
      if (pending?.lat != null && pending?.lon != null) {
        clearPendingFlyTo();
        setTarget({ lat: pending.lat, lon: pending.lon });
        setLocationLabel(pending.label ?? locationLabelFromSlug(slug, cities));
        scheduleFly();
        return () => {
          if (flyTimer) window.clearTimeout(flyTimer);
        };
      }

      const city = cities.find((c) => c.slug === slug);
      if (city) {
        setTarget({ lat: city.lat, lon: city.lon });
        setLocationLabel(city.label);
        scheduleFly();
      } else {
        setError(`Unknown slug "${slug}" (not found in cities_index.json).`);
      }

      return () => {
        if (flyTimer) window.clearTimeout(flyTimer);
      };
    }

    // slug === "auto": geolocate then redirect to nearest city slug
    if (!navigator.geolocation) {
      const fallback = cities[0];
      writePendingFlyTo({ lat: fallback.lat, lon: fallback.lon, label: fallback.label, chosenSlug: fallback.slug });
      router.replace(`/story/${fallback.slug}`);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        const chosen = nearestCity(cities, { lat, lon });

        writePendingFlyTo({
          lat,
          lon,
          label: chosen?.label,
          chosenSlug: chosen?.slug,
        });

        router.replace(`/story/${chosen?.slug ?? cities[0].slug}`);
      },
      (geoErr) => {
        const fallback = cities[0];
        writePendingFlyTo({ lat: fallback.lat, lon: fallback.lon, label: fallback.label, chosenSlug: fallback.slug });
        router.replace(`/story/${fallback.slug}`);
        setError(`Geolocation unavailable (${geoErr.code}). Using ${fallback.label}.`);
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60_000 }
    );
  }, [slug, cities, router]);

  // When we arrive, fetch current temp once (in C)
  useEffect(() => {
    if (phase !== "arrived" || !target) return;

    let cancelled = false;
    setCurrentTempC(null);
    setCurrentMeta(null);

    fetchCurrentTempC({ lat: target.lat, lon: target.lon })
      .then((r) => {
        if (cancelled) return;
        setCurrentTempC(r.temperature);
        setCurrentMeta({ cached: r.cached, age: r.cacheAgeSeconds });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      cancelled = true;
    };
  }, [phase, target]);

  useEffect(() => {
    if (!slug || slug === "auto") return;

    let cancelled = false;
    setIntroCaption(null);

    const bust = process.env.NODE_ENV === "development" ? `?v=${Date.now()}` : "";
    const url = `/data/story/${slug}/panels/intro.${unit}.caption.md${bust}`;
    
    fetch(url, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load intro caption: ${r.status}`);
        return r.text();
      })
      .then((text) => {
        if (cancelled) return;
        setIntroCaption(text);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      cancelled = true;
    };
  }, [slug, unit]);

  useEffect(() => {
    if (!slug || slug === "auto") return;
    fetch("/data/live/latest.json", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null)
      .then(j => {
        const asof = j?.[slug];
        if (asof) setLiveAsof(asof);
      })
      .catch(() => {});
  }, [slug]);

  useEffect(() => {
    if (phase !== "arrived") return;
    if (!slug || slug === "auto") return;
    if (!liveAsof) return;

    let cancelled = false;
    setLastWeekSvg(null);
    setLastWeekCaption(null);

    const bust = process.env.NODE_ENV === "development" ? `?v=${Date.now()}` : "";
    const base = `/data/live/${liveAsof}/${slug}`;
    const svgUrl = `${base}/last_week.${unit}.svg${bust}`;
    const capUrl = `${base}/last_week.${unit}.caption.md${bust}`;

    Promise.all([
      fetch(svgUrl, { cache: "no-store" }).then((r) => {
        if (!r.ok) throw new Error(`Failed to load last_week SVG: ${r.status}`);
        return r.text();
      }),
      fetch(capUrl, { cache: "no-store" }).then((r) => {
        if (!r.ok) throw new Error(`Failed to load last_week caption: ${r.status}`);
        return r.text();
      }),
    ])
      .then(([svg, md]) => {
        if (cancelled) return;
        setLastWeekSvg(svg);
        setLastWeekCaption(md);
      })
      .catch((e) => {
        if (cancelled) return;
        // Don’t kill the whole page if live panels missing; just show a message.
        console.warn(e);
      });

    return () => {
      cancelled = true;
    };
  }, [phase, slug, unit, liveAsof]);

  const rightCaption = useMemo(() => {
    if (phase !== "arrived") return "Finding your location…";
    if (currentTempC == null) return `Getting the temperature in ${locationLabel}…`;

    const t = unit === "F" ? cToF(currentTempC) : currentTempC;
    return `It’s currently ${t.toFixed(1)}°${unit} in ${locationLabel}.`;
  }, [phase, currentTempC, unit, locationLabel]);

  // Layout durations (from config)
  const globeMoveMs = M.layout.globeMoveMs;
  const textFadeMs = M.layout.textFadeMs;

  // Keep a single masked viewport all the time; animate zoom inside it
  const zoom =
    phase === "landing" ? M.globe.zoomLanding : phase === "flying" ? M.globe.zoomFlying : M.globe.zoomArrived;

  return (
    <div className="min-h-screen bg-white text-neutral-900">
      {/* Top bar (unit toggle only) */}
      <div className="fixed top-0 left-0 right-0 z-30 flex items-center justify-end px-4 py-3">
        <button
          className="rounded-full border border-neutral-200 px-3 py-1 text-sm hover:bg-neutral-50"
          onClick={() => setUnit((u) => (u === "C" ? "F" : "C"))}
          aria-label="Toggle units"
        >
          °{unit}
        </button>
      </div>

      {/* Title: big + centered on landing, then shrinks into the top bar area */}
      <div
        className={[
          "fixed z-30 left-1/2 -translate-x-1/2 transition-all ease-in-out text-center",
          phase === "landing"
            ? "top-24 opacity-100"
            : "top-3 left-4 -translate-x-0 opacity-100",
        ].join(" ")}
        style={{ transitionDuration: `${textFadeMs}ms` }}
      >
        <div
          className={[
            "transition-all ease-in-out",
            phase === "landing" ? "text-5xl sm:text-6xl font-semibold tracking-tight" : "text-sm font-medium tracking-wide",
          ].join(" ")}
          style={{ transitionDuration: `${textFadeMs}ms` }}
        >
          Your climate
        </div>
      </div>

      {/* Main stage */}
      <div className="pt-14">
        <div className="mx-auto max-w-6xl px-4">
          <div className="relative h-[88vh] lg:h-[78vh]">
            {/* Globe block (position + size animates smoothly) */}
            <div
              className={[
                "absolute top-20 left-1/2 -translate-x-1/2 transition-all ease-in-out",
                phase === "landing" ? "" : "lg:left-0 lg:translate-x-0",
              ].join(" ")}
              style={{ transitionDuration: `${globeMoveMs}ms` }}
            >
              {/* Size animates by changing width (no scaling/clipping surprises) */}
              <div
                className="aspect-square"
                style={{
                  width: phase === "landing" ? "760px" : "420px",
                  maxWidth: phase === "landing" ? "92vw" : "86vw",
                  transition: `width ${globeMoveMs}ms ease-in-out, max-width ${globeMoveMs}ms ease-in-out`,
                }}
              >
                {/* Mask/viewport ALWAYS on (fixes “cropped then jump”) */}
                <div className="w-full h-full rounded-3xl overflow-hidden bg-white">
                  {/* Inner zoom ALWAYS animates */}
                  <div
                    className="w-full h-full transition-transform ease-in-out"
                    style={{
                      transform: `scale(${zoom})`,
                      transitionDuration: `${globeMoveMs}ms`,
                      transformOrigin: "center",
                    }}
                  >
                    <Globe
                      targetLatLon={target}
                      phase={phase}
                      mode="real"
                      showClouds={true}
                      onArrive={() => {
                        if (arrivedOnceRef.current) return;
                        arrivedOnceRef.current = true;
                        setPhase("arrived");
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Right panel: fades/slides in after landing */}
            <div
              className={[
                "absolute right-0 top-40 w-full lg:w-[520px] transition-all ease-in-out",
                phase === "landing" ? "opacity-0 translate-y-2 pointer-events-none" : "opacity-100 translate-y-0",
              ].join(" ")}
              style={{ transitionDuration: `${textFadeMs}ms` }}
            >
              <div className="pb-16">
                <div className="mt-6 lg:mt-10">
                  <h1 className="text-3xl font-semibold tracking-tight">{locationLabel}</h1>
                  <p className="mt-4 text-lg leading-relaxed text-neutral-700">{rightCaption}</p>
                  {introCaption && (
                    <div className="mt-6 space-y-4 text-neutral-700">
                      {introCaption && <Caption md={introCaption} />}
                    </div>
                  )}
                  {currentMeta && (
                    <p className="mt-2 text-xs text-neutral-500">
                      {currentMeta.cached ? "Cached" : "Fresh"} · age {Math.round(currentMeta.age / 60)} min
                    </p>
                  )}

                  {phase === "arrived" && (
                    <div className="mt-10 text-center lg:text-left">
                      <div className="text-sm text-neutral-500">Scroll down to explore your local climate</div>
                      <div className="mt-2 text-2xl">↓</div>
                    </div>
                  )}

                  {error && <p className="mt-6 text-sm text-red-600">{error}</p>}
                </div>
              </div>
            </div>

            <div className="absolute bottom-6 left-0 right-0 text-center text-xs text-neutral-400 lg:hidden">
              {phase === "arrived" ? "Scroll to continue" : ""}
            </div>
          </div>
          {/* Panels below (scroll) */}
          {phase === "arrived" && (
            <div className="mx-auto max-w-6xl px-4 pb-24">
              {/* Spacer so the scroll feels intentional */}
              <div className="h-10" />

              <section className="mt-10">
                <h2 className="text-xl font-semibold tracking-tight">Last week</h2>

                {lastWeekSvg ? (
                  <div className="mt-4 rounded-2xl border border-neutral-200 bg-white p-3">
                    {/* Make SVG responsive and not squashed */}
                    <div
                      className="chart-svg w-full"
                      style={{ maxWidth: "100%" }}
                      dangerouslySetInnerHTML={{ __html: lastWeekSvg }}
                    />
                    <style jsx>{`
                      :global(.chart-svg svg) {
                        width: 100% !important;
                        height: auto !important;
                        display: block;
                      }
                    `}</style>
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-neutral-500">
                    Loading last week’s chart…
                  </p>
                )}

                {lastWeekCaption && <Caption md={lastWeekCaption} />}
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function locationLabelFromSlug(slug: string, cities: CityIndexEntry[]) {
  return cities.find((c) => c.slug === slug)?.label ?? slug;
}
