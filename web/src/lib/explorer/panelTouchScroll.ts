/**
 * Panel drag vs. inner scrolling.
 *
 * The mobile panel closes on a downward drag, but the embedded chat puts a
 * scrollable message pane inside that same panel. Without this, dragging down
 * to read earlier messages or to reach the suggested questions also drags the
 * panel and dismisses it. A gesture that starts inside a scroller which can
 * still move in that direction belongs to the scroller, not to the panel.
 */

export type ScrollOwner = {
  /** Distance already scrolled when the gesture started. */
  scrollTop: number;
  /** Largest scrollTop the element can reach. */
  maxScrollTop: number;
};

function isVerticallyScrollable(el: Element): boolean {
  if (el.scrollHeight - el.clientHeight <= 1) return false;
  const overflowY = getComputedStyle(el).overflowY;
  return (
    overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay"
  );
}

/**
 * Nearest scrollable ancestor of `target`, searching up to but excluding
 * `boundary` (the panel itself).
 */
export function findScrollOwner(
  target: Element | null,
  boundary: Element | null,
): ScrollOwner | null {
  let el: Element | null = target;
  while (el && el !== boundary) {
    if (isVerticallyScrollable(el)) {
      return {
        scrollTop: el.scrollTop,
        maxScrollTop: el.scrollHeight - el.clientHeight,
      };
    }
    el = el.parentElement;
  }
  return null;
}

/**
 * Whether the scroller under the finger absorbs a drag of `deltaY`.
 *
 * A positive `deltaY` (finger moving down) reveals content above, so it is
 * absorbed only while the scroller is off its top; a negative one is absorbed
 * until it reaches the bottom. The scroll position is the one captured when
 * the gesture started, so a scroller that hits its edge mid-drag does not hand
 * the rest of the gesture over to the panel.
 */
export function scrollOwnerAbsorbs(
  owner: ScrollOwner | null,
  deltaY: number,
): boolean {
  if (!owner) return false;
  if (deltaY > 0) return owner.scrollTop > 1;
  if (deltaY < 0) return owner.scrollTop < owner.maxScrollTop - 1;
  return false;
}
