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
  /** Land mask in the texture's projection; sea is knocked out when given. */
  maskUrl?: string;
  /**
   * Fallback backing-store height, used only until the canvas has been laid
   * out. Once it has, the backing store is sized from the element's real width
   * times the device pixel ratio.
   */
  renderHeight?: number;
  alt: string;
  className?: string;
};

// Beyond this the coastlines gain nothing and the canvas costs real memory.
const MAX_BACKING_WIDTH = 3000;

const AnomalyMap = forwardRef<AnomalyMapHandle, Props>(function AnomalyMap(
  {
    textureUrl,
    textureWidth,
    textureHeight,
    bbox,
    linesUrl,
    maskUrl,
    latMax = DEFAULT_MERCATOR_LAT_MAX,
    renderHeight = 900,
    alt,
    className,
  },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [ready, setReady] = useState(false);
  // Rendering at a fixed height and letting the browser scale the result up
  // softened the coastlines on dense displays; track the laid-out width so the
  // backing store can match the device pixels actually on screen.
  const [cssWidth, setCssWidth] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) setCssWidth(w);
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  // Display/export at the TRUE conformal mercator aspect (the stored texture is
  // non-square in pixels, so the crop's pixel aspect would stretch it ~1.5×).
  const aspect = mercatorAspect(bbox);

  const source: AnomalyMapSource = useMemo(
    () => ({
      textureUrl,
      textureWidth,
      textureHeight,
      bbox,
      linesUrl,
      latMax,
      maskUrl,
    }),
    [textureUrl, textureWidth, textureHeight, bbox, linesUrl, latMax, maskUrl],
  );

  useEffect(() => {
    let cancelled = false;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr =
      typeof window === "undefined"
        ? 1
        : Math.min(window.devicePixelRatio || 1, 3);
    const w = Math.min(
      MAX_BACKING_WIDTH,
      Math.round(cssWidth > 0 ? cssWidth * dpr : renderHeight * aspect),
    );
    const h = Math.round(w / aspect);
    canvas.width = w;
    canvas.height = h;

    async function render() {
      try {
        const [img, lines, mask] = await Promise.all([
          loadImage(textureUrl),
          loadLines(linesUrl),
          maskUrl ? loadImage(maskUrl) : Promise.resolve(null),
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
          mask,
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
    maskUrl,
    latMax,
    renderHeight,
    aspect,
    cssWidth,
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
