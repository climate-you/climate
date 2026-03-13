import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const coldOpenOverlayPath = resolve(
  "src/components/explorer/ColdOpenOverlay.tsx",
);
const coldOpenOverlaySource = readFileSync(coldOpenOverlayPath, "utf8");

const constantsPath = resolve("src/lib/explorer/constants.ts");
const constantsSource = readFileSync(constantsPath, "utf8");

test("cold-open pointerdown guard ignores touch events", () => {
  // Touch guard inside the window pointerdown handler
  assert.match(
    coldOpenOverlaySource,
    /handlePointerDown[\s\S]*if \(e\.pointerType === "touch"\)/,
  );
  // All three interaction types registered as window-level capture listeners
  assert.match(
    coldOpenOverlaySource,
    /window\.addEventListener\("pointerdown", handlePointerDown, true\)/,
  );
  assert.match(
    coldOpenOverlaySource,
    /window\.addEventListener\("touchstart", handleTouchStart,/,
  );
  assert.match(
    coldOpenOverlaySource,
    /window\.addEventListener\("wheel", handleWheel,/,
  );
  assert.match(
    coldOpenOverlaySource,
    /window\.addEventListener\("keydown", onWindowKeyDown, true\)/,
  );
});

test("cold-open interaction advances in two explicit steps before dismiss", () => {
  assert.match(
    coldOpenOverlaySource,
    /if \(!introQuestionVisible\) \{\s*showIntroQuestion\(\);\s*return;\s*\}/,
  );
  assert.match(
    coldOpenOverlaySource,
    /if \(!introPromptVisible\) \{\s*showIntroPrompt\(\);\s*return;\s*\}/,
  );
  assert.match(constantsSource, /COLD_OPEN_QUESTION_DELAY_MS = 1700/);
  assert.match(constantsSource, /COLD_OPEN_PROMPT_DELAY_MS = 4000/);
  assert.match(constantsSource, /COLD_OPEN_WHEEL_GESTURE_IDLE_MS = 55/);
  assert.match(constantsSource, /COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN = 0\.35/);
  // Wheel gesture tracking via closure variable (not ref)
  assert.match(coldOpenOverlaySource, /let wheelGestureActive = false;/);
  assert.match(
    coldOpenOverlaySource,
    /if \(!wheelGestureActive\) \{[\s\S]*wheelGestureActive = true;\s*handleInteraction\(\);/,
  );
  assert.match(
    coldOpenOverlaySource,
    /if \(gestureDelta < COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN\) return;/,
  );
  assert.match(
    coldOpenOverlaySource,
    /wheelResetTimer = window\.setTimeout\(\(\) => \{\s*wheelGestureActive = false;/,
  );
  assert.match(
    coldOpenOverlaySource,
    /const onWindowKeyDown = \(event: KeyboardEvent\) => \{[\s\S]*if \(event\.repeat\) return;/,
  );
});
