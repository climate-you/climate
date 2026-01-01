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

  const [tempLoading, setTempLoading] = useState(false);
  const tempFetchKeyRef = useRef<string | null>(null);

  const arrivedOnceRef = useRef(false);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);

  // For /story/auto: prevent double geolocation calls
  const [autoResolving, setAutoResolving] = useState(false);
  const didAutoRedirectRef = useRef(false);

  const COLD_OPEN_MS = 3200;   // tweak: pure spinning globe, no UI, no geolocation
  const PRELUDE_MS = 4200;     // tweak: locate + fly-to + brief settle before story UI

  const [coldOpenDone, setColdOpenDone] = useState(false);
  const [showStory, setShowStory] = useState(false);

  // Handoff: hero globe shrinks/moves to dock then fades out
  const HANDOFF_MS = 900;
  const [heroLeaving, setHeroLeaving] = useState(false);

  const [skipHeroPrelude, setSkipHeroPrelude] = useState(false);

  // prevents the “left then zip to center” on first paint
  const [titlePrimed, setTitlePrimed] = useState(false);

  // Reset when slug changes (navigating between cities)
  useEffect(() => {
  setShowStory(false);
  setSkipHeroPrelude(false);
  setTitlePrimed(false);
  setTitleX(null);
  setHeaderReady(false);

  tempFetchKeyRef.current = null;
  setCurrentTemp(null);
  setCurrentMeta(null);
  setError(null);
  setTempLoading(false);
}, [slug]);

  // Header animation (scroll-driven)
  // IMPORTANT: only compact after story is visible AND we've scrolled past the intro slide.
  const headerCompact = showStory && activeSlide > 0;
  const headerBarRef = useRef<HTMLDivElement | null>(null);
  const headerTitleRef = useRef<HTMLDivElement | null>(null);

  // null = not measured yet (so we can hide it and avoid the left->center slide)
  const [titleX, setTitleX] = useState<number | null>(null);
  const [headerReady, setHeaderReady] = useState(false);

  // 1) Cold open timer: no UI, no geolocation
  useEffect(() => {
    // If we just redirected from /auto, don't replay cold-open (prevents flashing)
    const pending = slug !== "auto" ? readPendingFlyTo() : null;
    if (pending) {
      setSkipHeroPrelude(true);
      setColdOpenDone(true);
      return;
    }

    setColdOpenDone(false);
    const t = window.setTimeout(() => setColdOpenDone(true), COLD_OPEN_MS);
    return () => window.clearTimeout(t);
  }, [slug]);

  // 2) Story mode timer: starts only once we have a target AND cold open is done
  const STORY_REVEAL_MS = 1200; // tweak: after cold-open, how quickly story UI appears on /story/<slug>
  useEffect(() => {
    // Never show story UI on /auto (we redirect instead)
    if (slug === "auto") {
      setShowStory(false);
      return;
    }

    // If we came from /auto redirect, skip hero and show story immediately
    if (skipHeroPrelude) {
      setShowStory(true);
      return;
    }

    // Otherwise show story shortly after cold open completes
    if (!coldOpenDone) {
      setShowStory(false);
      return;
    }

    const t = window.setTimeout(() => {
      setShowStory(true);
      if (scrollerRef.current) scrollerRef.current.scrollTo({ top: 0 });
      setActiveSlide(0);
    }, STORY_REVEAL_MS);

    return () => window.clearTimeout(t);
  }, [slug, skipHeroPrelude, coldOpenDone]);

  // 3) When story becomes visible, animate hero globe into dock and fade it out
  useEffect(() => {
    if (!showStory) return;

    setHeroLeaving(true);
    const t = window.setTimeout(() => setHeroLeaving(false), HANDOFF_MS);
    return () => window.clearTimeout(t);
  }, [showStory]);

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

  useEffect(() => {
    if (!showStory) return;
    if (!headerReady) return;
    if (titleX === null) return;
    if (titlePrimed) return;
    // Title has a valid X — allow subsequent transitions
    setTitlePrimed(true);
  }, [showStory, headerReady, titleX, titlePrimed]);

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
  }, [showStory]);

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
    if (!coldOpenDone) return;
    if (autoResolving) return;
    if (didAutoRedirectRef.current) return;

    setAutoResolving(true);

    if (!navigator.geolocation) {
      const fallback = cities[0];
      writePendingFlyTo({
        lat: fallback.lat,
        lon: fallback.lon,
        label: fallback.label,
        chosenSlug: fallback.slug,
      });
      didAutoRedirectRef.current = true;
      setTimeout(() => {
        router.replace(`/story/${fallback.slug}`);
      }, 0);
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

        didAutoRedirectRef.current = true;
        // microtask to avoid dev router edge cases
        setTimeout(() => {
          router.replace(`/story/${chosen?.slug ?? cities[0].slug}`);
        }, 0);
        // DO NOT setAutoResolving(false) here — navigation will replace the page
      },
      (geoErr) => {
        const fallback = cities[0];
        writePendingFlyTo({
          lat: fallback.lat,
          lon: fallback.lon,
          label: fallback.label,
          chosenSlug: fallback.slug,
        });
        didAutoRedirectRef.current = true;
        setTimeout(() => {
          router.replace(`/story/${fallback.slug}`);
        }, 0);
        setError(`Geolocation unavailable (${geoErr.code}). Using ${fallback.label}.`);
        // DO NOT setAutoResolving(false) here
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60_000 }
    );
  }, [slug, cities, router, coldOpenDone, autoResolving]);

  // Fetch current temperature (proxy API) once we have a target.
  useEffect(() => {
    if (!target) return;

    const key = `${target.lat.toFixed(4)},${target.lon.toFixed(4)}`;
    if (tempFetchKeyRef.current === key) return; // already fetched for this location
    tempFetchKeyRef.current = key;

    let cancelled = false;

    setTempLoading(true);
    setError(null);
    setCurrentTemp(null);
    setCurrentMeta(null);

    fetchCurrentTemp({ lat: target.lat, lon: target.lon, unit: "C" }) // always fetch C
      .then((r) => {
        if (cancelled) return;
        setCurrentTemp(r.temperature); // store Celsius
        setCurrentMeta({ cached: r.cached, age: r.cacheAgeSeconds });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (cancelled) return;
        setTempLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [target]);

  const { caption: introCaption } = useIntroCaption({
    slug,
    unit,
    enabled: phase !== "landing" && slug !== "auto",
  });

  const rightCaption = useMemo(() => {
    const locationResolved =
      locationLabel && locationLabel.toLowerCase() !== "your location";

    if (!locationResolved) return "Finding your location…";

    // If the long-term intro caption isn't ready yet, we're still assembling the story.
    if (!introCaption) return "Loading your climate story…";

    // After caption exists, the only remaining “loading” is temperature.
    if (error) return "Today’s temperature is temporarily unavailable.";
    if (tempLoading || currentTemp == null) return "Fetching today’s temperature…";

    const t = unit === "F" ? cToF(currentTemp) : currentTemp;
    return `It’s currently ${t.toFixed(1)}°${unit}.`;
  }, [locationLabel, introCaption, error, tempLoading, currentTemp, unit]);

  return (
    <div className="min-h-screen text-neutral-900 bg-gradient-to-b from-white via-slate-50 to-white">
      {/* subtle background accents */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -top-24 left-1/2 h-[520px] w-[520px] -translate-x-1/2 rounded-full bg-[radial-gradient(circle_at_center,rgba(59,130,246,0.12),transparent_60%)]" />
        <div className="absolute bottom-[-140px] right-[-160px] h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle_at_center,rgba(244,63,94,0.10),transparent_60%)]" />
      </div>

      {/* Top bar (scroll-driven sliding title) */}
      {showStory && (
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
                  (headerReady && titleX !== null) ? "opacity-100" : "opacity-0",
                  // Only enable transform transition once ready (prevents initial “slide-in”)
                  (titlePrimed ? "transition-transform duration-1200" : ""),
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
      )}


      {/* Main layout */}
      <div className="pt-14">
        {/* LG prelude hero globe overlay (big centered globe) + handoff move-to-dock */}
        {!showStory && (
          <div className="hidden lg:block fixed inset-0 z-10 pointer-events-none">
            <div
              className={[
                "absolute top-[84px] aspect-square transition-all",
                `duration-[${HANDOFF_MS}ms]`,
                "ease-[cubic-bezier(0.16,1,0.3,1)]",
                !showStory
                  ? "left-1/2 -translate-x-1/2 w-[760px] opacity-100"
                  : "left-[210px] -translate-x-1/2 w-[420px] opacity-0",
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

            {/* Loading chip (on top of the globe, not behind it) */}
            {coldOpenDone && !showStory && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="rounded-full bg-white/70 px-4 py-2 text-sm text-neutral-700 backdrop-blur">
                  Loading your climate story…
                </div>
              </div>
            )}
          </div>
        )}
        <div className="lg:grid lg:grid-cols-[420px_1fr]">
          {/* LEFT: persistent globe on lg only */}
          <div className="hidden lg:block pointer-events-none">
            <div className="sticky top-0 h-[calc(100vh-56px)]">
              <div className="flex h-full items-center justify-center px-6">
                <div
                  className={[
                    "aspect-square w-full max-w-[420px]",
                    showStory ? "opacity-100" : "opacity-0 pointer-events-none",
                    "transition-opacity duration-700",
                  ].join(" ")}
                >
                  <Globe
                    targetLatLon={target}
                    phase={"arrived"}
                    onArrive={() => {}}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* RIGHT: snap scroller */}
          <div
            ref={scrollerRef}
            className={[
              "h-[calc(100vh-56px)] scroll-smooth snap-y snap-mandatory",
              "overflow-y-auto",
              showStory
                ? "lg:opacity-100 lg:pointer-events-auto"
                : "lg:opacity-0 lg:pointer-events-none lg:overflow-hidden",
              "transition-opacity duration-700",
            ].join(" ")}
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
                        phase === "landing"
                          ? "w-[760px] max-w-[92vw]"
                          : "w-[520px] max-w-[86vw]",
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
                      phase === "landing"
                        ? "opacity-0 translate-y-2 pointer-events-none"
                        : "opacity-100 translate-y-0",
                    ].join(" ")}
                  >
                    <div className="pb-16">
                      <div className="mt-6">
                        <h1 className="text-3xl font-semibold tracking-tight">{locationLabel}</h1>
                        <p className="mt-4 text-lg leading-relaxed text-neutral-700">{rightCaption}</p>

                        {introCaption && (
                          <div className="mt-6 text-neutral-700">
                            <Caption md={introCaption} reveal="sentences" />
                          </div>
                        )}

                        {phase === "arrived" && (
                          <div className="mt-10 text-center">
                            <div className="text-sm text-neutral-500">
                              Scroll down to explore your local climate
                            </div>
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
                    <Caption md={introCaption} reveal="sentences" />
                  </div>
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
            {showStory && slug !== "auto" && (
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
                    <StoryPanel slug={slug} unit={unit} panel="last_year" title="Last year - the seasonal cycle" />
                  </div>
                </div>

                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <StoryPanel slug={slug} unit={unit} panel="five_year" title="Last 5 years - from seasons to climate" />
                  </div>
                </div>

                <div className="snap-start min-h-[calc(100vh-56px)] flex items-center">
                  <div className="mx-auto w-full max-w-6xl px-4">
                    <StoryPanel slug={slug} unit={unit} panel="fifty_year" title="Last 50 years - long term trend" />
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
