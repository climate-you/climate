import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { isAggregateScope, panelScope } from "./explorer/panelScope.ts";

const explorerPageSource = readFileSync(
  resolve("src/app/ExplorerPage.tsx"),
  "utf8",
);

test("a region panel is a region, not a point", () => {
  // France: a real geonameid, as every region has, plus its region id.
  const scope = panelScope({
    place: { geonameid: 2200000070 },
    region_id: "country:FR",
  });
  assert.equal(scope, "region");
  // The failure this guards: a region read as a point looks up *_local
  // headline keys, finds none, and shows no headline without any error.
  assert.equal(isAggregateScope(scope), true);
});

test("the globe is recognised by its geonameid sentinel", () => {
  const scope = panelScope({ place: { geonameid: 0 }, region_id: null });
  assert.equal(scope, "global");
  assert.equal(isAggregateScope(scope), true);
});

test("an ordinary location is a point", () => {
  for (const region_id of [null, undefined, ""]) {
    const scope = panelScope({ place: { geonameid: 2988507 }, region_id });
    assert.equal(scope, "point");
    assert.equal(isAggregateScope(scope), false);
  }
});

test("a response from before region panels existed still reads as a point", () => {
  assert.equal(panelScope({ place: { geonameid: 2988507 } }), "point");
});

test("headline keys are chosen by aggregate scope, not by the globe sentinel", () => {
  // Every *_global / *_local choice in the headline builder must go through
  // isAggregate. One left on isGlobal would work for the globe and quietly
  // break every region panel.
  const keyChoices = [
    ...explorerPageSource.matchAll(/(\w+)\s*\?\s*config\.\w+_global/g),
  ].map((m) => m[1]);
  assert.ok(keyChoices.length >= 4, "expected the headline key choices");
  assert.deepEqual(new Set(keyChoices), new Set(["isAggregate"]));
});
