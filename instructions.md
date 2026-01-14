# Climate Story — Updated Handoff Summary (2026-01)

This repo builds a **climate scrollytelling experience** driven by **Python-generated data + figures + captions**, rendered in a **Next.js/React** front-end.

The core design is now:

- **Python is the single source of truth** for:
  - panel logic
  - captions text
  - figure generation (Plotly → SVG)
  - unit-specific wording/value formatting (C/F)

- **Web app is a renderer**:
  - loads exported assets (SVG + Markdown captions) from `web/public/data/...`
  - implements narrative UX: scroll-snapped slides, progressive caption reveal, animated SVG drawing, dark/light/system theme, globe visuals.

---

## 1) Repository structure (what matters now)

### Python (source of truth)
- `climate/panels/`
  - Panel modules (e.g. `intro.py`, `zoomout.py`, `seasons.py`, `world.py`, etc.)
  - Pattern per panel still conceptually:
    - `build_*_data(ctx) -> dict`
    - `build_*_figure(ctx, facts, data) -> (fig or figs, tiny_caption?)`
    - `*_caption(ctx, facts, data) -> markdown`
  - But for the web, we mostly export **SVG + caption.md** (data.json is not needed for v1).

- `climate/export/`
  - `web_paths.py`: path conventions for exported web bundle
  - `web_write.py`: write helpers (`write_json`, `write_text`, etc.)
  - `normalize_caption()` helper was introduced (or should exist) to strip indentation/normalize markdown output for React markdown.

- `scripts/`
  - `build_frontend_bundle.py`
    - Reads per-city `.nc` files and exports the **long-term/static panels** for each slug.
  - `build_live_panels.py`
    - Fetches Open-Meteo data for short-term panels (last week/month) and exports them daily per slug.
    - Writes a `latest.json` so web can find the newest available “as-of” directory per slug.
  - (existing precompute scripts still exist for generating city climatology NetCDFs)

### Web (renderer)
- Next.js app under `web/`
- Story route:
  - `/story/[slug]` for explicit slug
  - `/story/auto` (and `/`) resolves location (geolocation) then selects nearest supported slug
- Key components/hooks:
  - `web/src/components/StoryClient.tsx`
    The orchestration layer: routing, unit/theme, scroller + slides layout, data fetching for captions/SVGs, header title transitions, and globe behavior.
  - `web/src/components/Caption.tsx`
    `react-markdown` renderer + **progressive reveal** support (`reveal="sentences"` etc.) + typography styling (`caption-md`).
  - `web/src/components/PanelFigure.tsx`
    Renders injected SVG safely, applies scoped CSS, and supports **SVG stroke-dash draw animations** (including sequencing, markers/annotations timing, dashed-line preservation).
  - `web/src/components/Globe.tsx` + `web/src/components/GlobeEngine.ts`
    Three.js globe and shader-based rendering, with multiple “variants” (hero/mini/warming).
  - Hooks that exist in the refactor:
    - `useCitiesIndex`, `useIntroCaption`, `useLivePanel`, `useLiveAsof`, etc.
  - Theme:
    - `web/src/hooks/useTheme.ts` provides System/Light/Dark (stored in localStorage) and toggles Tailwind’s `.dark` on `<html>`.

---

## 2) Slugs and file naming conventions (current consensus)

- **Slug is the canonical ID everywhere** and includes the `city_` prefix:
  - e.g. `city_gb_london`, `city_jp_tokyo`, `city_mu_tamarin`
- City climatology files:
  - `data/story_climatology/clim_<slug>.nc`
  - e.g. `data/story_climatology/clim_city_jp_tokyo.nc`
- Web story bundle output:
  - `web/public/data/story/<slug>/facts.json`
  - `web/public/data/story/<slug>/meta.json`
  - `web/public/data/story/<slug>/panels/<panel>.<unit>.caption.md`
  - `web/public/data/story/<slug>/panels/<panel>.<unit>.svg`

Units are `"C"` and `"F"` internally, and formatting helpers add the degree symbol and sign.

---

## 3) Export format and pipeline

### A) Long-term/static panels export
Run via `scripts/build_frontend_bundle.py` (typically monthly/quarterly):
- Inputs: `data/story_climatology/clim_<slug>.nc`
- Produces per slug:
  - `facts.json` + `meta.json`
  - panel assets: `panels/*.svg` and `panels/*.caption.md`
  - **both C and F variants** for SVG and caption (because captions embed numbers and units)

Common tweaks that were required for good SVG rendering in the web app:
- enforce Plotly layout `width/height/margins`
- ensure y-axis ticks are visible (`margin.l` etc.)

### B) Live panels export (short-term)
Run via `scripts/build_live_panels.py` (daily, for selected slugs):
- Outputs per date (“as-of”) directory:
  - `web/public/data/live/<YYYY-MM-DD>/<slug>/`
    - `last_week.C.svg`, `last_week.C.caption.md` (+ `.F`)
    - `last_month...`
    - `meta.json`
- Writes:
  - `web/public/data/live/latest.json` mapping `{ slug -> "YYYY-MM-DD" }`
- Web reads `latest.json` to choose the most recent available as-of date.

Strategy (compromise for v1):
- Precompute live panels daily for “popular” locations.
- For other locations: can generate on-demand server-side later (not implemented as a full service yet).
- Current temperature is still fetched through a **Next.js API proxy** (not direct browser → Open-Meteo), to keep visibility, caching, and troubleshooting centralized.

---

## 4) Slides currently implemented in the web app

The story is now a scroll-snapped scrollytelling sequence with “slides”, roughly:

### Intro + short-term weather
- Intro caption is exported from Python; “now temperature” line is **removed** from the exported intro caption (the web has its own “It’s currently …” line from the live proxy).
- Short-term slides:
  - Last week (SVG + caption)
  - Last month (SVG + caption)
  - These use live bundle assets.

### Zoom-out temperature history (from `zoomout.py`)
- Last year
- Last 5 years
- Last 50 years
- Future/trend panel(s) (e.g., 25 years ahead depending on what you exported)

### Seasons then vs now (from `seasons.py`)
Implemented as **two slides**:
1) One main figure + caption
2) Two side-by-side envelope figures + caption (markdown lists render correctly now)

### You vs the world (from `world.py`)
- Two side-by-side anomaly charts (local vs global) + caption
- Caption supports lists and italics correctly after fixing markdown splitting/rendering issues.

### Warming globe slide (new)
A special slide with a **centered big globe**:
- Uses a dedicated globe “warming” mode:
  - transitions land/border coloring to warming “data” texture
  - then begins spinning
  - **grid lines hidden in warming mode** (grid is shader-driven via `gridOpacity` uniform)
  - marker visible initially, then disappears when spinning starts
  - spin time anchored so it does not “jump”
  - optional “tilt reset”: spinning gradually removes pitch/roll so equator becomes horizontal after a few seconds

---

## 5) Front-end UX decisions and compromises

### Scroll snapping
- The main narrative uses a single scroll container with CSS snap:
  - `snap-y snap-mandatory`
  - `scroll-snap-stop: always` on slides to prevent skipping multiple slides on trackpads.
- Wheel event “hacks” were tried and removed; CSS snap works best.
- The scroll container now wraps both columns so scrolling works even when pointer is over the globe column.

### Progressive captions
- Captions are rendered via `react-markdown`.
- `Caption` supports progressive reveal (e.g. sentence-by-sentence).
- Some markdown transformations were needed to avoid breaking emphasis across sentence splits; this is now fixed.

### SVG draw animations
- `PanelFigure` can animate curves:
  - sequentially (grey then blue, etc.)
  - markers can be hidden until after paths draw
  - annotations can appear after lines
  - dashed lines required special handling to preserve dash patterns during stroke-dash animation

Hover tooltips from Plotly are **not** implemented in SVG mode. (Possible later: embed data for hover, switch to Plotly.js for interactive charts, or add custom hover overlays.)

### Theme
- System/Light/Dark theme toggle exists and works.
- Tailwind dark mode is enabled using `.dark` on `<html>`.
- Dark palette was tuned closer to ChatGPT-like colors (e.g. background `#212121`, pills `#171717`).
- SVGs required cleanup:
  - remove/override Plotly’s white background rects
  - adjust text/axis colors via CSS/processing so figures look correct in dark mode
  - result: SVGs look correct in both modes now.

### Globe
- Multiple globe “roles” exist:
  - hero cold-open globe
  - mini globe docked left (lg screens)
  - warming globe panel
- The globe engine is shader-based with uniforms (including `gridOpacity`, `dataOpacity`, etc.), so many visual toggles are done via uniforms rather than meshes.

---

## 6) Known “sharp edges” and gotchas

- **Dev caching**: sometimes stale `cities_index.json` or caption assets require a hard reload / restart; verifying by opening `/data/...` URLs in the browser is the quickest sanity check.
- `cities_index.json` can list more locations than actually exported; if auto-selection picks a missing slug, the page needs a fallback strategy (currently handled by ensuring the closest slug is generated, or regenerating the index).
- Exported markdown sometimes included leading indentation from triple-quoted Python strings; this is fixed by normalizing lines (e.g. lstrip each line) in the export pipeline (`normalize_caption`).
- Live “as-of” date logic must use `latest.json` (not “yesterday”) to be robust.

---

## 7) Instructions for code changes (how to request patches)

When making changes, prefer **surgical patches**. For requests:

- Always specify:
  - **file path**
  - **exact block** to change (copy/paste before)
  - show **after** code for that block
- Avoid vague instructions like “near your booleans”.
- If adding a function/variable, the patch must include:
  - the **definition**
  - how it’s wired into existing logic
  - any required imports
- Avoid introducing duplicate or contradictory `useEffect`/`useLayoutEffect` blocks.
- If fixing a UI behavior, include the relevant CSS classes and their file location.
- For Plotly export tweaks, prefer minimal changes:
  - adjust `fig.update_layout(width=..., height=..., margin=...)` in the Python panel code only.

---

## 8) Runbook (common workflows)

### A) Run the web app locally
From repo root:
- Install deps (first time):
  - `cd web`
  - `npm install`
- Run dev server:
  - `npm run dev`
- Then open:
  - `http://localhost:3000/` (auto mode)
  - `http://localhost:3000/story/city_mu_tamarin` (explicit slug)

### B) Build the long-term/static web bundle for a slug
From repo root:
- Ensure climatology NetCDF exists:
  - `data/story_climatology/clim_<slug>.nc`
- Run bundle:
  - `python scripts/build_frontend_bundle.py --slugs city_mu_tamarin`
- Expected outputs:
  - `web/public/data/story/city_mu_tamarin/facts.json`
  - `web/public/data/story/city_mu_tamarin/meta.json`
  - `web/public/data/story/city_mu_tamarin/panels/<panel>.<C|F>.svg`
  - `web/public/data/story/city_mu_tamarin/panels/<panel>.<C|F>.caption.md`
  - `web/public/data/cities_index.json` (copied/updated by bundle script)

### C) Build daily live panels for a slug (last week / last month)
From repo root:
- Run:
  - `python scripts/build_live_panels.py --slugs city_mu_tamarin`
- Expected outputs (example as-of date):
  - `web/public/data/live/2025-12-24/city_mu_tamarin/last_week.C.svg`
  - `web/public/data/live/2025-12-24/city_mu_tamarin/last_week.C.caption.md`
  - `web/public/data/live/2025-12-24/city_mu_tamarin/last_month.F.svg`
  - `web/public/data/live/2025-12-24/city_mu_tamarin/meta.json`
  - `web/public/data/live/latest.json` (maps slug → latest as-of date)

### D) Quick sanity checks when something “doesn’t update”
- Open the raw asset in browser to confirm it exists:
  - `http://localhost:3000/data/story/<slug>/panels/<panel>.C.caption.md`
  - `http://localhost:3000/data/live/latest.json`
- Restart dev server if Next.js is serving cached assets:
  - stop `npm run dev`
  - rerun `npm run dev`
- Hard refresh the page:
  - (Chrome) Cmd+Shift+R / Ctrl+Shift+R

---

## 9) Future directions (explicitly discussed)

### UX / storytelling improvements
- Better slide layout and hierarchy:
  - separate header area
  - timed text to match curve drawing
  - more deliberate pacing and transitions between slide “chapters”
- Advanced caption choreography:
  - interleave text reveals with staged SVG drawing (grey line → sentence → blue line → sentence → annotations)
  - requires a small “timeline” API (panel-level orchestration)

### Data expansion beyond 2m temperature
- Add other datasets where 2m temperature “story” is less compelling:
  - SST / water temperature
  - precipitation
  - pollution/air quality
- Data availability will vary by location; need fallback captions.

### Comparisons between locations
- “compare my city vs another city” slides
- ability to bookmark/share a comparison

### Precompute strategy at scale
- Improve city selection (`locations.csv` generation)
- Better Open-Meteo/CDS hybrid:
  - Open-Meteo for short windows + incremental
  - CDS for heavy backfill + unlimited extraction
- Goal: generate panels **on-demand** for any location efficiently.

### Case-study / headline pages
- Pages that explain items like:
  - “2025 was second hottest year on record” (or whatever the latest verified claim is)
  - El Niño / La Niña effects
  - notable recent extremes

### Monte Carlo simulation in React
- Port the Monte Carlo panel into the web narrative or as a separate page
- Likely still Python-exported assets first; later could become interactive.
