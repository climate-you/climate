# Spike Phase 1 — Key learnings (datasets, quirks, reliability)

## Goal achieved
We successfully pulled and processed:
- inland + big city “dry spell” metric from ERA5
- coastal SST warming + “hot days” from OISST
- coastal coral-heat-stress proxy (DHW) from NOAA Coral Reef Watch ERDDAP

Outputs proved:
- access works end-to-end
- chunking + caching patterns are essential
- metrics are story-worthy (Tamarin especially)

---

## Datasets used + what we learned

### 1) ERA5 (Copernicus CDS) — precip / dry-spells
**Status:** Works, but must chunk requests.
- Large multi-year daily requests hit CDS “cost limits exceeded / request too large”.
- Splitting into 1-year requests (then concatenating) avoids this.
- Good fit for “inland/big-city” metrics:
  - dry spell length
  - (next likely winners) heatwave days, hot nights, heavy rain days

**Operational notes:**
- Use caching for per-year files.
- Requests should be as small as possible (bbox vs global).
- Keep extraction lightweight; avoid downloading more variables than needed.

---

### 2) NOAA OISST v2.1 daily (ERDDAP griddap) — SST time series
**Status:** Works, but network-dependent + needs retries.
- PFEL ERDDAP hosts timed out on your home network; worked via phone hotspot or VPN.
  - Conclusion: ISP/router path issue; likely fine on a cloud VM later.
- Even when reachable, connections can be flaky:
  - “RemoteDisconnected” / intermittent failures
  - success with retries + backoff
- CSV parsing quirk:
  - ERDDAP CSV includes a second “units row” (e.g. first cell “UTC”); must skip it (`skiprows=[1]`).
- Chunking:
  - Fewer/larger requests sometimes behaved better than many tiny ones (but depends on network).
  - For your environment, decade NetCDF worked “sometimes”, smaller CSV chunks worked once VPN stabilized.

**Operational notes:**
- Keep robust downloader:
  - retries, exponential-ish backoff, jitter, caching, “resume if file exists”.
- Prefer consistent timestamp parsing (ISO Z strings).
- For story visuals: derive monthly/rolling series from daily data (no extra downloads).

---

### 3) NOAA Coral Reef Watch DHW daily (ERDDAP) — heat stress
**Status:** Works with the right variable + time axis + chunking.
- Correct variable is `degree_heating_week` (not `dhw`).
- `curl` needs `-g` / `--globoff` because of bracket syntax (Python requests is fine).
- Time axis is at **12:00Z**, and dataset minimum date is **1985-03-25T12:00Z**:
  - must clamp start date to >= 1985-03-25
  - must use `T12:00:00Z` in queries
- Long time spans triggered server/proxy errors (500/502):
  - solved by 1-year chunks + retries
- Near-coast boxes return mixed valid values + NaNs (land/mask):
  - box-mean must skip NaNs
  - (later) track “coverage fraction” so we know how many ocean pixels contributed

**Operational notes:**
- For storytelling, compute:
  - annual max DHW
  - days/year DHW >= 4
  - days/year DHW >= 8
  These give “moderate vs severe stress” layers.

---

## Reliability summary

### “Easy / stable with chunking”
- ERA5 via CDS (after splitting requests by year)

### “Works but network-sensitive + needs robust retries”
- OISST via PFEL ERDDAP (VPN/hotspot workaround on your current network)

### “Works but requires strict query correctness + small chunks”
- CRW DHW via coastwatch ERDDAP (variable name + 12:00Z + start date clamp + 1-year chunks)

---

## Reusable extractor patterns identified

### A) Chunk planner (time ranges)
- generate safe request windows (yearly / 5-year / decade)
- clamp to dataset coverage min/max
- consistent timestamp formatting per dataset

### B) Robust downloader
- cache-first (skip if file exists and non-empty)
- retries + exponential backoff + jitter
- clear logging per chunk (dataset, year range, attempt)
- tolerate intermittent “RemoteDisconnected”, 500/502

### C) Parser adapters
- ERDDAP CSV: skip units row; parse ISO times; handle NaNs
- NetCDF: open with xarray; select nearest; reduce dims; skip NaNs

### D) Metrics layer
- “daily → annual/monthly aggregates”
- baseline logic (1981–2010 for SST, etc.)
- threshold counts (>=4, >=8) & annual maxima
