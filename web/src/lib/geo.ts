import type { CityIndexEntry } from "@/lib/cities";

export function nearestCity(cities: CityIndexEntry[], pt: { lat: number; lon: number }): CityIndexEntry | null {
  if (!cities.length) return null;

  let best = cities[0];
  let bestD = Infinity;

  for (const c of cities) {
    const d = haversineKm(pt.lat, pt.lon, c.lat, c.lon);
    if (d < bestD) {
      bestD = d;
      best = c;
    }
  }
  return best;
}

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;

  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}
