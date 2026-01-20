export const runtime = "nodejs";

type CacheEntry = { expiresAt: number; createdAt: number; payload: any };

const CACHE = new Map<string, CacheEntry>();
const TTL_MS = 60 * 60 * 1000;

function cacheKey(lat: number, lon: number) {
  const rLat = Math.round(lat * 100) / 100;
  const rLon = Math.round(lon * 100) / 100;
  return `current:C:${rLat},${rLon}`;
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const lat = Number(url.searchParams.get("lat"));
  const lon = Number(url.searchParams.get("lon"));

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return Response.json(
      { error: "lat and lon must be numbers" },
      { status: 400 },
    );
  }

  const key = cacheKey(lat, lon);
  const now = Date.now();

  const hit = CACHE.get(key);
  if (hit && hit.expiresAt > now) {
    return Response.json(
      {
        ...hit.payload,
        cached: true,
        cacheAgeSeconds: Math.round((now - hit.createdAt) / 1000),
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  const base = "https://api.open-meteo.com/v1/forecast";
  const omUrl = new URL(base);
  omUrl.searchParams.set("latitude", String(lat));
  omUrl.searchParams.set("longitude", String(lon));
  omUrl.searchParams.set("timezone", "auto");
  omUrl.searchParams.set("current", "temperature_2m");

  const upstream = await fetch(omUrl.toString(), {
    // Keep upstream uncached; we manage our own TTL cache
    cache: "no-store",
    headers: { "User-Agent": "climate-story-frontend-proxy/1.0" },
  });

  if (!upstream.ok) {
    const text = await upstream.text().catch(() => "");
    return Response.json(
      {
        error: "Open-Meteo request failed",
        status: upstream.status,
        details: text.slice(0, 500),
      },
      { status: 502 },
    );
  }

  const json = await upstream.json();

  const temperature = json?.current?.temperature_2m;
  const time = json?.current?.time ?? null;
  const timezone = json?.timezone ?? null;

  if (typeof temperature !== "number") {
    return Response.json(
      { error: "Open-Meteo response missing current.temperature_2m" },
      { status: 502 },
    );
  }

  const payload = {
    temperature,
    time,
    timezone,
    lat,
    lon,
    source: "open-meteo",
    cached: false,
    cacheAgeSeconds: 0,
  };

  CACHE.set(key, { payload, createdAt: now, expiresAt: now + TTL_MS });

  return Response.json(payload, { headers: { "Cache-Control": "no-store" } });
}
