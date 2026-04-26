import type { TextureVariantOverride } from "@/components/MapLibreGlobe";

import { DEFAULT_OVERLAY_BASE_PATH } from "@/lib/explorer/constants";

export type OverlayRoute = "about" | "sources" | null;

export function parseDebugQuery(search: string): boolean {
  const raw = (new URLSearchParams(search).get("debug") ?? "")
    .trim()
    .toLowerCase();
  return raw === "on" || raw === "1" || raw === "true";
}

export function parseTextureVariantQuery(
  search: string,
): TextureVariantOverride {
  const raw = (new URLSearchParams(search).get("texture") ?? "")
    .trim()
    .toLowerCase();
  if (raw === "mobile") return "mobile";
  if (raw === "full") return "full";
  return "auto";
}

export function parseIntroOverrideQuery(search: string): boolean | null {
  const raw = (new URLSearchParams(search).get("intro") ?? "")
    .trim()
    .toLowerCase();
  if (!raw) return null;
  if (raw === "1" || raw === "true" || raw === "on") return true;
  if (raw === "0" || raw === "false" || raw === "off") return false;
  return null;
}

export function parseOverlayFromLocationParts(
  pathname: string,
  search: string,
): OverlayRoute {
  if (pathname === "/about") return "about";
  if (pathname === "/sources") return "sources";
  const params = new URLSearchParams(search);
  if (params.has("about")) return "about";
  if (params.has("sources")) return "sources";
  return null;
}

export function stripOverlayPath(pathname: string): string {
  if (pathname === "/about" || pathname === "/sources") {
    return DEFAULT_OVERLAY_BASE_PATH;
  }
  return pathname || DEFAULT_OVERLAY_BASE_PATH;
}

export function overlayPathForRoute(
  overlay: OverlayRoute,
  fallbackPath: string,
): string {
  if (overlay === "about") return "/about";
  if (overlay === "sources") return "/sources";
  return stripOverlayPath(fallbackPath);
}
