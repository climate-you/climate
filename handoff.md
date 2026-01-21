# Climate Story — Updated Instructions / Handoff (2026-01)

This repo builds a **climate scrollytelling experience** driven by **Python-generated data + figures + captions**, rendered in a **Next.js/React** front-end.

Core contract:

- **Python is the single source of truth** for:
  - story/panel logic
  - captions (Markdown today)
  - figure generation (Plotly → SVG; plus matplotlib/cartopy for context maps)
  - unit-specific wording/formatting (C/F)

- **Web app is a renderer**:
  - reads exported assets from `web/public/data/...`
  - renders slides with scroll-snapping + progressive captions + SVG draw animations
  - supports **manifest-driven** slide definitions (no hardcoded slide list)

## 0) Goals and current phase

### Overall product direction

Go beyond “temperature history” into **interesting climate stories**, potentially using:

- coastal: SST anomalies, DHW/coral stress, precipitation/dry spells, storms
- inland: heatwaves, hot nights, drought indicators
- big city: extremes + air quality correlations

Primary test slugs (familiar locations):

- coastal: `city_mu_tamarin` (Tamarin, Mauritius)
- inland: `city_fr_troyes` (Troyes, France)
- big city: `city_gb_london` (London, UK)

### Phase 1 (current)

Deliver a new story step **Ocean Stress** (coastal) end-to-end:

- precompute data to disk
- panel module loads cached data and builds SVGs + captions + context map(s)
- exporter writes assets + updates `story.json`
- React loads `story.json` and renders slides dynamically

**Milestone achieved:** React now loads slides from `story.json` manifest (not a hardcoded list).

## 1) Repository structure (what matters now)

### Python (source of truth)

- `climate/panels/`
  - Panel modules (existing: `intro.py`, `zoomout.py`, `seasons.py`, `world.py`, etc.)
  - New: `ocean.py` for Ocean Stress (loads cached ocean `.nc`, no network calls)
  - Typical panel pattern:
    - `build_*_data(ctx) -> dict`
    - `build_*_figure(ctx, facts, data) -> (fig or figs, tiny_caption?)`
    - `*_caption(ctx, facts, data) -> markdown`

- `climate/export/`
  - `web_paths.py`: path conventions for exported web bundle
  - `web_write.py`: write helpers
  - `captions.py` / `normalize_caption()`: fixes indentation / normalizes Markdown

- `scripts/`
  - `precompute_story_cities.py`: existing pipeline for climatology `.nc` per city (2m temps, etc.)
  - `precompute_ocean_cities.py`: precompute Ocean Stress cached `.nc files` (SST + DHW metrics)
  - `build_frontend_bundle.py`: exports static story assets (SVG + caption.md + `story.json`)
  - `build_live_panels.py`: exports last_week/last_month live assets and `live/latest.json`

### Web (renderer)

- Next.js app under `web/`
- Routes:
  - `/story/[slug]` explicit slug
  - `/story/auto` and `/` choose nearest supported slug

Key components:

- `web/src/components/StoryClient.tsx`
  - loads `story.json` and renders slides dynamically
  - manages unit/theme/scroller/globe/left column
- `web/src/components/panels/ManifestSlide.tsx`
  - renders one slide based on manifest entry (layout, figures, caption panel, left)
- `web/src/components/LeftSvg.tsx`
  - loads left-side SVG specified by `left.asset`
  - should soft-fail gracefully for missing assets (maps not exported yet)
- `web/src/components/Caption.tsx`
  - react-markdown + progressive reveal logic (sentence splitting)
- `web/src/components/PanelFigure.tsx`
  - injects SVG safely + applies theme fixups + supports draw animation

Theme:

- `web/src/hooks/useTheme.ts` toggles `.dark` on `<html>`

## 2) Export format & file conventions

### Slugs

Slug is canonical everywhere and includes `city_` prefix, e.g.

- `city_mu_tamarin`, `city_fr_troyes`, `city_gb_london`

### Static story bundle output (per slug)

- `web/public/data/story/<slug>/facts.json`
- `web/public/data/story/<slug>/meta.json`
- `web/public/data/story/<slug>/story.json` ← story manifest
- `web/public/data/story/<slug>/panels/<panel>.<unit>.svg`
- `web/public/data/story/<slug>/panels/<panel>.<unit>.caption.md`
- Maps (unit-agnostic) exported as SVG too:
  - `web/public/data/story/<slug>/maps/ocean_context_map.svg`
  - (future) `web/public/data/story/<slug>/maps/ocean_sst_map.svg`

Units are `"C"` and `"F"`. We export both variants for SVG + caption where units/values appear.

### Live bundle output

- `web/public/data/live/<YYYY-MM-DD>/<slug>/last_week.<unit>.svg` + `.caption.md`
- `web/public/data/live/<YYYY-MM-DD>/<slug>/last_month.<unit>.svg` + `.caption.md`
- `web/public/data/live/latest.json` maps `{ slug -> "YYYY-MM-DD" }`

## 3) `story.json` manifest (current direction)

Manifest drives slide order and rendering (no hardcoded slide list in React).

Key ideas:

- Each slide has an `id`, `layout`, `figures`, `caption_panel`, and `left`.
- Each figure can include:
  - `panel`: panel id used for asset resolution
  - `kind`: currently `"svg"`
  - `animate`: boolean to control SVG draw animation (renderer should not guess)

Example:

```json
{
  "id": "ocean_sst_hotdays",
  "layout": "single",
  "figures": [
    { "panel": "ocean_sst_hotdays", "kind": "svg", "animate": false }
  ],
  "caption_panel": "ocean_sst_hotdays",
  "left": { "kind": "svg", "asset": "maps/ocean_sst_map.svg" }
}
```

Left panel kinds:

```json
{ "kind": "globe" }
{ "kind": "svg", "asset": "maps/..." }
{ "kind": "none" }
```

## 4) Phase 1 — Ocean Stress (what was built)

### Precompute: `scripts/precompute_ocean_cities.py`

Produces cached per-city ocean dataset:

- output: `data/story_ocean/ocean_<slug>.nc` (exact folder/name may vary)
- includes annual metrics for:
  - SST anomaly vs baseline
  - SST “hot days” counts (baseline P90 by day-of-year)
  - DHW annual metrics (>=4 days, >=8 days, etc.)
- cache attrs include DHW box size, dataset ids, baseline range, etc.
- overwrite-safe behavior expected (write temp + replace)

### Panel: `climate/panels/ocean.py`

- loads ocean `.nc` from disk (NO network calls)
- builds three slides:
  - SST anomaly
  - SST hot days
  - DHW stress
- builds a context map figure for DHW box (matplotlib/cartopy)
- exports SVGs + captions via the standard exporter

### Exporter: `scripts/build_frontend_bundle.py`

- exports standard panels + Ocean Stress panels + maps
- updates:
  - `story.json` to include new Ocean Stress slides
  - `meta.json` to include reference to ocean cached `.nc` (for debugging/provenance)

### React

- loads `story.json` and renders slides dynamically
- left-side map loads via `left.asset`
- missing map assets should be handled gracefully (soft-fail 404)

## 5) Spike 1 findings (dataset access + operational lessons)

### ERA5/CDS

- Large CDS requests can hit “cost limits exceeded”.
- Splitting into smaller requests (often 1-year chunks) avoids 403/cost errors.

### NOAA OISST via ERDDAP (SST)

- Network reliability can be flaky (timeouts / remote disconnects); retries/backoff required.
- Some environments may require VPN/alternate network (observed: requests worked on hotspot/VPN).
- Correct ERDDAP query details mattered:
  - dataset requires `zlev=0.0` constraint (otherwise axis range errors)
  - chunking strategy matters (smaller blocks were sometimes more reliable than large pulls)

### NOAA Coral Reef Watch DHW via ERDDAP

- Variable is `degree_heating_week` (not `dhw`).
- Dataset time minimum starts at `1985-03-25T12:00:00Z` (requests earlier return “axis minimum” errors).
- Multi-year box requests can trigger 500/502 proxy errors; 1-year chunks were reliable.
- Use `curl -g` when testing bracketed ERDDAP URLs to avoid curl “bad range specification”.

### Summary insight from Phase 1 test

- Tamarin shows stronger signals in **ocean stress** than in air temperature:
  - SST anomalies increased substantially vs 1980s baseline.
  - DHW >=4 days emerged strongly from late 2000s onward; DHW >=8 appears in recent years.

## 6) Runbook (common workflows)

### A) Run web app locally

```bash
cd web
npm install
npm run dev
```

Open:

- `http://localhost:3000/`
- `http://localhost:3000/story/city_mu_tamarin`

### B) Precompute climatology bundle (existing pipeline)

```bash
python scripts/precompute_story_cities.py --slugs city_mu_tamarin
```

Outputs:

- `data/story_climatology/clim_<slug>.nc`

### C) test Precompute Ocean Stress cache

```bash
python scripts/precompute_ocean_cities.py --slugs city_mu_tamarin
```

Outputs:

- `data/story_ocean/ocean_<slug>.nc` (or equivalent)

### D) Export static story bundle (including Ocean Stress)

Test

```bash
python scripts/build_frontend_bundle.py --slugs city_mu_tamarin
```

Outputs:

- `web/public/data/story/<slug>/story.json`
- `web/public/data/story/<slug>/panels/*.svg`
- `web/public/data/story/<slug>/panels/*.caption.md`
- `web/public/data/story/<slug>/maps/*.svg` (context maps)
- `web/public/data/cities_index.json`

### E) Export live panels

```bash
python scripts/build_live_panels.py --slugs city_mu_tamarin
```

Outputs:

- `web/public/data/live/<YYYY-MM-DD>/<slug>/last_week.*`
- `web/public/data/live/latest.json`

## 7) How to request code changes (critical)

Prefer **surgical patches**:

- Specify **file path**
- Include the **exact “BEFORE” block** (unless replacing the entire function body)
- Provide the **AFTER** block
- Include required imports + wiring
- Avoid duplicate/conflicting `useEffect` blocks
- Keep Plotly tweaks minimal (`update_layout(...)` etc.)

Never provide unified diff blocks.

## 8) Next planned improvements (mentioned during Phase 1)

### A) Refactor dataset access into `climate.datasets`

Current state: dataset logic exists inside precompute scripts.
Goal: move reusable dataset querying into:

- `climate/datasets/specs.py` (dataset IDs, variable names, axis constraints, start dates)
- `climate/datasets/erddap.py` (URL building, robust download, CSV parsing, chunking helpers)
- `climate/datasets/openmeteo.py` (migrate from existing `climate/openmeteo.py`)

Motivation: “spike learnings” (zlev=0, time mins, chunk sizing, retries) must live in one place.

### B) Add SST anomaly left map for SST slides

- Export `maps/ocean_sst_map.svg`
- Left-side for SST slides should display SST anomaly field (grid-res, warm=red)
- Keep DHW slide left map as “context box” map

### C) DHW heatmap design (optional new slide or replace bars)

- A heatmap image where each pixel = day, color = DHW value
- Compare layouts:
  - 365px high (one column per year)
  - wrapped year into 4–5 strips
  - chronological vs sorted-by-DHW
- Export as SVG (or raster) and ensure React can load it as an asset
- Likely added as an additional slide first (don’t delete the simpler bars until heatmap is validated)

## 9) Phase 2 starter plan (inland + big city)

Goal: extend the “interesting stories” beyond coastal/ocean.

### Phase 2A — Troyes: heat + hot nights + dry spells

**Candidate metrics**

- Hot days per year (e.g. Tmax ≥ 30°C / 35°C thresholds)
- Tropical nights per year (Tmin ≥ 20°C)
- Heatwave duration indicators (e.g. consecutive days above threshold)
- Summer dry spells (max consecutive days with precipitation < X mm)

**Data sources**

- Start with the same pipeline style as Phase 1:
  - Use existing climatology `.nc` (if it already has daily temps/precip) or extend `precompute_story_cities.py` to store what’s missing.
  - If using CDS derived daily stats, prefer 1-year chunks to avoid “cost limits exceeded”.

**Story step**

- Add a new step after Zoom-out (or after Seasons):
  - “Heat stress” (single-slide or 2 slides: hot days + hot nights)
  - “Dry spells” (if it shows a clear change)

### Phase 2B — London: heat extremes + air quality

**Candidate metrics**

- Hot days above a high threshold (UK heat extremes, e.g. ≥ 30°C / ≥ 35°C)
- Air quality indicators (PM2.5, NO2, O3) if a reliable dataset is available at usable resolution/time span
- Compare pollution on extreme hot days vs typical summer days (distribution / anomaly)

**Data sources**

- Temperature: continue with ERA5/Open-Meteo/your climatology dataset.
- Air quality: pick a source that:
  - has multi-year coverage
  - supports point/box extraction efficiently
  - has an API or bulk format we can cache (avoid per-day tiny-file downloads)

**Story step**

- “City air + heat”:
  - one slide shows increasing hot extremes
  - one slide shows pollution metrics (or “pollution on hot days”)

### Phase 2 deliverable shape

- Repeat the Phase 1 “pattern”:
  1. spike script(s) to validate access + compute metrics
  2. precompute cache `.nc` per slug
  3. panel module (loads cache) + exporter + `story.json` entries
  4. React automatically renders via manifest

## 10) Definition of done for Phase 1

Phase 1 is “done” when:

- Ocean Stress step is fully integrated:
  - precompute works reliably
  - exporter emits all Ocean Stress assets + maps
  - story manifest includes Ocean Stress slides with correct left assets and animation flags
  - React renders everything from manifest
- and there is a clear plan for Phase 2 (Troyes/London stories + new datasets)
