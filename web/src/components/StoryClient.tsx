"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Globe from "@/components/Globe";
import type { CityIndexEntry } from "@/lib/cities";
import { nearestCity } from "@/lib/geo";

import { useCitiesIndex } from "@/hooks/useCitiesIndex";
import { useIntroCaption } from "@/hooks/useIntroCaption";
import Caption from "@/components/Caption";
import LastWeekPanel from "@/components/panels/LastWeekPanel";
import LastMonthPanel from "@/components/panels/LastMonthPanel";

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

  const headerTitle = useMemo(() => "Your climate", []);

  const rightCaption = useMemo(() => {
    if (phase !== "arrived") return "Finding your location…";
    if (currentTemp == null) return `Getting the temperature in ${locationLabel}…`;

    const t = unit === "F" ? cToF(currentTemp) : currentTemp;
    return `It’s currently ${t.toFixed(1)}°${unit} in ${locationLabel}.`;
  }, [phase, currentTemp, unit, locationLabel]);

  return (
    <div className="min-h-screen bg-white text-neutral-900">
      {/* Top bar */}
      <div className="fixed top-0 left-0 right-0 z-20 flex items-center justify-between px-4 py-3">
        <div className="text-sm font-medium tracking-wide">{headerTitle}</div>

        <div className="flex items-center gap-2">
          <button
            className="rounded-full border border-neutral-200 px-3 py-1 text-sm hover:bg-neutral-50"
            onClick={() => setUnit((u) => (u === "C" ? "F" : "C"))}
            aria-label="Toggle units"
          >
            °{unit}
          </button>
        </div>
      </div>

      {/* Main animated layout */}
      <div className="pt-14">
        <div className="mx-auto max-w-6xl px-4">
          <div className="relative h-[85vh] lg:h-[78vh]">
            <div
              className={[
                "absolute top-10 left-1/2 -translate-x-1/2 transition-all duration-[2800ms] ease-in-out",
                phase === "landing" ? "translate-y-0" : "lg:left-0 lg:translate-x-0 translate-y-0",
              ].join(" ")}
            >
              <div
                className={[
                  "aspect-square transition-all duration-[2800ms] ease-in-out",
                  phase === "landing" ? "w-[760px] max-w-[92vw]" : "w-[520px] max-w-[86vw] lg:w-[420px]",
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
                "absolute right-0 top-24 w-full lg:w-[520px] transition-all duration-[1800ms] ease-in-out",
                phase === "landing" ? "opacity-0 translate-y-2 pointer-events-none" : "opacity-100 translate-y-0",
              ].join(" ")}
            >
              <div className="pb-16">
                <div className="mt-6 lg:mt-10">
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
                    <div className="mt-10 text-center lg:text-left">
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

            <div className="absolute bottom-6 left-0 right-0 text-center text-xs text-neutral-400 lg:hidden">
              {phase === "arrived" ? "Scroll to continue" : ""}
            </div>
          </div>

          {/* Panels below (scroll) */}
          {phase === "arrived" && slug !== "auto" && (
            <div className="mx-auto max-w-6xl px-4 pb-24">
              <div className="h-10" />
                <LastWeekPanel slug={slug} unit={unit} />
                <div className="h-16" />
                <LastMonthPanel slug={slug} unit={unit} />
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
