#!/usr/bin/env python3
"""
Streamlit prototype: Precipitation metrics explorer.

Computes and displays 5 precipitation metrics on the fly from ERA5 daily
cache files (no pre-packaged tiles needed):

  1. CDD     - Max consecutive dry days (year-round)
  2. Rx5day  - Max 5-day precipitation total
  3. SDII    - Simple Daily Intensity Index (mm / wet-day)
  4. R95p    - % of annual precip from days above the long-term 95th percentile
  5. Wet days - Days per year with >= 1 mm

Run with:
    conda run -n climate streamlit run scripts/precip_metrics.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── config ────────────────────────────────────────────────────────────────────
CACHE_ROOT = Path("/Volumes/SDCard/Climate/cache/cds")
DATASET_PREFIX = "era5_daily_total_precipitation_global_0p25"
DRY_THRESHOLD_MM = 1.0

# Tile group labels (each group = 4 tile rows/cols × 64 cells = 256 cells)
_ROW_GROUPS = ["r000-003", "r004-007", "r008-011"]
_COL_GROUPS = [
    "c000-003", "c004-007", "c008-011",
    "c012-015", "c016-019", "c020-022",
]

# Clickable world-map grid
MAP_GRID_DEG = 5.0
_lats_g = np.arange(-87.5, 88.0, MAP_GRID_DEG)
_lons_g = np.arange(-177.5, 178.0, MAP_GRID_DEG)
_lat_m, _lon_m = np.meshgrid(_lats_g, _lons_g)
MAP_GRID_LAT = _lat_m.ravel()
MAP_GRID_LON = _lon_m.ravel()

PRESETS = {
    "Paris":         (48.85,   2.35),
    "Madrid":        (40.42,  -3.70),
    "London":        (51.51,  -0.13),
    "New York":      (40.71, -74.01),
    "San Francisco": (37.77, -122.42),
    "Cairo":         (30.05,  31.23),
    "Mumbai":        (19.08,  72.88),
    "Sydney":       (-33.87, 151.21),
    "São Paulo":    (-23.55, -46.63),
    "Singapore":      (1.35, 103.82),
    "Nairobi":       (-1.29,  36.82),
    "Moscow":        (55.75,  37.62),
}


# ── cache helpers ─────────────────────────────────────────────────────────────

def _cache_dir(lat: float, lon: float) -> Path:
    """Return the sliced cache directory that contains this lat/lon."""
    row_i = int((90.0 - lat) / 0.25)
    col_i = int((lon + 180.0) / 0.25)
    rg = min(row_i // 256, len(_ROW_GROUPS) - 1)   # 256 = 4 tiles × 64 cells
    cg = min(col_i // 256, len(_COL_GROUPS) - 1)
    return CACHE_ROOT / f"{DATASET_PREFIX}_{_ROW_GROUPS[rg]}_{_COL_GROUPS[cg]}"


# ── data loading ──────────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Loading ERA5 daily precipitation from cache…")
def load_daily_mm(lat: float, lon: float) -> pd.Series:
    """
    Return daily precipitation in mm for the nearest ERA5 grid cell.
    Opens monthly NetCDF files one-by-one (lazy per file, one cell extracted)
    to keep memory low, then concatenates.
    """
    import xarray as xr

    cache_dir = _cache_dir(lat, lon)
    if not cache_dir.exists():
        raise FileNotFoundError(f"Cache directory not found:\n{cache_dir}")

    files = sorted(cache_dir.glob("*.nc"))
    if not files:
        raise FileNotFoundError(f"No .nc files in {cache_dir}")

    chunks: list[pd.Series] = []
    for f in files:
        with xr.open_dataset(f) as ds:
            time_dim = "valid_time" if "valid_time" in ds.coords else "time"
            tp = ds["tp"].sel(latitude=lat, longitude=lon, method="nearest").load()
            vals = tp.values.ravel().astype(np.float64) * 24.0 * 1000.0  # m (daily_mean hourly rate) → mm/day
            times = pd.to_datetime(ds[time_dim].values)
            chunks.append(pd.Series(vals, index=times))

    daily = pd.concat(chunks).sort_index()
    daily.name = "tp_mm"
    # Replace negative values (ERA5 can produce tiny negatives) with 0
    daily = daily.clip(lower=0.0)
    return daily


# ── metric computation ─────────────────────────────────────────────────────────

def _max_cdd(s: pd.Series) -> float:
    """Max consecutive dry days (< threshold) in this series."""
    is_dry = ((s < DRY_THRESHOLD_MM) & s.notna()).to_numpy()
    max_run = cur = 0
    for v in is_dry:
        cur = cur + 1 if v else 0
        if cur > max_run:
            max_run = cur
    return float(max_run)


def _rx5day(s: pd.Series) -> float:
    """Max 5-consecutive-day rolling sum."""
    v = s.rolling(5, min_periods=5).sum().max()
    return float(v) if np.isfinite(v) else np.nan


def _sdii(s: pd.Series) -> float:
    """Total precipitation on wet days / number of wet days."""
    wet = s[s >= DRY_THRESHOLD_MM]
    return float(wet.sum() / len(wet)) if len(wet) > 0 else np.nan


def _r95p_frac(s: pd.Series, p95: float) -> float:
    """% of annual total falling on days that exceed the long-term p95."""
    total = s.sum()
    if total <= 0 or not np.isfinite(p95):
        return np.nan
    return float(100.0 * s[s >= p95].sum() / total)


def _wet_days(s: pd.Series) -> float:
    return float((s >= DRY_THRESHOLD_MM).sum())


def compute_metrics(daily: pd.Series) -> pd.DataFrame:
    # Long-term 95th percentile computed over all wet days in the full record
    all_wet = daily[daily >= DRY_THRESHOLD_MM].dropna()
    p95 = float(np.percentile(all_wet, 95)) if len(all_wet) > 0 else np.nan

    rows = []
    for year, grp in daily.groupby(daily.index.year):
        grp = grp.dropna()
        rows.append({
            "year":     year,
            "cdd":      _max_cdd(grp),
            "rx5day":   _rx5day(grp),
            "sdii":     _sdii(grp),
            "r95p":     _r95p_frac(grp, p95),
            "wet_days": _wet_days(grp),
        })

    return pd.DataFrame(rows).set_index("year")


# ── plotting helpers ───────────────────────────────────────────────────────────

def _trend(years: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, float]:
    mask = np.isfinite(values)
    if mask.sum() < 2:
        return np.full_like(values, np.nan), np.nan
    c = np.polyfit(years[mask], values[mask], 1)
    line = np.polyval(c, years)
    per_decade = c[0] * 10.0
    return line, per_decade


def _rolling5(values: np.ndarray) -> np.ndarray:
    return (
        pd.Series(values)
        .rolling(5, center=True, min_periods=3)
        .mean()
        .to_numpy()
    )


METRIC_META = [
    dict(
        key="cdd",
        title="CDD — Consecutive Dry Days",
        subtitle="Max consecutive days with < 1 mm (full calendar year)",
        y_label="Days",
        color="#E07B54",
        fmt=".0f",
    ),
    dict(
        key="rx5day",
        title="Rx5day — Max 5-day Precipitation",
        subtitle="Highest 5-consecutive-day total per year",
        y_label="mm",
        color="#1B7FCC",
        fmt=".1f",
    ),
    dict(
        key="sdii",
        title="SDII — Daily Precipitation Intensity",
        subtitle="Annual precipitation total ÷ number of wet days (≥ 1 mm)",
        y_label="mm/day",
        color="#2EAA6E",
        fmt=".2f",
    ),
    dict(
        key="r95p",
        title="R95p — Heavy Precipitation Fraction",
        subtitle="% of annual total from days exceeding the long-term 95th percentile",
        y_label="%",
        color="#7B4FCC",
        fmt=".1f",
    ),
    dict(
        key="wet_days",
        title="Wet Days",
        subtitle="Days per year with ≥ 1 mm precipitation",
        y_label="days/year",
        color="#3AAFB9",
        fmt=".0f",
    ),
]


def build_metric_fig(df: pd.DataFrame, meta: dict) -> go.Figure:
    years = df.index.to_numpy(dtype=float)
    vals  = df[meta["key"]].to_numpy(dtype=float)
    mean5 = _rolling5(vals)
    trend_line, per_decade = _trend(years, vals)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=years, y=vals,
        name="Annual",
        marker_color=meta["color"],
        opacity=0.40,
        hovertemplate=f"%{{x:.0f}}: %{{y:{meta['fmt']}}}<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=years, y=mean5,
        mode="lines", name="5-year mean",
        line=dict(color=meta["color"], width=2.5),
        hovertemplate=f"%{{x:.0f}}: %{{y:{meta['fmt']}}}<extra></extra>",
    ))

    if np.isfinite(per_decade):
        sign = "+" if per_decade >= 0 else ""
        trend_label = (
            f"Trend ({sign}{per_decade:{meta['fmt']}} "
            f"{meta['y_label']}/decade)"
        )
    else:
        trend_label = "Trend"

    fig.add_trace(go.Scatter(
        x=years, y=trend_line,
        mode="lines", name=trend_label,
        line=dict(color="#E63946", width=1.5, dash="dot"),
        hovertemplate=f"%{{x:.0f}}: %{{y:{meta['fmt']}}}<extra></extra>",
    ))

    fig.update_layout(
        title=dict(
            text=f"{meta['title']}<br><sup>{meta['subtitle']}</sup>",
            x=0.0, xanchor="left",
        ),
        xaxis=dict(
            title="Year", showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
        ),
        yaxis=dict(
            title=meta["y_label"], showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
        ),
        legend=dict(orientation="h", y=-0.22, x=0),
        height=360,
        margin=dict(l=60, r=20, t=70, b=80),
        plot_bgcolor="white",
        paper_bgcolor="white",
        bargap=0.15,
    )
    return fig


def build_map_fig(lat: float, lon: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scattergeo(
        lat=MAP_GRID_LAT, lon=MAP_GRID_LON,
        mode="markers",
        marker=dict(size=10, opacity=0, color="black"),
        hovertemplate="%{lat:.1f}°, %{lon:.1f}°<extra></extra>",
        showlegend=False, name="grid",
    ))
    fig.add_trace(go.Scattergeo(
        lat=[lat], lon=[lon],
        mode="markers",
        marker=dict(size=10, color="#E63946", symbol="circle"),
        hovertemplate=f"{lat:.2f}°N, {lon:.2f}°E<extra></extra>",
        showlegend=False, name="selected",
    ))
    fig.update_geos(
        projection_type="natural earth",
        showcoastlines=True, coastlinecolor="rgba(100,100,100,0.6)",
        showland=True,  landcolor="#e8f4e8",
        showocean=True, oceancolor="#cce5f0",
        showframe=False,
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=260,
        geo=dict(bgcolor="rgba(0,0,0,0)"),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ── Streamlit app ─────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Precipitation Metrics")
st.title("Precipitation Metrics — ERA5 1979–2025")
st.caption(
    "Computes 5 precipitation metrics on the fly from daily ERA5 cache files. "
    "**Bars** = annual values · **Solid line** = 5-year rolling mean · "
    "**Dotted red** = linear trend."
)

if "lat" not in st.session_state:
    st.session_state.lat = 48.85
if "lon" not in st.session_state:
    st.session_state.lon = 2.35

# ── sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Location")
    st.caption("Click the map or use the inputs below.")

    map_state = st.plotly_chart(
        build_map_fig(st.session_state.lat, st.session_state.lon),
        on_select="rerun",
        selection_mode="points",
        key="world_map",
        use_container_width=True,
        config={"displayModeBar": False},
    )

    if map_state.selection.points:
        pt = map_state.selection.points[0]
        if pt.get("curve_number") == 0:
            new_lat = round(float(pt["lat"]), 2)
            new_lon = round(float(pt["lon"]), 2)
            if new_lat != st.session_state.lat or new_lon != st.session_state.lon:
                st.session_state.lat = new_lat
                st.session_state.lon = new_lon
                st.rerun()

    lat = st.number_input(
        "Latitude",  min_value=-90.0,  max_value=90.0,
        value=st.session_state.lat, step=0.25, format="%.2f",
    )
    lon = st.number_input(
        "Longitude", min_value=-180.0, max_value=180.0,
        value=st.session_state.lon, step=0.25, format="%.2f",
    )
    if lat != st.session_state.lat or lon != st.session_state.lon:
        st.session_state.lat = lat
        st.session_state.lon = lon

    st.divider()
    with st.expander("Presets", expanded=True):
        cols = st.columns(2)
        for i, (name, (plat, plon)) in enumerate(PRESETS.items()):
            if cols[i % 2].button(name, use_container_width=True):
                st.session_state.lat = plat
                st.session_state.lon = plon
                st.rerun()

        st.divider()
        if st.button("Precompute all presets", use_container_width=True):
            bar = st.progress(0, text="Starting…")
            n = len(PRESETS)
            errors = []
            for i, (name, (plat, plon)) in enumerate(PRESETS.items()):
                bar.progress(i / n, text=f"Loading {name}… ({i + 1}/{n})")
                try:
                    load_daily_mm(plat, plon)
                except Exception as e:
                    errors.append(f"{name}: {e}")
            bar.progress(1.0, text="Done.")
            if errors:
                st.warning("Some cities failed:\n" + "\n".join(errors))
            else:
                st.success("All 12 presets cached — switching is now instant.")

lat = st.session_state.lat
lon = st.session_state.lon

# ── main content ───────────────────────────────────────────────────────────────
try:
    daily = load_daily_mm(lat, lon)
    df    = compute_metrics(daily)

    st.caption(
        f"📍 {lat:.2f}°N, {lon:.2f}°E · "
        f"{len(daily):,} daily observations · "
        f"{df.index[0]}–{df.index[-1]}"
    )

    for meta in METRIC_META:
        st.plotly_chart(build_metric_fig(df, meta), use_container_width=True)

except FileNotFoundError as e:
    st.error(str(e))
except Exception as e:
    st.exception(e)

# ── methodology ────────────────────────────────────────────────────────────────
with st.expander("Data & methodology"):
    st.markdown(f"""
**Data source:** ERA5 reanalysis, daily total precipitation (`tp`), 0.25° grid, 1979–2025.
Data is read on the fly from local monthly NetCDF cache files in `{CACHE_ROOT}`.

**Metrics (dry-day threshold: {DRY_THRESHOLD_MM} mm/day)**

| Metric | Definition |
|--------|-----------|
| **CDD** | Longest run of consecutive days with < {DRY_THRESHOLD_MM} mm, per calendar year |
| **Rx5day** | Maximum rolling 5-day precipitation total per year |
| **SDII** | Annual total on wet days ÷ number of wet days (≥ {DRY_THRESHOLD_MM} mm) |
| **R95p** | % of annual total from days exceeding the long-term 95th percentile of wet-day precipitation |
| **Wet days** | Days per year with ≥ {DRY_THRESHOLD_MM} mm |

**Long-term 95th percentile (R95p):** computed across all wet days in the full 1979–2025 record
for the selected location, then applied year by year.
""")
