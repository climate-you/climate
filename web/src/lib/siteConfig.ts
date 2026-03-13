const DEFAULT_SITE_URL = "https://example.com";

function normalizeSiteUrl(raw: string | undefined): string {
  const candidate = (raw ?? "").trim() || DEFAULT_SITE_URL;
  try {
    return new URL(candidate).origin;
  } catch {
    return DEFAULT_SITE_URL;
  }
}

function normalizeOptionalEnv(raw: string | undefined): string | null {
  const value = raw?.trim();
  return value ? value : null;
}

export const SITE_URL = normalizeSiteUrl(process.env.SITE_URL);
export const SITE_HOST = new URL(SITE_URL).host;
export const GOATCOUNTER_ENDPOINT = normalizeOptionalEnv(
  process.env.GOATCOUNTER_ENDPOINT,
);
