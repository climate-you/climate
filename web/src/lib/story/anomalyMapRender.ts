// Rendering of a regional anomaly map: crop a global mercator texture to a
// bounding box and draw the coastline overlay on top. Shared by the on-page
// <AnomalyMap> canvas and by exports triggered from elsewhere (e.g. the story
// globe's download button), so both produce an identical image.

import { composeAndDownload, type DownloadMeta } from "./download";
import {
  type Bbox,
  cropRectForBbox,
  DEFAULT_MERCATOR_LAT_MAX,
  mercatorAspect,
  projectToCanvas,
} from "./mercator";

export type LineFeatures = {
  bbox: [number, number, number, number];
  coast: number[][][];
  borders: number[][][];
};

/** Everything needed to reproduce one regional map. */
export type AnomalyMapSource = {
  textureUrl: string;
  textureWidth: number;
  textureHeight: number;
  bbox: Bbox;
  /** Public URL of the coastline/border overlay JSON. */
  linesUrl: string;
  latMax?: number;
};

const COAST_STROKE = "rgba(28, 20, 16, 0.62)";
const BORDER_STROKE = "rgba(28, 20, 16, 0.34)";
export const DOWNLOAD_HEIGHT = 1500; // hi-res backing store for crisp exports

const lineCache = new Map<string, Promise<LineFeatures>>();
export function loadLines(url: string): Promise<LineFeatures> {
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
export function loadImage(url: string): Promise<HTMLImageElement> {
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
export function drawMap(
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

/**
 * Render the map off-screen at export resolution and download it framed, with
 * title, colour scale and attribution.
 */
export async function downloadAnomalyMap(
  source: AnomalyMapSource,
  meta: DownloadMeta,
  filename: string,
  height: number = DOWNLOAD_HEIGHT,
) {
  const latMax = source.latMax ?? DEFAULT_MERCATOR_LAT_MAX;
  try {
    const [img, lines] = await Promise.all([
      loadImage(source.textureUrl),
      loadLines(source.linesUrl),
    ]);
    const h = Math.round(height);
    const w = Math.round(h * mercatorAspect(source.bbox));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawMap(
      ctx, img, lines, source.bbox,
      source.textureWidth, source.textureHeight, latMax, w, h,
    );
    await composeAndDownload(canvas, meta, filename);
  } catch {
    // Silently ignore; the download simply will not start.
  }
}
