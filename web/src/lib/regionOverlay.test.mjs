import test from "node:test";
import assert from "node:assert/strict";

import {
  regionFeatures,
  regionOutline,
  surroundingFeatures,
} from "./explorer/regionOverlay.ts";

const LAT_LIMIT = 85.05;

/** Twice the signed area: positive when counter-clockwise. */
function signedArea(ring) {
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  }
  return sum;
}
const isCounterClockwise = (ring) => signedArea(ring) > 0;

// A square country with a lake, and an island — the lake ring deliberately
// wound the same way as its outer ring, as a builder might emit it.
const square = (x0, y0, x1, y1) => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
  [x0, y0],
];
const clockwise = (ring) => [...ring].reverse();
const REGION = {
  type: "MultiPolygon",
  coordinates: [
    [clockwise(square(0, 0, 10, 10)), clockwise(square(4, 4, 6, 6))],
    [clockwise(square(20, 0, 22, 2))],
  ],
};

test("the region's outer boundaries run counter-clockwise, its holes clockwise", () => {
  const [{ geometry }] = regionFeatures(REGION).features;
  const [[outer, lake], [island]] = geometry.coordinates;
  assert.ok(isCounterClockwise(outer));
  assert.ok(isCounterClockwise(island));
  assert.ok(
    !isCounterClockwise(lake),
    "a hole wound like its outer ring would be filled",
  );
});

test("the surroundings are the world with every part of the region cut out", () => {
  const [{ geometry }] = surroundingFeatures(REGION, LAT_LIMIT).features;
  const [[world, ...cutOut]] = geometry.coordinates;
  assert.ok(isCounterClockwise(world));
  assert.equal(cutOut.length, 2, "the mainland and the island");
  assert.ok(cutOut.every((ring) => !isCounterClockwise(ring)));
});

test("a hole in the region is dimmed with the surroundings", () => {
  // The lake is not part of the country, so it recedes like everything else.
  const [{ geometry }] = surroundingFeatures(REGION, LAT_LIMIT).features;
  const [, lake] = geometry.coordinates;
  assert.deepEqual(
    lake[0].map(([x, y]) => `${x},${y}`).sort(),
    square(4, 4, 6, 6)
      .map(([x, y]) => `${x},${y}`)
      .sort(),
  );
  assert.ok(isCounterClockwise(lake[0]));
});

test("nothing reaches past the latitude the map can draw", () => {
  // The Arctic Ocean runs to the pole; a hole poking out of the world ring
  // would corrupt the whole fill.
  const polar = {
    type: "MultiPolygon",
    coordinates: [[square(-180, 70, 180, 90)]],
  };
  const [{ geometry }] = surroundingFeatures(polar, LAT_LIMIT).features;
  const lats = geometry.coordinates.flat(2).map(([, lat]) => lat);
  assert.ok(Math.max(...lats) <= LAT_LIMIT);
  assert.ok(Math.min(...lats) >= -LAT_LIMIT);
});

test("the outline leaves out the cut along the antimeridian", () => {
  // Russia's far east: a part ending exactly at 180°, as the build emits it.
  const farEast = {
    type: "MultiPolygon",
    coordinates: [[square(170, 60, 180, 70)]],
  };
  const [{ geometry }] = regionOutline(farEast).features;
  const segments = geometry.coordinates.flatMap((line) =>
    line.slice(1).map((to, i) => [line[i], to]),
  );
  const alongSeam = segments.filter(
    ([a, b]) => Math.abs(a[0]) === 180 && Math.abs(b[0]) === 180,
  );
  assert.equal(alongSeam.length, 0);
  // The three real edges are all still there.
  assert.equal(segments.length, 3);
});

test("an outline with no antimeridian cut is the whole boundary", () => {
  const [{ geometry }] = regionOutline(REGION).features;
  const segments = geometry.coordinates.reduce(
    (n, line) => n + line.length - 1,
    0,
  );
  // Two squares and a lake: three rings of four edges each.
  assert.equal(segments, 12);
});
