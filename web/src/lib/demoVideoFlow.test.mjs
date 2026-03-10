import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const timelinePath = resolve("src/lib/demoVideoTimeline.ts");
const timelineSource = readFileSync(timelinePath, "utf8");
const routePath = resolve("src/app/demo-video/page.tsx");
const routeSource = readFileSync(routePath, "utf8");

test("demo timeline declares the expected step order", () => {
  const expected = [
    "cold-open",
    "fly-to-london",
    "pick-london",
    "close-panel",
    "home",
    "switch-layer",
    "outro",
    "done",
  ];
  expected.forEach((step) => {
    assert.match(timelineSource, new RegExp(`"${step}"`));
  });
  assert.match(timelineSource, /export function isValidDemoVideoStepSequence/);
});

test("demo route is gated behind NEXT_PUBLIC_ENABLE_DEMO_VIDEO", () => {
  assert.match(
    routeSource,
    /if \(process\.env\.NEXT_PUBLIC_ENABLE_DEMO_VIDEO !== "1"\) \{\s*notFound\(\);\s*\}/,
  );
  assert.match(routeSource, /robots:\s*\{\s*index: false,\s*follow: false,\s*\}/);
});

