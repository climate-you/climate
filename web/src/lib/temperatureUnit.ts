import { useSyncExternalStore } from "react";

export function isUsLocale(locale: string): boolean {
  const normalized = locale.trim().toUpperCase();
  return normalized.endsWith("-US") || normalized.endsWith("_US");
}

/**
 * Locale default for the temperature unit. CLIENT-SIDE ONLY.
 *
 * Note the `navigator` check is not a reliable "am I on the server?" test:
 * Node 21+ defines a global `navigator`, so on the server this resolves from
 * the *server process's* locale (e.g. `LANG` unset → "en-US" → "F"). Rendering
 * that during SSR makes the markup depend on the server's environment and
 * mismatches every client whose locale disagrees. Server rendering must use
 * `useDefaultTemperatureUnit` below, which pins the server snapshot to "C".
 */
export function defaultTemperatureUnitForLocale(): "C" | "F" {
  if (typeof navigator === "undefined") return "C";
  const primaryLocale = navigator.languages?.[0] ?? navigator.language ?? "";
  return isUsLocale(primaryLocale) ? "F" : "C";
}

export function observedWarmingString(unit: "C" | "F"): string {
  return unit === "F" ? "1.9°F" : "1.1°C";
}

const subscribeToNothing = () => () => {};
const getLocaleUnitSnapshot = () => defaultTemperatureUnitForLocale();
const getServerUnitSnapshot = (): "C" | "F" => "C";

/**
 * Hydration-safe locale default for use during render.
 *
 * The server snapshot is always "C", so the served HTML is deterministic and
 * independent of the server's locale; the real locale unit is picked up
 * immediately after hydration.
 */
export function useDefaultTemperatureUnit(): "C" | "F" {
  return useSyncExternalStore(
    subscribeToNothing,
    getLocaleUnitSnapshot,
    getServerUnitSnapshot,
  );
}
