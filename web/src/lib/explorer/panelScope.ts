/**
 * What a panel response describes: one point, a whole region (a country or a
 * sea), or the globe.
 *
 * The distinction matters most for headlines, which the panel looks up by
 * key. A point panel carries `*_local` keys; the globe and a region both carry
 * `*_global` keys, being the same area-weighted computation over different
 * areas. Treating a region as a point finds no headline at all — silently, with
 * no error — so the rule lives here, where it can be tested.
 */
export type PanelScope = "point" | "region" | "global";

type ScopedLocation = {
  place: { geonameid: number };
  region_id?: string | null;
};

export function panelScope(location: ScopedLocation): PanelScope {
  // The region id is the explicit signal; the globe is recognised by the
  // geonameid-0 sentinel it has always used.
  if (location.region_id) return "region";
  if (location.place.geonameid === 0) return "global";
  return "point";
}

/** Whether headlines come from aggregates (`*_global` keys) rather than a point. */
export function isAggregateScope(scope: PanelScope): boolean {
  return scope !== "point";
}
