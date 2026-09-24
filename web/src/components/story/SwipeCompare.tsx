"use client";

import { useCallback, useRef, useState, type ReactNode } from "react";
import styles from "./story.module.css";

type Props = {
  /** Shown on the left of the handle. */
  left: ReactNode;
  /** Shown on the right of the handle. */
  right: ReactNode;
  leftLabel: string;
  rightLabel: string;
  /** Width / height of the stage; both children must share it. */
  aspect: number;
  /** Starting handle position, 0–100 (% from the left). */
  initial?: number;
  ariaLabel: string;
};

// Each corner label fades out as its own map is wiped away, so a label never
// stands over the other map claiming to describe it.
const FADE_OVER = 14;

/**
 * Two same-frame graphics with a draggable divider: the right one is clipped
 * to the region right of the handle, so dragging reveals one under the other.
 * The handle is also a range input, so it works from the keyboard.
 */
export default function SwipeCompare({
  left,
  right,
  leftLabel,
  rightLabel,
  aspect,
  initial = 50,
  ariaLabel,
}: Props) {
  const [pos, setPos] = useState(initial);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  const posFromEvent = useCallback((clientX: number) => {
    const el = stageRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const p = ((clientX - rect.left) / rect.width) * 100;
    setPos(Math.max(0, Math.min(100, p)));
  }, []);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    posFromEvent(e.clientX);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    posFromEvent(e.clientX);
  };
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  // The left map is revealed from the left, so it disappears as pos -> 0.
  const leftOpacity = Math.min(1, pos / FADE_OVER);
  const rightOpacity = Math.min(1, (100 - pos) / FADE_OVER);

  return (
    <div
      ref={stageRef}
      className={styles.swipe}
      style={{ aspectRatio: `${aspect}` }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      <div className={styles.swipeLayer}>{left}</div>
      <div
        className={styles.swipeLayer}
        style={{ clipPath: `inset(0 0 0 ${pos}%)` }}
      >
        {right}
      </div>
      <span
        className={`${styles.swipeLabel} ${styles.swipeLabelLeft}`}
        style={{ opacity: leftOpacity }}
      >
        {leftLabel}
      </span>
      <span
        className={`${styles.swipeLabel} ${styles.swipeLabelRight}`}
        style={{ opacity: rightOpacity }}
      >
        {rightLabel}
      </span>
      {/* The range input is the accessible control; pointer dragging on the
          stage is the mouse/touch equivalent. */}
      <input
        type="range"
        min={0}
        max={100}
        value={Math.round(pos)}
        onChange={(e) => setPos(Number(e.target.value))}
        className={styles.swipeRange}
        aria-label={ariaLabel}
        tabIndex={0}
      />
      <div className={styles.swipeDivider} style={{ left: `${pos}%` }}>
        <span className={styles.swipeHandle} aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="m9 6-5 6 5 6" />
            <path d="m15 6 5 6-5 6" />
          </svg>
        </span>
      </div>
    </div>
  );
}
