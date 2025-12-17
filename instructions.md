# Handoff Summary

## Project goal

Build a **public-facing climate “story”** web page that works worldwide. It should feel like scrollytelling (eventually front-end), but for now it’s implemented in Streamlit with a stepper-style UI and Plotly charts.

The page teaches:
- what climate change looks like **locally** (day/night cycle → month → year → 50 years → trend into future),
- how **seasons shifted** (recent vs earlier climate),
- how local warming compares to **global warming** (“You vs the world”),
- a world map showing **warming relative to a baseline**,
- later: a **Monte Carlo sampling** visualization that explains the “+1.5°C global warming” idea (currently a standalone demo with fake data).

Non-goals for v1: heatwave detection (parked), “typical year daily then vs now” at global scale (may be revisited later).

## Current repo structure (already refactored)

```
.
├── app
│   └── story_demo.py                # streamlit app entrypoint
├── climate
│   ├── __init__.py
│   ├── analytics.py                 # compute facts, trends, helpers
│   ├── fake.py                      # fake data generator (to be removed after world pages are real)
│   ├── io.py                        # load locations, load climatology datasets, small IO helpers
│   ├── models.py                    # dataclasses StoryFacts, StoryContext, etc.
│   ├── openmeteo.py                 # Open-Meteo request helpers + caching wrappers
│   ├── panels
│   │   ├── __init__.py
│   │   ├── helpers.py               # shared chart style helpers, annotations, etc.
│   │   ├── intro.py                 # Intro panel (real data)
│   │   ├── seasons.py               # Seasons panels (real data)
│   │   ├── world.py                 # placeholder (to implement)
│   │   └── zoomout.py               # Zoom-out panels (real data)
│   └── units.py                     # Celsius/Fahrenheit conversions, formatting helpers
├── data
│   └── story_climatology
│       ├── clim_city_*.nc           # precomputed city climatology files (Open-Meteo ERA5 archive)
├── draft
│   └── monte_carlo_demo.py          # standalone Monte Carlo demo (fake data)
├── locations
│   ├── favorites.txt
│   └── locations.csv
├── scripts
│   ├── make_city_list.py            # generates locations.csv from GeoNames + extras
│   └── precompute_story_cities.py   # precomputes clim_city_*.nc for all locations.csv
```

## Data model
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

## Precomputed city climatology files (data/story_climatology/clim_{slug}.nc)

Generated from Open-Meteo ERA5 archive API.

Each file contains:
- **Daily** (dimension `time` daily):
  - `t2m_daily_mean_c`
  - `t2m_daily_min_c`
  - `t2m_daily_max_c`
- **Monthly** (dimension `time_monthly` monthly):
  - `t2m_monthly_mean_c` (mean of daily mean)
  - `t2m_monthly_min_c` (mean of daily min)
  - `t2m_monthly_max_c` (mean of daily max)
- **Yearly** (dimension `time_yearly` yearly):
  - `t2m_yearly_mean_c`
- **Monthly climatology** (dimension month 1..12):
  - `t2m_monthly_clim_past_mean_c`
  - `t2m_monthly_clim_recent_mean_c`
  - plus (after recent changes) min/max climatology for side-by-side envelopes (if implemented): `t2m_monthly_clim_past_min_c`, `t2m_monthly_clim_past_max_c`, `t2m_monthly_clim_recent_min_c`, `t2m_monthly_clim_recent_max_c`

**Time coverage strategy:**
- Start year: **1979** (ERA5 standard).
- End date: last full quarter relative to “today” (e.g., if today is Dec 2025, end is Sep 30 2025).
- The app shows subtle “Data from 1979 to Sep 2025” captions.

Filenames now **do not include year**, to avoid duplicates and disk bloat.

## Live (non-precomputed) data

Even with precomputed city history, the page still needs “fresh”:
- **Current temperature** (for Intro), and
- **Last week / last month** series (to show the day/night oscillation and recent daily rhythm), because precomputes stop at last full quarter.

These are fetched live from Open-Meteo and cached:
- cached via `@st.cache_data` (in-memory per process) + some local discipline (cache key normalized to day granularity; also optional disk caching is under consideration)
- rate limits (429) were a recurring issue; scripts now do backoff. App should also handle 429 gracefully.

Timezone issue fixed: show temperatures in local time (Open-Meteo timezone handling) and put daily mean points at midday instead of 00:00.

There is an ability to “time travel” (override today date in sidebar) to test how the page looks at different time of the year, this will be kept only in test page, not the final world-visible page.

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

## Scripts
`scripts/make_city_list.py`

- Generates `locations/locations.csv` from GeoNames dump (cities500/1000/etc).
- Supports:
  - `--source` (e.g., cities500 vs cities1000)
  - `--extra` (add specific “City,Country” pairs)
  - `--extra-file` (file with extra city+country lines)
- Favorites file writing is optional (e.g. `--write-favorites`) to avoid overwriting manual favorites.

A separate simple Streamlit tool (`view_locations_map.py`) was created to visualize `locations.csv` on a world map (helpful for distribution sanity check).

`scripts/precompute_story_cities.py`
- Now reads `locations.csv` (not hardcoded cities).
- Can filter to favorites or subset.
- Uses progress bar (`tqdm`). Terminal output is expected to show multiple lines; it’s not a single-line refresh in some environments.
- Key requirements already added:
  - skips slugs if existing file is up-to-date (`is_existing_file_up_to_date(path, slug, target_end)` checks existence, variables present, and end-date)
  - Rate limiting:
    - A min gap between processed slugs (`--min-gap`) to avoid Open-Meteo 429s (when skipping already computed slugs, no wait is done)
    - On 429, backoff starts at `>= min-gap` and increases (with jitter).
    - Logs “rate-limit-ish” headers; Open-Meteo often does not send Retry-After.
  
## What works today (v1-ready-ish)

✅ Intro (real data + current temp + localized warming comparison placeholder)

✅ Zoom-out page with real data:
- last week (hourly + daily mean + min/max annotations)
- last month (daily + mean + min/max)
- last year (daily + smoothing + min/max arrow boxes; beware dark-mode annotation bg)
- last 5 years
- last 50 years (monthly, yearly mean, trend lines including coldest/warmest-month trend)
- 25 years ahead (trend extension; y-axis range adjusted to avoid exaggeration)

✅ Seasons page with real data:
- seasons then vs now (recent vs earlier)
- hover templates show “Month: +Δ°C” formatted correctly
- curves rotated so warmest month is centered (hemisphere-friendly)
- separate side-by-side envelope plots (min/mean/max with blue/red fills) are being wired; captions need to avoid “0.0°C warmer” awkwardness

✅ Location selection:
- now driven from disk: user can pick any precomputed city file (favorites to be added on top + dropdown)

✅ Error handling improvements:

- many previous Streamlit issues fixed (duplicate keys, streamlit.debug, deprecated params, etc.)
- 429 in the app still needs graceful handling + possibly disk caching.

---

## What is NOT implemented yet (next big tasks)

### World pages (to make real, no fake)

1. **Global anomaly series** generation:
- write script to compute `data/world/global_series.csv` (e.g. global mean temperature anomaly vs baseline; likely use ERA5 / reanalysis-based global average)
- then implement “You vs the world” panel:
  - local series already computed from city climatology (yearly mean etc.)
  - compare to global series
  - show both curves and explain “local faster/slower than global”.
2. **World warming map raster**:
- write script to generate a global grid raster (png/tif/zarr) of warming between baseline periods (e.g. 1979–1988 vs 2016–2025 or other) using ERA5 2m temperature
- store along with a JSON manifest (projection, bounds, min/max, baseline definitions)
- “World map” panel loads raster + highlights current location dot.

### Monte Carlo demo integration (currently standalone fake data)

- Monte Carlo idea: sample (lat, lon, time) points in two eras, show convergence of mean difference.
- Current `draft/monte_carlo_demo.py` uses fake data and has improved mean-line behavior (horizontal mean line that moves as samples increase).
- Want eventually: more animation-friendly front-end (React/Three) rather than Streamlit, but keep prototype.

### Admin/maintenance pages (future but planned)

- cache size, disk space, number of precomputed locations
- monitor Open-Meteo/CDS request counts and failures
- track real user locations (aggregated/anonymous) + world map
- feedback link/email
- run precompute jobs (with progress monitoring) regularly (quarterly baseline + more frequent “popular cities”)
- reliability/SRE-ish monitoring

## Key design decisions and rationale**

- Using **Open-Meteo ERA5** archive for precompute because CDS/ERA5 direct queries were slow and error-prone (CDS “no space left on device”, job failures). Open-Meteo is fast but rate-limited (429).
- Precompute city history to avoid live heavy queries and to support many users.
- Live Open-Meteo only for “fresh” windows (current temp, last week/month).
- Precompute end date set to **last full quarter** to keep data fresh but reduce compute frequency (quarterly update).
- Code refactored into modules with clear “data → figure → caption” pipeline so it can later move to a front-end scrollytelling framework.
- ERA5 “50 years” baseline starts at 1979 because ERA5 reanalysis coverage is conventionally used from 1979 onward.

---

## Current open questions / TODOs

- Add **disk cache** (shared across process restarts) for Open-Meteo live windows to reduce 429s.
- Improve app robustness: catch 429 and show “data temporarily unavailable, retry later” instead of crashing.
- Dark mode styling for Plotly annotations (min/max boxes).

---

## Current short-term roadmap

1. [DONE] Write the `make_city_list.py` to generate `locations.csv` from GeoNames
2. [IN PROGRESS] Change the `precompute_story_cities.py` to consume `locations.csv`
3. [TODO] Change `story_demo.py` to display one select box with favorites at the top for the location selection
4. [TODO] Write a script to generate the `data/world/global_series.csv` (global anomaly)
5. [TODO] Move the "You vs the world" page to use this data (local already computed + global computed just above)
6. [TODO] Write a script to generate `data/world/warming_map_{baselineA}_{baselineB}.(png|tif|zarr)` + a tiny JSON manifest for min/max, projection, etc. #7. Move the "world map" page to use this data

## What the new assistant should do next

1. Implement Step #2 completion if not done: ensure precompute_story_cities.py fully consumes locations.csv + supports favorites/subsets + stable progress output.
2. Implement Step #3 (change `story_demo.py`)
3. Implement Step #4–7 (world data):
- script: `global_series.csv`
- script: warming map raster + manifest
- implement `climate/panels/world.py` to use them
4. Remove fake data pipeline once world panels use real data.
5. Then revisit Monte Carlo integration (maybe keep in draft until front-end prototype).