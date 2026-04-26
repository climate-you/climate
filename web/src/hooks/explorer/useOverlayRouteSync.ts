import { useCallback, useEffect, useRef, useState } from "react";

import { DEFAULT_OVERLAY_BASE_PATH } from "@/lib/explorer/constants";
import {
  overlayPathForRoute,
  parseOverlayFromLocationParts,
  stripOverlayPath,
  type OverlayRoute,
} from "@/lib/explorer/routing";

type UseOverlayRouteSyncArgs = {
  initialOverlay: OverlayRoute;
  initialOverlayBasePath: string;
};

export function useOverlayRouteSync({
  initialOverlay,
  initialOverlayBasePath,
}: UseOverlayRouteSyncArgs) {
  const [aboutOpen, setAboutOpen] = useState(initialOverlay === "about");
  const [sourcesOpen, setSourcesOpen] = useState(initialOverlay === "sources");
  const overlayBasePathRef = useRef<string>(
    stripOverlayPath(initialOverlayBasePath),
  );

  const setOverlayOpenWithUrl = useCallback((overlay: OverlayRoute) => {
    if (typeof window === "undefined") return;
    const isOpening = overlay !== null;
    if (isOpening) {
      overlayBasePathRef.current = stripOverlayPath(window.location.pathname);
    }
    setAboutOpen(overlay === "about");
    setSourcesOpen(overlay === "sources");
    const targetPath = overlayPathForRoute(
      overlay,
      overlayBasePathRef.current || DEFAULT_OVERLAY_BASE_PATH,
    );
    const nextUrl = `${targetPath}${window.location.search}${window.location.hash}`;
    window.history.replaceState({}, "", nextUrl);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const syncFromLocation = () => {
      const overlay = parseOverlayFromLocationParts(
        window.location.pathname,
        window.location.search,
      );
      if (overlay === null) {
        overlayBasePathRef.current = stripOverlayPath(window.location.pathname);
      }
      setAboutOpen(overlay === "about");
      setSourcesOpen(overlay === "sources");
    };
    syncFromLocation();
    window.addEventListener("popstate", syncFromLocation);
    return () => window.removeEventListener("popstate", syncFromLocation);
  }, []);

  return {
    aboutOpen,
    sourcesOpen,
    setOverlayOpenWithUrl,
  };
}
