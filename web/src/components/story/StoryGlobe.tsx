"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import MapLibreGlobe from "@/components/MapLibreGlobe";
import type { MapLayerOption } from "@/components/MapLibreGlobe";
import DownloadIcon from "./DownloadIcon";
import LocationPanel from "./LocationPanel";
import styles from "./story.module.css";

export type GlobeStep = { id: string; label: string };

type Props = {
  layerOptions: MapLayerOption[];
  steps: GlobeStep[];
  initialLayerId: string;
  /** [west, south, east, north] framed on mount. */
  flyToBbox: [number, number, number, number];
  apiBase: string;
  release: string;
  /** Passed through to the location panel. */
  panelFromDate?: string;
  panelPeriodLabel?: string;
  /**
   * Cycle through the steps every N ms until the reader interacts. Omit (or
   * pass 0) to leave the globe on its initial step.
   */
  autoAdvanceMs?: number;
  /** Renders a download control that exports the map for the active step. */
  onDownloadStep?: (stepId: string) => void;
  downloadLabel?: string;
};

function cameraForBbox(bbox: [number, number, number, number]) {
  const [west, south, east, north] = bbox;
  const span = Math.max(east - west, north - south);
  const zoom = Math.max(1, Math.min(5, Math.floor(Math.log2(360 / Math.max(span, 1)))));
  return {
    center: [(west + east) / 2, (south + north) / 2] as [number, number],
    zoom,
  };
}

export default function StoryGlobe({
  layerOptions,
  steps,
  initialLayerId,
  flyToBbox,
  apiBase,
  release,
  panelFromDate,
  panelPeriodLabel,
  autoAdvanceMs = 0,
  onDownloadStep,
  downloadLabel = "Download the map for this window",
}: Props) {
  const [activeLayerId, setActiveLayerId] = useState(initialLayerId);
  const [initialCamera] = useState(() => cameraForBbox(flyToBbox));
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(
    null,
  );
  // A fresh array reference here re-triggers MapLibreGlobe's fly-to (used to
  // re-frame Europe after the location panel closes).
  const [recenter, setRecenter] = useState<
    [number, number, number, number] | null
  >(null);
  // The tour runs until the reader takes over; resuming it automatically would
  // fight someone who is exploring, so it only restarts from the play control.
  const [touring, setTouring] = useState(autoAdvanceMs > 0);
  const stageRef = useRef<HTMLDivElement | null>(null);

  const stopTour = useCallback(() => setTouring(false), []);
  const startTour = useCallback(() => setTouring(true), []);

  const noop = useCallback(() => {}, []);
  const handlePick = useCallback(
    (lat: number, lon: number) => {
      stopTour();
      setPicked({ lat, lon });
    },
    [stopTour],
  );
  const closePanel = useCallback(() => {
    setPicked(null);
    setRecenter([...flyToBbox]);
  }, [flyToBbox]);

  // Any drag, wheel or tap on the stage counts as taking over.
  useEffect(() => {
    if (!touring) return;
    const stage = stageRef.current;
    if (!stage) return;
    const opts = { passive: true } as const;
    stage.addEventListener("pointerdown", stopTour, opts);
    stage.addEventListener("wheel", stopTour, opts);
    return () => {
      stage.removeEventListener("pointerdown", stopTour);
      stage.removeEventListener("wheel", stopTour);
    };
  }, [touring, stopTour]);

  useEffect(() => {
    if (!touring || autoAdvanceMs <= 0 || steps.length < 2) return;
    if (
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const timer = window.setInterval(() => {
      setActiveLayerId((current) => {
        const i = steps.findIndex((s) => s.id === current);
        return steps[(i + 1) % steps.length].id;
      });
    }, autoAdvanceMs);
    return () => window.clearInterval(timer);
  }, [touring, autoAdvanceMs, steps]);

  return (
    <div className={styles.globeStage} ref={stageRef}>
      <span className={styles.globeBadge}>Interactive</span>
      {onDownloadStep ? (
        <DownloadIcon
          label={downloadLabel}
          className={styles.globeDownload}
          onClick={() => onDownloadStep(activeLayerId)}
        />
      ) : null}
      <div className={styles.globeCanvasWrap}>
        <MapLibreGlobe
          panelOpen={false}
          focusLocation={null}
          layerOptions={layerOptions}
          activeLayerId={activeLayerId}
          onLayerChange={setActiveLayerId}
          onPick={handlePick}
          onHome={noop}
          showControls={false}
          enablePick={true}
          autoRotate={false}
          initialCamera={initialCamera}
          chatFlyToBbox={recenter}
        />
      </div>
      {picked && (
        <LocationPanel
          key={`${picked.lat},${picked.lon}`}
          apiBase={apiBase}
          release={release}
          lat={picked.lat}
          lon={picked.lon}
          fromDate={panelFromDate}
          periodLabel={panelPeriodLabel}
          onClose={closePanel}
        />
      )}
      {autoAdvanceMs > 0 && !touring ? (
        <button
          type="button"
          className={styles.globePlay}
          onClick={startTour}
          aria-label="Resume stepping through the windows"
          title="Resume animation"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
            <path d="M8 5.5v13l11-6.5z" fill="currentColor" />
          </svg>
        </button>
      ) : null}
      <div className={styles.globeSteps} role="group" aria-label="Heat windows">
        {steps.map((step) => (
          <button
            key={step.id}
            type="button"
            className={`${styles.stepBtn} ${
              step.id === activeLayerId ? styles.stepBtnActive : ""
            }`}
            aria-pressed={step.id === activeLayerId}
            onClick={() => {
              stopTour();
              setActiveLayerId(step.id);
            }}
          >
            {step.label}
          </button>
        ))}
      </div>
    </div>
  );
}
