"use client";

import { useCallback, useState } from "react";
import MapLibreGlobe from "@/components/MapLibreGlobe";
import type { MapLayerOption } from "@/components/MapLibreGlobe";
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

  const noop = useCallback(() => {}, []);
  const handlePick = useCallback((lat: number, lon: number) => {
    setPicked({ lat, lon });
  }, []);
  const closePanel = useCallback(() => {
    setPicked(null);
    setRecenter([...flyToBbox]);
  }, [flyToBbox]);

  return (
    <div className={styles.globeStage}>
      <span className={styles.globeBadge}>Interactive</span>
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
      <div className={styles.globeSteps} role="group" aria-label="Heat windows">
        {steps.map((step) => (
          <button
            key={step.id}
            type="button"
            className={`${styles.stepBtn} ${
              step.id === activeLayerId ? styles.stepBtnActive : ""
            }`}
            aria-pressed={step.id === activeLayerId}
            onClick={() => setActiveLayerId(step.id)}
          >
            {step.label}
          </button>
        ))}
      </div>
    </div>
  );
}
