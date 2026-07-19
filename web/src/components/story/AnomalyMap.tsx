"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { composeAndDownload, type DownloadMeta } from "@/lib/story/download";
import {
  type Bbox,
  cropRectForBbox,
  DEFAULT_MERCATOR_LAT_MAX,
  mercatorAspect,
  projectToCanvas,
} from "@/lib/story/mercator";
import styles from "./story.module.css";

type LineFeatures = {
  bbox: [number, number, number, number];
  coast: number[][][];
  borders: number[][][];
};

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

const COAST_STROKE = "rgba(28, 20, 16, 0.62)";
const BORDER_STROKE = "rgba(28, 20, 16, 0.34)";
const DOWNLOAD_HEIGHT = 1500; // hi-res backing store for crisp exports

const lineCache = new Map<string, Promise<LineFeatures>>();
function loadLines(url: string): Promise<LineFeatures> {
  let cached = lineCache.get(url);
  if (!cached) {
    cached = fetch(url).then((r) => {
      if (!r.ok) throw new Error(`lines ${r.status}`);
      return r.json() as Promise<LineFeatures>;
    });
    lineCache.set(url, cached);
  }
  return cached;
}

const imageCache = new Map<string, Promise<HTMLImageElement>>();
function loadImage(url: string): Promise<HTMLImageElement> {
  let cached = imageCache.get(url);
  if (!cached) {
    cached = new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`image ${url}`));
      img.src = url;
    });
    imageCache.set(url, cached);
  }
  return cached;
}

function drawLines(
  ctx: CanvasRenderingContext2D,
  lines: number[][][],
  bbox: Bbox,
  w: number,
  h: number,
  latMax: number,
  stroke: string,
  width: number,
) {
  ctx.strokeStyle = stroke;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  for (const line of lines) {
    for (let i = 0; i < line.length; i++) {
      const [lon, lat] = line[i];
      const [px, py] = projectToCanvas(lon, lat, bbox, w, h, latMax);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
  }
  ctx.stroke();
}

/** Draw the cropped anomaly texture + coastline overlay into a w×h context. */
function drawMap(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  lines: LineFeatures,
  bbox: Bbox,
  textureWidth: number,
  textureHeight: number,
  latMax: number,
  w: number,
  h: number,
) {
  const crop = cropRectForBbox(bbox, textureWidth, textureHeight, latMax);
  ctx.clearRect(0, 0, w, h);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, h);
  const scale = h / 640;
  drawLines(ctx, lines.coast, bbox, w, h, latMax, COAST_STROKE, 1.4 * scale);
  drawLines(ctx, lines.borders, bbox, w, h, latMax, BORDER_STROKE, 1.0 * scale);
}

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
        drawMap(ctx, img, lines, bbox, textureWidth, textureHeight, latMax, w, h);
        if (!cancelled) setReady(true);
      } catch {
        // Leave the canvas blank on failure; the figure still renders.
      }
    }

    void render();
    return () => {
      cancelled = true;
    };
  }, [textureUrl, textureWidth, textureHeight, bbox, linesUrl, latMax, renderHeight, aspect]);

  useImperativeHandle(
    ref,
    () => ({
      async download(meta: DownloadMeta, filename: string) {
        try {
          const [img, lines] = await Promise.all([
            loadImage(textureUrl),
            loadLines(linesUrl),
          ]);
          // Hi-res map render, then hand off to the shared framed compositor.
          const mh = DOWNLOAD_HEIGHT;
          const mw = Math.round(mh * aspect);
          const mapCanvas = document.createElement("canvas");
          mapCanvas.width = mw;
          mapCanvas.height = mh;
          const mapCtx = mapCanvas.getContext("2d");
          if (!mapCtx) return;
          drawMap(mapCtx, img, lines, bbox, textureWidth, textureHeight, latMax, mw, mh);
          await composeAndDownload(mapCanvas, meta, filename);
        } catch {
          // Silently ignore; download simply won't start.
        }
      },
    }),
    [textureUrl, linesUrl, bbox, textureWidth, textureHeight, latMax, aspect],
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
