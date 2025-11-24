import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from datetime import datetime, timedelta
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Your Climate Story", layout="wide")

# -----------------------------------------------------------
# 1. Fake data generator (we'll later replace with real data)
# -----------------------------------------------------------

def make_fake_daily_series(years=50, baseline=23.0, trend_per_decade=0.3, noise=1.0):
    """Return a daily time series over `years` with a seasonal cycle and warming trend."""
    days = years * 365
    start_date = datetime(1975, 1, 1)
    time = pd.date_range(start_date, periods=days, freq="D")
    t = np.arange(days)

    # Seasonal cycle (simple sine)
    seasonal = 5.0 * np.sin(2 * np.pi * t / 365.0 - 0.5)

    # Linear warming trend
    trend = trend_per_decade / 10.0 * (t / 365.0)

    data = baseline + seasonal + trend + np.random.normal(0.0, noise, size=days)
    return pd.Series(data, index=time, name="temp")


def fake_local_and_global(location="mauritius"):
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

    local_daily = make_fake_daily_series(baseline=baseline, trend_per_decade=trend)
    global_daily = make_fake_daily_series(baseline=14.0, trend_per_decade=0.2, noise=0.7)

    # Aggregate to monthly and yearly means
    local_monthly = local_daily.resample("MS").mean()
    global_monthly = global_daily.resample("MS").mean()

    local_yearly = local_daily.resample("YS").mean()
    global_yearly = global_daily.resample("YS").mean()

    # anomalies vs 1979–1990 mean
    ref_period = slice("1979-01-01", "1990-12-31")
    local_ref = local_monthly[ref_period].mean()
    global_ref = global_monthly[ref_period].mean()

    local_anom = local_monthly - local_ref
    global_anom = global_monthly - global_ref

    return {
        "local_daily": local_daily,
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
# 2. Layout / "scrollytelling" structure
# -----------------------------------------------------------

# Sidebar: location selector (for now, fake)
with st.sidebar:
    st.header("Settings")
    loc_choice = st.radio("Location", ["Mauritius", "London"])
    loc_key = "mauritius" if loc_choice == "Mauritius" else "london"

    # fake coords just for map
    if loc_key == "mauritius":
        lat, lon = -20.2, 57.5
    else:
        lat, lon = 51.5074, -0.1278

data = fake_local_and_global(loc_key)

# Some headline stats
now_year = data["local_yearly"].index.year.max()
past_year = data["local_yearly"].index.year.min()
warming_local = data["local_yearly"].iloc[-1] - data["local_yearly"].iloc[0]
warming_global = data["global_yearly"].iloc[-1] - data["global_yearly"].iloc[0]

# -----------------------------------------------------------
# HERO SECTION
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

st.markdown(
    f"""
    <div class="hero-title">Your climate story</div>
    <div class="hero-subtitle">How temperatures have changed where you live</div>
    """,
    unsafe_allow_html=True,
)

col_map, col_text = st.columns([2.2, 1.3])

with col_map:
    st.write("")  # spacing
    m = folium.Map(location=[lat, lon], zoom_start=4, tiles="CartoDB positron")
    folium.CircleMarker(
        location=[lat, lon],
        radius=6,
        color="#d73027",
        fill=True,
        fill_opacity=0.9,
    ).add_to(m)
    st_folium(m, width="stretch", height=420)

with col_text:
    st.markdown("### Your place on a warming planet")
    st.markdown(
        f"""
        <p class="hero-metric">
        Since <strong>{past_year}</strong>, typical yearly temperatures in <strong>{loc_choice}</strong>
        have warmed by about <strong>{warming_local:.1f}°C</strong>.
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
        Scroll down to zoom out from last week’s weather to the last fifty years
        of climate, and see how your seasons have shifted.
        """
    )

st.markdown("---")

# -----------------------------------------------------------
# SECTION 1 — "Zooming out": week → month → year → 50 years
# -----------------------------------------------------------

st.header("1. Zooming out: from days to decades")

local_daily = data["local_daily"]
local_monthly = data["local_monthly"]

# 1A. Last 7 days
last_week = local_daily.iloc[-7:]
x_7 = last_week.index.to_pydatetime()
y_7 = last_week.values

fig7 = go.Figure()
fig7.add_trace(
    go.Scatter(
        x=x_7,
        y=y_7,
        mode="lines",
        name="Daily values (recent week)",
        line=dict(color="#444", width=2),
    )
)

imax = int(np.argmax(y_7))
imin = int(np.argmin(y_7))
max_val = float(y_7[imax])
min_val = float(y_7[imin])

fig7.add_annotation(
    x=x_7[imax],
    y=max_val,
    xref="x",
    yref="y",
    text=f"max {max_val:.1f}°C",
    showarrow=False,
    font=dict(color="rgba(220, 50, 47, 1.0)", size=14),
    yshift=10,
)
fig7.add_annotation(
    x=x_7[imin],
    y=min_val,
    xref="x",
    yref="y",
    text=f"min {min_val:.1f}°C",
    showarrow=False,
    font=dict(color="rgba(38, 139, 210, 1.0)", size=14),
    yshift=-14,
)
fig7.update_layout(
    height=260,
    margin=dict(l=40, r=20, t=20, b=40),
    yaxis_title="°C",
    xaxis_title="Last 7 days",
)
st.plotly_chart(fig7, use_container_width=True, config={"displayModeBar": False})

st.markdown(
    f"""
    Over the last week in **{loc_choice}**, temperatures swung between about
    **{min_val:.1f}°C** and **{max_val:.1f}°C**. This is the scale of day-to-day
    weather you actually feel.
    """
)

st.markdown("### Last month — daily temperatures")

# 1B. Last 30 days (daily)
last_30 = local_daily.iloc[-30:]
fig30 = go.Figure()
fig30.add_trace(
    go.Scatter(
        x=last_30.index.to_pydatetime(),
        y=last_30.values,
        mode="lines",
        name="Daily temperature",
        line=dict(color="#444", width=1.6),
    )
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
    Zooming out to a month, the ups and downs start to show the rhythm of days
    and nights and passing weather systems.
    """
)

st.markdown("### Last year — the seasonal cycle")

# 1C. Last 365 days (daily + 7-day rolling mean)
last_365 = local_daily.iloc[-365:]
smooth_365 = last_365.rolling(7, center=True).mean()

fig365 = go.Figure()
fig365.add_trace(
    go.Scatter(
        x=last_365.index.to_pydatetime(),
        y=last_365.values,
        mode="lines",
        name="Daily temperature",
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
fig365.update_layout(
    height=260,
    margin=dict(l=40, r=20, t=20, b=40),
    yaxis_title="°C",
    xaxis_title=f"{now_year-1}–{now_year}",
)
st.plotly_chart(fig365, use_container_width=True, config={"displayModeBar": False})

st.markdown(
    f"""
    Over a full year you can clearly see the **seasonal cycle**: the rise into
    the hottest months and the slide back down. Climate change adds a slow
    upward shift on top of this familiar pattern.
    """
)

st.markdown("### Last 50 years — monthly averages")

# 1D. Last ~50 years (monthly means)
fig50 = go.Figure()
fig50.add_trace(
    go.Scatter(
        x=local_monthly.index.to_pydatetime(),
        y=local_monthly.values,
        mode="lines",
        name="Monthly mean temperature",
        line=dict(color="#444", width=1.8),
    )
)
fig50.update_layout(
    height=280,
    margin=dict(l=40, r=20, t=20, b=40),
    yaxis_title="°C",
    xaxis_title="Year",
)
st.plotly_chart(fig50, use_container_width=True, config={"displayModeBar": False})

st.markdown(
    f"""
    When you zoom all the way out to nearly **{now_year - past_year} years**, the
    year-to-year noise fades and a clear trend emerges: **{loc_choice}** is now
    roughly **{warming_local:.1f}°C** warmer on average than it was in the
    mid-{past_year}s.
    """
)

st.markdown("---")

# -----------------------------------------------------------
# SECTION 2 — Seasons then vs now (typical year)
# -----------------------------------------------------------

st.header("2. How your seasons have shifted")

years_all = local_monthly.index.year
recent_mask = years_all >= (years_all.max() - 9)
early_mask = years_all <= (years_all.min() + 9)

recent_clim = local_monthly[recent_mask].groupby(local_monthly[recent_mask].index.month).mean()
early_clim = local_monthly[early_mask].groupby(local_monthly[early_mask].index.month).mean()

months = np.arange(1, 13)

fig_typical = go.Figure()
fig_typical.add_trace(
    go.Scatter(
        x=months,
        y=early_clim.values,
        mode="lines+markers",
        name=f"{years_all.min()}–{years_all.min()+9}",
        line=dict(color="rgba(38,139,210,1.0)", width=2),
    )
)
fig_typical.add_trace(
    go.Scatter(
        x=months,
        y=recent_clim.values,
        mode="lines+markers",
        name=f"{years_all.max()-9}–{years_all.max()}",
        line=dict(color="rgba(220,50,47,1.0)", width=2),
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

# Simple seasonal commentary
if loc_key == "mauritius":
    summer_months = [1, 2, 3]
    winter_months = [7, 8, 9]
else:  # london
    summer_months = [6, 7, 8]
    winter_months = [12, 1, 2]

summer_delta = (recent_clim.loc[summer_months].mean() - early_clim.loc[summer_months].mean()).item()
winter_delta = (recent_clim.loc[winter_months].mean() - early_clim.loc[winter_months].mean()).item()

st.markdown(
    f"""
    In **{loc_choice}**, the typical year has shifted:

    * **Summer months** are about **{summer_delta:.1f}°C** warmer than they were
      in the {years_all.min()}s.
    * **Cooler months** are about **{winter_delta:.1f}°C** warmer.

    In a full implementation, this is where we can also show a **“typical year
    of daily extremes”** — the hottest and coolest parts of each day now
    compared with 50 years ago, using daily max/min data from reanalysis.
    """
)

st.markdown("---")

# -----------------------------------------------------------
# SECTION 3 — You vs the world (anomaly charts)
# -----------------------------------------------------------

st.header("3. Your warming vs global warming")

local_anom = data["local_anom"]
global_anom = data["global_anom"]

def anomaly_bars(series, label):
    x = series.index
    y = series.values
    colors = np.where(y >= 0, "rgba(180, 0, 120, 0.8)", "rgba(0, 130, 0, 0.8)")
    fig = go.Figure(
        go.Bar(
            x=x,
            y=y,
            marker_color=colors,
            name=label,
        )
    )
    fig.add_hline(y=0, line_width=2, line_color="black")
    fig.update_layout(
        height=280,
        margin=dict(l=40, r=20, t=20, b=40),
        yaxis_title="°C vs 1979–1990 baseline",
        xaxis_title="Year",
        showlegend=False,
    )
    return fig

st.subheader("Global anomalies (relative to 1979–1990)")
st.plotly_chart(
    anomaly_bars(global_anom, "Global anomaly"),
    use_container_width=True,
    config={"displayModeBar": False},
)

st.subheader(f"{loc_choice} anomalies (same baseline)")
st.plotly_chart(
    anomaly_bars(local_anom, f"{loc_choice} anomaly"),
    use_container_width=True,
    config={"displayModeBar": False},
)

st.markdown(
    f"""
    Each bar shows how much warmer or cooler a month was compared with the
    **1979–1990 average** (the black line).

    * Bars **above** the line (magenta) are months warmer than that baseline.
    * Bars **below** the line (green) are months cooler.

    In **{loc_choice}**, the recent decades show many more warm-anomaly months,
    mirroring the global pattern but with a magnitude of roughly
    **{warming_local - warming_global:+.1f}°C** compared with the global average.
    """
)

st.markdown("---")

st.header("4. Where you fit on the world map (idea stub)")

st.markdown(
    """
    In the final version, this section would show a world map of temperature
    change since the pre-industrial period, with your location highlighted.

    For performance and reliability, the map would be built from a precomputed
    global dataset (for example a coarse grid from ERA5 or Berkeley Earth),
    loaded once on the server and reused for all visitors.
    """
)
