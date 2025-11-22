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
    f"""
    <style>
    .hero-title {{
        font-size: 2.6rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }}
    .hero-subtitle {{
        font-size: 1.15rem;
        color: #555;
        margin-bottom: 0.5rem;
    }}
    .hero-metric {{
        font-size: 1.1rem;
        font-weight: 600;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="hero-title">How the climate has changed in your lifetime</div>
    <div class="hero-subtitle">Location: {loc_choice}</div>
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
        The charts below walk you through what this means for the temperatures
        you feel day-to-day, how your seasons have shifted, and how your
        experience compares to the rest of the world.
        """
    )

st.markdown("---")

# -----------------------------------------------------------
# SECTION A — "Day to day" experience
# -----------------------------------------------------------

st.header("1. What you feel day to day")

# 7-day zoom (fake: just use the last 7 days from local_daily)
local_daily = data["local_daily"]
last_week = local_daily.iloc[-7:]
x_7 = last_week.index.to_pydatetime()
y_7 = last_week.values

fig7 = go.Figure()
fig7.add_trace(
    go.Scatter(
        x=x_7,
        y=y_7,
        mode="lines",
        name="Hourly-like daily values",
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
    height=280,
    margin=dict(l=40, r=20, t=20, b=40),
    yaxis_title="°C",
    xaxis_title="Time",
)
st.plotly_chart(fig7, use_container_width=True, config={"displayModeBar": False})

st.markdown(
    f"""
    Over the last week in **{loc_choice}**, temperatures fluctuated between
    about **{min_val:.1f}°C** and **{max_val:.1f}°C**. This short window
    doesn’t tell us much about climate, but it grounds the story in
    the weather you actually feel.
    """
)

st.markdown("### From days to months")

# Last few months daily mean vs earlier period (fake)
last_6m = local_daily.iloc[-180:]
prev_6m = local_daily.iloc[-360:-180]
mean_recent = last_6m.mean()
mean_prev = prev_6m.mean()

figm = go.Figure()
figm.add_trace(
    go.Scatter(
        x=last_6m.index.to_pydatetime(),
        y=last_6m.values,
        mode="lines",
        name="Daily temp (recent)",
        line=dict(color="#444", width=1.3),
    )
)
figm.update_layout(
    height=280,
    margin=dict(l=40, r=20, t=20, b=40),
    yaxis_title="°C",
    xaxis_title="Date",
)
st.plotly_chart(figm, use_container_width=True, config={"displayModeBar": False})

st.markdown(
    f"""
    Comparing the **last six months** to the **six months before that**,
    the typical day has warmed by about **{(mean_recent - mean_prev):.1f}°C**.
    Over decades, those small shifts stack up.
    """
)

st.markdown("---")

# -----------------------------------------------------------
# SECTION B — Seasons then vs now (typical year)
# -----------------------------------------------------------

st.header("2. How your seasons have shifted")

local_monthly = data["local_monthly"]
# Recent 10-year mean by month vs earliest 10-year mean by month
years = local_monthly.index.year
recent_mask = years >= (years.max() - 9)
early_mask = years <= (years.min() + 9)

recent_clim = local_monthly[recent_mask].groupby(local_monthly[recent_mask].index.month).mean()
early_clim = local_monthly[early_mask].groupby(local_monthly[early_mask].index.month).mean()

months = np.arange(1, 13)

fig_typical = go.Figure()
fig_typical.add_trace(
    go.Scatter(
        x=months,
        y=early_clim.values,
        mode="lines+markers",
        name=f"{years.min()}–{years.min()+9}",
        line=dict(color="rgba(38,139,210,1.0)", width=2),
    )
)
fig_typical.add_trace(
    go.Scatter(
        x=months,
        y=recent_clim.values,
        mode="lines+markers",
        name=f"{years.max()-9}–{years.max()}",
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

# Some seasonal commentary
summer_months = [1, 2, 3] if loc_key == "mauritius" else [7, 8, 9]
winter_months = [7, 8, 9] if loc_key == "mauritius" else [1, 2, 12]

summer_delta = (recent_clim.loc[summer_months].mean() - early_clim.loc[summer_months].mean()).item()
winter_delta = (recent_clim.loc[winter_months].mean() - early_clim.loc[winter_months].mean()).item()

st.markdown(
    f"""
    In **{loc_choice}**, the typical year has shifted:

    * **Summer months** are about **{summer_delta:.1f}°C** warmer than they were
      in the {years.min()}s.
    * **Winter months** are about **{winter_delta:.1f}°C** warmer.

    That means both hot days and cool relief have moved upward. For many people,
    this feels like *more frequent heatwaves* and *shorter, milder winters*.
    """
)

st.markdown("---")

# -----------------------------------------------------------
# SECTION C — You vs the world (Guardian-style anomaly chart)
# -----------------------------------------------------------

st.header("3. Your warming vs global warming")

local_anom = data["local_anom"]
global_anom = data["global_anom"]

# build anomaly bar chart like Guardian's fig
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


st.subheader("Global anomalies (fake Copernicus-style chart)")
st.plotly_chart(
    anomaly_bars(global_anom, "Global anomaly"),
    use_container_width=True,
    config={"displayModeBar": False},
)

st.subheader(f"{loc_choice} anomalies")
st.plotly_chart(
    anomaly_bars(local_anom, f"{loc_choice} anomaly"),
    use_container_width=True,
    config={"displayModeBar": False},
)

st.markdown(
    f"""
    On this chart, bars above the black line show months warmer than the
    **1979–1990** baseline; bars below show cooler months.

    *Globally*, the warm months have become more frequent and more extreme.
    In **{loc_choice}**, the pattern is similar, but the magnitude of change
    is about **{warming_local - warming_global:+.1f}°C** compared to the
    global average.
    """
)

st.markdown("---")

st.header("4. Where you fit on the world map (idea stub)")

st.markdown(
    """
    Here we could show a world map of temperature change since the pre-industrial
    period, with your location highlighted. For the prototype, we’re using only
    local & global time series, but the final version could use a precomputed
    global dataset (e.g. ERA5 or Berkeley Earth) to render a map of warming.

    The goal of this section is to show that warming is **uneven**: land and
    high latitudes have warmed more than oceans, and some regions warm faster
    than others.
    """
)
