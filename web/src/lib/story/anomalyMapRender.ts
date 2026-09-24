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
  /**
   * Optional land mask in the same projection as the texture. When given, sea
   * cells are knocked out: on a land quantity the ocean is not part of the
   * argument and is far noisier, which buries the pattern over land.
   */
  maskUrl?: string;
};

const SANS_STACK = '-apple-system, "Segoe UI", Roboto, sans-serif';

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
  mask?: HTMLImageElement | null,
) {
  const crop = cropRectForBbox(bbox, textureWidth, textureHeight, latMax);
  ctx.clearRect(0, 0, w, h);
  // The layers declare `resampling: "nearest"` and MapLibre honours it, which
  // is why the globe looks sharper than this canvas did: interpolating a
  // ~200px crop up to ~1600px smears every cell edge. Draw the grid as it is.
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(img, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, w, h);
  if (mask) {
    // The mask shares the texture's projection, so the same crop applies.
    // Coastlines are drawn afterwards so they survive the knockout.
    const mCrop = cropRectForBbox(bbox, mask.width, mask.height, latMax);
    ctx.imageSmoothingEnabled = false;
    ctx.globalCompositeOperation = "destination-in";
    ctx.drawImage(mask, mCrop.sx, mCrop.sy, mCrop.sw, mCrop.sh, 0, 0, w, h);
    ctx.globalCompositeOperation = "source-over";
  }
  // Coastlines are vector, and want the smoothing back.
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
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
    const [img, lines, mask] = await Promise.all([
      loadImage(source.textureUrl),
      loadLines(source.linesUrl),
      source.maskUrl ? loadImage(source.maskUrl) : Promise.resolve(null),
    ]);
    const h = Math.round(height);
    const w = Math.round(h * mercatorAspect(source.bbox));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawMap(
      ctx,
      img,
      lines,
      source.bbox,
      source.textureWidth,
      source.textureHeight,
      latMax,
      w,
      h,
      mask,
    );
    await composeAndDownload(canvas, meta, filename);
  } catch {
    // Silently ignore; the download simply will not start.
  }
}

/** A colour ramp drawn under a panel, matching the page's legend. */
export type PanelScale = { min: string; max: string; colors: string[] };

/**
 * Export two maps of the same frame side by side. Each sits in its own padded
 * cell with its title above and its colour ramp below, so neither the titles
 * nor the map edges touch the outer frame that composeAndDownload draws.
 */
export async function downloadAnomalyMapPair(
  left: AnomalyMapSource & { label: string; scale: PanelScale },
  right: AnomalyMapSource & { label: string; scale: PanelScale },
  meta: DownloadMeta,
  filename: string,
  height: number = DOWNLOAD_HEIGHT,
) {
  try {
    const panels = await Promise.all(
      [left, right].map(async (src) => {
        const latMax = src.latMax ?? DEFAULT_MERCATOR_LAT_MAX;
        const [img, lines, mask] = await Promise.all([
          loadImage(src.textureUrl),
          loadLines(src.linesUrl),
          src.maskUrl ? loadImage(src.maskUrl) : Promise.resolve(null),
        ]);
        const h = Math.round(height);
        const w = Math.round(h * mercatorAspect(src.bbox));
        const c = document.createElement("canvas");
        c.width = w;
        c.height = h;
        const cx = c.getContext("2d");
        if (!cx) throw new Error("no 2d context");
        drawMap(
          cx,
          img,
          lines,
          src.bbox,
          src.textureWidth,
          src.textureHeight,
          latMax,
          w,
          h,
          mask,
        );
        return { canvas: c, label: src.label, scale: src.scale };
      }),
    );

    const mapW = panels[0].canvas.width;
    const mapH = panels[0].canvas.height;
    const pad = Math.round(mapW * 0.035);
    const gap = Math.round(mapW * 0.06);
    const titleH = Math.round(mapH * 0.062);
    const scaleH = Math.round(mapH * 0.058);
    const hair = Math.max(1, Math.round(mapW * 0.0015));

    const totalW = pad * 2 + mapW * 2 + gap;
    const totalH = pad * 2 + titleH + mapH + scaleH;
    const out = document.createElement("canvas");
    out.width = totalW;
    out.height = totalH;
    const ctx = out.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, totalW, totalH);

    panels.forEach((panel, i) => {
      const x = pad + i * (mapW + gap);
      const titleY = pad;

      ctx.fillStyle = "#111111";
      ctx.font = `700 ${Math.round(titleH * 0.4)}px ${SANS_STACK}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(panel.label, x, titleY + titleH / 2);

      const mapY = pad + titleH;
      ctx.drawImage(panel.canvas, x, mapY);
      ctx.strokeStyle = "rgba(17,17,17,0.55)";
      ctx.lineWidth = hair;
      ctx.strokeRect(x + hair / 2, mapY + hair / 2, mapW - hair, mapH - hair);

      // Colour ramp under the map, same endpoints as the page's legend.
      const barY = mapY + mapH + Math.round(scaleH * 0.3);
      const barH = Math.round(scaleH * 0.22);
      const labelPx = Math.round(scaleH * 0.3);
      ctx.font = `500 ${labelPx}px ${SANS_STACK}`;
      ctx.fillStyle = "#555555";
      ctx.textAlign = "left";
      const minW = ctx.measureText(panel.scale.min).width;
      ctx.fillText(panel.scale.min, x, barY + barH / 2);
      ctx.textAlign = "right";
      const maxW = ctx.measureText(panel.scale.max).width;
      ctx.fillText(panel.scale.max, x + mapW, barY + barH / 2);

      const barX = x + minW + labelPx * 0.5;
      const barW = mapW - minW - maxW - labelPx;
      const grad = ctx.createLinearGradient(barX, 0, barX + barW, 0);
      panel.scale.colors.forEach((c, j) => {
        grad.addColorStop(j / (panel.scale.colors.length - 1), c);
      });
      ctx.fillStyle = grad;
      ctx.fillRect(barX, barY, barW, barH);
    });

    await composeAndDownload(out, meta, filename);
  } catch {
    // Silently ignore; the download simply will not start.
  }
}
