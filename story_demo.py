import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from datetime import datetime
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Your Climate Story", layout="wide")

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
    hourly_index = pd.date_range(start, end, freq="H")

    # Interpolate daily mean onto hourly grid
    # (convert timestamps to int nanoseconds for np.interp)
    x_daily = daily.index.view("int64")
    x_hourly = hourly_index.view("int64")
    base = np.interp(x_hourly, x_daily, daily.values)

    # Add a simple diurnal cycle (max mid-afternoon, min pre-dawn)
    hours = np.arange(len(hourly_index))
    hour_of_day = hours % 24
    diurnal = 4.0 * np.sin(2 * np.pi * (hour_of_day - 15) / 24.0)  # peak around 15:00

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

    st.markdown("### Story step")
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
    st.header("1. Zooming out: from days to decades")

    # 1A. Last 7 days — hourly + daily mean
    st.markdown("### Last week — hourly temperature and daily mean")

    # Take last 7 days from the hourly series
    last_week_hourly = local_hourly.last("7D")
    if last_week_hourly.empty:
        st.warning("No (fake) hourly data available for last 7 days.")
    else:
        # Daily mean from hourly
        week_daily_mean = last_week_hourly.resample("D").mean()

        fig7 = go.Figure()
        # Hourly curve
        fig7.add_trace(
            go.Scatter(
                x=last_week_hourly.index.to_pydatetime(),
                y=last_week_hourly.values,
                mode="lines",
                name="Hourly temperature",
                line=dict(color="rgba(120,120,120,0.6)", width=1),
            )
        )
        # Daily mean
        fig7.add_trace(
            go.Scatter(
                x=week_daily_mean.index.to_pydatetime(),
                y=week_daily_mean.values,
                mode="lines+markers",
                name="Daily mean",
                line=dict(color="#1f77b4", width=2),
                marker=dict(size=6),
            )
        )

        # Min/max over the week (based on hourly)
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
        st.plotly_chart(fig7, use_container_width=True, config={"displayModeBar": False})

        if min_val is not None and max_val is not None:
            st.markdown(
                f"""
                Over the last week in **{loc_choice}**, the air temperature has oscillated
                between about **{min_val:.1f}°C** at the coolest moments of the night and
                **{max_val:.1f}°C** at the warmest parts of the day.
                """
            )

    # 1B. Last 30 days — daily + 3-day mean + min/max
    st.markdown("### Last month — daily temperatures")

    last_30 = local_daily.last("30D")
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
                line=dict(color="rgba(150,150,150,0.7)", width=1),
            )
        )
        fig30.add_trace(
            go.Scatter(
                x=smooth_30.index.to_pydatetime(),
                y=smooth_30.values,
                mode="lines",
                name="3-day mean",
                line=dict(color="#1f77b4", width=2),
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
        st.plotly_chart(fig30, use_container_width=True, config={"displayModeBar": False})

        st.markdown(
            """
            Over a month, the jagged ups and downs reflect **passing weather systems**:
            short warm spells, cooler snaps, and the background shift between seasons.
            Here we’re looking at **daily averages**, not the full day–night cycle.
            """
        )

    # 1C. Last year — the seasonal cycle
    st.markdown("### Last year — the seasonal cycle")

    last_365 = local_daily.last("365D")
    if last_365.empty:
        st.warning("No daily data available for last year.")
    else:
        smooth_365 = last_365.rolling(7, center=True).mean()

        fig365 = go.Figure()
        fig365.add_trace(
            go.Scatter(
                x=last_365.index.to_pydatetime(),
                y=last_365.values,
                mode="lines",
                name="Daily mean",
                line=dict(color="rgba(150,150,150,0.7)", width=1),
            )
        )
        fig365.add_trace(
            go.Scatter(
                x=smooth_365.index.to_pydatetime(),
                y=smooth_365.values,
                mode="lines",
                name="7-day mean",
                line=dict(color="#1f77b4", width=2),
            )
        )

        min365, max365 = annotate_minmax_on_series(
            fig365, last_365.index.to_pydatetime(), last_365.values
        )

        fig365.update_layout(
            height=260,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="°C",
            xaxis_title=f"Last 12 months",
        )
        st.plotly_chart(fig365, use_container_width=True, config={"displayModeBar": False})

        st.markdown(
            """
            Over a full year you can clearly see the **seasonal cycle**: the rise into
            the hottest months and the slide back down. Climate change adds a slow
            upward shift on top of this familiar pattern.
            """
        )

    # 1D. Last 5 years — 7-day mean and monthly mean
    st.markdown("### Last 5 years — smoothing the seasons")

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
                line=dict(color="rgba(150,150,150,0.7)", width=1),
            )
        )
        fig5y.add_trace(
            go.Scatter(
                x=monthly_5y.index.to_pydatetime(),
                y=monthly_5y.values,
                mode="lines+markers",
                name="Monthly mean",
                line=dict(color="#d95f02", width=2),
                marker=dict(size=4),
            )
        )
        fig5y.update_layout(
            height=260,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="°C",
            xaxis_title="Last 5 years",
        )
        st.plotly_chart(fig5y, use_container_width=True, config={"displayModeBar": False})

        st.markdown(
            """
            Over several years, the individual days blur into a smoother picture:
            we start to think in terms of **typical months** rather than daily swings.
            """
        )

    # 1E. Last ~50 years — monthly averages and trend
    st.markdown("### Last 50 years — monthly averages and trend")

    fig50 = go.Figure()
    fig50.add_trace(
        go.Scatter(
            x=local_monthly.index.to_pydatetime(),
            y=local_monthly.values,
            mode="lines",
            name="Monthly mean temperature",
            line=dict(color="rgba(150,150,150,0.7)", width=1),
        )
    )

    roll_5y = local_monthly.rolling(60, center=True).mean()
    fig50.add_trace(
        go.Scatter(
            x=roll_5y.index.to_pydatetime(),
            y=roll_5y.values,
            mode="lines",
            name="5-year mean",
            line=dict(color="#d95f02", width=3),
        )
    )

    fig50.update_layout(
        height=280,
        margin=dict(l=40, r=20, t=20, b=40),
        yaxis_title="°C",
        xaxis_title="Year",
    )
    st.plotly_chart(fig50, use_container_width=True, config={"displayModeBar": False})

    approx_years = (now_year - past_year) + 1
    st.markdown(
        f"""
        When you zoom all the way out to about **{approx_years} years**, the
        year-to-year noise fades and a clear trend emerges: **{loc_choice}** is now
        roughly **{warming_local:.1f}°C** warmer on average than it was in the
        mid-{past_year}s.
        """
    )

    # 1F. A simple 25-year projection, assuming the same trend continues
    st.markdown("### Looking 25 years ahead (simple trend extension)")

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
            line=dict(color="#1f78b4", width=2),
            marker=dict(size=4),
        )
    )
    fig_future.add_trace(
        go.Scatter(
            x=future_years,
            y=future_temps,
            mode="lines",
            name="Linear projection",
            line=dict(color="#e31a1c", width=2, dash="dash"),
        )
    )
    fig_future.update_layout(
        height=280,
        margin=dict(l=40, r=20, t=20, b=40),
        yaxis_title="°C",
        xaxis_title="Year",
    )
    st.plotly_chart(fig_future, use_container_width=True, config={"displayModeBar": False})

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
    early_clim = local_monthly[early_mask].groupby(
        local_monthly[early_mask].index.month
    ).mean()

    months = np.arange(1, 13)

    fig_typical = go.Figure()
    fig_typical.add_trace(
        go.Scatter(
            x=months,
            y=early_clim.values,
            mode="lines+markers",
            name=f"Early decade (around {years_all.min()}s)",
            line=dict(color="rgba(150,150,150,1.0)", width=2),
            marker=dict(size=6),
        )
    )
    fig_typical.add_trace(
        go.Scatter(
            x=months,
            y=recent_clim.values,
            mode="lines+markers",
            name=f"Recent decade (around {years_all.max()}s)",
            line=dict(color="#d95f02", width=3),
            marker=dict(size=6),
        )
    )

    fig_typical.update_layout(
        height=320,
        margin=dict(l=40, r=20, t=20, b=40),
        yaxis_title="Monthly mean °C",
        xaxis_title="Month",
        xaxis=dict(tickmode="array", tickvals=months),
    )
    st.plotly_chart(fig_typical, use_container_width=True, config={"displayModeBar": False})

    # 2B. Min–max envelopes for early vs recent climates
    st.markdown("### How the range of monthly temperatures has changed")

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

    # Left: past envelope
    with col_past:
        fig_env_past = go.Figure()
        fig_env_past.add_trace(
            go.Scatter(
                x=months,
                y=early_min.values,
                mode="lines",
                name="Min",
                line=dict(color="rgba(38,139,210,1.0)", width=2),
            )
        )
        fig_env_past.add_trace(
            go.Scatter(
                x=months,
                y=early_max.values,
                mode="lines",
                name="Max",
                line=dict(color="rgba(220,50,47,1.0)", width=2),
                fill="tonexty",
                fillcolor="rgba(158,202,225,0.3)",
            )
        )
        fig_env_past.update_layout(
            height=280,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="Daily temperature °C",
            xaxis_title="Month",
            xaxis=dict(tickmode="array", tickvals=months),
            title="Earlier climate (monthly min–max envelope)",
        )
        st.plotly_chart(
            fig_env_past, use_container_width=True, config={"displayModeBar": False}
        )

    # Right: recent envelope
    with col_recent:
        fig_env_recent = go.Figure()
        fig_env_recent.add_trace(
            go.Scatter(
                x=months,
                y=recent_min.values,
                mode="lines",
                name="Min",
                line=dict(color="rgba(38,139,210,1.0)", width=2),
            )
        )
        fig_env_recent.add_trace(
            go.Scatter(
                x=months,
                y=recent_max.values,
                mode="lines",
                name="Max",
                line=dict(color="rgba(220,50,47,1.0)", width=2),
                fill="tonexty",
                fillcolor="rgba(254,224,210,0.3)",
            )
        )
        fig_env_recent.update_layout(
            height=280,
            margin=dict(l=40, r=20, t=20, b=40),
            yaxis_title="Daily temperature °C",
            xaxis_title="Month",
            xaxis=dict(tickmode="array", tickvals=months),
            title="Recent climate (monthly min–max envelope)",
        )
        st.plotly_chart(
            fig_env_recent, use_container_width=True, config={"displayModeBar": False}
        )

    # 2C. Summary text
    if loc_key == "mauritius":
        summer_months = [1, 2, 3]
        winter_months = [7, 8, 9]
    else:  # london
        summer_months = [6, 7, 8]
        winter_months = [12, 1, 2]

    summer_delta = (
        recent_clim.loc[summer_months].mean() - early_clim.loc[summer_months].mean()
    ).item()
    winter_delta = (
        recent_clim.loc[winter_months].mean() - early_clim.loc[winter_months].mean()
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
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with col_global:
        st.plotly_chart(
            anomaly_bars(global_anom, "Global average — monthly anomalies"),
            use_container_width=True,
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
