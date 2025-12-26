"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Globe from "@/components/Globe";
import type { CityIndexEntry } from "@/lib/cities";
import { nearestCity } from "@/lib/geo";

import { useCitiesIndex } from "@/hooks/useCitiesIndex";
import { useIntroCaption } from "@/hooks/useIntroCaption";
import Caption from "@/components/Caption";
import LastWeekPanel from "@/components/panels/LastWeekPanel";
import LastMonthPanel from "@/components/panels/LastMonthPanel";
import StoryPanel from "@/components/panels/StoryPanel";

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

async function fetchCurrentTemp(args: { lat: number; lon: number; unit: "C" | "F" }) {
  const url = new URL("/api/weather/current", window.location.origin);
  url.searchParams.set("lat", String(args.lat));
  url.searchParams.set("lon", String(args.lon));
  url.searchParams.set("unit", args.unit);

  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`current weather failed: ${res.status}`);

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
  const { cities, error: citiesError } = useCitiesIndex();

  const [phase, setPhase] = useState<Phase>("landing");
  const [unit, setUnit] = useState<"C" | "F">("C");

  const [target, setTarget] = useState<{ lat: number; lon: number } | null>(null);
  const [locationLabel, setLocationLabel] = useState<string>("your location");

  const [currentTemp, setCurrentTemp] = useState<number | null>(null);
  const [currentMeta, setCurrentMeta] = useState<{ cached: boolean; age: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const arrivedOnceRef = useRef(false);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);

  // Header animation (scroll-driven)
  const headerCompact = activeSlide > 0;
  const headerBarRef = useRef<HTMLDivElement | null>(null);
  const headerTitleRef = useRef<HTMLDivElement | null>(null);

  // null = not measured yet (so we can hide it and avoid the left->center slide)
  const [titleX, setTitleX] = useState<number | null>(null);
  const [headerReady, setHeaderReady] = useState(false);

  const computeTitleX = () => {
    const bar = headerBarRef.current;
    const title = headerTitleRef.current;
    if (!bar || !title) return;

    // Use layout widths (ignore transforms) so centering doesn't drift during scale animations.
    const barW = bar.clientWidth;      // ignores transforms
    const titleW = title.offsetWidth;  // ignores transforms
    const centerX = Math.max(0, (barW - titleW) / 2);

    setTitleX(headerCompact ? 0 : centerX);
  };

  useEffect(() => {
    if (!headerReady) return;
    requestAnimationFrame(() => computeTitleX());
  }, [activeSlide, headerReady]);
  
  // Track which snap “page” we’re on (0 = intro, 1 = last week, etc.)
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;

    const onScroll = () => {
      const h = el.clientHeight || 1;
      const idx = Math.round(el.scrollTop / h);
      setActiveSlide(idx);
    };

    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Compute the title X offset so it can smoothly slide center <-> left
  useLayoutEffect(() => {
    computeTitleX();

    if (!headerReady) {
      const raf = requestAnimationFrame(() => setHeaderReady(true));
      return () => cancelAnimationFrame(raf);
    }
  }, [headerCompact, headerReady]);
  useEffect(() => {
    window.addEventListener("resize", computeTitleX);
    return () => window.removeEventListener("resize", computeTitleX);
  }, [headerCompact]);

  // Re-measure after web fonts finish loading (fixes subtle off-center)
  useEffect(() => {
    let cancelled = false;

    const kick = () => {
      if (cancelled) return;
      computeTitleX();
      requestAnimationFrame(() => {
        if (cancelled) return;
        computeTitleX();
        requestAnimationFrame(() => {
          if (cancelled) return;
          computeTitleX();
        });
      });
    };

    const fontsAny = (document as any).fonts;
    if (fontsAny?.ready) {
      fontsAny.ready.then(kick).catch(() => {});
    }

    const t = window.setTimeout(kick, 50);

    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [headerCompact]);

  // Boot logic: resolve slug -> target; for /auto -> geolocate and redirect
  useEffect(() => {
    if (!cities) return;

    // If we're on a concrete slug page, try to restore pending fly-to (from /auto redirect)
    if (slug !== "auto") {
      const pending = readPendingFlyTo();
      if (pending?.lat != null && pending?.lon != null) {
        clearPendingFlyTo();
        setTarget({ lat: pending.lat, lon: pending.lon });
        setLocationLabel(pending.label ?? locationLabelFromSlug(slug, cities));
        setPhase("landing");
        window.setTimeout(() => setPhase("flying"), 3600);
        return;
      }

      const city = cities.find((c) => c.slug === slug);
      if (city) {
        setTarget({ lat: city.lat, lon: city.lon });
        setLocationLabel(city.label);
        setPhase("landing");
        window.setTimeout(() => setPhase("flying"), 3600);
      } else {
        setError(`Unknown slug "${slug}" (not found in cities_index.json).`);
      }
      return;
    }

    // slug === "auto": request geolocation then choose nearest city and redirect
    if (!navigator.geolocation) {
      const fallback = cities[0];
      writePendingFlyTo({
        lat: fallback.lat,
        lon: fallback.lon,
        label: fallback.label,
        chosenSlug: fallback.slug,
      });
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
        writePendingFlyTo({
          lat: fallback.lat,
          lon: fallback.lon,
          label: fallback.label,
          chosenSlug: fallback.slug,
        });
        router.replace(`/story/${fallback.slug}`);
        setError(`Geolocation unavailable (${geoErr.code}). Using ${fallback.label}.`);
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60_000 }
    );
  }, [slug, cities, router]);

  // When we “arrive”, fetch current temperature (proxy API)
  useEffect(() => {
    if (phase !== "arrived" || !target) return;

    let cancelled = false;
    setCurrentTemp(null);
    setCurrentMeta(null);

    fetchCurrentTemp({ lat: target.lat, lon: target.lon, unit })
      .then((r) => {
        if (cancelled) return;
        setCurrentTemp(r.temperature);
        setCurrentMeta({ cached: r.cached, age: r.cacheAgeSeconds });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      cancelled = true;
    };
  }, [phase, target, unit]);

  const { caption: introCaption } = useIntroCaption({
    slug,
    unit,
    enabled: phase !== "landing" && slug !== "auto",
  });

  const rightCaption = useMemo(() => {
    if (phase !== "arrived") return "Finding your location…";
    if (currentTemp == null) return `Getting the temperature in ${locationLabel}…`;

    const t = unit === "F" ? cToF(currentTemp) : currentTemp;
    return `It’s currently ${t.toFixed(1)}°${unit} in ${locationLabel}.`;
  }, [phase, currentTemp, unit, locationLabel]);

  return (
    <div className="min-h-screen text-neutral-900 bg-gradient-to-b from-white via-slate-50 to-white">
      {/* subtle background accents */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -top-24 left-1/2 h-[520px] w-[520px] -translate-x-1/2 rounded-full bg-[radial-gradient(circle_at_center,rgba(59,130,246,0.12),transparent_60%)]" />
        <div className="absolute bottom-[-140px] right-[-160px] h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle_at_center,rgba(244,63,94,0.10),transparent_60%)]" />
      </div>

      {/* Top bar (scroll-driven sliding title) */}
      <div className="fixed top-0 left-0 right-0 z-20 bg-white/70 backdrop-blur">
        <div ref={headerBarRef} className="mx-auto w-full px-4 sm:px-6 lg:px-10 py-3">
          <div className="relative h-[56px]">
            {/* Title: slides center <-> left via transform, eases both ways */}
            <div
              ref={headerTitleRef}
              className={[
                "absolute top-1/2 left-0 will-change-transform",
                // Fade in only after first measurement
                "transition-opacity duration-300",
                headerReady ? "opacity-100" : "opacity-0",
                // Only enable transform transition once ready (prevents initial “slide-in”)
                headerReady ? "transition-transform duration-1200" : "",
              ].join(" ")}
              style={{
                transform: `translateX(${titleX ?? 0}px) translateY(-50%) scale(${headerCompact ? 0.62 : 1})`,
                transformOrigin: "left center",
                // A noticeably “eased” curve (more obvious than plain ease-in-out)
                transitionTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
              }}
            >
              <div className="text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight">Your climate</div>
            </div>

            {/* Subtitle: fades in on panels */}
            <div
              className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-base sm:text-lg text-neutral-600 transition-opacity duration-500 ease-in-out"
              style={{ opacity: headerCompact ? 1 : 0 }}
            >
              Zooming out: from days to decades
            </div>

            {/* Units toggle */}
            <div className="absolute right-0 top-1/2 -translate-y-1/2">
              <button
                className="rounded-full border border-neutral-200 bg-white px-3 py-1 text-sm hover:bg-neutral-50"
                onClick={() => setUnit((u) => (u === "C" ? "F" : "C"))}
                aria-label="Toggle units"
              >
                °{unit}
              </button>
            </div>
          </div>
        </div>
      </div>


      {/* Main layout */}
      <div className="pt-14">
        <div className="lg:grid lg:grid-cols-[420px_1fr]">
          {/* LEFT: persistent globe on lg only */}
          <div className="hidden lg:block">
            <div className="sticky top-0 h-[calc(100vh-56px)]">
              <div className="flex h-full items-center justify-center px-6">
                <div className="aspect-square w-full max-w-[420px] overflow-hidden rounded-3xl">
                  <Globe
                    targetLatLon={target}
                    phase={phase}
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

          {/* RIGHT: snap scroller */}
          <div
            ref={scrollerRef}
            className="h-[calc(100vh-56px)] overflow-y-auto snap-y snap-mandatory scroll-smooth"
          >
            {/* Slide 1 (mobile): intro with animated globe */}
            <div className="snap-start lg:hidden">
              <div className="mx-auto max-w-6xl px-4">
                <div className="relative min-h-[calc(100vh-56px)]">
                  <div
                    className={[
                      "absolute top-10 left-1/2 -translate-x-1/2 transition-all duration-[2800ms] ease-in-out",
                      phase === "landing" ? "translate-y-0" : "translate-y-0",
                    ].join(" ")}
                  >
                    <div
                      className={[
                        "aspect-square transition-all duration-[2800ms] ease-in-out",
                        phase === "landing" ? "w-[760px] max-w-[92vw]" : "w-[520px] max-w-[86vw]",
                      ].join(" ")}
                    >
                      <Globe
                        targetLatLon={target}
                        phase={phase}
                        onArrive={() => {
                          if (arrivedOnceRef.current) return;
                          arrivedOnceRef.current = true;
                          setPhase("arrived");
                        }}
                      />
                    </div>
                  </div>

                  <div
                    className={[
                      "absolute right-0 top-24 w-full transition-all duration-[1800ms] ease-in-out",
                      phase === "landing" ? "opacity-0 translate-y-2 pointer-events-none" : "opacity-100 translate-y-0",
                    ].join(" ")}
                  >
                    <div className="pb-16">
                      <div className="mt-6">
                        <h1 className="text-3xl font-semibold tracking-tight">{locationLabel}</h1>
                        <p className="mt-4 text-lg leading-relaxed text-neutral-700">{rightCaption}</p>

                        {introCaption && (
                          <div className="mt-6 text-neutral-700">
                            <Caption md={introCaption} />
                          </div>
                        )}

                        {currentMeta && (
                          <p className="mt-2 text-xs text-neutral-500">
                            {currentMeta.cached ? "Cached" : "Fresh"} · age {Math.round(currentMeta.age / 60)} min
                          </p>
                        )}

                        {phase === "arrived" && (
                          <div className="mt-10 text-center">
                            <div className="text-sm text-neutral-500">Scroll down to explore your local climate</div>
                            <div className="mt-2 text-2xl">↓</div>
                          </div>
                        )}

                        {(citiesError || error) && (
                          <p className="mt-6 text-sm text-red-600">{citiesError ?? error}</p>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="absolute bottom-6 left-0 right-0 text-center text-xs text-neutral-400">
                    {phase === "arrived" ? "Scroll to continue" : ""}
                  </div>
                </div>
              </div>
            </div>

            {/* Slide 1 (lg): intro text only (globe is on the left) */}
            <div className="snap-start hidden lg:flex min-h-[calc(100vh-56px)] items-center">
              <div className="mx-auto w-full max-w-2xl px-4">
                <h1 className="text-4xl font-semibold tracking-tight">{locationLabel}</h1>
                <p className="mt-5 text-xl leading-relaxed text-neutral-700">{rightCaption}</p>

                {introCaption && (
                  <div className="mt-8 text-neutral-700">
                    <Caption md={introCaption} />
                  </div>
                )}

                {currentMeta && (
                  <p className="mt-3 text-xs text-neutral-500">
                    {currentMeta.cached ? "Cached" : "Fresh"} · age {Math.round(currentMeta.age / 60)} min
                  </p>
                )}

                {phase === "arrived" && (
                  <div className="mt-10">
                    <div className="text-sm text-neutral-500">Scroll down to explore your local climate</div>
                    <div className="mt-2 text-2xl">↓</div>
                  </div>
                )}

                {(citiesError || error) && (
                  <p className="mt-6 text-sm text-red-600">{citiesError ?? error}</p>
                )}
              </div>
            </div>

            {/* Slides 2+: Panels */}
            {phase === "arrived" && slug !== "auto" && (
              <>
                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <LastWeekPanel slug={slug} unit={unit} />
                  </div>
                </div>

                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <LastMonthPanel slug={slug} unit={unit} />
                  </div>
                </div>

                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <StoryPanel slug={slug} unit={unit} panel="last_year" title="Last year" />
                  </div>
                </div>

                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <StoryPanel slug={slug} unit={unit} panel="five_year" title="Last 5 years" />
                  </div>
                </div>

                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <StoryPanel slug={slug} unit={unit} panel="fifty_year" title="Last 50 years" />
                  </div>
                </div>

                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <StoryPanel slug={slug} unit={unit} panel="twenty_five_years" title="25 years ahead" />
                  </div>
                </div>

                <div className="h-24" />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function locationLabelFromSlug(slug: string, cities: CityIndexEntry[]) {
  return cities.find((c) => c.slug === slug)?.label ?? slug;
}
