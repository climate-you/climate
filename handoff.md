# Climate tiles + API v0 — Handoff (next step: registry/refactor)

## Current state (works end-to-end)

We have a working v0 pipeline:

- Packager downloads ERA5 monthly means from CDS, computes annual means, writes tiles:
  - Metric example: `t2m_yearly_mean_c`
  - Grid: `global_0p25` (0.25°), tile size 64x64
  - Tile files: `data/releases/<release>/series/global_0p25/<metric>/z64/rXXX_cYYY.bin.zst`
  - Per-metric axis: `data/releases/<release>/series/global_0p25/<metric>/time/yearly.json`
- Tile format: `.bin` with a header (nyears, dtype, tile dims), compressed with zstd.
- FastAPI:
  - Has `PlaceResolver` (locations.csv ~ 33k geonames cities>500).
  - Has `TileDataStore` as source of truth for tile metrics.
  - Panel endpoint works for `t2m_50y`:
    - Reads `t2m_yearly_mean_c` vector for the snapped cell.
    - Derives: 5y mean + linear trend (currently hardcoded functions).
    - Returns `PanelResponse` including `LocationInfo` and `DataCell` (grid + i_lat/i_lon + center lat/lon).
- Next.js demo page:
  - Map picker works.
  - Clicking shows place label and draws dotted rectangle of selected cell.
  - Also displays debug cell/tile info so we can tell whether we’re in same cell.

Validation:

- Tile coverage script reads tiles directly from disk and prints:
  - “container fill” = fill of the 64x64 container
  - “real-grid fill” = fill of only valid cells for edge tiles
- We found and fixed a partial/empty tile that was tiny (hundreds of bytes).
- Full wipe + rerun packager confirmed all tiles now come purely from CDS and coverage is 100%.

## Pain points / why refactor

The system is currently hardcoded in multiple places:

- Metric names (`t2m_yearly_mean_c`) are hardcoded in packager, store, and panel builder.
- Derived series are computed via ad-hoc functions scattered in API code.
- Packager is single-metric-oriented; adding a new metric requires touching Python code in multiple places.
- There isn’t a clean “user journey” for:
  - prototyping a new metric/graph in Streamlit
  - promoting it to “official” tiled metric in release
  - exposing it via API and rendering it in React

## Desired direction (goal)

Create a coherent registry-driven pipeline where:

- Adding a new metric is primarily data/config-driven:
  - add JSON entry (either per-metric file or a `series.json` manifest)
  - define source: `cds` / `derived` / later `other`
  - define axis: yearly/monthly/daily
  - define dependencies (source metrics)
  - define derivation functions by name (with params)
- Packager iterates over registered metrics:
  - downloads required CDS datasets in batches
  - materializes tiles for all configured metrics (unless flagged as “compute-on-fly”)
- API becomes generic:
  - `get_series(metric_id, lat, lon)` reads a vector from tiles
  - derived metrics can either:
    - be pre-tiled by packager, OR
    - computed on the fly by API, OR
    - computed client-side in React
- Panels become config-driven:
  - panel JSON declares which graphs/series to return + styling hints
  - API “panel builder” mostly orchestrates loading series + applying declared transforms

## Proposed core abstractions (to implement next)

1. Metric registry (JSON):

- Example fields:
  - id: "t2m_yearly_mean_c"
  - grid_id: "global_0p25"
  - time_axis: "yearly"
  - dtype: "float32"
  - missing: "nan"
  - source:
    - type: "cds"
    - dataset: "reanalysis-era5-single-levels-monthly-means"
    - variable: "2m_temperature"
    - postprocess: ["k_to_c"]
    - agg: "annual_mean_from_monthly"
  - or source:
    - type: "derived"
    - inputs: ["t2m_yearly_mean_c"]
    - derive: { fn: "rolling_mean", window: 5, centered: true }
  - storage:
    - tiled: true/false
    - compression: { codec: "zstd", level: 10 }

2. Derive function registry:

- A dictionary mapping string names to pure functions:
  - rolling_mean_centered(y, window)
  - linear_trend_line(x, y)
  - slope(x, y)
  - delta_over_period(y, start_idx, end_idx)
- Must be generic (works for any metric vector).

3. Packager framework:

- Loads metric registry
- Groups metrics by:
  - grid_id + dataset source (to reuse downloads)
  - time axis
- Produces:
  - tiles for raw metrics
  - yearly/monthly axis files per metric
  - tiles for derived metrics (optional, depending on config)

4. API store:

- TileDataStore becomes fully generic:
  - get_vector(metric_id, lat, lon) -> np.ndarray
  - get_axis(metric_id) -> list[int]|list[str]
  - no metric-specific methods (no `panel_t2m_50y` in store)
- Panel building uses registry + panel config.

## Interest selector (“interestness”) decision

We want a selector grid later: “cells where slope over ~46y is positive”.
But we will NOT implement selector tiles until after the registry refactor.
Once registry exists:

- define derived metric: "t2m_yearly_slope_c_per_year" from yearly mean
- define selector rule: slope > 0 (or > epsilon)
- packager can generate a compact bitmask grid as a separate artifact.

## Concrete next steps (recommended order)

1. Define `metrics.json` (or `series.json`) schema + load/validate it in Python.
2. Refactor API to use `tile_store.get_vector(metric_id, ...)` + registry for axis.
3. Move derivations (rolling mean, trend, slope) into a generic `climate/derive/` module and call by name.
4. Refactor packager into:
   - download stage (CDS -> cache)
   - materialize stage (cached netcdf -> tiles) driven by metric specs
5. Only then: implement interest selector tiles as one more registry-driven output.

## File/path conventions already in use

- tiles root: `data/releases/<release>/series/<grid_id>/<metric>/z64/rXXX_cYYY.bin.zst`
- per-metric axis: `data/releases/<release>/series/<grid_id>/<metric>/time/yearly.json`
- locations: `locations/locations.csv` (slug, label, lat, lon, etc.)
- API endpoint: `/api/v/{release}/panel?lat=...&lon=...&panel_id=t2m_50y&unit=C`

## How to request code changes (critical)

Prefer **surgical patches**:

- Specify **file path**
- Include the **exact “BEFORE” block** (unless replacing the entire function body)
- Provide the **AFTER** block
- Include required imports + wiring

Never provide unified diff blocks.
