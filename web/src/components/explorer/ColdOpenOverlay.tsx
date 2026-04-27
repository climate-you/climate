"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  COLD_OPEN_FADE_MS,
  COLD_OPEN_PRIMARY_REVEAL_DELAY_MS,
  COLD_OPEN_PROMPT_DELAY_MS,
  COLD_OPEN_QUESTION_DELAY_MS,
  COLD_OPEN_SESSION_SEEN_KEY,
  COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN,
  COLD_OPEN_WHEEL_GESTURE_IDLE_MS,
  PREINDUSTRIAL_TITLE_SUFFIX,
} from "@/lib/explorer/constants";
import { parseIntroOverrideQuery } from "@/lib/explorer/routing";
import {
  defaultTemperatureUnitForLocale,
  observedWarmingString,
} from "@/lib/temperatureUnit";
import styles from "./ColdOpenOverlay.module.css";

type ColdOpenOverlayProps = {
  active: boolean;
  paused: boolean;
  onVisibleChange: (visible: boolean) => void;
  onShowMapChange: (show: boolean) => void;
  onAutoRotateChange: (rotate: boolean) => void;
  accentColor?: string;
};

export default function ColdOpenOverlay({
  active,
  paused,
  onVisibleChange,
  onShowMapChange,
  onAutoRotateChange,
  accentColor,
}: ColdOpenOverlayProps) {
  const [introVisible, setIntroVisible] = useState(active);
  const [introFading, setIntroFading] = useState(false);
  const [introPromptVisible, setIntroPromptVisible] = useState(!active);
  const [introPrimaryVisible, setIntroPrimaryVisible] = useState(!active);
  const [introQuestionVisible, setIntroQuestionVisible] = useState(!active);

  const introDismissTimerRef = useRef<number | null>(null);
  const introPhaseTimerRef = useRef<number | null>(null);
  const introPrimaryTimerRef = useRef<number | null>(null);
  const introQuestionTimerRef = useRef<number | null>(null);

  const introPaused = introVisible && paused;

  const warmingText = `+${observedWarmingString(defaultTemperatureUnitForLocale())}`;

  // Sync parent state via callbacks
  useEffect(() => {
    onVisibleChange(introVisible);
  }, [introVisible, onVisibleChange]);

  useEffect(() => {
    onShowMapChange(!introVisible || introPromptVisible);
  }, [introVisible, introPromptVisible, onShowMapChange]);

  useEffect(() => {
    onAutoRotateChange(
      introVisible && introPromptVisible && !introFading && !introPaused,
    );
  }, [
    introVisible,
    introPromptVisible,
    introFading,
    introPaused,
    onAutoRotateChange,
  ]);

  const markColdOpenSeen = useCallback(() => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(COLD_OPEN_SESSION_SEEN_KEY, "1");
    } catch {
      // Ignore storage access issues (private mode, policy restrictions).
    }
  }, []);

  // Check session storage on mount — skip intro if already seen
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const introOverride = parseIntroOverrideQuery(window.location.search);
    if (introOverride === true) return;
    if (introOverride === false) {
      setIntroVisible(false);
      setIntroFading(false);
      setIntroPrimaryVisible(true);
      setIntroQuestionVisible(true);
      setIntroPromptVisible(true);
      markColdOpenSeen();
      return;
    }
    const seen =
      window.sessionStorage.getItem(COLD_OPEN_SESSION_SEEN_KEY) === "1";
    if (!seen) return;
    setIntroVisible(false);
    setIntroFading(false);
    setIntroPrimaryVisible(true);
    setIntroQuestionVisible(true);
    setIntroPromptVisible(true);
  }, [active, markColdOpenSeen]);

  const dismissColdOpen = useCallback(() => {
    if (!introVisible || introFading || introPaused) return;
    setIntroFading(true);
    introDismissTimerRef.current = window.setTimeout(() => {
      setIntroVisible(false);
      setIntroFading(false);
      markColdOpenSeen();
      introDismissTimerRef.current = null;
    }, COLD_OPEN_FADE_MS);
  }, [introFading, introPaused, introVisible, markColdOpenSeen]);

  const showIntroPrompt = useCallback(() => {
    if (!introVisible || introPromptVisible || introPaused) return;
    if (introPhaseTimerRef.current) {
      window.clearTimeout(introPhaseTimerRef.current);
      introPhaseTimerRef.current = null;
    }
    setIntroPromptVisible(true);
  }, [introPaused, introPromptVisible, introVisible]);

  const showIntroQuestion = useCallback(() => {
    if (!introVisible || introQuestionVisible || introPaused) return;
    if (introQuestionTimerRef.current) {
      window.clearTimeout(introQuestionTimerRef.current);
      introQuestionTimerRef.current = null;
    }
    setIntroQuestionVisible(true);
  }, [introPaused, introQuestionVisible, introVisible]);

  // Auto-advance question text after delay
  useEffect(() => {
    if (!introVisible || introQuestionVisible || introPaused) return;
    introPhaseTimerRef.current = window.setTimeout(() => {
      setIntroQuestionVisible(true);
      introPhaseTimerRef.current = null;
    }, COLD_OPEN_QUESTION_DELAY_MS);
    return () => {
      if (introPhaseTimerRef.current) {
        window.clearTimeout(introPhaseTimerRef.current);
        introPhaseTimerRef.current = null;
      }
    };
  }, [introPaused, introQuestionVisible, introVisible]);

  // Auto-reveal primary text after delay
  useEffect(() => {
    if (
      !introVisible ||
      introPromptVisible ||
      introPrimaryVisible ||
      introPaused
    )
      return;
    introPrimaryTimerRef.current = window.setTimeout(() => {
      setIntroPrimaryVisible(true);
      introPrimaryTimerRef.current = null;
    }, COLD_OPEN_PRIMARY_REVEAL_DELAY_MS);
    return () => {
      if (introPrimaryTimerRef.current) {
        window.clearTimeout(introPrimaryTimerRef.current);
        introPrimaryTimerRef.current = null;
      }
    };
  }, [introPaused, introPrimaryVisible, introPromptVisible, introVisible]);

  // Auto-show prompt after question is visible
  useEffect(() => {
    if (
      !introVisible ||
      !introQuestionVisible ||
      introPromptVisible ||
      introPaused
    )
      return;
    introQuestionTimerRef.current = window.setTimeout(() => {
      setIntroPromptVisible(true);
      introQuestionTimerRef.current = null;
    }, COLD_OPEN_PROMPT_DELAY_MS);
    return () => {
      if (introQuestionTimerRef.current) {
        window.clearTimeout(introQuestionTimerRef.current);
        introQuestionTimerRef.current = null;
      }
    };
  }, [introPaused, introPromptVisible, introQuestionVisible, introVisible]);

  // Window-level capture listeners for pointer, touch, and wheel interactions
  useEffect(() => {
    if (!introVisible || introPaused) return;

    const handleInteraction = () => {
      if (!introQuestionVisible) {
        showIntroQuestion();
        return;
      }
      if (!introPromptVisible) {
        showIntroPrompt();
        return;
      }
      dismissColdOpen();
    };

    const handlePointerDown = (e: PointerEvent) => {
      if (e.pointerType === "touch") {
        // Touch interactions are handled in touchstart to avoid
        // processing the same tap twice on mobile browsers.
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      handleInteraction();
    };

    const handleTouchStart = (e: TouchEvent) => {
      e.preventDefault();
      e.stopPropagation();
      handleInteraction();
    };

    let wheelGestureActive = false;
    let wheelResetTimer: number | null = null;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const gestureDelta = Math.max(Math.abs(e.deltaX), Math.abs(e.deltaY));
      if (!wheelGestureActive) {
        if (gestureDelta < COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN) return;
        wheelGestureActive = true;
        handleInteraction();
      }
      // Do not extend the gesture session for tiny inertial wheel events.
      if (gestureDelta < COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN) return;
      if (wheelResetTimer) window.clearTimeout(wheelResetTimer);
      wheelResetTimer = window.setTimeout(() => {
        wheelGestureActive = false;
        wheelResetTimer = null;
      }, COLD_OPEN_WHEEL_GESTURE_IDLE_MS);
    };

    window.addEventListener("pointerdown", handlePointerDown, true);
    window.addEventListener("touchstart", handleTouchStart, {
      capture: true,
      passive: false,
    });
    window.addEventListener("wheel", handleWheel, {
      capture: true,
      passive: false,
    });

    return () => {
      window.removeEventListener("pointerdown", handlePointerDown, true);
      window.removeEventListener("touchstart", handleTouchStart, true);
      window.removeEventListener("wheel", handleWheel, true);
      if (wheelResetTimer) window.clearTimeout(wheelResetTimer);
    };
  }, [
    dismissColdOpen,
    introPaused,
    introPromptVisible,
    introQuestionVisible,
    introVisible,
    showIntroPrompt,
    showIntroQuestion,
  ]);

  // Keyboard capture: any key advances or dismisses the cold open
  useEffect(() => {
    if (!introVisible || introPaused) return;
    const onWindowKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (
        event.key === "Shift" ||
        event.key === "Control" ||
        event.key === "Alt" ||
        event.key === "Meta"
      ) {
        return;
      }
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      if (!introQuestionVisible) {
        showIntroQuestion();
        return;
      }
      if (!introPromptVisible) {
        showIntroPrompt();
        return;
      }
      dismissColdOpen();
    };
    window.addEventListener("keydown", onWindowKeyDown, true);
    return () => {
      window.removeEventListener("keydown", onWindowKeyDown, true);
    };
  }, [
    dismissColdOpen,
    introPaused,
    introPromptVisible,
    introQuestionVisible,
    introVisible,
    showIntroPrompt,
    showIntroQuestion,
  ]);

  // Cleanup all pending timers on unmount
  useEffect(
    () => () => {
      if (introDismissTimerRef.current)
        window.clearTimeout(introDismissTimerRef.current);
      if (introPhaseTimerRef.current)
        window.clearTimeout(introPhaseTimerRef.current);
      if (introPrimaryTimerRef.current)
        window.clearTimeout(introPrimaryTimerRef.current);
      if (introQuestionTimerRef.current)
        window.clearTimeout(introQuestionTimerRef.current);
    },
    [],
  );

  if (!introVisible) return null;

  return (
    <div
      className={`${styles.coldOpenOverlay} ${introFading ? styles.coldOpenOverlayFading : ""}`}
      aria-hidden="true"
    >
      <div className={styles.coldOpenMessageStack}>
        <h1
          className={`${styles.coldOpenMessage} ${styles.coldOpenMessagePrimary} ${
            introPromptVisible ? styles.coldOpenMessagePrimaryHidden : ""
          }`}
        >
          <span
            className={`${styles.coldOpenPrimaryLine} ${
              introPrimaryVisible ? styles.coldOpenPrimaryLineVisible : ""
            }`}
          >
            Human activities have caused{" "}
            <span className={styles.coldOpenMessageAccent} style={accentColor ? { color: accentColor } : undefined}>{warmingText}</span>{" "}
            of global warming {PREINDUSTRIAL_TITLE_SUFFIX}
          </span>
          <span
            className={`${styles.coldOpenQuestion} ${
              introQuestionVisible ? styles.coldOpenQuestionVisible : ""
            }`}
          >
            What does this mean{" "}
            <span className={styles.coldOpenMessageAccent} style={accentColor ? { color: accentColor } : undefined}>for you</span> ?
          </span>
        </h1>
        <h1
          className={`${styles.coldOpenMessage} ${
            introPromptVisible ? styles.coldOpenMessageSecondaryVisible : ""
          }`}
        >
          <span className={styles.coldOpenMessageAccent} style={accentColor ? { color: accentColor } : undefined}>Ple</span>
          <span className={styles.coldOpenMessageDark}>ase select locat</span>
          <span className={styles.coldOpenMessageAccent} style={accentColor ? { color: accentColor } : undefined}>ion</span>
        </h1>
      </div>
    </div>
  );
}
