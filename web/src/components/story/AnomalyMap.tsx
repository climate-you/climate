"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { type DownloadMeta } from "@/lib/story/download";
import {
  type AnomalyMapSource,
  downloadAnomalyMap,
  drawMap,
  loadImage,
  loadLines,
} from "@/lib/story/anomalyMapRender";
import {
  type Bbox,
  DEFAULT_MERCATOR_LAT_MAX,
  mercatorAspect,
} from "@/lib/story/mercator";
import styles from "./story.module.css";

export type AnomalyMapHandle = {
  /** Composite the map with a framed border + attribution and download a PNG. */
  download: (meta: DownloadMeta, filename: string) => void;
};

type Props = {
  textureUrl: string;
  textureWidth: number;
  textureHeight: number;
  bbox: Bbox;
  /** Public URL of the coastline/border overlay JSON. */
  linesUrl: string;
  latMax?: number;
  /** Backing-store height in device pixels; width follows the crop aspect. */
  renderHeight?: number;
  alt: string;
  className?: string;
};

const AnomalyMap = forwardRef<AnomalyMapHandle, Props>(function AnomalyMap(
  {
    textureUrl,
    textureWidth,
    textureHeight,
    bbox,
    linesUrl,
    latMax = DEFAULT_MERCATOR_LAT_MAX,
    renderHeight = 900,
    alt,
    className,
  },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [ready, setReady] = useState(false);

  // Display/export at the TRUE conformal mercator aspect (the stored texture is
  // non-square in pixels, so the crop's pixel aspect would stretch it ~1.5×).
  const aspect = mercatorAspect(bbox);

  const source: AnomalyMapSource = useMemo(
    () => ({ textureUrl, textureWidth, textureHeight, bbox, linesUrl, latMax }),
    [textureUrl, textureWidth, textureHeight, bbox, linesUrl, latMax],
  );

  useEffect(() => {
    let cancelled = false;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const h = Math.round(renderHeight);
    const w = Math.round(h * aspect);
    canvas.width = w;
    canvas.height = h;

    async function render() {
      try {
        const [img, lines] = await Promise.all([
          loadImage(textureUrl),
          loadLines(linesUrl),
        ]);
        if (cancelled) return;
        const ctx = canvas!.getContext("2d");
        if (!ctx) return;
        drawMap(
          ctx,
          img,
          lines,
          bbox,
          textureWidth,
          textureHeight,
          latMax,
          w,
          h,
        );
        if (!cancelled) setReady(true);
      } catch {
        // Leave the canvas blank on failure; the figure still renders.
      }
    }

    void render();
    return () => {
      cancelled = true;
    };
  }, [
    textureUrl,
    textureWidth,
    textureHeight,
    bbox,
    linesUrl,
    latMax,
    renderHeight,
    aspect,
  ]);

  useImperativeHandle(
    ref,
    () => ({
      download(meta: DownloadMeta, filename: string) {
        void downloadAnomalyMap(source, meta, filename);
      },
    }),
    [source],
  );

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={alt}
      data-ready={ready}
      className={className ?? styles.mapCanvas}
    />
  );
});

export default AnomalyMap;
