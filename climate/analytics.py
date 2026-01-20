import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

from climate.models import StoryFacts

# -----------------------------------------------------------
# Helpers to detect trends
# -----------------------------------------------------------


def estimate_30d_trend(dates: pd.DatetimeIndex, temps: np.ndarray) -> float:
    """
    Rough linear trend over the period, in °C per 30 days.
    Returns np.nan if not enough data.
    """
    if len(dates) < 5:
        return np.nan
    # x in days since start
    x = (dates - dates[0]).days.astype(float)
    y = np.asarray(temps, dtype="float64")
    if np.all(np.isnan(y)):
        return np.nan

    # Mask nans
    mask = ~np.isnan(y)
    if mask.sum() < 5:
        return np.nan

    x = x[mask]
    y = y[mask]

    # Simple linear fit
    slope, intercept = np.polyfit(x, y, 1)
    total_span_days = float(x[-1] - x[0]) if x[-1] != x[0] else 0.0
    if total_span_days <= 0:
        return 0.0

    # Trend over 30 days
    trend_30d = slope * 30.0
    return trend_30d


def season_phrase(lat: float, ref_date: pd.Timestamp) -> str:
    """
    Very rough seasonal label for storytelling purposes.
    """
    north = lat >= 0
    m = ref_date.month

    if north:
        if m in (12, 1, 2):
            return "mid-winter"
        elif m in (3, 4, 5):
            return "spring heading into summer"
        elif m in (6, 7, 8):
            return "mid-summer"
        else:  # 9,10,11
            return "autumn heading into winter"
    else:
        # Southern hemisphere seasons are flipped
        if m in (12, 1, 2):
            return "mid-summer"
        elif m in (3, 4, 5):
            return "autumn heading into winter"
        elif m in (6, 7, 8):
            return "mid-winter"
        else:  # 9,10,11
            return "spring heading into summer"


# -----------------------------------------------------------
# Compute global facts
# -----------------------------------------------------------


def compute_story_facts(ds, lat: Optional[float] = None) -> StoryFacts:
    """
    Derive a few high-level 'story' numbers from the yearly series.

    Uses:
      - t2m_yearly_mean_c  (dim: time_yearly)
    """
    da_year = ds["t2m_yearly_mean_c"]
    time_year = pd.to_datetime(ds["time_yearly"].values)
    years = time_year.year.astype(float)
    temps = np.asarray(da_year.values, dtype="float64")

    mask = np.isfinite(temps)
    if mask.sum() < 6:
        # Not enough data to say much, return mostly Nones
        return StoryFacts(
            data_start_year=int(years.min()),
            data_end_year=int(years.max()),
            total_warming_50y=None,
            recent_warming_10y=None,
            last_year_anomaly=None,
            hemisphere="north" if (lat or 0.0) >= 0 else "south",
        )

    x = years[mask]
    y = temps[mask]

    # Long-term trend over full record
    slope, intercept = np.polyfit(x, y, 1)
    trend = intercept + slope * x
    total_warming_50y = float(trend[-1] - trend[0])

    # "Recent" ~10-year trend, estimated over last ~20 years to reduce noise
    if len(x) >= 12:
        recent_window_start = x.max() - 20.0
        recent_mask = x >= recent_window_start
        xr = x[recent_mask]
        yr = y[recent_mask]
        if xr.size >= 6:
            s10, i10 = np.polyfit(xr, yr, 1)
            recent_warming_10y = float(s10 * 10.0)
        else:
            recent_warming_10y = None
    else:
        recent_warming_10y = None

    # Last-year anomaly vs a baseline (prefer 1981–2010 if available)
    base_mask = (x >= 1981.0) & (x <= 2010.0)
    if base_mask.sum() >= 10:
        baseline = float(y[base_mask].mean())
    else:
        baseline = float(y.mean())
    last_year_anomaly = float(y[-1] - baseline)

    # Hemisphere: from lat argument if given, else from dataset attrs, else default north
    if lat is None:
        lat_attr = ds.attrs.get("latitude", None)
        if lat_attr is not None:
            try:
                lat = float(lat_attr)
            except Exception:
                lat = 0.0
        else:
            lat = 0.0

    hemisphere = "north" if lat >= 0 else "south"

    return StoryFacts(
        data_start_year=int(x.min()),
        data_end_year=int(x.max()),
        total_warming_50y=total_warming_50y,
        recent_warming_10y=recent_warming_10y,
        last_year_anomaly=last_year_anomaly,
        hemisphere=hemisphere,
    )
