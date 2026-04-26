import { useEffect, useState } from "react";

import type { TextureVariantOverride } from "@/components/MapLibreGlobe";
import {
  parseDebugQuery,
  parseTextureVariantQuery,
} from "@/lib/explorer/routing";

type UseDebugTextureSyncResult = {
  debugMode: boolean;
  textureVariantOverride: TextureVariantOverride;
};

export function useDebugTextureSync(
  debugAllowed: boolean,
): UseDebugTextureSyncResult {
  const [debugMode, setDebugMode] = useState<boolean>(false);
  const [textureVariantOverride, setTextureVariantOverride] =
    useState<TextureVariantOverride>("auto");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () =>
      setTextureVariantOverride(
        debugAllowed
          ? parseTextureVariantQuery(window.location.search)
          : "auto",
      );
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [debugAllowed]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () =>
      setDebugMode(debugAllowed && parseDebugQuery(window.location.search));
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [debugAllowed]);

  return { debugMode, textureVariantOverride };
}
