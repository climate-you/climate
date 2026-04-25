#!/usr/bin/env python3
"""
Streamlit prototype: Annual temperature cycle visualization.

Shows t2m temperature over the past ~50 years as overlapping annual curves.
Old years (>5 years ago) are grey; recent years get bright colours; current year is red.

Run with:
    /opt/homebrew/anaconda3/envs/climate/bin/streamlit run scripts/annual_cycle.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.interpolate import CubicSpline

# ── repo on path ─────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
from climate_api.store.tile_data_store import TileDataStore
from climate.datasets.products.era5 import ERA5_MONTHLY_MEANS_DATASET, build_monthly_means_request
from climate.datasets.sources.cds import retrieve as cds_retrieve

# ── config ────────────────────────────────────────────────────────────────────
TILES_ROOT = REPO_ROOT / "data/releases/dev/series"
CACHE_DIR = REPO_ROOT / "data/cache"

# Day-of-year at the midpoint of each month (non-leap year)
MONTH_DOY = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]

# Years in the tile store
TILE_RECENT_YEARS = list(range(2021, 2026))   # 2021–2025
RECENT_COLORS: dict[int, str] = {
    2021: "#FF9F1C",   # amber
    2022: "#2EC4B6",   # teal
    2023: "#9B5DE5",   # purple
    2024: "#00BBF9",   # sky blue
    2025: "#E63946",   # red  (most recent complete year)
}

# 2026 partial year shown separately
YEAR_2026_COLOR = "#7FBA00"  # lime green

# Clickable grid resolution for the world map (degrees)
MAP_GRID_DEG = 5.0

# ── pre-compute the clickable grid (module-level, not per-render) ─────────────
_lats_g = np.arange(-87.5, 88.0, MAP_GRID_DEG)
_lons_g = np.arange(-177.5, 178.0, MAP_GRID_DEG)
_lat_m, _lon_m = np.meshgrid(_lats_g, _lons_g)
MAP_GRID_LAT = _lat_m.ravel()
MAP_GRID_LON = _lon_m.ravel()

# ── data helpers ──────────────────────────────────────────────────────────────

@st.cache_resource
def get_store() -> TileDataStore:
    return TileDataStore.discover(TILES_ROOT)


@st.cache_data(show_spinner="Loading ERA5 data…")
def load_tile_data(lat: float, lon: float) -> dict[int, list]:
    """
    Returns monthly_by_year: {year: list[float]}  (12 values, Jan→Dec)
    from the packaged tile store (1979–2025).
    """
    store = get_store()
    monthly_vec = store.try_get_metric_vector("t2m_monthly_mean_c", lat, lon)
    monthly_axis = store.axis("t2m_monthly_mean_c")

    monthly_by_year: dict[int, list] = {}
    for i, label in enumerate(monthly_axis):
        year, month = int(label[:4]), int(label[5:7])
        if year not in monthly_by_year:
            monthly_by_year[year] = [None] * 12
        monthly_by_year[year][month - 1] = float(monthly_vec[i])

    return monthly_by_year


@st.cache_data(show_spinner="Downloading 2026 ERA5 data from CDS…")
def fetch_2026_monthly(lat: float, lon: float) -> list[float] | None:
    """
    Download monthly ERA5 t2m for 2026 (available months only) for a small
    area around the location. Returns a list[float | None] of length 12,
    with None for months not yet available.
    """
    import xarray as xr

    # Small bounding box: snap to nearest 0.25° grid and add ±0.5° padding
    lat_s = round(round(lat / 0.25) * 0.25, 2)
    lon_s = round(round(lon / 0.25) * 0.25, 2)
    area = (lat_s + 0.5, lon_s - 0.5, lat_s - 0.5, lon_s + 0.5)  # N, W, S, E

    target = CACHE_DIR / f"proto_2026_t2m_{lat_s:.2f}_{lon_s:.2f}.nc"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    request = build_monthly_means_request(
        years=["2026"],
        grid_deg=0.25,
        area=area,
    )

    try:
        cds_retrieve(ERA5_MONTHLY_MEANS_DATASET, request, target, overwrite=True)
    except Exception as e:
        st.warning(f"CDS download failed: {e}")
        return None

    try:
        ds = xr.open_dataset(target)
        t2m = ds["t2m"]  # shape: (time, lat, lon) or similar
        # Average over lat/lon to get a single time series
        t2m_mean = t2m.mean(dim=[d for d in t2m.dims if d not in ("valid_time", "time")])
        times = ds["valid_time"].values if "valid_time" in ds else ds["time"].values
        vals: list[float | None] = [None] * 12
        for i, t in enumerate(times):
            month = int(pd.Timestamp(t).month)
            vals[month - 1] = float(t2m_mean.values[i]) - 273.15  # K → °C
        return vals
    except Exception as e:
        st.warning(f"Could not parse 2026 data: {e}")
        return None


def monthly_to_smooth(
    monthly_vals: list,
) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
    """Interpolate up to 12 monthly values to a smooth day-of-year curve.

    Handles partial years: only the available (non-None) months are used.
    The curve is only drawn for the range covered by available data.
    """
    available = [(MONTH_DOY[i], v) for i, v in enumerate(monthly_vals) if v is not None]
    if len(available) < 2:
        return None, None

    x = np.array([p[0] for p in available], dtype=float)
    y = np.array([p[1] for p in available], dtype=float)

    if len(available) == 12:
        # Full year: use wrap-around for a periodic spline
        x_ext = np.concatenate([x[-3:] - 365, x, x[:3] + 365])
        y_ext = np.concatenate([y[-3:], y, y[:3]])
        cs = CubicSpline(x_ext, y_ext)
        doy = np.arange(1, 366)
    else:
        # Partial year: simple spline, only draw between first and last month
        cs = CubicSpline(x, y)
        doy = np.arange(int(x[0]), int(x[-1]) + 1)

    return doy, cs(doy)


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert '#RRGGBB' + alpha to an rgba() string for Plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.2f})"


# ── chart builders ────────────────────────────────────────────────────────────

def build_figure(
    lat: float,
    lon: float,
    vals_2026: list | None = None,
) -> go.Figure:
    monthly_by_year = load_tile_data(lat, lon)

    fig = go.Figure()

    all_years = sorted(monthly_by_year.keys())
    old_years = [y for y in all_years if y < min(TILE_RECENT_YEARS)]

    # ── grey curves for old years (monthly → smooth spline) ───────────────────
    for year in old_years:
        doy, vals = monthly_to_smooth(monthly_by_year.get(year, [None] * 12))
        if doy is None:
            continue
        fig.add_trace(
            go.Scatter(
                x=doy,
                y=vals,
                mode="lines",
                line=dict(color="rgba(160,160,160,0.25)", width=0.7),
                hovertemplate=f"{year}: %{{y:.1f}}°C<extra></extra>",
                showlegend=False,
                name=str(year),
            )
        )

    # ── coloured curves for recent tile-store years ────────────────────────────
    n_recent = len(TILE_RECENT_YEARS)
    for i, year in enumerate(TILE_RECENT_YEARS):
        hex_color = RECENT_COLORS.get(year, "#888")
        # Alpha ramps linearly: oldest = 0.30, most recent = 1.00
        alpha = 0.30 + 0.70 * (i / (n_recent - 1))
        color = hex_to_rgba(hex_color, alpha)
        is_current = year == max(TILE_RECENT_YEARS)

        doy, vals = monthly_to_smooth(monthly_by_year.get(year, [None] * 12))
        if doy is None:
            continue

        fig.add_trace(
            go.Scatter(
                x=doy,
                y=vals,
                mode="lines",
                line=dict(color=color, width=2.5 if is_current else 1.8),
                hovertemplate=f"{year}: %{{y:.1f}}°C<extra></extra>",
                showlegend=True,
                name=str(year),
            )
        )

        # Year label sitting just above the curve's peak temperature
        peak_idx = int(np.argmax(vals))
        fig.add_annotation(
            x=float(doy[peak_idx]),
            y=float(vals[peak_idx]),
            text=f"<b>{year}</b>",
            font=dict(color=color, size=10, family="monospace"),
            showarrow=False,
            yshift=9,
            bgcolor="rgba(255,255,255,0.65)",
            borderpad=1,
        )

    # ── partial 2026 curve ─────────────────────────────────────────────────────
    if vals_2026 is not None:
        doy_26, v_26 = monthly_to_smooth(vals_2026)
        if doy_26 is not None:
            fig.add_trace(
                go.Scatter(
                    x=doy_26,
                    y=v_26,
                    mode="lines",
                    line=dict(color=YEAR_2026_COLOR, width=2.5),
                    hovertemplate="2026: %{y:.1f}°C<extra></extra>",
                    showlegend=True,
                    name="2026",
                )
            )
            peak_idx = int(np.argmax(v_26))
            fig.add_annotation(
                x=float(doy_26[peak_idx]),
                y=float(v_26[peak_idx]),
                text="<b>2026</b>",
                font=dict(color=YEAR_2026_COLOR, size=10, family="monospace"),
                showarrow=False,
                yshift=9,
                bgcolor="rgba(255,255,255,0.65)",
                borderpad=1,
            )

    # ── layout ─────────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=f"Annual temperature cycle — {lat:.2f}°N, {lon:.2f}°E",
            x=0.5,
        ),
        xaxis=dict(
            title="Month",
            tickmode="array",
            tickvals=[1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335],
            ticktext=[
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
            ],
            range=[1, 365],
            showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
        ),
        yaxis=dict(
            title="Temperature (°C)",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
        ),
        legend=dict(title="Year", orientation="v", x=1.01, y=0.98),
        height=520,
        margin=dict(l=60, r=100, t=60, b=50),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
    )

    return fig


def build_map_figure(lat: float, lon: float) -> go.Figure:
    """World map with a dense invisible grid for click detection + red location dot."""
    fig = go.Figure()

    # Trace 0: invisible clickable grid
    fig.add_trace(
        go.Scattergeo(
            lat=MAP_GRID_LAT,
            lon=MAP_GRID_LON,
            mode="markers",
            marker=dict(size=10, opacity=0, color="black"),
            hovertemplate="%{lat:.1f}°, %{lon:.1f}°<extra></extra>",
            showlegend=False,
            name="grid",
        )
    )

    # Trace 1: selected location marker
    fig.add_trace(
        go.Scattergeo(
            lat=[lat],
            lon=[lon],
            mode="markers",
            marker=dict(size=10, color="#E63946", symbol="circle"),
            hovertemplate=f"{lat:.2f}°N, {lon:.2f}°E<extra></extra>",
            showlegend=False,
            name="selected",
        )
    )

    fig.update_geos(
        projection_type="natural earth",
        showcoastlines=True,
        coastlinecolor="rgba(100,100,100,0.6)",
        showland=True,
        landcolor="#e8f4e8",
        showocean=True,
        oceancolor="#cce5f0",
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

st.set_page_config(layout="wide", page_title="Annual Temperature Cycle")

st.title("Annual Temperature Cycle — ERA5 t2m")
st.caption(
    "Grey curves: 1979–2020 (monthly ERA5, spline-interpolated). "
    "Coloured curves: 2021–2025. **Red = 2025** (most recent complete year)."
)

# ── session state ──────────────────────────────────────────────────────────────
if "lat" not in st.session_state:
    st.session_state.lat = 48.85
if "lon" not in st.session_state:
    st.session_state.lon = 2.35
if "vals_2026" not in st.session_state:
    st.session_state["vals_2026"] = None

# ── sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Location")
    st.caption("Click the map or use the inputs below.")

    # Map (clickable via on_select)
    map_state = st.plotly_chart(
        build_map_figure(st.session_state.lat, st.session_state.lon),
        on_select="rerun",
        selection_mode="points",
        key="world_map",
        use_container_width=True,
        config={"displayModeBar": False},
    )

    # Handle map clicks — grid is trace 0, so curve_number == 0
    if map_state.selection.points:
        pt = map_state.selection.points[0]
        if pt.get("curve_number") == 0:
            new_lat = round(float(pt["lat"]), 2)
            new_lon = round(float(pt["lon"]), 2)
            if new_lat != st.session_state.lat or new_lon != st.session_state.lon:
                st.session_state.lat = new_lat
                st.session_state.lon = new_lon
                st.session_state["vals_2026"] = None
                st.rerun()

    # No widget key — value= drives the display; return value is written back below.
    lat = st.number_input(
        "Latitude", min_value=-90.0, max_value=90.0,
        value=st.session_state.lat, step=0.25, format="%.2f",
    )
    lon = st.number_input(
        "Longitude", min_value=-180.0, max_value=180.0,
        value=st.session_state.lon, step=0.25, format="%.2f",
    )
    # Sync back so map, chart, and presets all see the current value
    if lat != st.session_state.lat or lon != st.session_state.lon:
        st.session_state.lat = lat
        st.session_state.lon = lon
        st.session_state["vals_2026"] = None

    st.divider()
    with st.expander("Presets", expanded=True):
        presets = {
            "Paris": (48.85, 2.35),
            "New York": (40.71, -74.01),
            "Sydney": (-33.87, 151.21),
            "Nairobi": (-1.29, 36.82),
            "Reykjavik": (64.13, -21.82),
            "Singapore": (1.35, 103.82),
            "Buenos Aires": (-34.60, -58.38),
            "Moscow": (55.75, 37.62),
        }
        cols = st.columns(2)
        for i, (name, (plat, plon)) in enumerate(presets.items()):
            if cols[i % 2].button(name, use_container_width=True):
                st.session_state.lat = plat
                st.session_state.lon = plon
                st.session_state["vals_2026"] = None
                st.rerun()

    st.divider()
    st.header("2026 data")
    if st.session_state["vals_2026"] is None:
        st.caption(
            "The tile store only has data through Dec 2025. "
            "Click below to download the latest available ERA5 monthly data for 2026 "
            "from CDS (~1–3 min)."
        )
        if st.button("Fetch 2026 data from CDS", use_container_width=True):
            result = fetch_2026_monthly(lat, lon)
            st.session_state["vals_2026"] = result if result is not None else []
            st.rerun()
    else:
        n = sum(1 for v in st.session_state["vals_2026"] if v is not None)
        if n > 0:
            st.success(f"2026 data loaded ({n} month{'s' if n != 1 else ''}).")
        else:
            st.warning("No 2026 data could be retrieved.")
        if st.button("Clear 2026 data", use_container_width=True):
            st.session_state["vals_2026"] = None
            st.rerun()

# ── main chart ─────────────────────────────────────────────────────────────────
vals_2026 = st.session_state["vals_2026"] or None
if vals_2026 is not None and not any(v is not None for v in vals_2026):
    vals_2026 = None  # treat empty list as no data

try:
    fig = build_figure(
        lat,
        lon,
        vals_2026=vals_2026,
    )
    st.plotly_chart(fig, use_container_width=True)
except FileNotFoundError as e:
    st.error(f"Tile not found for this location: {e}")
except Exception as e:
    st.exception(e)

# ── methodology note ───────────────────────────────────────────────────────────
with st.expander("Data & methodology"):
    st.markdown(
        """
**Data source:** ERA5 reanalysis, 2m air temperature (t2m), 0.25° grid.

| Period | Resolution | Storage |
|--------|-----------|---------|
| 1979–2025 | Monthly means | Packaged tile store |
| 2026 | Monthly means (optional, fetched on demand) | CDS API download |

**Monthly → smooth curve:** Cubic spline with 3-month wrap-around for full years;
simple spline for partial years (only draws between available months).

**Clickable map:** Snaps to the nearest 5° grid point. Use the number inputs for finer control.
"""
    )
