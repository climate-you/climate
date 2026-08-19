import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  findScrollOwner,
  scrollOwnerAbsorbs,
} from "./explorer/panelTouchScroll.ts";

const explorerPageSource = readFileSync(
  resolve("src/app/ExplorerPage.tsx"),
  "utf8",
);

/** Minimal stand-in for a DOM element, with only what the helper reads. */
function fakeElement({
  scrollTop = 0,
  scrollHeight = 100,
  clientHeight = 100,
  overflowY = "visible",
  parentElement = null,
} = {}) {
  return { scrollTop, scrollHeight, clientHeight, overflowY, parentElement };
}

function withComputedStyle(fn) {
  const previous = globalThis.getComputedStyle;
  globalThis.getComputedStyle = (el) => ({ overflowY: el.overflowY });
  try {
    return fn();
  } finally {
    globalThis.getComputedStyle = previous;
  }
}

test("a scrolled pane absorbs a downward drag", () => {
  const owner = { scrollTop: 120, maxScrollTop: 400 };
  assert.equal(scrollOwnerAbsorbs(owner, 40), true);
  assert.equal(scrollOwnerAbsorbs(owner, -40), true);
});

test("a pane at its top hands a downward drag to the panel", () => {
  const owner = { scrollTop: 0, maxScrollTop: 400 };
  assert.equal(scrollOwnerAbsorbs(owner, 40), false);
  // Upward still scrolls: there is content below.
  assert.equal(scrollOwnerAbsorbs(owner, -40), true);
});

test("a pane at its bottom hands an upward drag to the panel", () => {
  const owner = { scrollTop: 400, maxScrollTop: 400 };
  assert.equal(scrollOwnerAbsorbs(owner, -40), false);
  assert.equal(scrollOwnerAbsorbs(owner, 40), true);
});

test("a gesture outside any scroller always drags the panel", () => {
  assert.equal(scrollOwnerAbsorbs(null, 40), false);
  assert.equal(scrollOwnerAbsorbs(null, -40), false);
});

test("findScrollOwner walks up to the nearest scrollable ancestor", () => {
  withComputedStyle(() => {
    const messages = fakeElement({
      scrollTop: 90,
      scrollHeight: 800,
      clientHeight: 300,
      overflowY: "auto",
    });
    const chip = fakeElement({ parentElement: messages });

    assert.deepEqual(findScrollOwner(chip, null), {
      scrollTop: 90,
      maxScrollTop: 500,
    });
  });
});

test("findScrollOwner ignores overflowing elements that do not scroll", () => {
  withComputedStyle(() => {
    // Content overflows but the element clips it, so it cannot absorb a drag.
    const clipped = fakeElement({
      scrollHeight: 800,
      clientHeight: 300,
      overflowY: "hidden",
    });
    // Scrollable styling, but nothing to scroll.
    const short = fakeElement({
      scrollHeight: 300,
      clientHeight: 300,
      overflowY: "auto",
      parentElement: clipped,
    });

    assert.equal(findScrollOwner(short, null), null);
  });
});

test("findScrollOwner stops at the panel boundary", () => {
  withComputedStyle(() => {
    const panel = fakeElement({
      scrollTop: 40,
      scrollHeight: 800,
      clientHeight: 300,
      overflowY: "auto",
    });
    const child = fakeElement({ parentElement: panel });

    assert.equal(findScrollOwner(child, panel), null);
  });
});

test("the panel drag and close paths both consult the scroll owner", () => {
  // Captured at touchstart, before native scrolling moves the pane.
  assert.match(
    explorerPageSource,
    /handlePanelTouchStart[\s\S]*touchScrollOwnerRef\.current = findScrollOwner\(/,
  );
  // Follow-the-finger drag bails out when the pane absorbs the gesture.
  assert.match(
    explorerPageSource,
    /scrollOwnerAbsorbs\(touchScrollOwnerRef\.current, deltaY\)/,
  );
  // And the close threshold is not reached by a scroll gesture either.
  assert.match(
    explorerPageSource,
    /TOUCH_CLOSE_PANEL_THRESHOLD_PX &&\s*!scrollOwnerAbsorbs\(scrollOwner, deltaY\)/,
  );
});
