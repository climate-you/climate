// Web-Mercator helpers for cropping the site's global anomaly textures to a
// regional bounding box and projecting overlay geometry into that same crop.
// The textures span the full globe from +latMax (top) to -latMax (bottom),
// where latMax comes from a map's `mercator_lat_max` (default ~85.05°).

export const DEFAULT_MERCATOR_LAT_MAX = 85.05112878;

export type Bbox = { west: number; south: number; east: number; north: number };

function mercatorY(latDeg: number): number {
  return Math.log(Math.tan(Math.PI / 4 + (latDeg * Math.PI) / 180 / 2));
}

/** Fractional x in [0,1] across the full-globe texture for a longitude. */
export function lonToU(lonDeg: number): number {
  return (lonDeg + 180) / 360;
}

/** Fractional y in [0,1] (0 = top/+latMax) across the texture for a latitude. */
export function latToV(latDeg: number, latMax: number): number {
  const maxM = mercatorY(latMax);
  return (maxM - mercatorY(latDeg)) / (2 * maxM);
}

export type CropRect = {
  sx: number;
  sy: number;
  sw: number;
  sh: number;
  /** aspect ratio (width / height) of the cropped *pixels* */
  aspect: number;
};

/** Pixel crop rectangle within a texture of the given dimensions for a bbox. */
export function cropRectForBbox(
  bbox: Bbox,
  textureWidth: number,
  textureHeight: number,
  latMax: number = DEFAULT_MERCATOR_LAT_MAX,
): CropRect {
  const sx = lonToU(bbox.west) * textureWidth;
  const ex = lonToU(bbox.east) * textureWidth;
  const sy = latToV(bbox.north, latMax) * textureHeight;
  const ey = latToV(bbox.south, latMax) * textureHeight;
  const sw = ex - sx;
  const sh = ey - sy;
  return { sx, sy, sw, sh, aspect: sw / sh };
}

/**
 * True (conformal) Web-Mercator display aspect for a bbox — width/height in
 * projected space. The stored textures are non-square in pixels (oversampled
 * vertically), so the crop's *pixel* aspect would stretch the map; use this to
 * size the canvas instead.
 */
export function mercatorAspect(bbox: Bbox): number {
  const lonExtent = ((bbox.east - bbox.west) * Math.PI) / 180;
  const latExtent = mercatorY(bbox.north) - mercatorY(bbox.south);
  return lonExtent / latExtent;
}

/** Project a lon/lat point to pixel coordinates inside a rendered crop. */
export function projectToCanvas(
  lonDeg: number,
  latDeg: number,
  bbox: Bbox,
  canvasWidth: number,
  canvasHeight: number,
  latMax: number = DEFAULT_MERCATOR_LAT_MAX,
): [number, number] {
  const uW = lonToU(bbox.west);
  const uE = lonToU(bbox.east);
  const vN = latToV(bbox.north, latMax);
  const vS = latToV(bbox.south, latMax);
  const x = ((lonToU(lonDeg) - uW) / (uE - uW)) * canvasWidth;
  const y = ((latToV(latDeg, latMax) - vN) / (vS - vN)) * canvasHeight;
  return [x, y];
}
