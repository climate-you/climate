import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const explorerPagePath = resolve("src/app/ExplorerPage.tsx");
const explorerPageSource = readFileSync(explorerPagePath, "utf8");

test("cold-open pointerdown guard ignores touch events", () => {
  assert.match(
    explorerPageSource,
    /const handleColdOpenPointerDownCapture[\s\S]*if \(e\.pointerType === "touch"\)/,
  );
  assert.match(
    explorerPageSource,
    /onPointerDownCapture=\{handleColdOpenPointerDownCapture\}/,
  );
  assert.match(
    explorerPageSource,
    /onTouchStartCapture=\{handleColdOpenInteractionCapture\}/,
  );
  assert.match(
    explorerPageSource,
    /onWheelCapture=\{handleColdOpenWheelCapture\}/,
  );
  assert.match(
    explorerPageSource,
    /window\.addEventListener\("keydown", onWindowKeyDown, true\);/,
  );
});

test("cold-open interaction advances in two explicit steps before dismiss", () => {
  assert.match(
    explorerPageSource,
    /const advanceColdOpenStep = useCallback\(\(\) => \{[\s\S]*if \(!introQuestionVisible\) \{\s*showIntroQuestion\(\);\s*return;\s*\}/,
  );
  assert.match(
    explorerPageSource,
    /if \(!introPromptVisible\) \{\s*showIntroPrompt\(\);\s*return;\s*\}/,
  );
  assert.match(explorerPageSource, /dismissColdOpen\(\);/);
  assert.match(explorerPageSource, /const COLD_OPEN_QUESTION_DELAY_MS = 1700;/);
  assert.match(explorerPageSource, /const COLD_OPEN_PROMPT_DELAY_MS = 4000;/);
  assert.match(
    explorerPageSource,
    /const COLD_OPEN_WHEEL_GESTURE_IDLE_MS = 55;/,
  );
  assert.match(
    explorerPageSource,
    /const COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN = 0\.35;/,
  );
  assert.match(
    explorerPageSource,
    /if \(!coldOpenWheelGestureActiveRef\.current\) \{[\s\S]*coldOpenWheelGestureActiveRef\.current = true;\s*handleColdOpenInteractionCapture\(e\);/,
  );
  assert.match(
    explorerPageSource,
    /if \(gestureDelta < COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN\) \{\s*return;\s*\}/,
  );
  assert.match(
    explorerPageSource,
    /coldOpenWheelGestureResetTimerRef\.current = window\.setTimeout\(\(\) => \{\s*coldOpenWheelGestureActiveRef\.current = false;/,
  );
  assert.match(explorerPageSource, /advanceColdOpenStep\(\);/);
  assert.match(
    explorerPageSource,
    /const onWindowKeyDown = \(event: KeyboardEvent\) => \{[\s\S]*if \(event\.repeat\) return;/,
  );
});
