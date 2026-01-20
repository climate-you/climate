# Climate Story — Updated Handoff Summary (2026-01)

This repo builds a **climate scrollytelling experience** driven by **Python-generated data + figures + captions**, rendered in a **Next.js/React** front-end.

Core contract:

- **Python is the single source of truth** for:
  - panel logic
  - caption text (Markdown)
  - figure generation (Plotly → SVG)
  - unit-specific wording/value formatting (C/F)

- **Web app is a renderer**:
  - loads exported assets (SVG + Markdown captions) from `web/public/data/...`
  - implements narrative UX: scroll-snapped slides, progressive caption reveal, SVG draw animation, dark/light/system theme, globe visuals.

---

## 1) Repository structure (what matters now)

### Python (source of truth)

- `climate/panels/`
  - Panel modules (e.g. `intro.py`, `zoomout.py`, `seasons.py`, `world.py`, etc.)
  - Conceptual pattern per panel:
    - `build_*_data(ctx) -> dict`
    - `build_*_figure(ctx, facts, data) -> (fig or figs, tiny_caption?)`
    - `*_caption(ctx, facts, data) -> markdown`
  - For the web we primarily export **SVG + caption.md** (data.json is not needed for v1).

- `climate/export/`
  - `web_paths.py`: path conventions for exported web bundle
  - `web_write.py`: write helpers (`write_json`, `write_text`, etc.)
  - `normalize_caption()` helper strips indentation / normalizes markdown output for React markdown.

- `scripts/`
  - `build_frontend_bundle.py`
    - Reads per-city `.nc` files and exports the **long-term/static panels** for each slug.
  - `build_live_panels.py`
    - Fetches Open-Meteo data for short-term panels (last week/month) and exports them daily per slug.
    - Writes a `latest.json` so web can find the newest available “as-of” directory per slug.

### Web (renderer)

- Next.js app under `web/`
- Story route:
  - `/story/[slug]` for explicit slug
  - `/story/auto` (and `/`) resolves location (geolocation) then selects nearest supported slug

Key components/hooks:

- `web/src/components/StoryClient.tsx`
  Orchestrates routing, unit/theme, scroller + slides layout, asset fetching for captions/SVGs, header transitions, and globe behavior.
- `web/src/components/Caption.tsx`
  `react-markdown` renderer + progressive reveal support (`reveal="sentences"` etc.) + typography styling.
- `web/src/components/PanelFigure.tsx`
  Renders injected SVG safely, applies scoped CSS, supports SVG stroke-dash draw animations (including sequencing, markers timing, dashed-line preservation).
- `web/src/components/Globe.tsx` + `web/src/components/GlobeEngine.ts`
  Three.js globe and shader-based rendering, with multiple “roles” (hero/mini/warming).
- Theme:
  - `web/src/hooks/useTheme.ts` provides System/Light/Dark (localStorage) and toggles Tailwind’s `.dark` on `<html>`.

---

## 2) Slugs and file naming conventions (current consensus)

- **Slug is the canonical ID everywhere** and includes the `city_` prefix:
  - e.g. `city_gb_london`, `city_jp_tokyo`, `city_mu_tamarin`

- City climatology files:
  - `data/story_climatology/clim_<slug>.nc`

- Web story bundle output:
  - `web/public/data/story/<slug>/facts.json`
  - `web/public/data/story/<slug>/meta.json`
  - `web/public/data/story/<slug>/panels/<panel>.<unit>.caption.md`
  - `web/public/data/story/<slug>/panels/<panel>.<unit>.svg`

Units are `"C"` and `"F"`. We export **both SVG and caption** in both units because numbers/units are embedded in both.

---

## 3) Export format and pipeline

### A) Long-term/static panels export

Run via `scripts/build_frontend_bundle.py` (typically monthly/quarterly):

- Inputs: `data/story_climatology/clim_<slug>.nc`
- Produces per slug:
  - `facts.json` + `meta.json`
  - panel assets: `panels/*.svg` and `panels/*.caption.md`
  - **both C and F variants**

Plotly SVG export tweaks required for web:

- enforce Plotly layout `width/height/margins`
- ensure y-axis ticks are visible (`margin.l` etc.)

### B) Live panels export (short-term)

Run via `scripts/build_live_panels.py` (daily, for selected slugs):

- Outputs per date (“as-of”) directory:
  - `web/public/data/live/<YYYY-MM-DD>/<slug>/`
    - `last_week.<unit>.svg`, `last_week.<unit>.caption.md`
    - `last_month.<unit>.svg`, `last_month.<unit>.caption.md`
    - `meta.json`
- Writes:
  - `web/public/data/live/latest.json` mapping `{ slug -> "YYYY-MM-DD" }`
- Web reads `latest.json` to choose the most recent available as-of date.

Compromise for v1:

- Precompute live panels daily for “popular” locations.
- For other locations: generate on-demand server-side later (not implemented yet).
- Current temperature is fetched via a **Next.js API proxy** (not browser → Open-Meteo) to centralize caching/troubleshooting.

---

## 4) Slides currently implemented in the web app

Story is a scroll-snapped scrollytelling sequence with “slides”, roughly:

### Intro + short-term weather

- Intro caption is exported from Python; the “now temperature” line is removed from exported intro caption (web has its own “It’s currently …” from the live proxy).
- Short-term slides use live bundle assets:
  - Last week (SVG + caption)
  - Last month (SVG + caption)

### Zoom-out temperature history (from `zoomout.py`)

- Last year
- Last 5 years
- Last 50 years
- Future/trend panels (depending on export)

### Seasons then vs now (from `seasons.py`)

Two slides:

1. One main figure + caption
2. Two side-by-side envelope figures + caption (markdown lists render correctly)

### You vs the world (from `world.py`)

- Two side-by-side anomaly charts (local vs global) + caption

### Warming globe slide (new)

- Dedicated “warming” mode:
  - transitions to warming “data” texture, then spins
  - grid lines hidden in warming mode (`gridOpacity` uniform)
  - marker visible initially, then disappears when spinning starts
  - spin time anchored to avoid “jump”
  - optional “tilt reset”: spinning gradually removes pitch/roll so equator becomes horizontal

---

## 5) Front-end UX decisions and compromises

### Scroll snapping

- Single scroll container with CSS snap:
  - `snap-y snap-mandatory`
  - `scroll-snap-stop: always` on slides (prevents skipping with trackpads)
- Wheel event hacks were tried and removed; CSS snap works best.
- Scroll container wraps both columns so scrolling works when pointer is over the globe column.

### Progressive captions

- Captions via `react-markdown`.
- `Caption` supports progressive reveal (sentence-by-sentence).
- Markdown splitting issues (emphasis across sentence splits) fixed by normalization.

### SVG draw animations

- `PanelFigure` can animate curves sequentially; markers/annotations can appear after lines.
- Dashed lines require special handling to preserve dash patterns during stroke-dash animation.
- Plotly hover tooltips are not available in SVG mode (future: embed data for hover / switch to Plotly.js / custom overlays).

### Theme

- System/Light/Dark toggle works; Tailwind dark mode via `.dark` on `<html>`.
- SVGs are post-processed / CSS-overridden to remove Plotly white rects and adapt axis/text colors.

### Globe

- Multiple globe roles: hero, mini (docked), warming globe panel.
- Engine is shader-based; visual toggles are mostly uniforms.

---

## 6) Known sharp edges / gotchas

- Dev caching: sometimes stale `cities_index.json` or assets require hard reload / server restart.
- `cities_index.json` may list more locations than actually exported; auto-selection must avoid missing slugs.
- Exported markdown can include leading indentation from triple-quoted strings; fixed by `normalize_caption`.
- Live date logic must use `latest.json` (not “yesterday”) to be robust.

---

## 7) Instructions for code changes (how to request patches)

Prefer **surgical patches**:

- Specify **file path**
- Copy/paste the **exact block** to change (“before”)
- Provide the “after” code for that block
- Include required imports + wiring
- Avoid duplicate/conflicting `useEffect` blocks
- For Plotly export tweaks, keep changes minimal:
  - `fig.update_layout(width=..., height=..., margin=...)` in Python panel code

---

## 8) Runbook (common workflows)

### A) Run the web app locally

From repo root:

- `cd web`
- `npm install`
- `npm run dev`
  Open:
- `http://localhost:3000/`
- `http://localhost:3000/story/city_mu_tamarin`

### B) Build the long-term/static web bundle for a slug

From repo root:

- Ensure `data/story_climatology/clim_<slug>.nc` exists
- `python scripts/build_frontend_bundle.py --slugs city_mu_tamarin`
  Expected:
- `web/public/data/story/<slug>/facts.json`
- `web/public/data/story/<slug>/meta.json`
- `web/public/data/story/<slug>/panels/<panel>.<C|F>.svg`
- `web/public/data/story/<slug>/panels/<panel>.<C|F>.caption.md`
- `web/public/data/cities_index.json`

### C) Build daily live panels for a slug

From repo root:

- `python scripts/build_live_panels.py --slugs city_mu_tamarin`
  Expected (example):
- `web/public/data/live/<YYYY-MM-DD>/<slug>/last_week.C.svg`
- `web/public/data/live/<YYYY-MM-DD>/<slug>/last_week.C.caption.md`
- `web/public/data/live/<YYYY-MM-DD>/<slug>/last_month.F.svg`
- `web/public/data/live/<YYYY-MM-DD>/<slug>/meta.json`
- `web/public/data/live/latest.json`

### D) Quick sanity checks

- Open raw assets:
  - `/data/story/<slug>/panels/<panel>.C.caption.md`
  - `/data/live/latest.json`
- Restart dev server if cached:
  - stop `npm run dev`, rerun
- Hard refresh:
  - Cmd+Shift+R / Ctrl+Shift+R

---

## 9) Future directions (discussed)

- Better slide layout hierarchy + timed text tied to curve drawing (timeline API)
- More datasets beyond 2m temperature (SST, precipitation, pollution)
- Location comparisons (“my city vs another city”)
- Scalable precompute / on-demand generation strategy
- Case-study / headline pages about recent events
- Monte Carlo simulation port to React (start as Python-exported assets, later interactive)
