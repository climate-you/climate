"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import styles from "@/app/page.module.css";

type InfoBubbleProps = {
  text: string;
  label: string;
  className?: string;
  preferAboveOnMobile?: boolean;
};

export default function InfoBubble({
  text,
  label,
  className,
  preferAboveOnMobile = false,
}: InfoBubbleProps) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{
    left: number;
    top: number;
    placement: "below" | "left" | "right" | "rightAbove";
  } | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const updateCoords = useCallback(() => {
    const btn = buttonRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const tooltipMinWidth = 170;
    const spaceRight = viewportWidth - rect.right;
    const spaceLeft = rect.left;
    const useAbovePlacement = preferAboveOnMobile && viewportWidth <= 900;
    if (spaceRight >= tooltipMinWidth || spaceLeft >= tooltipMinWidth) {
      if (spaceRight >= spaceLeft) {
        setCoords({
          left: Math.round(rect.right),
          top: Math.round(useAbovePlacement ? rect.top - 8 : rect.bottom + 8),
          placement: useAbovePlacement ? "rightAbove" : "right",
        });
        return;
      }
      setCoords({
        left: Math.round(rect.left),
        top: Math.round(rect.bottom),
        placement: "left",
      });
      return;
    }
    const fallbackLeft = Math.min(
      Math.max(Math.round(rect.left), 0),
      Math.max(0, viewportWidth - tooltipMinWidth),
    );
    setCoords({
      left: fallbackLeft,
      top: Math.round(rect.bottom),
      placement: "below",
    });
  }, [preferAboveOnMobile]);

  useEffect(() => {
    if (!open) return;
    updateCoords();
    window.addEventListener("resize", updateCoords);
    window.addEventListener("scroll", updateCoords, true);
    return () => {
      window.removeEventListener("resize", updateCoords);
      window.removeEventListener("scroll", updateCoords, true);
    };
  }, [open, updateCoords]);

  return (
    <span className={[styles.infoBubble, className].filter(Boolean).join(" ")}>
      <button
        ref={buttonRef}
        type="button"
        className={styles.infoBubbleButton}
        aria-label={label}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        i
      </button>
      {open && coords
        ? createPortal(
            <span
              className={`${styles.infoBubbleTooltipGlobal} ${
                coords.placement === "left" ? styles.infoBubbleTooltipLeft : ""
              } ${
                coords.placement === "right"
                  ? styles.infoBubbleTooltipRight
                  : ""
              } ${
                coords.placement === "rightAbove"
                  ? styles.infoBubbleTooltipRightAbove
                  : ""
              }`}
              style={{ left: `${coords.left}px`, top: `${coords.top}px` }}
              role="tooltip"
            >
              {text}
            </span>,
            document.body,
          )
        : null}
    </span>
  );
}
