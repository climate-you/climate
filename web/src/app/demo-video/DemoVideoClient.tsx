"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ExplorerPage, { type ExplorerDemoApi } from "../ExplorerPage";
import { type DemoVideoStepId } from "@/lib/demoVideoTimeline";
import styles from "./demoVideo.module.css";

type DemoVideoStatus = {
  status: "idle" | "running" | "done" | "error";
  step: DemoVideoStepId | "init";
  error?: string;
};

declare global {
  interface Window {
    __CLIMATE_DEMO_VIDEO_STATUS__?: DemoVideoStatus;
  }
}

const LONDON = { lat: 51.5074, lon: -0.1278 };
const INDONESIA = { lat: -1.8, lon: 117.3 };

function matchLayerIdOrLabel(
  layers: Array<{ id: string; label: string }>,
  patterns: RegExp[],
): string | null {
  for (const layer of layers) {
    const hay = `${layer.id} ${layer.label}`.toLowerCase();
    if (patterns.some((pattern) => pattern.test(hay))) {
      return layer.id;
    }
  }
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitForCondition(
  predicate: () => boolean,
  timeoutMs: number,
  label: string,
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (predicate()) return;
    await sleep(50);
  }
  throw new Error(`Timeout while waiting for ${label}`);
}

export default function DemoVideoClient() {
  const apiRef = useRef<ExplorerDemoApi | null>(null);
  const runStartedRef = useRef(false);
  const [outroVisible, setOutroVisible] = useState(false);

  const setStatus = useCallback(
    (status: DemoVideoStatus["status"], step: DemoVideoStatus["step"], error?: string) => {
      window.__CLIMATE_DEMO_VIDEO_STATUS__ = { status, step, error };
    },
    [],
  );

  useEffect(() => {
    setStatus("idle", "init");
  }, [setStatus]);

  useEffect(() => {
    if (!apiRef.current || runStartedRef.current) return;
    runStartedRef.current = true;
    let cancelled = false;

    const run = async () => {
      const requireApi = () => {
        const api = apiRef.current;
        if (!api) throw new Error("Demo API is not ready.");
        return api;
      };
      try {
        setStatus("running", "cold-open");
        await waitForCondition(
          () => Boolean(apiRef.current?.getState().mapReady),
          90000,
          "map ready",
        );
        await sleep(950);
        requireApi().advanceColdOpenStep();
        await waitForCondition(
          () => Boolean(apiRef.current?.getState().introQuestionVisible),
          8000,
          "cold open question",
        );
        await sleep(2800);
        requireApi().advanceColdOpenStep();
        await waitForCondition(
          () => Boolean(apiRef.current?.getState().introPromptVisible),
          8000,
          "cold open prompt",
        );
        await sleep(3400);
        requireApi().advanceColdOpenStep();
        await waitForCondition(
          () => !apiRef.current?.getState().introVisible,
          8000,
          "cold open dismiss",
        );
        await sleep(900);
        if (cancelled) return;

        setStatus("running", "fly-to-london");
        await requireApi().flyTo({
          lon: LONDON.lon,
          lat: LONDON.lat,
          zoom: 4.6,
          duration: 4200,
        });
        await sleep(1000);
        if (cancelled) return;

        setStatus("running", "pick-london");
        await requireApi().pickAt({
          lon: LONDON.lon,
          lat: LONDON.lat,
          duration: 2600,
        });
        await waitForCondition(
          () => {
            const state = apiRef.current?.getState();
            if (!state) return false;
            return state.panelOpen && !state.panelLoading && state.panelHasData;
          },
          22000,
          "panel open and data loaded",
        );
        await sleep(3600);
        if (cancelled) return;

        setStatus("running", "close-panel");
        requireApi().closePanel();
        await waitForCondition(
          () => !apiRef.current?.getState().panelOpen,
          5000,
          "panel close",
        );
        await sleep(1200);
        if (cancelled) return;

        setStatus("running", "home");
        await requireApi().home(2400);
        await sleep(1300);
        if (cancelled) return;

        setStatus("running", "switch-layer");
        const state = requireApi().getState();
        const layers = state.layers;
        const preindustrialLayerId = matchLayerIdOrLabel(layers, [
          /pre[-_\s]?industrial/i,
          /1850/i,
          /warming/i,
        ]);
        const coralLayerId = matchLayerIdOrLabel(layers, [
          /coral/i,
          /reef/i,
          /stress/i,
          /dhw/i,
        ]);

        // Start from the default globe, then rotate into Africa.
        requireApi().setLayer("none");
        requireApi().setAutoRotate(true, 14);
        await requireApi().flyTo({
          lon: 18,
          lat: 12,
          zoom: 2.35,
          duration: 3000,
        });
        await sleep(2400);
        if (cancelled) return;

        // While Africa is still in view, switch to pre-industrial warming and
        // keep rotating towards India.
        if (preindustrialLayerId && preindustrialLayerId !== "none") {
          requireApi().setLayer(preindustrialLayerId);
        }
        await sleep(3600);
        if (cancelled) return;

        // Around India view, switch to coral reef stress and zoom to Indonesia.
        if (coralLayerId && coralLayerId !== "none") {
          requireApi().setLayer(coralLayerId);
        }
        await sleep(1100);
        requireApi().setAutoRotate(false);
        const zoomToIndonesia = requireApi().flyTo({
          lon: INDONESIA.lon,
          lat: INDONESIA.lat,
          zoom: 6.1,
          duration: 7600,
        });
        await sleep(2900);
        if (cancelled) return;

        setStatus("running", "outro");
        setOutroVisible(true);
        await zoomToIndonesia;
        await sleep(2200);
        if (cancelled) return;

        setStatus("done", "done");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown error";
        setStatus("error", "init", message);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [setStatus]);

  return (
    <div className={styles.frame}>
      <ExplorerPage
        coldOpen
        demoMode
        onDemoApiReady={(api) => {
          apiRef.current = api;
        }}
      />
      <div
        className={`${styles.outro} ${outroVisible ? styles.outroVisible : ""}`}
        aria-hidden={!outroVisible}
      >
        <div className={styles.outroText}>https://climate.you</div>
      </div>
    </div>
  );
}
