import glob
import os
from pathlib import Path
import xarray as xr
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from datetime import date, datetime, timedelta
import requests
import folium
from dataclasses import dataclass
from typing import Optional
from streamlit_folium import st_folium

st.set_page_config(page_title="Your Climate Story", layout="wide")

DATA_DIR = Path("story_climatology")


# -----------------------------------------------------------
# Helpers to load precomputed caches
# -----------------------------------------------------------

def discover_locations(clim_dir: str = "story_climatology") -> dict:
    """
    Scan story_climatology/clim_*.nc and build a dict:
      slug -> {slug, label, lat, lon, path}
    Expects precompute_story_cities.py to have stored latitude/longitude and
    optional city_name/country_name in ds.attrs.
    """
    locations = {}
    pattern = os.path.join(clim_dir, "clim_*.nc")
    for path in glob.glob(pattern):
        fname = os.path.basename(path)
        # "clim_<slug>.nc" -> <slug>
        if not fname.startswith("clim_") or not fname.endswith(".nc"):
            continue
        slug = fname[len("clim_") : -len(".nc")]

        try:
            ds_meta = xr.open_dataset(path)
            city_name = ds_meta.attrs.get("name_short", slug)
            country_name = ds_meta.attrs.get("country", "")
            lat_attr = ds_meta.attrs.get("latitude", np.nan)
            lon_attr = ds_meta.attrs.get("longitude", np.nan)
            lat = float(lat_attr) if lat_attr is not None else np.nan
            lon = float(lon_attr) if lon_attr is not None else np.nan
            ds_meta.close()
        except Exception:
            city_name = slug
            country_name = ""
            lat = np.nan
            lon = np.nan

        if country_name:
            label = f"{city_name}, {country_name}"
        else:
            label = city_name

        locations[slug] = {
            "slug": slug,
            "label": label,
            "lat": lat,
            "lon": lon,
            "path": path,
        }

    return locations

@st.cache_data
def load_city_climatology(slug: str) -> xr.Dataset:
    """Load precomputed climatology NetCDF for a given location slug."""
    path = DATA_DIR / f"clim_{slug}.nc"
    ds = xr.load_dataset(path)
    return ds

def dataset_coverage_text(ds: xr.Dataset) -> str:
    """Return a short caption like 'Data from 1979 to Sep 2025'."""
    start_year = ds.attrs.get("start_year")
    end_str = ds.attrs.get("data_end_date")

    if not start_year or not end_str:
        return ""

    try:
        end_date = datetime.fromisoformat(str(end_str)).date()
    except Exception:
        # Fallback if the date is weird, but don't crash the UI
        return f"Data starting {start_year}"

    # Example: "Sep 2025"
    end_label = end_date.strftime("%b %Y")
    return f"Range: {start_year} - {end_label}"


# -----------------------------------------------------------
# Helpers to fetch recent data from OpenMeteo
# -----------------------------------------------------------

@st.cache_data(show_spinner=False)
def fetch_recent_7d(slug: str, lat: float, lon: float, end_date_str: str) -> xr.Dataset:
    """
    Fetch last 7 full days of hourly + daily temps from Open-Meteo ERA5 archive.
    end_date_str is ISO string of the last full day included (YYYY-MM-DD).
    Cached per (slug, end_date_str).
    """
    end_date = date.fromisoformat(end_date_str)
    start_date = end_date - timedelta(days=6)

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ["temperature_2m"],
        "daily": ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "auto",
    }
    url = "https://archive-api.open-meteo.com/v1/era5"

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    j = r.json()

    # Hourly
    h = j["hourly"]
    t_h = pd.to_datetime(h["time"])
    temp_h = np.array(h["temperature_2m"], dtype="float32")

    # Daily
    d = j["daily"]
    t_d = pd.to_datetime(d["time"])
    tmean_d = np.array(d["temperature_2m_mean"], dtype="float32")
    tmax_d = np.array(d["temperature_2m_max"], dtype="float32")
    tmin_d = np.array(d["temperature_2m_min"], dtype="float32")

    ds = xr.Dataset(
        data_vars=dict(
            t_hourly=("time_hourly", temp_h),
            t_daily_mean=("time_daily", tmean_d),
            t_daily_max=("time_daily", tmax_d),
            t_daily_min=("time_daily", tmin_d),
        ),
        coords=dict(
            time_hourly=("time_hourly", t_h),
            time_daily=("time_daily", t_d),
        ),
        attrs={"range": f"{start_date.isoformat()} to {end_date.isoformat()}"},
    )
    return ds


@st.cache_data(show_spinner=False)
def fetch_recent_30d(slug: str, lat: float, lon: float, end_date_str: str) -> xr.Dataset:
    """
    Fetch last 30 full days of daily temps from Open-Meteo ERA5 archive.
    Cached per (slug, end_date_str).
    """
    end_date = date.fromisoformat(end_date_str)
    start_date = end_date - timedelta(days=29)

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "auto",
    }
    url = "https://archive-api.open-meteo.com/v1/era5"

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    j = r.json()

    d = j["daily"]
    t_d = pd.to_datetime(d["time"])
    tmean_d = np.array(d["temperature_2m_mean"], dtype="float32")
    tmax_d = np.array(d["temperature_2m_max"], dtype="float32")
    tmin_d = np.array(d["temperature_2m_min"], dtype="float32")

    ds = xr.Dataset(
        data_vars=dict(
            t_daily_mean=("time_daily", tmean_d),
            t_daily_max=("time_daily", tmax_d),
            t_daily_min=("time_daily", tmin_d),
        ),
        coords=dict(
            time_daily=("time_daily", t_d),
        ),
        attrs={"range": f"{start_date.isoformat()} to {end_date.isoformat()}"},
    )
    return ds


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
# Small helper: annotate min/max on a curve
# -----------------------------------------------------------

def add_trace(figure, x, y, name, hovertemplate=""): 
    """
    Add trace to figure.
    """
    figure.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name=name,
            line=dict(color="rgba(180,180,180,0.7)", width=1.5, shape="spline"),
            marker=dict(size=3),
            hovertemplate=hovertemplate,
        )
    )

def add_mean_trace(figure, x, y, name, showmarkers=False, hovertemplate=""): 
    """
    Add mean trace to figure.
    """
    figure.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers" if showmarkers else "lines",
                name=name,
                line=dict(
                    color="rgba(38,139,210,0.9)",
                    width=3,
                    shape="spline",
                ),
                hovertemplate=hovertemplate,
            )
        )

def annotate_minmax_on_series(fig, x, y, label_prefix=""):
    """
    Add text labels for min and max along a given series, and return (min_val, max_val).
    """
    y_arr = np.asarray(y)
    if y_arr.size == 0:
        return None, None

    idx_min = int(y_arr.argmin())
    idx_max = int(y_arr.argmax())
    min_val = float(y_arr[idx_min])
    max_val = float(y_arr[idx_max])
    x_min = x[idx_min]
    x_max = x[idx_max]

    # Min annotation
    if idx_min <= len(y_arr) / 10:
        shift_min_x = 40
    else:
        shift_min_x = -40
    fig.add_annotation(
        x=x_min,
        y=min_val,
        xref="x",
        yref="y",
        text=f"{label_prefix}min {min_val:.1f}°C",
        showarrow=True,
        arrowhead=2,
        ax=shift_min_x,
        ay=30,
        font=dict(color="rgba(38,139,210,1.0)", size=13),
        arrowcolor="rgba(38,139,210,0.9)",
    )

    # Max annotation
    if idx_max >= len(y_arr) * 0.9:
        shift_max_x = -40
    else:
        shift_max_x = 40
    fig.add_annotation(
        x=x_max,
        y=max_val,
        xref="x",
        yref="y",
        text=f"{label_prefix}max {max_val:.1f}°C",
        showarrow=True,
        arrowhead=2,
        ax=shift_max_x,
        ay=-30,
        font=dict(color="rgba(220,50,47,1.0)", size=13),
        arrowcolor="rgba(220,50,47,0.9)",
    )
    
    return min_val, max_val

def last_n_days(series: pd.Series, n: int):
    if series.empty:
        return series
    cutoff = series.index.max() - pd.Timedelta(days=n)
    return series.loc[series.index >= cutoff]

# -----------------------------------------------------------
# Compute global facts
# -----------------------------------------------------------

@dataclass
class StoryFacts:
    data_start_year: int
    data_end_year: int
    total_warming_50y: Optional[float]
    recent_warming_10y: Optional[float]
    last_year_anomaly: Optional[float]
    hemisphere: str


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

# -----------------------------------------------------------
# 1. Fake data generator (we'll later replace with real data)
# -----------------------------------------------------------

def make_fake_daily_series(
    years: int = 50,
    baseline: float = 23.0,
    trend_per_decade: float = 0.3,
    noise: float = 1.0,
) -> pd.Series:
    """
    Return a DAILY time series over `years` with:
    - a simple seasonal cycle
    - a linear warming trend
    """
    days = years * 365
    start_date = datetime(1975, 1, 1)
    time = pd.date_range(start_date, periods=days, freq="D")
    t = np.arange(days)

    # Seasonal cycle
    seasonal = 5.0 * np.sin(2 * np.pi * t / 365.0 - 0.5)

    # Linear warming trend (°C per decade)
    trend = trend_per_decade / 10.0 * (t / 365.0)

    data = baseline + seasonal + trend + np.random.normal(0.0, noise, size=days)
    return pd.Series(data, index=time, name="temp")


def make_fake_hourly_from_daily(daily: pd.Series) -> pd.Series:
    """
    Build a HOURLY series from a daily mean series, adding a diurnal cycle.

    This is just for demo purposes. For real data we would query hourly ERA5
    directly and derive daily means/min/max.
    """
    # Hourly index spanning the same date range
    start = daily.index[0]
    end = daily.index[-1] + pd.Timedelta(days=1) - pd.Timedelta(hours=1)
    hourly_index = pd.date_range(start, end, freq="h")

    # Interpolate daily mean onto hourly grid
    x_daily = daily.index.view("int64")
    x_hourly = hourly_index.view("int64")
    base = np.interp(x_hourly, x_daily, daily.values)

    # Add a simple diurnal cycle (max mid-afternoon, min pre-dawn)
    hours = np.arange(len(hourly_index))
    hour_of_day = hours % 24
    diurnal = 4.0 * np.sin(2 * np.pi * (hour_of_day - 15) / 24.0)  # peak ~15:00

    # Small extra noise
    noise = np.random.normal(0.0, 0.5, size=len(hourly_index))

    data = base + diurnal + noise
    return pd.Series(data, index=hourly_index, name="temp_hourly")


def fake_local_and_global(location: str = "mauritius"):
    """
    Provide fake 'local' and 'global' daily series,
    plus precomputed annual & monthly means and anomalies.
    """
    if location == "mauritius":
        baseline = 24.0
        trend = 0.35  # °C / decade
    else:  # london
        baseline = 11.0
        trend = 0.25

    # Local daily series
    local_daily = make_fake_daily_series(baseline=baseline, trend_per_decade=trend)

    # A fake global series with smaller warming
    global_daily = make_fake_daily_series(
        baseline=14.0, trend_per_decade=0.2, noise=0.7
    )

    # Local hourly series for recent weeks/months
    local_hourly = make_fake_hourly_from_daily(local_daily)

    # Aggregate to monthly and yearly means
    local_monthly = local_daily.resample("MS").mean()
    global_monthly = global_daily.resample("MS").mean()

    local_yearly = local_daily.resample("YS").mean()
    global_yearly = global_daily.resample("YS").mean()

    # anomalies vs 1979–1990 mean (roughly a "pre-warming" baseline)
    ref_period = slice("1979-01-01", "1990-12-31")
    local_ref = local_monthly[ref_period].mean()
    global_ref = global_monthly[ref_period].mean()

    local_anom = local_monthly - local_ref
    global_anom = global_monthly - global_ref

    return {
        "local_daily": local_daily,
        "local_hourly": local_hourly,
        "global_daily": global_daily,
        "local_monthly": local_monthly,
        "global_monthly": global_monthly,
        "local_yearly": local_yearly,
        "global_yearly": global_yearly,
        "local_anom": local_anom,
        "global_anom": global_anom,
        "local_ref": float(local_ref),
        "global_ref": float(global_ref),
    }


# -----------------------------------------------------------
# 2. Sidebar: location + stepper
# -----------------------------------------------------------

# Discover all available locations from precomputed files
LOCATIONS = discover_locations(clim_dir=DATA_DIR)

if not LOCATIONS:
    st.error("No climatology files found in story_climatology/. "
             "Run precompute_story_cities.py first.")
    st.stop()

# Sort slugs to have stable ordering
slug_list = sorted(LOCATIONS.keys())
labels = [LOCATIONS[s]["label"] for s in slug_list]

# Optional: if you still want a default slug, keep this
DEFAULT_SLUG = "city_mu_port_louis"

default_index = 0
if DEFAULT_SLUG in slug_list:
    default_index = slug_list.index(DEFAULT_SLUG)

with st.sidebar:
    st.header("Location")
    chosen_label = st.radio(
        "Choose a city:",
        options=labels,
        index=default_index,
    )

    st.subheader("Story step")
    step = st.radio(
        "Go to",
        [
            "Intro",
            "Zoom out",
            "Seasons then vs now",
            "You vs the world",
            "World map (idea)",
        ],
    )

# Map label back to slug + meta
chosen_idx = labels.index(chosen_label)
slug = slug_list[chosen_idx]
loc_meta = LOCATIONS[slug]

location_label = loc_meta["label"]
location_lat = loc_meta["lat"]
location_lon = loc_meta["lon"]
clim_path = loc_meta["path"]

# Load dataset for this location
ds = xr.open_dataset(clim_path)

# Compute high-level facts once
facts = compute_story_facts(ds, lat=location_lat)

fake_data = fake_local_and_global("mauritius")

now_year = fake_data["local_yearly"].index.year.max()
past_year = fake_data["local_yearly"].index.year.min()
warming_local = fake_data["local_yearly"].iloc[-1] - fake_data["local_yearly"].iloc[0]
warming_global = fake_data["global_yearly"].iloc[-1] - fake_data["global_yearly"].iloc[0]

local_daily = fake_data["local_daily"]
local_hourly = fake_data["local_hourly"]
local_monthly = fake_data["local_monthly"]

# -----------------------------------------------------------
# Common CSS
# -----------------------------------------------------------

st.markdown(
    """
    <style>
    .hero-title {
        font-size: 2.6rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .hero-subtitle {
        font-size: 1.15rem;
        color: #555;
        margin-bottom: 0.5rem;
    }
    .hero-metric {
        font-size: 1.1rem;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------
# Compute last year data, graph and captions
# -----------------------------------------------------------

def build_last_year_data(ds: xr.Dataset) -> dict:
    """
    Prepare the data needed for the 'Last year — the seasonal cycle' panel.

    Uses:
      - time_daily
      - t2m_daily_mean_c
    Returns a dict so it's easy to plug into other front-ends later.
    """
    t_daily = ds["t2m_daily_mean_c"]  # (time)
    time_all = pd.to_datetime(t_daily["time"].values)
    temp_all = t_daily.values

    # Take the last 12 FULL calendar months in the dataset
    last_day = time_all.max()
    # First day of last month in dataset
    end_month_start = last_day.replace(day=1)
    # First day 11 months earlier (gives 12 months total)
    start_month_start = (end_month_start - pd.DateOffset(months=11)).normalize()

    mask = (time_all >= start_month_start) & (time_all <= last_day)
    time_last = time_all[mask]
    temp_last = temp_all[mask]

    s_daily = pd.Series(temp_last, index=time_last)
    s_smooth = s_daily.rolling(window=7, center=True, min_periods=2).mean()

    # --- 3. Find min / max over this last year ---
    imax = int(np.nanargmax(s_daily.values))
    imin = int(np.nanargmin(s_daily.values))
    t_max = s_daily.index[imax]
    t_min = s_daily.index[imin]
    v_max = float(s_daily.values[imax])
    v_min = float(s_daily.values[imin])

    return {
        "time_daily": time_last,
        "temp_daily_mean": s_daily.values,
        "temp_7d": s_smooth.values,
        "last_day": last_day,
        "start_month": start_month_start,
    }


def build_last_year_figure(data: dict) -> (go.Figure, str):
    """
    Build the Plotly figure for the last-year seasonal cycle.

    Styling is consistent with other panels:
      - grey noisy curve (daily)
      - blue smooth curve (7-day mean)
      - min/max annotations via annotate_minmax_on_series()
    """
    fig = go.Figure()

    time_daily = data["time_daily"]
    t_daily = data["temp_daily_mean"]
    t_7d = data["temp_7d"]

    # Noisy base curve
    add_trace(
        fig,
        x=time_daily,
        y=t_daily,
        name="Daily mean",
        hovertemplate="%{x|%d %b %Y}<br>Daily mean: %{y:.1f}°C<extra></extra>",
    )

    # Smooth curve
    add_mean_trace(
        fig,
        x=time_daily,
        y=t_7d,
        name="7-day mean",
        showmarkers=False,
        hovertemplate="%{x|%d %b %Y}<br>7-day mean: %{y:.1f}°C<extra></extra>",
    )

    # Min/max annotations on the smooth curve
    annotate_minmax_on_series(fig, time_daily, t_daily, label_prefix="")

    fig.update_layout(
        height=400,
        xaxis=dict(
            title="Date",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title="Temperature (°C)",
            zeroline=False,
        ),
        margin=dict(l=40, r=20, t=30, b=40),
        showlegend=True,
    )

    start_label = data["start_month"].strftime("%b %Y")
    end_label = data["last_day"].strftime("%b %Y")
    caption = f"Source: OpenMeteo | Range: last 12 months in dataset ({start_label} – {end_label})"

    return fig, caption

def last_year_caption(facts: StoryFacts) -> str:
    """
    Generate the markdown caption for the last-year panel
    using StoryFacts (so it's easy to reuse elsewhere).
    """
    base_text = (
        "Over a full year you can clearly see the **seasonal cycle**: the rise into the "
        "hottest months and the slide back down. Climate change adds a slow upward "
        "shift on top of this familiar pattern."
    )

    extra = ""
    if facts.last_year_anomaly is not None:
        anom = facts.last_year_anomaly
        if anom > 0.8:
            extra = (
                f" This particular year was about **{anom:.1f}°C warmer** than the "
                "long-term average for this location."
            )
        elif anom > 0.3:
            extra = (
                f" This particular year was **slightly warmer than usual**, roughly "
                f"{anom:.1f}°C above the long-term average."
            )
        elif anom < -0.8:
            extra = (
                f" This particular year was about **{abs(anom):.1f}°C cooler** than the "
                "long-term average here."
            )
        elif anom < -0.3:
            extra = (
                f" This particular year ran **a bit cooler than usual**, around "
                f"{abs(anom):.1f}°C below the long-term average."
            )

    return base_text + extra

# -----------------------------------------------------------
# Compute seasons data, graph and captions
# -----------------------------------------------------------

def build_seasons_then_now_data(ds: xr.Dataset) -> dict:
    """
    Prepare data for the 'How your seasons have shifted' panel.

    Uses monthly climatologies:
      - t2m_monthly_clim_past_mean_c   (month: 1..12)
      - t2m_monthly_clim_recent_mean_c (month: 1..12)
    """
    if "t2m_monthly_clim_past_mean_c" not in ds or "t2m_monthly_clim_recent_mean_c" not in ds:
        return {}

    past = np.asarray(ds["t2m_monthly_clim_past_mean_c"].values, dtype="float64")
    recent = np.asarray(ds["t2m_monthly_clim_recent_mean_c"].values, dtype="float64")

    # Expect length 12; if not, bail out gracefully
    if past.size != 12 or recent.size != 12:
        return {}

    # Use a dummy year just for nice month labels
    month_index = pd.date_range("2000-01-01", periods=12, freq="MS")
    month_names = [d.strftime("%b") for d in month_index]

    delta = recent - past  # positive => recent is warmer

    return {
        "month_index": month_index,
        "month_names": month_names,
        "temp_past": past,
        "temp_recent": recent,
        "delta": delta,
    }

def build_seasons_then_now_figure(data: dict, location_label: str) -> go.Figure:
    """
    Build overlay figure: monthly climatology past vs recent.
    """
    month_index = data["month_index"]
    past = data["temp_past"]
    recent = data["temp_recent"]
    delta = data["delta"]

    fig = go.Figure()

    # Past climatology – in blue
    fig.add_trace(
        go.Scatter(
            x=month_index,
            y=past,
            mode="lines+markers",
            name="Earlier climate",
            line=dict(color="rgba(38,139,210,0.9)", width=2, shape="spline"),
            marker=dict(size=6),
            hovertemplate="%{x|%b}<br>Earlier: %{y:.1f}°C<extra></extra>",
        )
    )

    # Recent climatology – in red
    fig.add_trace(
        go.Scatter(
            x=month_index,
            y=recent,
            mode="lines+markers",
            name="Recent climate",
            line=dict(color="rgba(217,95,2,0.9)", width=2, shape="spline"),
            marker=dict(size=6),
            hovertemplate="%{x|%b}<br>Recent: %{y:.1f}°C<extra></extra>",
        )
    )

    # Make y-axis span sensible between both curves
    y_all = np.concatenate([past, recent])
    y_min = float(np.nanmin(y_all))
    y_max = float(np.nanmax(y_all))
    span = max(y_max - y_min, 5.0)  # at least about 5°C span
    pad = span * 0.1
    y_center = 0.5 * (y_min + y_max)
    y0 = y_center - span / 2.0 - pad
    y1 = y_center + span / 2.0 + pad

    fig.update_layout(
        title=f"How your seasons have shifted – {location_label}",
        xaxis=dict(
            title="Month",
            tickmode="array",
            tickvals=month_index,
            ticktext=[d.strftime("%b") for d in month_index],
            showgrid=True,
            gridcolor="rgba(220,220,220,0.3)",
        ),
        yaxis=dict(
            title="Typical monthly temperature (°C)",
            range=[y0, y1],
        ),
        margin=dict(l=40, r=160, t=60, b=40),
        legend=dict(
            orientation="v",
            x=1.02,
            xanchor="left",
            y=1.0,
        ),
    )

    return fig

def seasons_then_now_caption(facts: StoryFacts, data: dict) -> str:
    """
    Generate caption for the 'Seasons then vs now' panel.
    Uses StoryFacts + the month-by-month deltas.
    """
    base = (
        "Here we compare a **typical year in the earlier climate** (grey) to a "
        "**typical year in the recent climate** (blue). Each point is the average "
        "monthly temperature over its period."
    )

    if not data:
        return base

    delta = data["delta"]
    month_names = data["month_names"]
    mean_delta = float(np.nanmean(delta))

    # Find month with strongest positive shift
    imax = int(np.nanargmax(delta))
    max_month = month_names[imax]
    max_delta = float(delta[imax])

    # Short paragraph about how big the shift is
    extra = ""
    if mean_delta > 0.8:
        extra += (
            f" On average, the recent climate here is about **{mean_delta:.1f}°C warmer** "
            "throughout the year."
        )
    elif mean_delta > 0.3:
        extra += (
            f" On average, the recent climate is about **{mean_delta:.1f}°C warmer** "
            "— a subtle but persistent shift."
        )
    elif mean_delta < -0.8:
        extra += (
            f" Surprisingly, the recent climate here comes out about **{abs(mean_delta):.1f}°C cooler** "
            "on average than the earlier period."
        )
    elif mean_delta < -0.3:
        extra += (
            f" On average, the recent climate is about **{abs(mean_delta):.1f}°C cooler** "
            "than the earlier period."
        )

    # If warming is uneven, call out the biggest seasonal change
    if max_delta > 0.4:
        extra += (
            f" The biggest seasonal shift shows up in **{max_month}**, "
            f"which is now around **{max_delta:.1f}°C warmer** than it used to be."
        )

    # Optionally tie back to long-term 50y fact
    if facts.total_warming_50y is not None and abs(facts.total_warming_50y) > 0.3:
        extra += (
            f" These monthly changes are one way that the roughly "
            f"**{facts.total_warming_50y:.1f}°C** long-term warming at this spot "
            "shows up in everyday seasons."
        )

    return base + extra




# -----------------------------------------------------------
# STEP: INTRO
# -----------------------------------------------------------
if step == "Intro":
    st.markdown(
        f"""
        <div class="hero-title">Your climate story</div>
        <div class="hero-subtitle">How temperatures have changed where you live</div>
        """,
        unsafe_allow_html=True,
    )

    col_map, col_text = st.columns([2.2, 1.3])

    with col_map:
        st.write("")
        m = folium.Map(location=[location_lat, location_lon], zoom_start=4, tiles="CartoDB positron")
        folium.CircleMarker(
            location=[location_lat, location_lon],
            radius=8,
            color="#d73027",
            fill=True,
            fill_opacity=0.9,
        ).add_to(m)
        st_folium(m, width="stretch", height=420)

    with col_text:
        loc_name = ds.attrs.get("name_long", "this location")
        st.markdown(
            f"""
            <p class="hero-metric">
            Since the mid-{past_year}s, the typical yearly temperature in
            <strong>{loc_name}</strong> has warmed by about
            <strong>{warming_local:.1f}°C</strong>.
            </p>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            Globally, the average warming over the same period is around
            <strong>{warming_global:.1f}°C</strong>. Your local climate is warming
            <strong>{'faster' if warming_local > warming_global else 'slower'}</strong>
            than the global average.
            """
        )

        st.markdown(
            """
            Use the steps in the sidebar to zoom out from last week’s weather
            to the last fifty years of climate, and see how your seasons have shifted.
            """
        )

# -----------------------------------------------------------
# STEP: ZOOM OUT
# -----------------------------------------------------------
if step == "Zoom out":
    #ds = load_city_climatology(DEFAULT_SLUG)
    loc_name = ds.attrs.get("name_long", "this location")
    
    # After loading ds and knowing the location lat
    # facts = compute_story_facts(ds, lat=lat)

    st.header("1. Zooming out: from days to decades")

    # 1A. Last 7 days — hourly + daily mean
    st.subheader("Last week — the daily cycle")

    # Use last full day as the endpoint (yesterday)
    today = date.today()
    end_7d = today - timedelta(days=1)
    end_7d_str = end_7d.isoformat()

    ds_7d = fetch_recent_7d(DEFAULT_SLUG, location_lat, location_lon, end_7d_str)

    t_hourly = pd.to_datetime(ds_7d["time_hourly"].values)
    temp_hourly = ds_7d["t_hourly"].values

    t_daily_mid = pd.to_datetime(ds_7d["time_daily"].values) + pd.Timedelta(hours=12)
    temp_daily = ds_7d["t_daily_mean"].values

    fig_7d = go.Figure()

    # Hourly temp (light grey)
    add_trace(fig_7d, t_hourly, temp_hourly, "Hourly", hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:.1f}°C<extra></extra>")

    # Daily mean (blue-ish)
    add_mean_trace(fig_7d, t_daily_mid, temp_daily, "Daily mean", showmarkers=True, hovertemplate="%{x|%Y-%m-%d}<br>Daily mean: %{y:.1f}°C<extra></extra>")

    annotate_minmax_on_series(fig_7d, t_hourly, temp_hourly, label_prefix="")

    fig_7d.update_layout(
        margin=dict(l=0, r=0, t=10, b=40),
        height=320,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.02,
        ),
        xaxis=dict(
            title="Date",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title="°C",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    st.plotly_chart(fig_7d, width="stretch", config={"displayModeBar": False})

    st.caption(f"Range: {ds_7d.attrs.get('range', end_7d_str)}")

    st.markdown(
        """
    Over a single week you can see the **heartbeat of days and nights**: temperatures
    rise during the day, fall at night, and swing with passing weather systems.
    """
    )

    # 1B. Last 30 days — daily + 3-day mean + min/max
    st.subheader("Last month — daily temperatures")

    end_30d = today - timedelta(days=1)
    end_30d_str = end_30d.isoformat()

    ds_30d = fetch_recent_30d(DEFAULT_SLUG, location_lat, location_lon, end_30d_str)

    t_daily_30 = pd.to_datetime(ds_30d["time_daily"].values)
    tmean_30 = ds_30d["t_daily_mean"].values

    trend_30d = estimate_30d_trend(t_daily_30, tmean_30)
    trend_sentence = ""

    if not np.isnan(trend_30d) and abs(trend_30d) >= 0.5:
        # threshold: ≈ ±0.5°C over 30 days to be "noticeable"
        direction = "rising" if trend_30d > 0 else "falling"
        sign_word = "warmer" if trend_30d > 0 else "cooler"
        season = season_phrase(location_lat, t_daily_30[-1])
        trend_sentence = (
            f" Over this 30-day window, daily averages have been **{direction}** "
            f"by about {trend_30d:+.1f}°C, consistent with {season}."
        )

    # 3-day rolling mean
    mean_3d = pd.Series(tmean_30, index=t_daily_30).rolling(window=3, center=True).mean().values

    fig_30d = go.Figure()

    add_trace(fig_30d, t_daily_30, tmean_30, "Daily mean", "%{x|%Y-%m-%d}<br>Daily mean: %{y:.1f}°C<extra></extra>"), 

    # 3-day mean (blue)
    add_mean_trace(fig_30d, t_daily_30, mean_3d, "3-day mean", hovertemplate="%{x|%Y-%m-%d}<br>3-day mean: %{y:.1f}°C<extra></extra>")

    annotate_minmax_on_series(fig_30d, t_daily_30, tmean_30, label_prefix="")

    fig_30d.update_layout(
        margin=dict(l=0, r=0, t=10, b=40),
        height=320,
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=1.02,
        ),
        xaxis=dict(
            title="Date",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title="°C",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    st.plotly_chart(fig_30d, width="stretch", config={"displayModeBar": False})

    st.caption(f"Range: {ds_30d.attrs.get('range', end_30d_str)}")

    base_text = """
    Here we’re looking at **daily averages**, not the full day–night cycle.
    Over a month, the jagged ups and downs reflect **passing weather systems**:
    short warm spells, cooler snaps, and the background shift between seasons.
    """

    st.markdown(base_text + ("" if not trend_sentence else "\n\n" + trend_sentence))

    # 1C. Last year — the seasonal cycle
    st.subheader("Last year — the seasonal cycle")
    last_year_data = build_last_year_data(ds)
    if last_year_data:
        fig_year, fig_year_caption = build_last_year_figure(last_year_data)
        st.plotly_chart(fig_year, width="stretch", config={"displayModeBar": False})
        st.caption(fig_year_caption)       
        st.markdown(last_year_caption(facts))
    else:
        st.info("Not enough recent daily data available to show the last year for this location.")
        
    # 1D. Last 5 years — 7-day mean and monthly mean
    st.subheader("Last 5 years — zoom from seasons to climate")

    # Daily mean temperature (precomputed), with explicit 'time' coord
    da_daily = ds["t2m_daily_mean_c"]
    time_daily = pd.to_datetime(da_daily["time"].values)

    # End of record = last timestamp in daily series
    end_date = time_daily[-1].normalize()

    # Start 5 years earlier
    start_5y = end_date - pd.DateOffset(years=5)

    # If the record is shorter than 5 years for some reason, just use full range
    if time_daily[0] > start_5y:
        start_5y = time_daily[0]

    # Slice daily data to last ~5 years
    daily_5y = da_daily.sel(time=slice(start_5y, end_date))

    # 7-day rolling mean (centered)
    weekly_5y = daily_5y.rolling(time=7, center=True).mean()

    # Monthly mean series (precomputed, but we don't assume coord is named 'time')
    da_mon = ds["t2m_monthly_mean_c"]

    # Use first dimension and its coord as the monthly time axis, whatever it's called
    mon_dim = da_mon.dims[0]                      # e.g. "time" or "valid_time" or "month"
    mon_coord = pd.to_datetime(da_mon[mon_dim].values)

    # Mask to last ~5 years
    mon_mask = (mon_coord >= start_5y) & (mon_coord <= end_date)
    monthly_5y = da_mon.isel({mon_dim: mon_mask})
    x_month = mon_coord[mon_mask]

    fig_5y = go.Figure()

    # 7-day mean (grey, light)
    add_trace(
        fig_5y,
        pd.to_datetime(weekly_5y.time.values),
        weekly_5y.values,
        "7-day mean",
        hovertemplate="%{x|%Y-%m-%d}<br>7-day mean: %{y:.1f}°C<extra></extra>"
    )

    # Monthly mean (warmer color, thicker)
    add_mean_trace(fig_5y, x_month, monthly_5y.values, "Monthly mean", hovertemplate="%{x|%Y-%m}<br>Monthly mean: %{y:.1f}°C<extra></extra>")

    fig_5y.update_layout(
        margin=dict(l=0, r=0, t=10, b=40),
        height=320,
        showlegend=True,
        xaxis=dict(
            title="Year",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
        yaxis=dict(
            title="°C",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.3)",
        ),
    )

    st.plotly_chart(fig_5y, width="stretch", config={"displayModeBar": False})

    # Reuse the small coverage caption if you like
    cov = dataset_coverage_text(ds)
    if cov:
        st.caption(cov)

    base_5y = (
        "Over the last five years, the shorter-term wiggles (the 7-day mean) sit on top of a smoother monthly pattern. "
        "As you zoom out, weather becomes noise and you start to see the underlying climate: which seasons are warming "
        "the most, and how often the line pushes into new territory."
    )

    extra_5y = ""
    if facts.recent_warming_10y is not None and facts.total_warming_50y is not None:
        short = facts.recent_warming_10y
        long_ = facts.total_warming_50y

        if abs(short) < 0.3 and abs(long_) > 0.8:
            # Short-term trend is subtle, but long-term is clear
            extra_5y = (
                " At this scale, the warming is **subtle** – these recent years only hint "
                "at a change. The bigger shift really jumps out when you zoom all the way "
                "out to the full record below."
            )
        elif abs(short) >= 0.3:
            direction = "warmer" if short >= 0 else "cooler"
            extra_5y = (
                f" Even over just these recent years, the smoothed curve points to a change "
                f"equivalent to about {short:+.1f}°C per decade. That trend connects directly "
                "to the longer-term shift you’ll see in the 50-year view."
        )

    st.markdown(base_5y + extra_5y)
   

    # 1E. Last ~50 years — monthly averages and trend
    st.subheader("Last 50 years — monthly averages and trend")

    # --- 1. Load real data for this location ---
    da_mon = ds["t2m_monthly_mean_c"]  # (time_monthly)
    time_mon = pd.to_datetime(da_mon["time_monthly"].values)
    temp_mon = da_mon.values

    # --- 2. Yearly mean and 5-year running mean (from the monthly series) ---
    monthly_da = xr.DataArray(
        temp_mon,
        coords={"time_monthly": time_mon},
        dims=["time_monthly"],
        name="t2m_monthly_mean_c",
    )

    yearly_mean = monthly_da.groupby("time_monthly.year").mean("time_monthly")
    years = yearly_mean["year"].values.astype(float)
    t_year = yearly_mean.values

    # 5-year running mean on yearly series

    da_year = ds["t2m_yearly_mean_c"]
    time_year = pd.to_datetime(ds["time_yearly"].values)
    #years = time_year.year.astype(float)
    temps_year = np.asarray(da_year.values, dtype="float64")

    # --- 3. Coldest & warmest months per year and their linear trends ---
    cold_by_year = monthly_da.groupby("time_monthly.year").min("time_monthly")
    warm_by_year = monthly_da.groupby("time_monthly.year").max("time_monthly")

    cold_years = cold_by_year["year"].values.astype(float)
    warm_years = warm_by_year["year"].values.astype(float)
    cold_vals = cold_by_year.values
    warm_vals = warm_by_year.values

    cold_trend = warm_trend = None
    if len(cold_years) >= 2:
        coef_cold = np.polyfit(cold_years, cold_vals, 1)
        cold_trend = np.polyval(coef_cold, cold_years)
    if len(warm_years) >= 2:
        coef_warm = np.polyfit(warm_years, warm_vals, 1)
        warm_trend = np.polyval(coef_warm, warm_years)

    # --- 4. Build the figure using your original styling ---
    fig_50 = go.Figure()

    # Monthly mean (thin grey spline)
    add_trace(fig_50, time_mon, temp_mon, "Monthly mean")

    add_mean_trace(
        fig_50,
        x=time_year,
        y=temps_year,
        name="Yearly mean",
        showmarkers=True,
        hovertemplate="Year %{x|%Y}<br>%{y:.1f}°C<extra></extra>",
    )

    # Linear trend
    mask = np.isfinite(temps_year)
    if mask.sum() >= 5:
        x = years[mask]
        y = temps_year[mask]
        # Linear trend on yearly means (red) – as a true straight line in time
        slope, intercept = np.polyfit(x, y, 1)

        # Continuous year grid
        trend_years = np.linspace(x.min(), x.max(), 200)
        # Map fractional years -> datetimes (approximate using 365.25 days per year)
        ref_start = pd.Timestamp(f"{int(x.min())}-01-01")
        trend_dates = ref_start + pd.to_timedelta((trend_years - x.min()) * 365.25, unit="D")
        trend_vals = intercept + slope * trend_years

        fig_50.add_trace(
            go.Scatter(
                x=trend_dates,
                y=trend_vals,
                mode="lines",
                name="Trend (yearly mean)",
                line=dict(color="rgba(220,50,47,0.9)", width=3, shape="linear"),
                hovertemplate="Trend %{x|%Y}<br>%{y:.1f}°C<extra></extra>",
            )
        )

        # For caption later
        total_span_years = int(x.max() - x.min())
        total_warming = float(trend_vals[-1] - trend_vals[0])
    else:
        trend_years = None
        total_span_years = None
        total_warming = None

    # Coldest-month trend (blue dotted spline)
    if cold_trend is not None:
        x_cold = [datetime(int(y), 1, 1) for y in cold_years]
        fig_50.add_trace(
            go.Scatter(
                x=x_cold,
                y=cold_trend,
                mode="lines",
                name="Coldest-month trend",
                line=dict(
                    color="rgba(38,139,210,0.9)",
                    width=2,
                    dash="dot",
                    shape="spline",
                ),
            )
        )

    # Warmest-month trend (red dotted spline)
    if warm_trend is not None:
        x_warm = [datetime(int(y), 7, 1) for y in warm_years]
        fig_50.add_trace(
            go.Scatter(
                x=x_warm,
                y=warm_trend,
                mode="lines",
                name="Warmest-month trend",
                line=dict(
                    color="rgba(220,50,47,0.9)",
                    width=2,
                    dash="dot",
                    shape="spline",
                ),
            )
        )

    fig_50.update_layout(
        height=400,
        margin=dict(l=40, r=20, t=30, b=40),
        xaxis_title="Year",
        yaxis_title="Temperature (°C)",
        showlegend=True,
    )

    st.plotly_chart(fig_50, width="stretch", config={"displayModeBar": False})

    cov = dataset_coverage_text(ds)
    if cov:
        st.caption(cov)
       
    # --- 5. Text: “zoom out” narrative + sign-sensitive wording ---

    if total_span_years is not None and total_span_years > 0:
        if abs(total_warming) < 0.15:
            # ~flat
            total_warming_sign = "+" if total_warming>0 else "-"
            change_text = (
                f"has changed very little **({total_warming_sign}{total_warming:.1f}°C)** — the long-term average is almost the same "
                f"now as it was at the start of the record."
            )
        elif total_warming > 0:
            # warmer
            change_text = (
                f"is now roughly **{total_warming:.1f}°C warmer on average** than it was "
                f"at the start of the record."
            )
        else:
            # cooler
            change_text = (
                f"is now roughly **{abs(total_warming):.1f}°C cooler on average** than it was "
                f"at the start of the record — a smaller change than in many places."
            )

        st.markdown(
            f"""
    When you zoom out over about **{total_span_years} years**, the year-to-year noise
    fades and a clear pattern emerges. In **{loc_name}**, the climate {change_text}
            """
        )
    else:
        st.markdown(
            f"""
    When you zoom out over about **{total_span_years} years**, the year-to-year noise
    fades and a clearer pattern would normally emerge — but here the data window is too short
    to say much yet for **{loc_name}**.
            """
        )

    # 1F. A simple 25-year projection, assuming the same trend continues
    st.subheader("Looking 25 years ahead (simple trend extension)")

    da_year = ds["t2m_yearly_mean_c"]
    time_yearly = pd.to_datetime(ds["time_yearly"].values)

    years = time_yearly.year.astype(float)
    temps = np.asarray(da_year.values, dtype="float64")

    mask = np.isfinite(temps)
    if mask.sum() >= 5:
        x = years[mask]
        y = temps[mask]

        # Base: yearly mean
        fig_future = go.Figure()

        add_trace(
            fig_future,
            x=time_yearly,
            y=temps,
            name="Yearly mean",
            hovertemplate="Year %{x|%Y}<br>%{y:.1f}°C<extra></extra>",
        )

        # 5-year rolling mean (blue smoothing)
        df_year = pd.DataFrame({"year": years, "temp": temps}).set_index("year")
        smooth5 = (
            df_year["temp"].rolling(window=5, center=True, min_periods=3).mean().values
        )

        add_mean_trace(
            fig_future,
            x=time_yearly,
            y=smooth5,
            name="5-year mean",
            showmarkers=False,
            hovertemplate="Year %{x|%Y}<br>%{y:.1f}°C<extra></extra>",
        )

        # Linear trend on yearly means (red)
        slope, intercept = np.polyfit(x, y, 1)

        first_year = float(x.min())
        last_year = float(x.max())
        horizon = 25.0

        # Build a continuous year axis from first year through future
        full_years = np.linspace(first_year, last_year + horizon, 300)
        trend_vals_full = intercept + slope * full_years

        # Map fractional years to datetimes
        ref_start = pd.Timestamp(f"{int(first_year)}-01-01")
        full_dates = ref_start + pd.to_timedelta((full_years - first_year) * 365.25, unit="D")

        # Split into historical vs future segments
        past_mask = full_years <= (last_year + 1e-6)
        future_mask = full_years > (last_year + 1e-6)

        # Plot past trend (solid red)
        fig_future.add_trace(
            go.Scatter(
                x=full_dates[past_mask],
                y=trend_vals_full[past_mask],
                mode="lines",
                name="Trend (yearly mean)",
                line=dict(color="rgba(220,50,47,0.9)", width=3, shape="linear"),
                hovertemplate="Trend %{x|%Y}<br>%{y:.1f}°C<extra></extra>",
            )
        )

        # Plot future extension (dashed red)
        fig_future.add_trace(
            go.Scatter(
                x=full_dates[future_mask],
                y=trend_vals_full[future_mask],
                mode="lines",
                name="Straight-line extension",
                line=dict(
                    color="rgba(220,50,47,0.9)", width=3, dash="dash", shape="linear"
                ),
                hovertemplate="Extension %{x|%Y}<br>%{y:.1f}°C<extra></extra>",
            )
        )

        # Shade future region based on last_year
        last_year_int = int(round(last_year))
        future_end_year_int = int(round(last_year + horizon))
        fig_future.add_vrect(
            x0=pd.Timestamp(f"{last_year_int+1}-01-01"),
            x1=pd.Timestamp(f"{future_end_year_int}-12-31"),
            fillcolor="rgba(220,50,47,0.06)",
            line_width=0,
            layer="below",
        )

        # --- Choose a sane y-axis range so year-to-year bumps aren't exaggerated ---
        y_all = np.concatenate([np.asarray(temps, dtype="float64"),
                                np.asarray(trend_vals_full, dtype="float64")])

        y_min = float(np.nanmin(y_all))
        y_max = float(np.nanmax(y_all))

        # Enforce at least ~2°C span
        span = max(y_max - y_min, 2.0)
        pad = span * 0.1  # 10% padding top/bottom

        y_center = 0.5 * (y_min + y_max)
        y0 = y_center - span / 2.0 - pad
        y1 = y_center + span / 2.0 + pad

        fig_future.update_layout(
            margin=dict(l=0, r=0, t=10, b=40),
            height=320,
            showlegend=True,
            xaxis=dict(
                title="Year",
                showgrid=True,
                gridcolor="rgba(200,200,200,0.3)",
            ),
            yaxis=dict(
                title="Temperature (°C)",
                showgrid=True,
                gridcolor="rgba(200,200,200,0.3)",
                range=[y0, y1],
            ),
        )

        st.plotly_chart(fig_future, width="stretch", config={"displayModeBar": False})

       # Story numbers
        hist_warming = float(trend_vals_full[past_mask][-1] - trend_vals_full[past_mask][0])
        extra_25 = float(trend_vals_full[future_mask][-1] - trend_vals_full[past_mask][-1])
        total_span_years = last_year - first_year
        direction_hist = "warmer" if hist_warming >= 0 else "cooler"
        direction_future = "warmer" if extra_25 >= 0 else "cooler"
        
        st.markdown(
            f"Over the observed **{total_span_years:.0f} years**, the straight-line trend in yearly "
            f"temperatures suggests this location has become about {hist_warming:+.1f}°C "
            f"{direction_hist}. If that linear trend simply continued, another 25 years "
            f"would add roughly {extra_25:+.1f}°C. This is a **what-if extrapolation**, "
            " not a forecast."
        )

    else:
        st.info("Not enough yearly data to draw a simple trend extension here.")


# -----------------------------------------------------------
# STEP: SEASONS THEN VS NOW
# -----------------------------------------------------------
if step == "Seasons then vs now":
    st.header("2. How your seasons have shifted")

    seasons_data = build_seasons_then_now_data(ds)

    if seasons_data:
        fig_seasons = build_seasons_then_now_figure(seasons_data, location_label)
        st.plotly_chart(fig_seasons, width="stretch", config={"displayModeBar": False})

        st.markdown(seasons_then_now_caption(facts, seasons_data))

        # Optional: small caption under the graph with data periods
        st.caption(
            f"Earlier climate: {facts.data_start_year}–{facts.data_start_year + 9}, "
            f"recent climate: {facts.data_end_year - 9}–{facts.data_end_year} "
            "(based on daily ERA5 2m temperature via Open-Meteo)."
        )
    else:
        st.info("Monthly climatologies are not available for this location.")
        
    # 2B. Min–max envelopes for early vs recent climates
    st.subheader("How the range of monthly temperatures has changed")

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    years_all = local_monthly.index.year
    recent_mask = years_all >= (years_all.max() - 9)
    early_mask = years_all <= (years_all.min() + 9)
    recent_clim = local_monthly[recent_mask].groupby(
        local_monthly[recent_mask].index.month
    ).mean()
    past_clim = local_monthly[early_mask].groupby(
        local_monthly[early_mask].index.month
    ).mean()

    # Build daily masks for early vs recent decades
    years_daily = local_daily.index.year
    early_mask_daily = years_daily <= (years_daily.min() + 9)
    recent_mask_daily = years_daily >= (years_daily.max() - 9)

    daily_early = local_daily[early_mask_daily]
    daily_recent = local_daily[recent_mask_daily]

    def month_minmax(series: pd.Series):
        g = series.groupby([series.index.month])
        return g.min(), g.max()

    early_min, early_max = month_minmax(daily_early)
    recent_min, recent_max = month_minmax(daily_recent)

    col_past, col_recent = st.columns(2)

    # Left: past envelope – min/mean/max with coloured bands
    with col_past:
        fig_env_past = go.Figure()
        # 1) Min line
        fig_env_past.add_trace(
            go.Scatter(
                x=months,
                y=early_min.values,
                mode="lines",
                name="Monthly min",
                line=dict(
                    color="rgba(38,139,210,1.0)",
                    width=2,
                    shape="spline",
                ),
            )
        )
        # 2) Mean line (grey), fill between min and mean in blue
        fig_env_past.add_trace(
            go.Scatter(
                x=months,
                y=past_clim.values,
                mode="lines",
                name="Monthly mean",
                line=dict(
                    color="rgba(120,120,120,1.0)",
                    width=2,
                    shape="spline",
                ),
                fill="tonexty",
                fillcolor="rgba(158,202,225,0.3)",  # blue-ish between min & mean
            )
        )
        # 3) Max line, fill between mean and max in red
        fig_env_past.add_trace(
            go.Scatter(
                x=months,
                y=early_max.values,
                mode="lines",
                name="Monthly max",
                line=dict(
                    color="rgba(220,50,47,1.0)",
                    width=2,
                    shape="spline",
                ),
                fill="tonexty",
                fillcolor="rgba(244,165,130,0.3)",  # red-ish between mean & max
            )
        )

        fig_env_past.update_layout(
            height=280,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="Daily temperature °C",
            xaxis_title="Month",
            xaxis=dict(tickmode="array", tickvals=months),
            title="Earlier climate (monthly min–mean–max)",
        )
        st.plotly_chart(
            fig_env_past, width="stretch", config={"displayModeBar": False}
        )

    # Right: recent envelope – same structure
    with col_recent:
        fig_env_recent = go.Figure()
        # 1) Min
        fig_env_recent.add_trace(
            go.Scatter(
                x=months,
                y=recent_min.values,
                mode="lines",
                name="Monthly min",
                line=dict(
                    color="rgba(38,139,210,1.0)",
                    width=2,
                    shape="spline",
                ),
            )
        )
        # 2) Mean
        fig_env_recent.add_trace(
            go.Scatter(
                x=months,
                y=recent_clim.values,
                mode="lines",
                name="Monthly mean",
                line=dict(
                    color="rgba(120,120,120,1.0)",
                    width=2,
                    shape="spline",
                ),
                fill="tonexty",
                fillcolor="rgba(158,202,225,0.3)",
            )
        )
        # 3) Max
        fig_env_recent.add_trace(
            go.Scatter(
                x=months,
                y=recent_max.values,
                mode="lines",
                name="Monthly max",
                line=dict(
                    color="rgba(220,50,47,1.0)",
                    width=2,
                    shape="spline",
                ),
                fill="tonexty",
                fillcolor="rgba(254,224,210,0.4)",
            )
        )

        fig_env_recent.update_layout(
            height=280,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="Daily temperature °C",
            xaxis_title="Month",
            xaxis=dict(tickmode="array", tickvals=months),
            title="Recent climate (monthly min–mean–max)",
        )
        st.plotly_chart(
            fig_env_recent, width="stretch", config={"displayModeBar": False}
        )

    # 2C. Summary text
    loc_key = "mauritius"
    if loc_key == "mauritius":
        summer_months = [1, 2, 3]
        winter_months = [7, 8, 9]
    else:  # london
        summer_months = [6, 7, 8]
        winter_months = [12, 1, 2]

    summer_delta = (
        recent_clim.loc[summer_months].mean() - past_clim.loc[summer_months].mean()
    ).item()
    winter_delta = (
        recent_clim.loc[winter_months].mean() - past_clim.loc[winter_months].mean()
    ).item()

    st.markdown(
        f"""
        In **{location_label}**, the typical year has shifted:

        * **Summer months** are about **{summer_delta:.1f}°C** warmer than they were
          in the {years_all.min()}s.
        * **Cooler months** are about **{winter_delta:.1f}°C** warmer.

        The envelopes above show how the **range** of daily temperatures within
        each month has changed: not just the average, but also the typical
        **coldest** and **hottest** days of each month.
        """
    )

# -----------------------------------------------------------
# STEP: YOU VS THE WORLD (ANOMALIES)
# -----------------------------------------------------------
if step == "You vs the world":
    st.header("3. Your warming vs global warming")

    local_anom = data["local_anom"]
    global_anom = data["global_anom"]

    def anomaly_bars(series, label):
        x = series.index.year + (series.index.month - 0.5) / 12.0
        y = series.values
        colors = np.where(
            y >= 0, "rgba(180, 0, 120, 0.8)", "rgba(0, 130, 0, 0.8)"
        )
        fig = go.Figure(
            go.Bar(
                x=x,
                y=y,
                marker=dict(color=colors),
            )
        )
        fig.update_layout(
            height=260,
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis_title="Year",
            yaxis_title="Anomaly vs 1979–1990 (°C)",
            title=label,
        )
        return fig

    col_local, col_global = st.columns(2)
    with col_local:
        st.plotly_chart(
            anomaly_bars(local_anom, f"{loc_choice} — monthly anomalies"),
            width="stretch",
            config={"displayModeBar": False},
        )
    with col_global:
        st.plotly_chart(
            anomaly_bars(global_anom, "Global average — monthly anomalies"),
            width="stretch",
            config={"displayModeBar": False},
        )

    st.markdown(
        """
        Here we compare your location to a simple **global average**.  
        Both are measured relative to the same baseline (roughly 1979–1990).

        In a full implementation, this section would use **real global datasets**
        (for example, published global temperature indices) and the local record
        from ERA5, so you can see exactly how much faster or slower your
        region has warmed compared to the planet as a whole.
        """
    )

# -----------------------------------------------------------
# STEP: WORLD MAP IDEA
# -----------------------------------------------------------
if step == "World map (idea)":
    st.header("4. Where you fit on the world map (idea stub)")

    st.markdown(
        """
        This is a placeholder for a **world map of warming**, where each point or
        grid cell shows how much the climate has warmed relative to a reference
        period.

        For now, we just show a base map and your location. In the future we can:
        * Precompute a global map of warming (e.g. from ERA5).
        * Colour each land region by its **local warming**.
        * Highlight your location and nearby regions.
        """
    )

    m2 = folium.Map(location=[20, 0], zoom_start=2, tiles="CartoDB positron")
    folium.CircleMarker(
        location=[location_lat, location_lon],
        radius=6,
        color="#d73027",
        fill=True,
        fill_opacity=0.9,
    ).add_to(m2)
    st_folium(m2, width="stretch", height=420)
