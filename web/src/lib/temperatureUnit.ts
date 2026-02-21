export function isUsLocale(locale: string): boolean {
  const normalized = locale.trim().toUpperCase();
  return normalized.endsWith("-US") || normalized.endsWith("_US");
}

export function defaultTemperatureUnitForLocale(): "C" | "F" {
  if (typeof navigator === "undefined") return "C";
  const primaryLocale = navigator.languages?.[0] ?? navigator.language ?? "";
  return isUsLocale(primaryLocale) ? "F" : "C";
}
