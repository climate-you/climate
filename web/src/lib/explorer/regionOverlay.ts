/**
 * Geometry for the overlay drawn over a selected country or sea.
 *
 * Two treatments, depending on whether a data layer is showing:
 *
 * - none showing, over the greyscale globe: tint the region itself
 *   (`regionFeatures`);
 * - one showing: leave the region at full colour and dim everything else
 *   (`surroundingFeatures`), so the region reads first while its neighbours
 *   stay legible for comparison.
 *
 * MapLibre tells an outer boundary from a hole by the ring's winding, not by
 * its place in the list, so rings are normalised to RFC 7946 — outer boundaries
 * counter-clockwise, holes clockwise. Without that, a region coming out of the
 * build with the other winding would be filled where it should be cut out.
 */
import type {
  Feature,
  FeatureCollection,
  MultiLineString,
  MultiPolygon,
  Position,
} from "geojson";

type Ring = Position[];

/** Twice the signed area: positive when the ring runs counter-clockwise. */
function signedArea(ring: Ring): number {
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[i + 1];
    sum += x1 * y2 - x2 * y1;
  }
  return sum;
}

function wound(ring: Ring, counterClockwise: boolean): Ring {
  return signedArea(ring) > 0 === counterClockwise ? ring : [...ring].reverse();
}

function clampLatitude(ring: Ring, limit: number): Ring {
  return ring.map(([lon, lat]) => [
    lon,
    Math.max(-limit, Math.min(limit, lat)),
  ]);
}

function feature(coordinates: Ring[][]): Feature<MultiPolygon> {
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "MultiPolygon", coordinates },
  };
}

/** The region itself, for a tint and for the outline. */
export function regionFeatures(
  region: MultiPolygon,
): FeatureCollection<MultiPolygon> {
  const coordinates = region.coordinates.map(([outer, ...holes]) => [
    wound(outer, true),
    ...holes.map((hole) => wound(hole, false)),
  ]);
  return { type: "FeatureCollection", features: [feature(coordinates)] };
}

// Where the map's longitudes wrap. A region crossing it — Russia, Fiji, the
// Pacific — arrives as separate parts either side, each with an edge along it.
const ANTIMERIDIAN = 180;

function onAntimeridian([lon]: Position): boolean {
  return Math.abs(lon) === ANTIMERIDIAN;
}

/**
 * The region's boundary as lines, without the cuts along the antimeridian.
 *
 * Those cuts are where the coordinates wrap, not a border: stroking them would
 * draw a line down Russia's far east, or across the open Pacific. The tint
 * needs closed rings, so it keeps `regionFeatures`; only the outline drops them.
 */
export function regionOutline(
  region: MultiPolygon,
): FeatureCollection<MultiLineString> {
  const lines: Ring[] = [];
  for (const ring of region.coordinates.flat()) {
    let line: Ring = [];
    for (let i = 0; i < ring.length - 1; i++) {
      const from = ring[i];
      const to = ring[i + 1];
      if (onAntimeridian(from) && onAntimeridian(to)) {
        if (line.length > 1) lines.push(line);
        line = [];
        continue;
      }
      if (line.length === 0) line.push(from);
      line.push(to);
    }
    if (line.length > 1) lines.push(line);
  }
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: { type: "MultiLineString", coordinates: lines },
      },
    ],
  };
}

/**
 * A point strictly inside a counter-clockwise ring: a hair to the left of its
 * first edge, and a little off that edge's midpoint. The rings trace 0.05° grid
 * cells, so their vertices and edges sit on grid lines; the offsets keep the
 * point off every one of them, where a containment test would be ambiguous.
 */
function interiorPoint(ring: Ring): Position {
  const [x1, y1] = ring[0];
  const [x2, y2] = ring[1];
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.hypot(dx, dy) || 1;
  const along = 0.5003;
  const inward = 1e-5 / length;
  return [x1 + dx * along - dy * inward, y1 + dy * along + dx * inward];
}

/** Whether a point lies inside a ring, by counting crossings of a ray. */
function contains(ring: Ring, [x, y]: Position): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/**
 * Everything except the region: the world with each part of the region cut
 * out. A hole inside the region — a lake inside a country — is not part of it,
 * so it is dimmed too, as a polygon of its own.
 *
 * A part of the region can itself lie inside one of those holes: the channel
 * between two islands of the Tiwi group is Timor Sea, inside the islands, which
 * are inside the Timor Sea. Such a part is cut out of the smallest hole around
 * it, not out of the world: a hole within a hole is something the triangulator
 * cannot represent, and it bridges the inner one to the nearest outline instead,
 * drawing a dimmed wedge across the region.
 *
 * `latLimit` is the latitude web-mercator tiling stops at. MapLibre draws
 * nothing beyond it, so neither the world ring nor any hole may extend further:
 * a hole poking out of the world ring corrupts the whole fill.
 */
export function surroundingFeatures(
  region: MultiPolygon,
  latLimit: number,
): FeatureCollection<MultiPolygon> {
  const L = latLimit;
  const world: Ring = [
    [-180, -L],
    [180, -L],
    [180, L],
    [-180, L],
    [-180, -L],
  ];
  // Every hole in the region becomes a dimmed polygon, wound as an outer ring.
  const holes = region.coordinates.flatMap(([, ...rings]) =>
    rings.map((ring) => {
      const outer = wound(ring, true);
      return { outer, area: Math.abs(signedArea(outer)), cutOut: [] as Ring[] };
    }),
  );
  const cutFromWorld: Ring[] = [];
  for (const [outer] of region.coordinates) {
    const part = wound(outer, true);
    const probe = interiorPoint(part);
    let within: (typeof holes)[number] | null = null;
    for (const hole of holes) {
      if (
        (within === null || hole.area < within.area) &&
        contains(hole.outer, probe)
      ) {
        within = hole;
      }
    }
    const cut = wound(clampLatitude(part, L), false);
    (within ? within.cutOut : cutFromWorld).push(cut);
  }
  return {
    type: "FeatureCollection",
    features: [
      feature([
        [wound(world, true), ...cutFromWorld],
        ...holes.map((hole) => [
          wound(clampLatitude(hole.outer, L), true),
          ...hole.cutOut,
        ]),
      ]),
    ],
  };
}
