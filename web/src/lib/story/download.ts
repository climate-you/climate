// Client-side "download with attribution" helpers. The on-page graphics stay
// clean; the framed border, title, colour scale (maps), and attribution strip
// (source left, logo + climate.you right) are added only to the exported PNG.

const LOGO_URL = "/story/logo.png";

export type DownloadScale = {
  min: string;
  max: string;
  colors: string[];
};

export type DownloadMeta = {
  title: string;
  sourceText: string;
  scale?: DownloadScale;
};

let logoPromise: Promise<HTMLImageElement | null> | null = null;
function loadLogo(): Promise<HTMLImageElement | null> {
  if (!logoPromise) {
    logoPromise = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = LOGO_URL;
    });
  }
  return logoPromise;
}

function triggerPng(canvas: HTMLCanvasElement, filename: string) {
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }, "image/png");
}

const SANS = '-apple-system, "Segoe UI", Roboto, sans-serif';

/**
 * Compose a source graphic into a shareable PNG: white outer border, a bold
 * title, a thin black frame around the graphic, an optional colour scale
 * (maps), and an attribution strip with source left / climate.you logo right.
 */
export async function composeAndDownload(
  source: HTMLCanvasElement,
  meta: DownloadMeta,
  filename: string,
) {
  const logo = await loadLogo();
  const w = source.width;
  const h = source.height;
  const border = Math.round(w * 0.024);
  const frame = Math.max(2, Math.round(w * 0.004));
  const gap = Math.round(w * 0.016);
  const titleH = Math.round(w * 0.05);
  const scaleH = meta.scale ? Math.round(w * 0.05) : 0;
  const stripH = Math.round(w * 0.05);

  const out = document.createElement("canvas");
  out.width = w + 2 * frame + 2 * border;
  out.height =
    border +
    titleH +
    gap +
    frame +
    h +
    frame +
    (scaleH ? gap + scaleH : 0) +
    gap +
    stripH +
    border;
  const ctx = out.getContext("2d");
  if (!ctx) return;

  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, out.width, out.height);

  const gx = border + frame; // graphic left edge
  const rightX = gx + w;

  // Title. Descriptive titles can be long, so shrink to fit the graphic width
  // rather than letting fillText run off the edge of the canvas.
  ctx.fillStyle = "#111111";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  const titleFont = (px: number) =>
    `700 ${px}px Georgia, "Times New Roman", serif`;
  let titlePx = Math.round(titleH * 0.66);
  const minTitlePx = Math.round(titleH * 0.3);
  ctx.font = titleFont(titlePx);
  while (titlePx > minTitlePx && ctx.measureText(meta.title).width > w) {
    titlePx -= 2;
    ctx.font = titleFont(titlePx);
  }
  ctx.fillText(meta.title, gx, border + titleH / 2);

  // Framed graphic
  const gy = border + titleH + gap + frame;
  ctx.drawImage(source, gx, gy, w, h);
  ctx.strokeStyle = "#111111";
  ctx.lineWidth = frame;
  ctx.strokeRect(gx - frame / 2, gy - frame / 2, w + frame, h + frame);

  let cursorY = gy + h + frame;

  // Colour scale (maps only)
  if (meta.scale) {
    const barY = cursorY + gap;
    const barH = Math.round(scaleH * 0.4);
    const labelFont = Math.round(scaleH * 0.34);
    ctx.font = `500 ${labelFont}px ${SANS}`;
    ctx.textBaseline = "middle";
    const midBarY = barY + barH / 2;
    ctx.textAlign = "left";
    ctx.fillStyle = "#555555";
    ctx.fillText(meta.scale.min, gx, midBarY);
    const minW = ctx.measureText(meta.scale.min).width;
    ctx.textAlign = "right";
    ctx.fillText(meta.scale.max, rightX, midBarY);
    const maxW = ctx.measureText(meta.scale.max).width;
    const barX = gx + minW + gap;
    const barW = rightX - maxW - gap - barX;
    if (barW > 20) {
      const grad = ctx.createLinearGradient(barX, 0, barX + barW, 0);
      const n = meta.scale.colors.length;
      meta.scale.colors.forEach((c, i) => grad.addColorStop(i / (n - 1), c));
      ctx.fillStyle = grad;
      ctx.fillRect(barX, barY, barW, barH);
    }
    cursorY = barY + barH;
  }

  // Attribution strip
  const stripY = cursorY + gap;
  const midY = stripY + stripH / 2;
  const fontPx = Math.round(stripH * 0.42);
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#111111";
  ctx.font = `500 ${fontPx}px ${SANS}`;
  ctx.textAlign = "left";
  ctx.fillText(meta.sourceText, gx, midY);

  ctx.font = `600 ${fontPx}px ${SANS}`;
  ctx.textAlign = "right";
  ctx.fillText("climate.you", rightX, midY);
  if (logo) {
    const brandW = ctx.measureText("climate.you").width;
    const logoSize = Math.round(stripH * 0.92);
    const logoGap = Math.round(stripH * 0.22);
    ctx.drawImage(
      logo,
      rightX - brandW - logoGap - logoSize,
      midY - logoSize / 2,
      logoSize,
      logoSize,
    );
  }

  triggerPng(out, filename);
}

// Presentation properties worth baking so the serialized SVG renders without
// the page's stylesheet (CSS custom properties don't survive serialization).
const BAKED_PROPS = [
  "fill",
  "stroke",
  "stroke-width",
  "opacity",
  "font",
] as const;

/**
 * Rasterize a live <svg> to a canvas (baking computed styles so it renders
 * standalone and matches the reader's current theme), then hand it to
 * composeAndDownload for the framed export.
 */
export function downloadSvgWithAttribution(
  svg: SVGSVGElement,
  meta: DownloadMeta,
  filename: string,
  scale = 3,
) {
  const viewBox = svg.viewBox.baseVal;
  const vbW = viewBox && viewBox.width ? viewBox.width : svg.clientWidth;
  const vbH = viewBox && viewBox.height ? viewBox.height : svg.clientHeight;
  if (!vbW || !vbH) return;

  const clone = svg.cloneNode(true) as SVGSVGElement;
  const originals = svg.querySelectorAll<SVGElement>("*");
  const clones = clone.querySelectorAll<SVGElement>("*");
  for (let i = 0; i < originals.length; i++) {
    const cs = window.getComputedStyle(originals[i]);
    const target = clones[i];
    if (!target) continue;
    for (const prop of BAKED_PROPS) {
      const value = cs.getPropertyValue(prop);
      if (value && value !== "none" && value !== "normal") {
        target.setAttribute(prop, value.trim());
      }
    }
  }
  clone.setAttribute("width", String(vbW));
  clone.setAttribute("height", String(vbH));
  // Paint the surface so text/grid read against it.
  const surface = window.getComputedStyle(svg).backgroundColor;
  const bg = surface && surface !== "rgba(0, 0, 0, 0)" ? surface : "#ffffff";
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("x", "0");
  rect.setAttribute("y", "0");
  rect.setAttribute("width", String(vbW));
  rect.setAttribute("height", String(vbH));
  rect.setAttribute("fill", bg);
  clone.insertBefore(rect, clone.firstChild);

  const svgText = new XMLSerializer().serializeToString(clone);
  const svgUrl =
    "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgText);
  const img = new Image();
  img.onload = () => {
    const target = document.createElement("canvas");
    target.width = Math.round(vbW * scale);
    target.height = Math.round(vbH * scale);
    const ctx = target.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(img, 0, 0, target.width, target.height);
    void composeAndDownload(target, meta, filename);
  };
  img.src = svgUrl;
}
