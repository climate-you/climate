# Climate Story — Handoff Summary (instructions.md)

This repo builds a **climate scrollytelling experience**. Today it’s primarily prototyped in **Streamlit** (`app/story_demo.py`), but the long-term plan is a **separate front-end scrollytelling site** that reuses the same Python backend outputs (data files, figures, captions).

The project is organized around a consistent pattern for panels:
- `build_*_data(ctx, facts) -> dict`
- `build_*_figure(ctx, facts, data) -> figure(s)`
- `*_caption(ctx, facts, data) -> str`

Panels live under `climate/panels/`. Scripts to generate datasets and assets live under `scripts/`. Outputs go to `data/`.

## Story

The page teaches:
- what climate change looks like **locally** (day/night cycle → month → year → 50 years → trend into future),
- how **seasons shifted** (recent vs earlier climate),
- how local warming compares to **global warming** (“You vs the world”),
- a world map showing **warming relative to a baseline**,
- a **Monte Carlo sampling** visualization that explains the “+1.5°C global warming” idea (currently a standalone demo with fake data).

Non-goals for v1: heatwave detection (parked), “typical year daily then vs now” at global scale (may be revisited later).

---

## Current “story” structure

### Streamlit prototype
- Entry point: `story_demo.py`
- Panels now include:
  - **Seasons then vs now** (existing)
  - **You vs the world** (now uses real data; was fake in early prototype)
  - **World map** warming layer (now uses real ERA5-based warming map; was fake)
  - **Monte Carlo** global-mean experiment (now uses real ERA5 daily mean data from CDS; was fake)

### Front-end plan (future)
- Keep Streamlit as a fast iteration / prototyping tool.
- When a panel is “ready”, port it 1:1 into a front-end “step” (scrollytelling).
- Python continues to generate:
  - precomputed data files (CSV/NetCDF/Parquet)
  - textures (webp/png) + manifests
  - captions / derived “facts” blobs

---

## Key datasets & outputs

### Dataclasses
```python
@dataclass
class StoryFacts:
    data_start_year: int
    data_end_year: int
    total_warming_50y: Optional[float]
    recent_warming_10y: Optional[float]
    last_year_anomaly: Optional[float]
    hemisphere: str

@dataclass
class StoryContext:
    today: date
    slug: str
    location_label: str
    city_name: str
    location_lat: float
    location_lon: float
    unit: str                    # "C" or "F"
    ds: xr.Dataset               # precomputed climatology dataset for selected slug
```

### Panel function pattern (now used consistently)

Each panel uses:
```python
def build_x_data(ctx: StoryContext) -> dict
def build_x_figure(ctx: StoryContext, facts: StoryFacts, data: dict) -> (go.Figure, str)   # returns (figure, tiny caption like “Source/range”)
def x_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str
```
Goal: keep Streamlit layer thin; later can reuse same data/fig/caption builders in a JS frontend.

### Global temperature series (for “You vs the world”)
- Script: `scripts/make_global_series.py`
- Outputs:
  - `data/world/global_series.csv`
  - `data/world/global_series.meta.json`
- Used by: “You vs the world” panel (global anomalies chart).

### World warming map (2D Leaflet/Folium overlay)
- Script: `scripts/make_warming_map.py`
- Outputs:
  - `data/world/warming_map_....nc`
  - `data/world/warming_map_....manifest.json`
- Panel: `climate/panels/worldmap.py` (Folium-based interactive map)
- Notes:
  - NetCDF grid is typically `(latitude, longitude)` with:
    - lat descending: 90..-90
    - lon 0..359
  - Rendering had issues earlier (upside-down / offset / no repeat). Fixed by:
    - correct lat orientation
    - correct bounds
    - correct lon handling (0..360 vs -180..180)
    - optional longitude rolling for centering.

### World warming texture (for 3D globe)
- Script: `scripts/make_warming_texture.py`
- Outputs:
  - `data/world/warming_texture_*.webp`
  - `data/world/warming_texture_*.manifest.json`
- This produces a single equirectangular texture (global) suitable for a globe mesh.
- There is a helper in the script to roll lon 0..360 → -180..180 to center Greenwich; this affects how the JS globe needs to set its initial longitude.

### Borders overlay texture (coastlines + country borders)
- Script: `scripts/make_borders_overlay.py`
- Outputs:
  - `data/world/borders_<WxH>.png`
- Used by: globe prototype as a transparent overlay.
- Raster looks great zoomed out; for very deep zoom you’ll eventually want vector or tiled raster.

### Monte Carlo experiment (ERA5 daily mean, global mean warming)
- Download script (CDS): `scripts/download_era5_daily_t2m_cds.py`
- Experiment script: `scripts/make_montecarlo_experiment.py`
- Outputs:
  - Input NetCDFs in `data/mc/`:
    - `era5_daily_t2m_<YEAR>_gridX.nc` (+ meta)
  - Experiment sample parquet (optional):
    - `data/mc/experiment_XX_samples.parquet` (+ meta)
  - Experiment curve images (optional visualisation mode):
    - convergence curves plot
    - delta plot (difference over samples)
- Panel: `climate/panels/montecarlo.py`

---

## Units

Global toggle **Celsius vs Fahrenheit** is implemented and used across real-data pages. Default by location (US → F) is desired/implemented. Captions must handle delta formatting (“0.5°F colder” rather than “-0.5°F colder”).

## UI behavior & styling conventions

- Graph style standardized:
  - grey for noisy/raw (eg. hourly temp)
  - blue for smoothing/means (eg. daily mean)
  - red for trend
  - dotted red for future extension (with shaded period)
- Annotations:
  - min and max annotated with `annotate_minmax_on_series(fig, x, y, ...)` 
- Timezones:
  - Live Open-Meteo data queried with `"timezone"="auto"`
- Plotly rendering:
  - use `st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})` to avoid Streamlit deprecation warnings.

---

## Admin/maintenance pages (future but planned)

- cache size, disk space, number of precomputed locations
- monitor Open-Meteo/CDS request counts and failures
- track real user locations (aggregated/anonymous) + world map
- feedback link/email
- run precompute jobs (with progress monitoring) regularly (quarterly baseline + more frequent “popular cities”)
- reliability/SRE-ish monitoring

## Key design decisions and rationale**

- Conda environment is set up on user workstation (running MacOS)
- Account is set up with CDS
- Using **Open-Meteo ERA5** archive for precompute because CDS/ERA5 direct queries were slow and error-prone (CDS “no space left on device”, job failures). Open-Meteo is fast but rate-limited (429).
- Precompute city history to avoid live heavy queries and to support many users.
- Live Open-Meteo only for “fresh” windows (current temp, last week/month).
- Precompute end date set to **last full quarter** to keep data fresh but reduce compute frequency (quarterly update).
- Code refactored into modules with clear “data → figure → caption” pipeline so it can later move to a front-end scrollytelling framework.
- ERA5 “50 years” baseline starts at 1979 because ERA5 reanalysis coverage is conventionally used from 1979 onward.
- temperatures are shown in local time (Open-Meteo timezone handling) and put daily mean points at midday instead of 00:00.
- There is an ability to “time travel” (override today date in sidebar) to test how the page looks at different time of the year, this will be kept only in test page, not the final world-visible page.

---

## JS globe prototype (scrollytelling “v1” visual target)

### Prototype file(s)
- Minimal globe demo page: `scripts/globe_demo.html` (or similar static HTML)
- Loads:
  - warming texture webp
  - borders overlay png

### Rendering choice
- Use `MeshBasicMaterial` (no lights) to match “flat” Guardian-like look.
- Use a white page background (CSS + renderer clear color if needed).

### Notes / gotchas
- If the texture is rolled/shifted in Python (lon rolling), then “startLon” in JS may need adjustment.
- “Fly to London” issues:
  - If rotation is applied incrementally from current orientation, you get offsets.
  - Fix by computing absolute target orientation and tweening to it.
  - Maintaining north-up in view needs careful camera/rotation handling (avoid introducing roll).

---

## Open-Meteo precompute pipeline (cities)

### Current state
- There is a `scripts/precompute_story_cities.py` that precomputes city histories via Open-Meteo ERA5 archive.
- We implemented:
  - chunked fallback on `timeoutReached` (e.g., 5-year chunks)
  - reduced unnecessary waits between chunk requests
  - skip-if-up-to-date fast path
  - view map improvements: bigger map + state breakdown bar

### Rate limiting reality (429s)
- Open-Meteo free tier counts “long-range” queries (>2 weeks, many years) as **multiple calls**.
- Precomputing 40–50 years per city can cost hundreds of “call units” per city.
- You can hit limits quickly (minutely/hourly/daily/monthly).

### Strategy options (still under discussion)
A) **Open-Meteo subscription bootstrap**
- Pay for 1 month, bulk precompute (e.g., 2k+ cities)
- Then cancel and do small periodic updates.

B) **CDS backfill + Open-Meteo incremental**
- Use CDS to download global gridded data once per era / per year
- Extract city point time series locally (no 429s)
- Use Open-Meteo only for “live-ish” short windows (last week/month).

C) **All CDS for backfill + incremental**
- Each quarter/month: download new CDS year or month blocks and append locally.
- Most freedom (no Open-Meteo limits), but heavier pipeline and local storage.

Key tradeoff: CDS gives stable reproducibility + unlimited local extraction, but you manage more data.

---

## File map (what matters most)

### Panels
- `climate/panels/world.py`  
  “You vs the world” (local anomalies vs global anomalies). Uses:
  - local: precomputed ERA5 (Open-Meteo) city files
  - global: `data/world/global_series.csv`

- `climate/panels/worldmap.py`  
  “World map” (Folium/Leaflet overlay of warming + local inset caption logic)

- `climate/panels/montecarlo.py`  
  Monte Carlo experiment panel (playback loop in Streamlit; uses precomputed experiment data)

### Scripts
- `scripts/make_global_series.py`
- `scripts/make_warming_map.py`
- `scripts/make_warming_texture.py`
- `scripts/make_borders_overlay.py`
- `scripts/globe_demo.html`
- `scripts/download_era5_daily_t2m_cds.py`
- `scripts/make_montecarlo_experiment.py`
- `scripts/precompute_story_cities.py`
- `scripts/make_city_list.py` (needs rewrite / smarter selection)

---

## Monte Carlo “sampling” model (current intended default)
Goal: estimate change in **global mean near-surface air temperature** between eras.

Recommended default choices for v1:
- **Space sampling**: “area-weighted” (cos(latitude) correction) so each unit area contributes equally.
- **Time sampling**: monthly stratification (easier story) or day-of-year stratification (optional).

Important: Without proper area weighting, experiments can converge to noticeably different deltas because high latitudes get overrepresented.

---

## Known issues / work in progress

### Monte Carlo
- Large N (10M–50M) runs show some drift/run-to-run variance; likely remaining sampling variance + implementation details.
- We added options to skip writing full sample parquet for huge N to avoid memory blowups.

### City list / precompute strategy
- `make_city_list.py` currently selects poorly (e.g., small territories get same slots as large countries).
- Need a new selection scheme: population-weighted, region-balanced, and “likely user origins”.

### CDS vs Open-Meteo integration
- Decide primary “backfill” source:
  - Open-Meteo subscription vs CDS download-and-extract workflow.

---

## Immediate next tasks (for future chats)
1) Rewrite `make_city_list.py` to produce a better city set:
   - prioritize expected users (UK/Europe/US) + global coverage
   - avoid 3-per-country naive rule
   - cap tiny territories

2) Rewrite `precompute_story_cities.py` around the chosen strategy:
   - ideally append-only updates
   - possibly CDS-backed extraction for long history
   - Open-Meteo only for short “live” windows

3) Front-end integration:
   - keep Streamlit as a panel prototyping environment
   - port panels into front-end scrollytelling steps
   - reuse Python-generated assets (textures, borders, parquet/CSV, captions)

---

## Notes on running

### CDS downloads
- `download_era5_daily_t2m_cds.py` must split requests (typically by year) to avoid “cost limits exceeded”.
- CDS sometimes returns files that are not ZIP even if requested that way; code should detect and handle.

### World textures
- Consider 4096x2048 (good default) and 8192x4096 (high quality).
- Output resolution should roughly match grid resolution:
  - 1.0° grid ≈ 360x181 cells → upscale to 2048/4096+ is mostly interpolation
  - 0.25° grid has enough native detail to justify 8192x4096.

---

## API limits reminder (Open-Meteo)
Long-range requests (>2 weeks) can count as multiple calls; precomputing dozens of years per city is expensive in “call units” and easily triggers 429s. Prefer append-only updates and/or CDS-based backfill.

---

## Instructions for code changes

- for surgical patches, please print the code block (with befor/after is clearer) rather than uploading the whole file.
