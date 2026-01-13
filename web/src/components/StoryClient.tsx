"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Globe } from "@/components/Globe";
import { useTheme } from "@/hooks/useTheme";
import type { CityIndexEntry } from "@/lib/cities";
import { nearestCity } from "@/lib/geo";
import { Sun, Moon, Monitor } from "lucide-react";

import { useCitiesIndex } from "@/hooks/useCitiesIndex";
import { useIntroCaption } from "@/hooks/useIntroCaption";
import Caption from "@/components/Caption";
import LastWeekPanel from "@/components/panels/LastWeekPanel";
import LastMonthPanel from "@/components/panels/LastMonthPanel";
import StoryPanel from "@/components/panels/StoryPanel";
import SeasonsShiftPanel from "@/components/panels/SeasonsShiftPanel";
import SeasonsRangePanel from "@/components/panels/SeasonsRangePanel";
import YouVsWorldPanel from "@/components/panels/YouVsWorldPanel";
import WarmingGlobePanel from "@/components/panels/WarmingGlobePanel";

type Phase = "landing" | "flying" | "arrived";

function cToF(c: number) {
  return (c * 9) / 5 + 32;
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

// StoryClient.tsx (near top)
function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(query);
    const onChange = () => setMatches(m.matches);
    onChange();
    m.addEventListener?.("change", onChange);
    return () => m.removeEventListener?.("change", onChange);
  }, [query]);
  return matches;
}

export default function StoryClient() {
  // Display
  const isLg = useMediaQuery("(min-width: 1024px)");
  const { cycleTheme, themeLabel, themePref } = useTheme();

  const params = useParams();
  const slugParam = (params as any)?.slug;
  const slug =
    typeof slugParam === "string" ? slugParam : Array.isArray(slugParam) ? slugParam[0] : "auto";

  const { cities, error: citiesError } = useCitiesIndex();
  const themeIcon =
    themePref === "system" ? <Monitor size={16} /> :
    themePref === "dark" ? <Moon size={16} /> :
    <Sun size={16} />;

  const themeText =
    themePref === "system" ? "System" :
    themePref === "dark" ? "Dark" :
    "Light";
    
  // Timing
  const COLD_OPEN_MS = 6000; // pure spinning hero globe, no UI, no geolocation
  const FLY_START_DELAY_MS = 3000; // beat before flight begins after target is chosen
  const POST_ARRIVE_MS = 1500; // beat after reaching target before story UI fades in

  const [coldOpenDone, setColdOpenDone] = useState(false);
  const [showStory, setShowStory] = useState(false);

  const [phase, setPhase] = useState<Phase>("landing");
  const [unit, setUnit] = useState<"C" | "F">("C");

  const [target, setTarget] = useState<{ lat: number; lon: number } | null>(null);
  const [locationLabel, setLocationLabel] = useState<string>("your location");

  // This is the slug used to load data/captions/panels.
  // For /auto, we choose it from nearestCity, but we keep the URL as /auto.
  const [storySlug, setStorySlug] = useState<string | null>(slug === "auto" ? null : slug);

  const [currentTemp, setCurrentTemp] = useState<number | null>(null);
  const [currentMeta, setCurrentMeta] = useState<{ cached: boolean; age: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [tempLoading, setTempLoading] = useState(false);
  const tempFetchKeyRef = useRef<string | null>(null);

  const arrivedOnceRef = useRef(false);
  const didStartFlyRef = useRef(false);

  // /auto resolving guard
  const [autoResolving, setAutoResolving] = useState(false);
  const [awaitingGeo, setAwaitingGeo] = useState(false);

  // Snap scroller (NOTE: now this wraps BOTH columns on lg)
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [activeSlide, setActiveSlide] = useState(0);

  // Header section (drives the subtitle)
  const [activeSection, setActiveSection] = useState<"intro" | "zoomout" | "seasons" | "world" | "warming">(
    "intro"
  );

  // Header animation (scroll-driven)
  const headerCompact = showStory && activeSlide > 0;
  const headerBarRef = useRef<HTMLDivElement | null>(null);
  const headerTitleRef = useRef<HTMLDivElement | null>(null);

  const [titleX, setTitleX] = useState<number | null>(null);
  const [headerReady, setHeaderReady] = useState(false);
  const [titlePrimed, setTitlePrimed] = useState(false);

  const heroSnapshotRef = useRef<any>(null);
  const [miniSnapshot, setMiniSnapshot] = useState<any>(null);

  // Reset when slug changes
  useEffect(() => {
    setShowStory(false);
    setColdOpenDone(false);

    setPhase("landing");
    setTarget(null);
    setLocationLabel("your location");

    setStorySlug(slug === "auto" ? null : slug);

    arrivedOnceRef.current = false;
    didStartFlyRef.current = false;

    tempFetchKeyRef.current = null;
    setCurrentTemp(null);
    setCurrentMeta(null);
    setError(null);
    setTempLoading(false);

    setAutoResolving(false);
    setAwaitingGeo(false);

    // header measurement resets
    setTitlePrimed(false);
    setTitleX(null);
    setHeaderReady(false);
  }, [slug]);

    useEffect(() => {
      if (showStory) setMiniSnapshot(heroSnapshotRef.current);
    }, [showStory]);

  // Cold open timer (no UI, no geolocation)
  useEffect(() => {
    const t = window.setTimeout(() => setColdOpenDone(true), COLD_OPEN_MS);
    return () => window.clearTimeout(t);
  }, [slug]);

  // IMPORTANT: Do not add custom wheel listeners here.
  // Native scrolling + scroll-snap works best across browsers.

  // Resolve target + start fly (after cold open), with no redirect
  useEffect(() => {
    if (!cities) return;
    if (!coldOpenDone) return;
    if (didStartFlyRef.current) return;

    const startFly = (lat: number, lon: number, label: string) => {
      didStartFlyRef.current = true;
      setTarget({ lat, lon });
      setLocationLabel(label);
      setPhase("landing");
      window.setTimeout(() => setPhase("flying"), FLY_START_DELAY_MS);
    };

    // Direct slug
    if (slug !== "auto") {
      const city = cities.find((c) => c.slug === slug);
      if (!city) {
        setError(`Unknown slug "${slug}" (not found in cities_index.json).`);
        return;
      }
      setStorySlug(city.slug);
      startFly(city.lat, city.lon, city.label);
      return;
    }

    // /auto
    if (autoResolving) return;
    setAutoResolving(true);

    const fallback = cities.find((c) => c.slug === "city_gb_london") ?? cities[0];

    const finish = (chosen: CityIndexEntry, flyLat: number, flyLon: number) => {
      setAwaitingGeo(false);
      setStorySlug(chosen.slug);
      startFly(flyLat, flyLon, chosen.label);
      setAutoResolving(false);
    };

    if (!navigator.geolocation) {
      finish(fallback, fallback.lat, fallback.lon);
      return;
    }

    setAwaitingGeo(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;

        const chosen = nearestCity(cities, { lat, lon }) ?? fallback;

        // Fly to user's actual coordinate (feels right) but load panels for chosen.slug
        finish(chosen, lat, lon);
      },
      (geoErr) => {
        setError(`Geolocation unavailable (${geoErr.code}). Using ${fallback.label}.`);
        finish(fallback, fallback.lat, fallback.lon);
      },
      // NOTE: increase timeout so the UI stays in "Finding your location…" while user decides
      { enableHighAccuracy: false, timeout: 30_000, maximumAge: 60_000 }
    );
  }, [slug, cities, coldOpenDone, autoResolving]);

  // Reveal story UI only after arrival (+ delay)
  useEffect(() => {
    if (!storySlug) {
      setShowStory(false);
      return;
    }
    if (!coldOpenDone) {
      setShowStory(false);
      return;
    }
    if (phase !== "arrived") {
      setShowStory(false);
      return;
    }
    if (showStory) return;

    const t = window.setTimeout(() => {
      setShowStory(true);
      if (scrollerRef.current) scrollerRef.current.scrollTo({ top: 0 });
      setActiveSlide(0);
    }, POST_ARRIVE_MS);

    return () => window.clearTimeout(t);
  }, [storySlug, coldOpenDone, phase, showStory]);

  // Track which "section" is currently visible (intro / zoomout / seasons / world)
  useEffect(() => {
    const root = scrollerRef.current;
    if (!root) return;

    const slides = Array.from(root.querySelectorAll<HTMLElement>("[data-story-section]"));
    if (!slides.length) return;

    const obs = new IntersectionObserver(
      (entries) => {
        // Choose the most-visible intersecting slide
        let best: IntersectionObserverEntry | null = null;
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          if (!best || e.intersectionRatio > best.intersectionRatio) best = e;
        }
        if (!best) return;

        const el = best.target as HTMLElement;
        const sec = el.dataset.storySection as any;
        if (sec) setActiveSection(sec);
      },
      {
        root,
        threshold: [0.55, 0.7, 0.85],
      }
    );

    slides.forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, [showStory, storySlug]);

  // Compute title X (centered when not compact)
  const computeTitleX = () => {
    const bar = headerBarRef.current;
    const title = headerTitleRef.current;
    if (!bar || !title) return;

    const barW = bar.clientWidth;
    const titleW = title.offsetWidth;
    const centerX = Math.max(0, (barW - titleW) / 2);

    setTitleX(headerCompact ? 0 : centerX);
  };

  // Only measure header once it exists (showStory)
  useLayoutEffect(() => {
    if (!showStory) return;

    computeTitleX();

    if (!headerReady) {
      const raf = requestAnimationFrame(() => setHeaderReady(true));
      return () => cancelAnimationFrame(raf);
    }
  }, [showStory, headerCompact, headerReady]);

  useEffect(() => {
    if (!showStory) return;
    const onResize = () => computeTitleX();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [showStory, headerCompact]);

  // Allow transitions only after first valid measurement
  useEffect(() => {
    if (!showStory) return;
    if (!headerReady) return;
    if (titleX === null) return;
    if (titlePrimed) return;
    setTitlePrimed(true);
  }, [showStory, headerReady, titleX, titlePrimed]);

  // Re-measure after web fonts finish loading
  useEffect(() => {
    if (!showStory) return;

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
  }, [showStory, headerCompact]);

  // Track active snap slide index (based on scroller top)
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

  // Fetch current temperature once we have a target
  useEffect(() => {
    if (!target) return;

    const key = `${target.lat.toFixed(4)},${target.lon.toFixed(4)}`;
    if (tempFetchKeyRef.current === key) return;
    tempFetchKeyRef.current = key;

    let cancelled = false;

    setTempLoading(true);
    setError(null);
    setCurrentTemp(null);
    setCurrentMeta(null);

    fetchCurrentTemp({ lat: target.lat, lon: target.lon, unit: "C" })
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

  // Intro caption (load as soon as we know storySlug, even during flight)
  const { caption: introCaption } = useIntroCaption({
    slug: storySlug ?? "auto",
    unit,
    enabled: !!storySlug,
  });

  // --- Debug logs (dev only)
  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return;
    // eslint-disable-next-line no-console
    console.debug("[story]", {
      slug,
      storySlug,
      coldOpenDone,
      autoResolving,
      awaitingGeo,
      phase,
      showStory,
      target,
      locationLabel,
      introCaptionLoaded: !!introCaption,
      tempLoading,
      currentTemp,
      error,
    });
  }, [
    slug,
    storySlug,
    coldOpenDone,
    autoResolving,
    awaitingGeo,
    phase,
    showStory,
    target,
    locationLabel,
    introCaption,
    tempLoading,
    currentTemp,
    error,
  ]);

  const rightCaption = useMemo(() => {
    // While the browser permission prompt is open (or we are waiting on geolocation):
    if (slug === "auto" && awaitingGeo && !target) return "Finding your location…";

    const locationResolved = locationLabel && locationLabel.toLowerCase() !== "your location";
    if (!locationResolved) return "Finding your location…";

    if (!introCaption) return "Loading your climate story…";

    if (error) return "Today’s temperature is temporarily unavailable.";
    if (tempLoading || currentTemp == null) return "Fetching today’s temperature…";

    const t = unit === "F" ? cToF(currentTemp) : currentTemp;
    return `It’s currently ${t.toFixed(1)}°${unit}.`;
  }, [slug, awaitingGeo, target, locationLabel, introCaption, error, tempLoading, currentTemp, unit]);

  const heroChipText = useMemo(() => {
    if (!coldOpenDone) return null;
    if (showStory) return null;

    if (slug === "auto" && awaitingGeo && !target) return "Finding your location…";
    if (!target) return "Finding your location…";
    return "Loading your climate story…";
  }, [coldOpenDone, showStory, slug, awaitingGeo, target]);

  return (
    <div className="
      min-h-screen text-neutral-900 dark:text-neutral-50
      bg-gradient-to-b from-white via-slate-50 to-white
      dark:from-[#212121] dark:via-[#212121] dark:to-[#212121]
    ">
      {/* subtle background accents */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -top-24 left-1/2 h-[520px] w-[520px] -translate-x-1/2 rounded-full bg-[radial-gradient(circle_at_center,rgba(59,130,246,0.12),transparent_60%)]" />
        <div className="absolute bottom-[-140px] right-[-160px] h-[520px] w-[520px] rounded-full bg-[radial-gradient(circle_at_center,rgba(244,63,94,0.10),transparent_60%)]" />
      </div>

      {/* Top bar only after story reveal */}
      {showStory && (
        <div className="fixed top-0 left-0 right-0 z-20 bg-white/70 dark:bg-[#212121]/80 backdrop-blur">
          <div ref={headerBarRef} className="mx-auto w-full px-4 sm:px-6 lg:px-10 py-3">
            <div className="relative h-[56px]">
              <div
                ref={headerTitleRef}
                className={[
                  "absolute top-1/2 left-0 will-change-transform",
                  "transition-opacity duration-300",
                  headerReady && titleX !== null ? "opacity-100" : "opacity-0",
                  titlePrimed ? "transition-transform duration-1200" : "",
                ].join(" ")}
                style={{
                  transform: `translateX(${titleX ?? 0}px) translateY(-50%) scale(${
                    headerCompact ? 0.62 : 1
                  })`,
                  transformOrigin: "left center",
                  transitionTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
                }}
              >
                <div className="text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight">
                  Your climate
                </div>
              </div>

              <div
                className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-base sm:text-lg text-neutral-600 transition-opacity duration-500 ease-in-out"
                style={{ opacity: headerCompact ? 1 : 0 }}
              >
                {activeSection === "seasons"
                  ? "Seasons then and now"
                  : activeSection === "world"
                    ? "You vs the world"
                    : activeSection === "warming"
                      ? "Warming around the world"
                      : "Zooming out: from days to decades"}
              </div>

              <div className="absolute right-0 top-1/2 -translate-y-1/2 flex items-center gap-2">
                <button
                  className="rounded-full border border-neutral-200 bg-white px-3 py-1 text-sm hover:bg-neutral-50
                            dark:border-neutral-800 dark:bg-[#171717] dark:hover:bg-neutral-800"
                  onClick={cycleTheme}
                  aria-label={`Theme: ${themeText}`}
                  title={`Theme: ${themeText}`}
                >
                  <span className="flex items-center gap-2">
                    {themeIcon}
                    <span className="hidden sm:inline">{themeText}</span>
                  </span>
                </button>

                <button
                  className="rounded-full border border-neutral-200 bg-white px-3 py-1 text-sm hover:bg-neutral-50
                            dark:border-neutral-800 dark:bg-[#171717] dark:hover:bg-neutral-800"
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

      {isLg && (
        <div className="pt-14">
        {/* LG hero overlay stays mounted and fades out once showStory is true */}
        <div
          className={[
            "hidden lg:block fixed inset-0 z-10 pointer-events-none transition-opacity duration-700",
            "pointer-events-none [&_*]:pointer-events-none",
            showStory ? "opacity-0" : "opacity-100",
          ].join(" ")}
          aria-hidden={showStory}
        >
          <div className="absolute top-[84px] left-1/2 -translate-x-1/2 w-[760px] aspect-square">
            <Globe
              variant="hero"
              targetLatLon={target}
              phase={phase}
              onSnapshot={(s) => { heroSnapshotRef.current = s; }}
              onArrive={() => { if (arrivedOnceRef.current) return; arrivedOnceRef.current = true; setPhase("arrived"); }}
            />
          </div>
          {/* Loading chip (appears only after cold open) */}
          {heroChipText && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="rounded-full bg-white/70 px-4 py-2 text-sm text-neutral-700 dark:text-neutral-200 backdrop-blur">
                {heroChipText}
              </div>
            </div>
          )}
        </div>

        {/* === IMPORTANT CHANGE ===
            The snap scroller now wraps BOTH columns on lg.
            This makes scrolling work even when the cursor is over the mini globe. */}
        <div
          ref={scrollerRef}
          data-story-scroller
          className={[
            "relative z-30",
            "h-[calc(100vh-56px)] overflow-y-auto overscroll-contain scroll-smooth",
            "snap-y snap-mandatory",
            showStory
              ? "lg:opacity-100 lg:pointer-events-auto"
              : "lg:opacity-0 lg:pointer-events-none lg:overflow-hidden",
            "transition-opacity duration-700",
          ].join(" ")}
        >
          {isLg && (
            <div className="lg:grid lg:grid-cols-[420px_1fr]">
            {/* LEFT: mini globe (lg only), sticky */}
            <div className="hidden lg:block">
              <div className="sticky top-0 h-[calc(100vh-56px)]">
                <div className="flex h-full items-center justify-center px-6">
                  <div
                    className={[
                      "aspect-square w-full max-w-[420px]",
                      "pointer-events-none [&_*]:pointer-events-none",
                      "transition-opacity duration-700",
                      showStory && activeSection !== "warming" ? "opacity-100" : "opacity-0",
                    ].join(" ")}
                  >
                    <Globe
                      variant="mini"
                      targetLatLon={target}
                      phase={"arrived"}
                      onArrive={() => {}} />
                  </div>
                </div>
              </div>
            </div>

            {/* RIGHT: slides */}
            <div>
              {/* Slide 1 (mobile): intro with animated globe */}
              {!isLg && (
                <div data-story-section="intro" className="snap-start [scroll-snap-stop:always]">
                <div className="mx-auto max-w-6xl px-4">
                  <div className="relative min-h-[calc(100vh-56px)]">
                    <div className="absolute top-10 left-1/2 -translate-x-1/2 transition-all duration-[2800ms] ease-in-out">
                      <div className="aspect-square w-[760px] max-w-[92vw] pointer-events-none [&_*]:pointer-events-none">
                        <Globe
                          variant="hero"
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
                          <p className="mt-4 text-lg leading-relaxed text-neutral-700 dark:text-neutral-200 ">{rightCaption}</p>

                          {introCaption && (
                            <div className="mt-6 text-neutral-700 dark:text-neutral-200 ">
                              <Caption md={introCaption} reveal="sentences" />
                            </div>
                          )}

                          {phase === "arrived" && (
                            <div className="mt-10 text-center">
                              <div className="text-sm text-neutral-500 dark:text-neutral-400 ">
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

                    <div className="absolute bottom-6 left-0 right-0 text-center text-xs text-neutral-400 dark:text-neutral-500 ">
                      {phase === "arrived" ? "Scroll to continue" : ""}
                    </div>
                  </div>
                </div>
                </div>
              )}

              {/* Slide 1 (lg): intro text only */}
              <div data-story-section="intro" className="snap-start [scroll-snap-stop:always] hidden lg:flex min-h-[calc(100vh-56px)] items-center">
                <div className="mx-auto w-full max-w-3xl px-6">
                  <h1 className="text-5xl font-semibold tracking-tight">{locationLabel}</h1>
                  <p className="mt-6 text-2xl leading-relaxed text-neutral-700 dark:text-neutral-200">{rightCaption}</p>

                  {introCaption && (
                    <div className="mt-8 text-neutral-700 dark:text-neutral-200 ">
                      <Caption md={introCaption} reveal="sentences" />
                    </div>
                  )}

                  {phase === "arrived" && (
                    <div className="mt-10">
                      <div className="text-sm text-neutral-500 dark:text-neutral-400 ">Scroll down to explore your local climate</div>
                      <div className="mt-2 text-2xl">↓</div>
                    </div>
                  )}

                  {(citiesError || error) && (
                    <p className="mt-6 text-sm text-red-600">{citiesError ?? error}</p>
                  )}
                </div>
              </div>

              {/* Slides 2+: Panels (use storySlug, works for /auto too) */}
              {showStory && storySlug && (
                <>
                  <div data-story-section="zoomout" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <LastWeekPanel slug={storySlug} unit={unit} />
                    </div>
                  </div>

                  <div data-story-section="zoomout" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <LastMonthPanel slug={storySlug} unit={unit} />
                    </div>
                  </div>

                  <div data-story-section="zoomout" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <StoryPanel
                        slug={storySlug}
                        unit={unit}
                        panel="last_year"
                        title="Last year - the seasonal cycle"
                      />
                    </div>
                  </div>

                  <div data-story-section="zoomout" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <StoryPanel
                        slug={storySlug}
                        unit={unit}
                        panel="five_year"
                        title="Last 5 years - from seasons to climate"
                      />
                    </div>
                  </div>

                  <div data-story-section="zoomout" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <StoryPanel slug={storySlug} unit={unit} panel="fifty_year" title="Last 50 years - long term trend" />
                    </div>
                  </div>

                  <div data-story-section="zoomout" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <StoryPanel slug={storySlug} unit={unit} panel="twenty_five_years" title="25 years ahead" />
                    </div>
                  </div>

                  <div data-story-section="seasons" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <SeasonsShiftPanel slug={storySlug} unit={unit} />
                    </div>
                  </div>

                  <div data-story-section="seasons" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <SeasonsRangePanel slug={storySlug} unit={unit} />
                    </div>
                  </div>

                  <div data-story-section="world" className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center">
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <YouVsWorldPanel slug={storySlug} unit={unit} />
                    </div>
                  </div>

                  <div
                    data-story-section="warming"
                    className="snap-start [scroll-snap-stop:always] min-h-[calc(100vh-56px)] flex items-center"
                  >
                    <div className="mx-auto w-full max-w-7xl px-6">
                      <WarmingGlobePanel target={target} unit={unit} locationLabel={locationLabel} />
                    </div>
                  </div>

                  <div className="h-24" />
                </>
              )}
            </div>
            </div>
          )}
        </div>
        </div>
      )}
    </div>
  );
}
