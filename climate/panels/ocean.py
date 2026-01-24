from __future__ import annotations

from pathlib import Path
from typing import Tuple, Optional, Dict

import numpy as np
import pandas as pd
import plotly.graph_objs as go
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from functools import lru_cache

import xarray as xr

from climate.models import StoryContext, StoryFacts
from climate.panels.helpers import add_trace, add_mean_trace
from climate.units import fmt_delta, convert_delta, fmt_unit

# --------------------------------------------------------------------------------------
# Cache helpers
# --------------------------------------------------------------------------------------

OCEAN_DATA_DIR = Path("data/story_ocean")


@lru_cache(maxsize=128)
def _open_ocean_cache(slug: str) -> xr.Dataset | None:
    """
    Load precomputed ocean cache:
      data/story_ocean/ocean_<slug>.nc

    Panels should not do network I/O. If missing, return None.
    """
    p = OCEAN_DATA_DIR / f"ocean_{slug}.nc"
    if not p.exists():
        return None
    return xr.open_dataset(p)


# --------------------------------------------------------------------------------------
# OISST (SST)
# --------------------------------------------------------------------------------------


def build_sst_anom_data(ctx: StoryContext) -> dict:
    """
    Load SST anomaly annual series from precomputed ocean cache.

    Requires:
      data/story_ocean/ocean_<slug>.nc
    """
    ds = _open_ocean_cache(ctx.slug)
    if ds is None or "sst_anom_year_c" not in ds:
        return {}

    years = ds["year"].values.astype(int)
    y = ds["sst_anom_year_c"].values.astype("float64")
    anom_year = pd.Series(y, index=years).sort_index()
    anom_year.name = "sst_anom_year_c"

    anom_5y = anom_year.rolling(window=5, center=True, min_periods=2).mean()
    anom_5y.name = "sst_anom_5y_c"

    baseline_years = (anom_year.index >= 1981) & (anom_year.index <= 1990)
    recent_years = (anom_year.index >= 2016) & (anom_year.index <= 2025)
    mean_81_90 = (
        float(np.nanmean(anom_year.loc[baseline_years].values))
        if baseline_years.any()
        else None
    )
    mean_16_25 = (
        float(np.nanmean(anom_year.loc[recent_years].values))
        if recent_years.any()
        else None
    )

    return {
        "anom_year_c": anom_year,
        "anom_5y_c": anom_5y,
        "mean_81_90_c": mean_81_90,
        "mean_16_25_c": mean_16_25,
    }


def build_sst_anom_figure(
    ctx: StoryContext, facts: StoryFacts, data: dict
) -> Tuple[go.Figure, str]:
    fig = go.Figure()

    y = data["anom_year_c"].astype("float64").values
    x = data["anom_year_c"].index.values

    y_local = np.asarray([convert_delta(v, ctx.unit) for v in y], dtype="float64")
    add_trace(
        fig,
        x=x,
        y=y_local,
        name="Annual mean anomaly",
        hovertemplate="Year %{x}<br>Anomaly: %{y:.2f}"
        + fmt_unit(ctx.unit)
        + "<extra></extra>",
    )

    y5 = data["anom_5y_c"].astype("float64").values
    y5_local = np.asarray([convert_delta(v, ctx.unit) for v in y5], dtype="float64")
    add_mean_trace(
        fig,
        x=x,
        y=y5_local,
        name="5-year mean",
        hovertemplate="Year %{x}<br>5y mean: %{y:.2f}"
        + fmt_unit(ctx.unit)
        + "<extra></extra>",
    )

    # Linear trend line (least squares) on annual mean anomaly
    x_num = np.asarray(x, dtype="float64")
    mask = np.isfinite(x_num) & np.isfinite(y_local)
    if mask.sum() >= 2:
        m, c = np.polyfit(x_num[mask], y_local[mask], 1)
        y_trend = m * x_num + c
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y_trend,
                mode="lines",
                name="Trend",
                line=dict(color="red", width=2),
                hovertemplate="Year %{x}<br>Trend: %{y:.2f}"
                + fmt_unit(ctx.unit)
                + "<extra></extra>",
            )
        )

    fig.update_layout(
        width=1350,
        height=350,
        margin=dict(l=70, r=30, t=30, b=30),
        showlegend=True,
        xaxis=dict(
            title="Year",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title=f"SST anomaly ({fmt_unit(ctx.unit)})",
            zeroline=True,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    tiny = "Source: NOAA OISST v2.1 (daily) via ERDDAP | Baseline: 1981–2010"
    return fig, tiny


def sst_anom_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    mean_81_90 = data.get("mean_81_90_c", None)
    mean_16_25 = data.get("mean_16_25_c", None)

    extra = ""
    if (mean_81_90 is not None) and (mean_16_25 is not None):
        delta = mean_16_25 - mean_81_90
        sign = "higher" if delta >= 0 else "lower"
        extra = (
            f"\n\nCompared to the 1980s, the 2016–2025 average sea-surface temperature "
            f"here is about **{fmt_delta(delta, ctx.unit, sign=False)} {sign}**."
        )

    return (
        "This chart shows **sea surface temperature (SST) anomaly** near this location, "
        "relative to a **1981–2010** baseline. Even small-looking shifts in the mean can "
        "translate into **much more frequent heat stress** for coral ecosystems."
        + extra
    )


def build_sst_hotdays_data(ctx: StoryContext) -> dict:
    """
    Load SST hot-days annual series from precomputed ocean cache.

    Requires:
      data/story_ocean/ocean_<slug>.nc
    """
    ds = _open_ocean_cache(ctx.slug)
    if ds is None or "sst_hotdays_p90_year" not in ds:
        return {}

    years = ds["year"].values.astype(int)
    y = ds["sst_hotdays_p90_year"].values.astype("float64")
    hot_days_year = pd.Series(y, index=years).sort_index()
    hot_days_year.name = "sst_hotdays_p90_year"

    hot_5y = hot_days_year.rolling(window=5, center=True, min_periods=2).mean()
    hot_5y.name = "sst_hotdays_5y"

    baseline_years = (hot_days_year.index >= 1981) & (hot_days_year.index <= 1990)
    recent_years = (hot_days_year.index >= 2016) & (hot_days_year.index <= 2025)
    mean_81_90 = (
        float(np.nanmean(hot_days_year.loc[baseline_years].values))
        if baseline_years.any()
        else None
    )
    mean_16_25 = (
        float(np.nanmean(hot_days_year.loc[recent_years].values))
        if recent_years.any()
        else None
    )

    return {
        "hot_days_year": hot_days_year,
        "hot_days_5y": hot_5y,
        "mean_81_90": mean_81_90,
        "mean_16_25": mean_16_25,
    }


def build_sst_hotdays_figure(
    ctx: StoryContext, facts: StoryFacts, data: dict
) -> Tuple[go.Figure, str]:
    fig = go.Figure()

    x = data["hot_days_year"].index.values
    y = data["hot_days_year"].astype("float64").values

    # Bars for annual counts
    fig.add_trace(
        go.Bar(
            x=x,
            y=y,
            name="Hot days (baseline P90)",
            marker=dict(color="#FF7F7F"),
            hovertemplate="Year %{x}<br>Hot days: %{y:.0f}<extra></extra>",
        )
    )

    # 5-year mean as a line on top
    y5 = data["hot_days_5y"].astype("float64").values
    add_mean_trace(
        fig,
        x=x,
        y=y5,
        name="5-year mean",
        hovertemplate="Year %{x}<br>5y mean: %{y:.1f}<extra></extra>",
    )

    fig.update_layout(
        width=1350,
        height=350,
        margin=dict(l=70, r=30, t=30, b=30),
        showlegend=True,
        barmode="overlay",
        xaxis=dict(
            title="Year",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title="Days / year",
            range=[0, 365],
            zeroline=False,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    tiny = "Source: NOAA OISST v2.1 (daily) via ERDDAP | Hot day threshold: baseline P90 (1981–2010)"
    return fig, tiny


def sst_hotdays_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    mean_81_90 = data.get("mean_81_90", None)
    mean_16_25 = data.get("mean_16_25", None)

    extra = ""
    if (mean_81_90 is not None) and (mean_16_25 is not None):
        extra = (
            f"\n\nIn the 1980s this location averaged about **{mean_81_90:.1f}** hot days/year. "
            f"From 2016–2025 it’s closer to **{mean_16_25:.1f}** hot days/year."
        )

    return (
        "Averages don’t tell the whole story: ecosystems respond strongly to **extreme days**.\n\n"
        "This chart counts **SST ‘hot days’**: days when the ocean is warmer than the **90th percentile** "
        "of the 1981–2010 baseline for the same time of year." + extra
    )


# --------------------------------------------------------------------------------------
# Coral Reef Watch DHW
# --------------------------------------------------------------------------------------


def build_dhw_data(ctx: StoryContext) -> dict:
    """
    Load DHW annual series from precomputed ocean cache.

    Requires:
      data/story_ocean/ocean_<slug>.nc
    """
    ds = _open_ocean_cache(ctx.slug)
    if ds is None or "dhw_max_year" not in ds:
        return {}

    years = ds["year"].values.astype(int)

    dhw_max = pd.Series(
        ds["dhw_max_year"].values.astype("float64"), index=years
    ).sort_index()
    dhw_ge4 = pd.Series(
        ds["dhw_ge4_days_year"].values.astype("float64"), index=years
    ).sort_index()
    dhw_ge8 = pd.Series(
        ds["dhw_ge8_days_year"].values.astype("float64"), index=years
    ).sort_index()

    dhw_max.name = "dhw_max_year"
    dhw_ge4.name = "dhw_ge4_days_year"
    dhw_ge8.name = "dhw_ge8_days_year"

    recent_years = (dhw_max.index >= 2016) & (dhw_max.index <= 2025)
    base_years = (dhw_max.index >= 1985) & (dhw_max.index <= 1994)

    dhw_max_85_94 = (
        float(np.nanmean(dhw_max.loc[base_years].values)) if base_years.any() else None
    )
    dhw_max_16_25 = (
        float(np.nanmean(dhw_max.loc[recent_years].values))
        if recent_years.any()
        else None
    )
    ge8_16_25 = (
        float(np.nanmean(dhw_ge8.loc[recent_years].values))
        if recent_years.any()
        else None
    )

    box_deg = float(ds.attrs.get("dhw_box_half_deg", 0.05))

    return {
        "dhw_max": dhw_max,
        "dhw_ge4_days": dhw_ge4,
        "dhw_ge8_days": dhw_ge8,
        "dhw_max_85_94": dhw_max_85_94,
        "dhw_max_16_25": dhw_max_16_25,
        "dhw_ge8_days_16_25": ge8_16_25,
        "box_deg": box_deg,
    }


def _build_dhw_bars(
    *,
    x: np.ndarray,
    y_ok: np.ndarray,
    y_mod: np.ndarray,
    y8: np.ndarray,
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x,
            y=y_ok,
            name="No risk (< 4)",
            marker=dict(color="#88E788"),
            hovertemplate="Year=%{x}<br>No risk days=%{y:.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=x,
            y=y_mod,
            name="Moderate (4–8)",
            marker=dict(color="#FFD166"),
            hovertemplate="Year=%{x}<br>Moderate days=%{y:.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=x,
            y=y8,
            name="High (≥ 8)",
            marker=dict(color="#EF476F"),
            hovertemplate="Year=%{x}<br>High days=%{y:.0f}<extra></extra>",
        )
    )
    return fig


def _dhw_tiny(data: dict) -> str:
    box_deg = data.get("box_deg", 0.05)
    return (
        f"Source: NOAA Coral Reef Watch DHW (daily) via ERDDAP | "
        f"Box mean: ±{box_deg:.2f}° | Thresholds: 4 and 8"
    )


def build_dhw_figure(
    ctx: StoryContext, facts: StoryFacts, data: dict
) -> Tuple[go.Figure, str]:
    """
    Bars-only DHW panel (default view).
    """
    x = data["dhw_ge4_days"].index.values

    y4 = data["dhw_ge4_days"].astype("float64").values
    y8 = data["dhw_ge8_days"].astype("float64").values

    # Moderate-only (avoid double-counting)
    y_mod = np.clip(y4 - y8, 0, None)

    # No-risk days (fill to 365 for strong visual)
    y_ok = np.clip(365.0 - y4, 0, 365)

    fig = _build_dhw_bars(x=x, y_ok=y_ok, y_mod=y_mod, y8=y8)

    fig.update_layout(
        width=1350,
        height=510,
        margin=dict(l=50, r=30, t=80, b=30),
        barmode="stack",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(title="Year", showgrid=False),
        yaxis=dict(
            title="Days / year",
            range=[0, 365],
            zeroline=False,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    return fig, _dhw_tiny(data)


def build_dhw_figure_with_trend(
    ctx: StoryContext, facts: StoryFacts, data: dict
) -> Tuple[go.Figure, str]:
    """
    Dual-axis variant (bars + annual max DHW line).
    """
    x = data["dhw_ge4_days"].index.values

    y4 = data["dhw_ge4_days"].astype("float64").values
    y8 = data["dhw_ge8_days"].astype("float64").values
    y_max = data["dhw_max"].astype("float64").values

    y_mod = np.clip(y4 - y8, 0, None)
    y_ok = np.clip(365.0 - y4, 0, 365)

    fig = _build_dhw_bars(x=x, y_ok=y_ok, y_mod=y_mod, y8=y8)

    # Overlay: annual max DHW line (right axis)
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y_max,
            name="Max DHW",
            mode="lines",
            line=dict(color="white", width=2),
            yaxis="y2",
            hovertemplate="Year=%{x}<br>Max DHW=%{y:.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        width=1350,
        height=510,
        margin=dict(l=50, r=30, t=80, b=30),
        barmode="stack",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(title="Year", showgrid=False),
        yaxis=dict(
            title="Days / year",
            range=[0, 365],
            zeroline=False,
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis2=dict(
            title="Max DHW",
            overlaying="y",
            side="right",
            showgrid=False,
            rangemode="tozero",
        ),
    )

    return fig, _dhw_tiny(data)


# --------------------------------------------------------------------------------------
# DHW daily heatmap (Design 2)
# --------------------------------------------------------------------------------------


def _dhw_heatmap_cmap() -> LinearSegmentedColormap:
    # Green -> Yellow -> Orange -> Red
    return LinearSegmentedColormap.from_list(
        "dhw_gyr",
        [
            (0.00, "#2e7d32"),  # green
            (0.35, "#cddc39"),  # yellow-green
            (0.55, "#ffeb3b"),  # yellow
            (0.75, "#ff9800"),  # orange
            (1.00, "#d32f2f"),  # red
        ],
    )


class _JumpNorm(Normalize):
    """
    Piecewise linear normalization with visible 'jumps' at 4 and 8 DHW.

      0..4   -> 0.00..0.45
      4..8   -> 0.55..0.80   (gap => jump at 4)
      8..16  -> 0.86..1.00   (gap => jump at 8)
    """

    def __init__(self, vmin: float = 0.0, vmax: float = 16.0, clip: bool = False):
        super().__init__(vmin=vmin, vmax=vmax, clip=clip)

    def __call__(self, value, clip=None):
        v = np.asarray(value, dtype=float)
        v = np.clip(v, self.vmin, self.vmax)

        out = np.empty_like(v, dtype=float)

        m1 = v <= 4.0
        out[m1] = 0.00 + (v[m1] / 4.0) * 0.45

        m2 = (v > 4.0) & (v <= 8.0)
        out[m2] = 0.55 + ((v[m2] - 4.0) / 4.0) * (0.80 - 0.55)

        m3 = v > 8.0
        out[m3] = 0.86 + ((v[m3] - 8.0) / 8.0) * (1.00 - 0.86)

        return out


def _find_dhw_daily_var(ds: xr.Dataset) -> Optional[str]:
    if "dhw_daily" in ds:
        return "dhw_daily"
    if "degree_heating_week" in ds and "time" in ds["degree_heating_week"].dims:
        return "degree_heating_week"

    for name, da in ds.data_vars.items():
        if "time" in da.dims and ("dhw" in name.lower() or "heating" in name.lower()):
            return name
    return None


def _build_dhw_daily_matrix(ds: xr.Dataset) -> Optional[Dict[str, object]]:
    var = _find_dhw_daily_var(ds)
    if var is None:
        return None

    da = ds[var]
    if "time" not in da.dims:
        return None

    t = pd.DatetimeIndex(da["time"].values)
    s = pd.Series(da.values.astype("float32"), index=t).sort_index()

    # Drop Feb 29 (keep 365-day matrix)
    s = s[~((s.index.month == 2) & (s.index.day == 29))]

    years = np.arange(int(s.index.year.min()), int(s.index.year.max()) + 1, dtype=int)
    mat = np.full((len(years), 365), np.nan, dtype=np.float32)

    for yi, y in enumerate(years):
        sy = s[s.index.year == y]
        if sy.empty:
            continue

        doy = sy.index.dayofyear.values.astype(int)
        if pd.Timestamp(f"{y}-12-31").is_leap_year:
            doy = doy.copy()
            doy[doy > 59] -= 1  # shift after Feb 28 back by 1

        mask = (doy >= 1) & (doy <= 365)
        mat[yi, doy[mask] - 1] = sy.values[mask]

    return {"years": years, "mat": mat, "var": var}


def build_dhw_heatmap_figure(
    ctx: StoryContext,
    facts: StoryFacts,
    data: dict,
    *,
    vmax: float = 16.0,
    use_threshold_jumps: bool = True,
    with_axes: bool = True,
    transparent: bool = True,
) -> Tuple[Optional[plt.Figure], str]:
    """
    Design 2 heatmap: years on Y, day-of-year on X.

    Returns (fig_or_None, tiny).
    """
    ds = _open_ocean_cache(ctx.slug)
    if ds is None:
        return None, _dhw_tiny(data)

    m = _build_dhw_daily_matrix(ds)
    if not m:
        return None, _dhw_tiny(data)

    years = m["years"]
    mat = m["mat"]

    cmap = _dhw_heatmap_cmap()
    norm = (
        _JumpNorm(vmin=0.0, vmax=vmax)
        if use_threshold_jumps
        else Normalize(vmin=0.0, vmax=vmax)
    )

    fig = plt.figure(figsize=(12.5, 5.2))
    ax = fig.add_axes([0.06, 0.12, 0.88, 0.80])
    ax.imshow(mat, aspect="auto", interpolation="nearest", cmap=cmap, norm=norm)

    if transparent:
        fig.patch.set_alpha(0.0)
        ax.set_facecolor("none")

    if with_axes:
        ax.set_title(f"DHW daily heatmap — {ctx.location_label}", fontsize=12, pad=10)
        ax.set_ylabel("Year")
        ax.set_xlabel("Day of year")

        yt = np.linspace(0, len(years) - 1, 9).round().astype(int)
        ax.set_yticks(yt)
        ax.set_yticklabels(years[yt])

        ax.set_xticks([0, 59, 120, 181, 243, 304, 364])
        ax.set_xticklabels(["Jan", "Mar", "May", "Jul", "Sep", "Nov", "Dec"])
    else:
        ax.set_axis_off()

    return fig, _dhw_tiny(data)


def build_ocean_context_map_figure(ctx: StoryContext, facts: StoryFacts, data: dict):
    """
    Unit-agnostic context map for ocean panels (Matplotlib + Cartopy).

    Draws:
      - land/ocean + coastline (Natural Earth, 10m)
      - city marker
      - red DHW box (± dhw_box_half_deg)

    Returns a Matplotlib Figure (SVG-export friendly).
    """
    lat = float(ctx.location_lat)
    lon = float(ctx.location_lon)

    box_half = data.get("dhw_box_half_deg", None)
    if box_half is None:
        box_half = data.get("box_deg", 0.05)
    box_half = float(box_half)

    # Local extent: show coastline context but keep the DHW box readable.
    span = max(0.35, box_half * 6.0)  # degrees
    lat0, lat1 = lat - span, lat + span
    lon0, lon1 = lon - span, lon + span

    # DHW box polygon (closed ring)
    box_lons = [
        lon - box_half,
        lon + box_half,
        lon + box_half,
        lon - box_half,
        lon - box_half,
    ]
    box_lats = [
        lat - box_half,
        lat - box_half,
        lat + box_half,
        lat + box_half,
        lat - box_half,
    ]

    fig = plt.figure(figsize=(5.2, 5.2), dpi=150)
    ax = plt.axes(projection=ccrs.Mercator())

    ax.set_extent([lon0, lon1, lat0, lat1], crs=ccrs.PlateCarree())

    # Background (keep it simple + export-friendly)
    ax.add_feature(
        cfeature.OCEAN.with_scale("10m"),
        facecolor=(214 / 255, 230 / 255, 245 / 255),
        edgecolor="none",
    )
    ax.add_feature(
        cfeature.LAND.with_scale("10m"),
        facecolor=(240 / 255, 240 / 255, 240 / 255),
        edgecolor="none",
    )

    # Coastline (high-res for small islands)
    ax.coastlines(resolution="10m", color=(80 / 255, 80 / 255, 80 / 255), linewidth=0.8)

    # DHW box fill + outline
    ax.fill(
        box_lons,
        box_lats,
        transform=ccrs.PlateCarree(),
        facecolor=(220 / 255, 0, 0, 0.18),
        edgecolor=(220 / 255, 0, 0, 0.85),
        linewidth=1.6,
        zorder=5,
    )

    # City marker
    ax.scatter(
        [lon],
        [lat],
        transform=ccrs.PlateCarree(),
        s=35,
        color=(0.1, 0.1, 0.1, 0.95),
        zorder=6,
    )

    # City name
    ax.text(
        lon + span * 0.03,
        lat + span * 0.02,
        ctx.city_name,
        transform=ccrs.PlateCarree(),
        fontsize=9,
        color=(0.1, 0.1, 0.1, 0.95),
        zorder=7,
    )

    # Clean frame
    ax.set_axis_off()
    fig.tight_layout(pad=0)

    tiny = "Context map: Natural Earth 10m coastline + DHW box"
    return fig, tiny


def build_ocean_sst_map_figure(ctx: StoryContext, facts: StoryFacts, data: dict):
    """
    Unit-agnostic SST anomaly map (Matplotlib + Cartopy), built from cached gridded data
    stored in data/story_ocean/ocean_<slug>.nc.

    Requires variables:
      - sst_map_recent_anom_c (sst_lat, sst_lon)
      - coords: sst_lat, sst_lon
    """
    ds = _open_ocean_cache(ctx.slug)
    if ds is None or "sst_map_recent_anom_c" not in ds:
        return None, ""

    if "sst_lat" not in ds.coords or "sst_lon" not in ds.coords:
        return None, ""

    lat = float(ctx.location_lat)
    lon = float(ctx.location_lon)

    # Quick iteration knobs (plot-time crop, no re-fetch needed)
    # Using "cells" avoids the "mask < 2 points" problem when cached grid is coarse.
    SST_MAP_HALF_CELLS = 2  # 3 => (2*3+1)=7 cells across; try 2,3,4,6

    lats = ds["sst_lat"].values.astype("float64")
    lons = ds["sst_lon"].values.astype("float64")
    anom = ds["sst_map_recent_anom_c"].values.astype("float64")

    # Find nearest grid index to the city and take a window of cells around it
    i0 = int(np.nanargmin(np.abs(lats - lat)))
    j0 = int(np.nanargmin(np.abs(lons - lon)))

    i_min = max(0, i0 - SST_MAP_HALF_CELLS)
    i_max = min(len(lats), i0 + SST_MAP_HALF_CELLS + 1)
    j_min = max(0, j0 - SST_MAP_HALF_CELLS)
    j_max = min(len(lons), j0 + SST_MAP_HALF_CELLS + 1)

    lats = lats[i_min:i_max]
    lons = lons[j_min:j_max]
    anom = anom[i_min:i_max, j_min:j_max]

    lon0, lon1 = float(np.nanmin(lons)), float(np.nanmax(lons))
    lat0, lat1 = float(np.nanmin(lats)), float(np.nanmax(lats))

    v = anom[np.isfinite(anom)]
    if v.size == 0:
        return None, ""

    vmax = float(np.nanpercentile(np.abs(v), 95))
    vmax = max(0.25, vmax)

    fig = plt.figure(figsize=(5.2, 5.2), dpi=150)
    ax = plt.axes(projection=ccrs.Mercator())
    ax.set_extent([lon0, lon1, lat0, lat1], crs=ccrs.PlateCarree())

    ax.add_feature(
        cfeature.OCEAN.with_scale("10m"),
        facecolor=(214 / 255, 230 / 255, 245 / 255),
        edgecolor="none",
        zorder=0,
    )

    # Field first
    mesh = ax.pcolormesh(
        lons,
        lats,
        anom,
        transform=ccrs.PlateCarree(),
        shading="auto",
        cmap="RdBu_r",
        vmin=-vmax,
        vmax=vmax,
        zorder=1,
    )
    # Then land on top to visually mask inland pixels
    ax.add_feature(
        cfeature.LAND.with_scale("10m"),
        facecolor=(0.92, 0.92, 0.92, 1.0),
        edgecolor="none",
        zorder=2,
    )
    # Coastlines on top
    ax.coastlines(
        resolution="10m", color=(0.25, 0.25, 0.25, 1.0), linewidth=1.0, zorder=3
    )

    ax.scatter(
        [lon],
        [lat],
        transform=ccrs.PlateCarree(),
        s=28,
        color=(0.1, 0.1, 0.1, 0.95),
        zorder=4,
    )

    b0 = ds.attrs.get("sst_map_baseline_start", "1981-01-01")
    b1 = ds.attrs.get("sst_map_baseline_end", "2010-12-31")
    r0 = ds.attrs.get("sst_map_recent_start", "2016-01-01")
    r1 = ds.attrs.get("sst_map_recent_end", "")

    title = (
        f"SST anomaly ({fmt_unit(ctx.unit)})\n{r0}–{r1} vs {b0}–{b1}"
        if r1
        else f"SST anomaly ({fmt_unit(ctx.unit)})\n{r0}–… vs {b0}–{b1}"
    )

    # Put this in the left margin (acts like a legend block)
    fig.text(
        0.04,
        0.915,
        title,
        ha="left",
        va="top",
        fontsize=10,
        bbox=dict(
            facecolor="white", edgecolor="none", alpha=0.85, boxstyle="round,pad=0.35"
        ),
    )

    # Reserve right margin for the colorbar (tight_layout() fights manual cax placement)
    ax.set_axis_off()
    fig.subplots_adjust(left=0.02, right=0.84, top=0.98, bottom=0.02)

    # Colorbar further to the right
    cax = fig.add_axes([0.87, 0.18, 0.04, 0.64])
    cax.set_facecolor("white")

    cb = fig.colorbar(mesh, cax=cax)
    cb.ax.tick_params(labelsize=9, colors="black")
    cb.outline.set_edgecolor("black")

    tiny = "SST anomaly map: NOAA OISST v2.1 via ERDDAP (sampled) | recent mean minus baseline mean"
    return fig, tiny


def dhw_caption(ctx: StoryContext, facts: StoryFacts, data: dict) -> str:
    max_85_94 = data.get("dhw_max_85_94", None)
    max_16_25 = data.get("dhw_max_16_25", None)
    ge8_16_25 = data.get("dhw_ge8_days_16_25", None)

    extra = ""
    if (max_85_94 is not None) and (max_16_25 is not None):
        extra += (
            f"\n\nAverage annual **max DHW** rose from about **{max_85_94:.2f}** (1985–1994) "
            f"to **{max_16_25:.2f}** (2016–2025)."
        )
    if ge8_16_25 is not None:
        extra += f"\n\nIn 2016–2025 there were about **{ge8_16_25:.1f} days/year** with **DHW ≥ 8**."

    return (
        "Corals are stressed by **cumulative marine heat**.\n\n"
        "**Degree Heating Weeks (DHW)** is a widely used indicator of accumulated heat stress that correlates with "
        "bleaching risk. Here we show the **annual max DHW**, plus how many days each year exceeded "
        "moderate (**≥ 4**) and severe (**≥ 8**) stress thresholds." + extra
    )
