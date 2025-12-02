from pathlib import Path
import xarray as xr
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from datetime import datetime
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Your Climate Story", layout="wide")

STORY_START_YEAR = 1979
STORY_END_YEAR = 2024

DATA_DIR = Path("story_climatology")

# Hardcode Port Louis
DEFAULT_SLUG = "city_mu_port_louis"

@st.cache_data
def load_city_climatology(slug: str) -> xr.Dataset:
    """Load precomputed climatology NetCDF for a given location slug."""
    path = DATA_DIR / f"clim_{slug}_{STORY_START_YEAR}_{STORY_END_YEAR}.nc"
    ds = xr.load_dataset(path)
    return ds

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

with st.sidebar:
    st.header("Settings")
    loc_choice = st.radio("Location", ["Mauritius", "London"])
    loc_key = "mauritius" if loc_choice == "Mauritius" else "london"

    if loc_key == "mauritius":
        lat, lon = -20.2, 57.5
    else:
        lat, lon = 51.5074, -0.1278

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

data = fake_local_and_global(loc_key)

now_year = data["local_yearly"].index.year.max()
past_year = data["local_yearly"].index.year.min()
warming_local = data["local_yearly"].iloc[-1] - data["local_yearly"].iloc[0]
warming_global = data["global_yearly"].iloc[-1] - data["global_yearly"].iloc[0]

local_daily = data["local_daily"]
local_hourly = data["local_hourly"]
local_monthly = data["local_monthly"]

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
# Small helper: annotate min/max on a curve
# -----------------------------------------------------------


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

    # Max annotation
    fig.add_annotation(
        x=x_max,
        y=max_val,
        xref="x",
        yref="y",
        text=f"{label_prefix}max {max_val:.1f}°C",
        showarrow=False,
        font=dict(color="rgba(220,50,47,1.0)", size=13),
        yshift=10,
    )
    # Min annotation
    fig.add_annotation(
        x=x_min,
        y=min_val,
        xref="x",
        yref="y",
        text=f"{label_prefix}min {min_val:.1f}°C",
        showarrow=False,
        font=dict(color="rgba(38,139,210,1.0)", size=13),
        yshift=-10,
    )

    return min_val, max_val

def last_n_days(series: pd.Series, n: int):
    if series.empty:
        return series
    cutoff = series.index.max() - pd.Timedelta(days=n)
    return series.loc[series.index >= cutoff]

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
        m = folium.Map(location=[lat, lon], zoom_start=4, tiles="CartoDB positron")
        folium.CircleMarker(
            location=[lat, lon],
            radius=8,
            color="#d73027",
            fill=True,
            fill_opacity=0.9,
        ).add_to(m)
        st_folium(m, width="stretch", height=420)

    with col_text:
        st.markdown(
            f"""
            <p class="hero-metric">
            Since the mid-{past_year}s, the typical yearly temperature in
            <strong>{loc_choice}</strong> has warmed by about
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
    ds = load_city_climatology(DEFAULT_SLUG)
    loc_name = ds.attrs.get("name_long", "this location")

    st.header("1. Zooming out: from days to decades")

    # 1A. Last 7 days — hourly + daily mean
    st.subheader("Last week — hourly temperature and daily mean")

    last_week_hourly = last_n_days(local_hourly,7)
    if last_week_hourly.empty:
        st.warning("No (fake) hourly data available for last 7 days.")
    else:
        week_daily_mean = last_week_hourly.resample("D").mean()

        fig7 = go.Figure()
        # Hourly curve
        fig7.add_trace(
            go.Scatter(
                x=last_week_hourly.index.to_pydatetime(),
                y=last_week_hourly.values,
                mode="lines",
                name="Hourly temperature",
                line=dict(
                    color="rgba(120,120,120,0.6)",
                    width=1,
                    shape="spline",
                ),
            )
        )
        # Daily mean
        fig7.add_trace(
            go.Scatter(
                x=week_daily_mean.index.to_pydatetime(),
                y=week_daily_mean.values,
                mode="lines+markers",
                name="Daily mean",
                line=dict(
                    color="#1f77b4",
                    width=2,
                    shape="spline",
                ),
                marker=dict(size=6),
            )
        )

        min_val, max_val = annotate_minmax_on_series(
            fig7,
            last_week_hourly.index.to_pydatetime(),
            last_week_hourly.values,
        )

        fig7.update_layout(
            height=260,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="°C",
            xaxis_title="Last 7 days",
        )
        st.plotly_chart(fig7, width="stretch", config={"displayModeBar": False})

        if min_val is not None and max_val is not None:
            st.markdown(
                f"""
                Over the last week in **{loc_choice}**, the air temperature has oscillated
                between about **{min_val:.1f}°C** at the coolest moments of the night and
                **{max_val:.1f}°C** at the warmest parts of the day.
                """
            )

    # 1B. Last 30 days — daily + 3-day mean + min/max
    st.subheader("Last month — daily temperatures")

    last_30 = last_n_days(local_daily,30)
    if last_30.empty:
        st.warning("No daily data available for last 30 days.")
    else:
        smooth_30 = last_30.rolling(3, center=True).mean()

        fig30 = go.Figure()
        fig30.add_trace(
            go.Scatter(
                x=last_30.index.to_pydatetime(),
                y=last_30.values,
                mode="lines",
                name="Daily mean temperature",
                line=dict(
                    color="rgba(150,150,150,0.7)",
                    width=1,
                    shape="spline",
                ),
            )
        )
        fig30.add_trace(
            go.Scatter(
                x=smooth_30.index.to_pydatetime(),
                y=smooth_30.values,
                mode="lines",
                name="3-day mean",
                line=dict(
                    color="#1f77b4",
                    width=2,
                    shape="spline",
                ),
            )
        )

        min30, max30 = annotate_minmax_on_series(
            fig30, last_30.index.to_pydatetime(), last_30.values
        )

        fig30.update_layout(
            height=260,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="°C",
            xaxis_title="Last 30 days",
        )
        st.plotly_chart(fig30, width="stretch", config={"displayModeBar": False})

        st.markdown(
            """
            Over a month, the jagged ups and downs reflect **passing weather systems**:
            short warm spells, cooler snaps, and the background shift between seasons.
            Here we’re looking at **daily averages**, not the full day–night cycle.
            """
        )

    # 1C. Last year — the seasonal cycle
    st.subheader("Last year — the seasonal cycle")

    da_daily = ds["t2m_daily_mean_c"]  # (time)
    time_all = pd.to_datetime(da_daily["time"].values)
    temp_all = da_daily.values

    # Take the last 365 days in the dataset (typically the last full year)
    if len(time_all) > 365:
        end_time = time_all.max()
        start_time = end_time - pd.Timedelta(days=365)
        mask = (time_all >= start_time)
        time_last = time_all[mask]
        temp_last = temp_all[mask]
    else:
        time_last = time_all
        temp_last = temp_all

    year_label = time_last.max().year

    # --- 2. Build daily + 7-day mean series ---
    s_daily = pd.Series(temp_last, index=time_last)
    s_smooth = s_daily.rolling(window=7, center=True, min_periods=2).mean()

    # --- 3. Find min / max over this last year ---
    imax = int(np.nanargmax(s_daily.values))
    imin = int(np.nanargmin(s_daily.values))
    t_max = s_daily.index[imax]
    t_min = s_daily.index[imin]
    v_max = float(s_daily.values[imax])
    v_min = float(s_daily.values[imin])

    # --- 4. Build the figure (keep the old look: grey daily, blue 7-day mean) ---
    fig_last_year = go.Figure()

    # Daily curve — light grey fine wiggles
    fig_last_year.add_trace(
        go.Scatter(
            x=time_last,
            y=s_daily.values,
            mode="lines",
            name="Daily mean",
            line=dict(
                color="rgba(180,180,180,0.7)",
                width=1,
                shape="spline",
            ),
        )
    )

    # 7-day mean — smoother blue curve
    fig_last_year.add_trace(
        go.Scatter(
            x=time_last,
            y=s_smooth.values,
            mode="lines",
            name="7-day mean",
            line=dict(
                color="rgba(38,139,210,0.9)",
                width=3,
                shape="spline",
            ),
        )
    )

    # Annotations for extremes (no extra markers, just text near the curve)
    fig_last_year.add_annotation(
        x=t_max,
        y=v_max,
        text=f"max {v_max:.1f}°C",
        showarrow=True,
        arrowhead=2,
        ax=40,
        ay=-30,
        bgcolor="rgba(255,255,255,0.8)",
        bordercolor="rgba(220,50,47,0.8)",
        borderwidth=1,
        font=dict(size=11),
    )

    fig_last_year.add_annotation(
        x=t_min,
        y=v_min,
        text=f"min {v_min:.1f}°C",
        showarrow=True,
        arrowhead=2,
        ax=-40,
        ay=30,
        bgcolor="rgba(255,255,255,0.8)",
        bordercolor="rgba(38,139,210,0.8)",
        borderwidth=1,
        font=dict(size=11),
    )

    fig_last_year.update_layout(
        height=400,
        margin=dict(l=40, r=20, t=30, b=40),
        xaxis_title=f"Date (last year in dataset: {year_label})",
        yaxis_title="Temperature (°C)",
        showlegend=True,
    )

    st.plotly_chart(
        fig_last_year,
        width="stretch",
        config={"displayModeBar": False},
    )

    # Optional explanatory text (you can tweak the copy)
    st.markdown(
        f"""
    Over the most recent full year in the dataset ({year_label}), you can see the
    day-to-day ups and downs riding on top of the slower march of the seasons in **{loc_name}**.
    The grey curve shows each day's mean temperature, and the blue line smooths this
    into a 7-day average so the seasonal pattern is easier to see.
    """
    )

    st.caption(
        f"Last-year extremes in {loc_name}: "
        f"maximum daily mean ≈ **{v_max:.1f}°C**, minimum daily mean ≈ **{v_min:.1f}°C**."
    )

    # 1D. Last 5 years — 7-day mean and monthly mean
    st.subheader("Last 5 years — smoothing the seasons")

    five_years_ago = local_daily.index.max() - pd.DateOffset(years=5)
    last_5y = local_daily[local_daily.index >= five_years_ago]

    if last_5y.empty:
        st.warning("No daily data available for the last 5 years.")
    else:
        smooth_7d_5y = last_5y.rolling(7, center=True).mean()
        monthly_5y = last_5y.resample("MS").mean()

        fig5y = go.Figure()
        fig5y.add_trace(
            go.Scatter(
                x=smooth_7d_5y.index.to_pydatetime(),
                y=smooth_7d_5y.values,
                mode="lines",
                name="7-day mean",
                line=dict(
                    color="rgba(150,150,150,0.7)",
                    width=1,
                    shape="spline",
                ),
            )
        )
        fig5y.add_trace(
            go.Scatter(
                x=monthly_5y.index.to_pydatetime(),
                y=monthly_5y.values,
                mode="lines+markers",
                name="Monthly mean",
                line=dict(
                    color="#d95f02",
                    width=2,
                    shape="spline",
                ),
                marker=dict(size=4),
            )
        )
        fig5y.update_layout(
            height=260,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="°C",
            xaxis_title="Last 5 years",
        )
        st.plotly_chart(fig5y, width="stretch", config={"displayModeBar": False})

        st.markdown(
            """
            Over several years, the individual days blur into a smoother picture:
            we start to think in terms of **typical months** rather than daily swings.
            """
        )

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
    yr_series = pd.Series(t_year, index=pd.Index(years, name="year"))
    yr_smooth = yr_series.rolling(window=5, center=True, min_periods=2).mean()
    years_smooth = yr_smooth.index.values
    t_smooth = yr_smooth.values

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
    fig_50.add_trace(
        go.Scatter(
            x=time_mon,
            y=temp_mon,
            mode="lines",
            name="Monthly mean",
            line=dict(
                color="rgba(150,150,150,0.7)",
                width=1,
                shape="spline",
            ),
        )
    )

    # 5-year mean (thick orange spline)
    if np.isfinite(t_smooth).any():
        x_smooth = [datetime(int(y), 1, 1) for y in years_smooth]
        fig_50.add_trace(
            go.Scatter(
                x=x_smooth,
                y=t_smooth,
                mode="lines",
                name="5-year mean",
                line=dict(
                    color="#d95f02",
                    width=3,
                    shape="spline",
                ),
            )
        )

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
    
    # --- 5. Text: “zoom out” narrative + sign-sensitive wording ---

    # Use the 5-year mean to describe overall change, if available
    mask = np.isfinite(t_smooth)
    if mask.any():
        ys = years_smooth[mask]
        vs = t_smooth[mask]
        delta = float(vs[-1] - vs[0])
        start_year = int(ys[0])
        end_year = int(ys[-1])

        if abs(delta) < 0.15:
            # ~flat
            change_text = (
                f"has changed very little — the long-term average is almost the same "
                f"now as it was in the late {start_year}s."
            )
        elif delta > 0:
            # warmer
            change_text = (
                f"is now roughly **{delta:.1f}°C warmer on average** than it was "
                f"in the late {start_year}s."
            )
        else:
            # cooler
            change_text = (
                f"is now roughly **{abs(delta):.1f}°C cooler on average** than it was "
                f"in the late {start_year}s — a smaller change than in many places."
            )

        st.markdown(
            f"""
    When you zoom all the way out over the last few decades, the year-to-year noise
    fades and a clear pattern emerges. In **{loc_name}**, the climate {change_text}
            """
        )
    else:
        st.markdown(
            f"""
    When you zoom all the way out over the last few decades, the year-to-year noise
    fades and a clearer pattern would normally emerge — but here the data window is too short
    to say much yet for **{loc_name}**.
            """
        )

    # 1F. A simple 25-year projection, assuming the same trend continues
    st.subheader("Looking 25 years ahead (simple trend extension)")

    local_yearly = data["local_yearly"]
    years = local_yearly.index.year.values.astype(float)
    temps = local_yearly.values.astype(float)

    # Simple linear fit over all years
    coeffs = np.polyfit(years, temps, 1)
    a, b = coeffs  # temp ≈ a * year + b

    future_years = np.arange(years.max() + 1, years.max() + 26)
    future_temps = a * future_years + b

    fig_future = go.Figure()
    fig_future.add_trace(
        go.Scatter(
            x=years,
            y=temps,
            mode="lines+markers",
            name="Observed yearly mean",
            line=dict(
                color="#1f78b4",
                width=2,
                shape="spline",
            ),
            marker=dict(size=4),
        )
    )
    fig_future.add_trace(
        go.Scatter(
            x=future_years,
            y=future_temps,
            mode="lines",
            name="Linear projection",
            line=dict(
                color="#e31a1c",
                width=2,
                dash="dash",
                shape="spline",
            ),
        )
    )
    fig_future.update_layout(
        height=280,
        margin=dict(l=40, r=20, t=20, b=40),
        yaxis_title="°C",
        xaxis_title="Year",
    )
    st.plotly_chart(fig_future, width="stretch", config={"displayModeBar": False})

    delta_future = float(future_temps[-1] - temps[0])
    st.markdown(
        f"""
        This simple line just extends the **past trend** into the future.  
        If warming continued at the same pace, a typical year in the late
        {int(future_years[-1])}s would be about **{delta_future:.1f}°C** warmer than
        the earliest years in this record.

        In a real version of this page, we would replace this simple line with
        **actual projections** from climate models.
        """
    )

# -----------------------------------------------------------
# STEP: SEASONS THEN VS NOW
# -----------------------------------------------------------
if step == "Seasons then vs now":
    st.header("2. How your seasons have shifted")

    # 2A. Monthly mean in early vs recent decades
    years_all = local_monthly.index.year
    recent_mask = years_all >= (years_all.max() - 9)
    early_mask = years_all <= (years_all.min() + 9)

    recent_clim = local_monthly[recent_mask].groupby(
        local_monthly[recent_mask].index.month
    ).mean()
    past_clim = local_monthly[early_mask].groupby(
        local_monthly[early_mask].index.month
    ).mean()

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    fig_seasons = go.Figure()
    fig_seasons.add_trace(
        go.Scatter(
            x=months,
            y=past_clim.values,
            mode="lines+markers",
            name=f"Early decade (around {years_all.min()}s)",
            line=dict(
                color="rgba(150,150,150,1.0)",
                width=2,
                shape="spline",
            ),
            marker=dict(size=6),
        )
    )
    fig_seasons.add_trace(
        go.Scatter(
            x=months,
            y=recent_clim.values,
            mode="lines+markers",
            name=f"Recent decade (around {years_all.max()}s)",
            line=dict(
                color="#d95f02",
                width=3,
                shape="spline",
            ),
            marker=dict(size=6),
        )
    )

    fig_seasons.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="lines+markers+text",
            name="ΔT (month highlight)",
            line=dict(color="rgba(117,107,177,0.9)", width=3),
            marker=dict(size=10),
            text=[""],
            showlegend=False,
        )
    )

    # Build frames: for each month, draw a vertical segment between past & recent
    frames = []
    for i, m in enumerate(months):
        y_p = float(past_clim.values[i])
        y_r = float(recent_clim.values[i])
        delta = y_r - y_p
        mid_y = 0.5 * (y_p + y_r)

        frames.append(
            go.Frame(
                name=f"month_{i}",
                data=[
                    {},  # trace 0 (past) unchanged
                    {},  # trace 1 (recent) unchanged
                    go.Scatter(
                        x=[m, m],
                        y=[y_p, y_r],
                        mode="lines+markers+text",
                        line=dict(color="rgba(117,107,177,0.9)", width=3),
                        marker=dict(size=10),
                        text=[None, f"{delta:+.1f}°C"],
                        textposition="top right",
                        showlegend=False,
                    ),
                ],
            )
        )

    fig_seasons.frames = frames

    fig_seasons.update_layout(
        xaxis_title="Month",
        yaxis_title="Monthly mean temperature (°C)",
        margin=dict(l=40, r=20, t=60, b=60),
        sliders=[
            dict(
                active=0,
                x=0.0,
                y=-0.15,
                xanchor="left",
                yanchor="top",
                currentvalue={"visible": True, "prefix": "Month: "},
                steps=[
                    dict(
                        label=months[i],
                        method="animate",
                        args=[
                            [f"month_{i}"],
                            {
                                "frame": {"duration": 0, "redraw": True},
                                "mode": "immediate",
                                "transition": {"duration": 0},
                            },
                        ],
                    )
                    for i in range(len(months))
                ],
            )
        ],
    )
    st.plotly_chart(fig_seasons, width="stretch", config={"displayModeBar": False})

    # 2B. Min–max envelopes for early vs recent climates
    st.subheader("How the range of monthly temperatures has changed")

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
        In **{loc_choice}**, the typical year has shifted:

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
        location=[lat, lon],
        radius=6,
        color="#d73027",
        fill=True,
        fill_opacity=0.9,
    ).add_to(m2)
    st_folium(m2, width="stretch", height=420)
