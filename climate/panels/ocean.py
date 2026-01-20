from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
import plotly.graph_objs as go
import matplotlib.pyplot as plt
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


def build_dhw_figure(
    ctx: StoryContext, facts: StoryFacts, data: dict
) -> Tuple[go.Figure, str]:
    fig = go.Figure()

    x = data["dhw_ge4_days"].index.values

    y4 = data["dhw_ge4_days"].astype("float64").values
    y8 = data["dhw_ge8_days"].astype("float64").values
    y_max = data["dhw_max"].astype("float64").values

    # Moderate-only (avoid double-counting)
    y_mod = y4 - y8
    y_mod = np.clip(y_mod, 0, None)

    # No-risk days (fill to 365 for strong visual)
    y_ok = 365.0 - y4
    y_ok = np.clip(y_ok, 0, 365)

    fig.add_trace(
        go.Bar(
            x=x,
            y=y_ok,
            name="No risk (< 4)",
            marker=dict(color="#88E788"),
            customdata=y_max,
            hovertemplate="Year %{x}<br>No risk: %{y:.0f}<br>Max DHW: %{customdata:.2f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            x=x,
            y=y_mod,
            name="Moderate (4–8)",
            marker=dict(color="#FFAD00"),
            customdata=y_max,
            hovertemplate="Year %{x}<br>Moderate (4–8): %{y:.0f}<br>Max DHW: %{customdata:.2f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            x=x,
            y=y8,
            name="Severe (≥ 8)",
            marker=dict(color="#F01E2C"),
            customdata=y_max,
            hovertemplate="Year %{x}<br>Severe (≥ 8): %{y:.0f}<br>Max DHW: %{customdata:.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        width=1350,
        height=350,
        margin=dict(l=70, r=30, t=30, b=30),
        showlegend=True,
        barmode="stack",
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

    box_deg = data.get("box_deg", 0.05)
    tiny = f"Source: NOAA Coral Reef Watch DHW (daily) via ERDDAP | Box mean: ±{box_deg:.2f}° | Thresholds: 4 and 8"
    return fig, tiny


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
