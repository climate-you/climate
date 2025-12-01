import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objs as go

# ------------------------------
# Page config
# ------------------------------
st.set_page_config(
    page_title="Monte Carlo Global Warming Demo",
    layout="wide",
)

st.markdown(
    """
    # Monte Carlo sampling of global temperature (toy demo)

    This page uses **fake data** to illustrate an idea:
    > how randomly sampling temperatures around the world, in two different time
    > periods, gradually reveals a difference in the **global mean**.

    We’ll pretend we have a global gridded temperature dataset and:
    * Define a simple "past" climate (1971–2000).
    * Define a "recent" climate (1991–2020) that is a bit warmer everywhere.
    * Draw random samples of (lat, lon, year).
    * Watch how the average of those samples converges for each period.
    """,
    unsafe_allow_html=True,
)

# ------------------------------
# Fake global climate model
# ------------------------------


def fake_global_temperature(period: str, lat_deg: float, lon_deg: float, year: int) -> float:
    """
    Return a fake 'global temperature' at (lat, lon, year) for a given period:
    - 'past'   ~ 1971–2000
    - 'recent' ~ 1991–2020

    Structure:
    - baseline 14°C
    - latitudinal gradient (warmer at equator, colder at poles)
    - some spatial noise from lon
    - small warming term for 'recent'
    """
    lat_rad = np.deg2rad(lat_deg)
    lon_rad = np.deg2rad(lon_deg)

    baseline = 14.0

    # Warmer at equator, cooler at poles: cos^2(lat)
    lat_gradient = 12.0 * (np.cos(lat_rad) ** 2)

    # Mild zonal variation (just for variety)
    lon_variation = 1.5 * np.sin(2.0 * lon_rad)

    # Tiny pseudo-random pattern based on both lat and lon
    pattern = 0.8 * np.sin(lat_rad * 3.0 + lon_rad * 2.0)

    # Warming offset
    if period == "past":
        warming = 0.0
    elif period == "recent":
        warming = 1.0  # recent period is about 1°C warmer globally
    else:
        raise ValueError("period must be 'past' or 'recent'")

    # Add a very small temporal drift within each 30-year window
    # so that not all years are identical
    if period == "past":
        year0 = 1971
    else:
        year0 = 1991
    t = (year - year0) / 30.0
    year_term = 0.3 * t

    temp = baseline + lat_gradient + lon_variation + pattern + warming + year_term
    return float(temp)


# ------------------------------
# Sampling utilities
# ------------------------------


def sample_lat_lon(n: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Sample lat, lon uniformly over Earth's surface:
    - lat in [-90, 90] with cos(lat) weighting (via sin^-1 trick).
    - lon in [-180, 180] uniform.
    """
    u = np.random.rand(n)
    v = np.random.rand(n)
    lat = np.degrees(np.arcsin(2.0 * u - 1.0))
    lon = -180.0 + 360.0 * v
    return lat, lon


def sample_years(n: int, start_year: int, end_year: int) -> np.ndarray:
    """
    Sample integer years uniformly between start_year and end_year inclusive.
    """
    years = np.random.randint(start_year, end_year + 1, size=n)
    return years


@st.cache_data(show_spinner=False)
def generate_samples(n_samples: int = 2000, seed: int = 42):
    """
    Generate Monte Carlo samples for two periods:
    - Past:   1971–2000
    - Recent: 1991–2020

    Returns a dict with past & recent lat, lon, year, value, and
    running means for each period.
    """
    rng = np.random.default_rng(seed)

    # --- Past period ------------------------------------------------------
    lat_p, lon_p = sample_lat_lon(n_samples)
    year_p = sample_years(n_samples, 1971, 2000)

    temp_p = np.array(
        [
            fake_global_temperature("past", lat_p[i], lon_p[i], int(year_p[i]))
            for i in range(n_samples)
        ],
        dtype=float,
    )

    # running mean
    cumsum_p = np.cumsum(temp_p)
    running_mean_p = cumsum_p / np.arange(1, n_samples + 1)

    # --- Recent period ----------------------------------------------------
    lat_r, lon_r = sample_lat_lon(n_samples)
    year_r = sample_years(n_samples, 1991, 2020)

    temp_r = np.array(
        [
            fake_global_temperature("recent", lat_r[i], lon_r[i], int(year_r[i]))
            for i in range(n_samples)
        ],
        dtype=float,
    )

    cumsum_r = np.cumsum(temp_r)
    running_mean_r = cumsum_r / np.arange(1, n_samples + 1)

    return {
        "n_samples": n_samples,
        "lat_p": lat_p,
        "lon_p": lon_p,
        "year_p": year_p,
        "temp_p": temp_p,
        "running_mean_p": running_mean_p,
        "lat_r": lat_r,
        "lon_r": lon_r,
        "year_r": year_r,
        "temp_r": temp_r,
        "running_mean_r": running_mean_r,
    }


# ------------------------------
# Generate / load samples
# ------------------------------
N_DEFAULT = 1500
samples = generate_samples(N_DEFAULT, seed=123)

col_left, col_right = st.columns([1.2, 1.6])

# ------------------------------
# LEFT: World map of samples
# ------------------------------
with col_left:
    st.subheader("Where the samples come from")

    st.markdown(
        """
        Each dot is a random place and time where we "measure" a temperature
        from our toy climate model.  
        Blue-ish dots are from an earlier period, red-ish from a more recent one.
        """
    )

    # To avoid too dense a cloud, just plot the first ~400 points of each
    max_plot = 400
    idx_p = np.arange(min(max_plot, samples["n_samples"]))
    idx_r = np.arange(min(max_plot, samples["n_samples"]))

    fig_map = go.Figure()

    fig_map.add_trace(
        go.Scattergeo(
            lon=samples["lon_p"][idx_p],
            lat=samples["lat_p"][idx_p],
            mode="markers",
            name="Past samples (1971–2000)",
            marker=dict(
                size=4,
                color="rgba(33,113,181,0.7)",  # blue-ish
            ),
        )
    )

    fig_map.add_trace(
        go.Scattergeo(
            lon=samples["lon_r"][idx_r],
            lat=samples["lat_r"][idx_r],
            mode="markers",
            name="Recent samples (1991–2020)",
            marker=dict(
                size=4,
                color="rgba(215,25,28,0.7)",  # red-ish
            ),
        )
    )

    fig_map.update_layout(
        height=450,
        margin=dict(l=0, r=0, t=0, b=0),
        geo=dict(
            projection_type="natural earth",
            showland=True,
            landcolor="rgb(240, 240, 240)",
            showcountries=True,
            countrycolor="rgb(200, 200, 200)",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.01,
            xanchor="left",
            x=0.01,
        ),
    )

    st.plotly_chart(fig_map, width="stretch", config={"displayModeBar": False})

# ------------------------------
# RIGHT: Running mean convergence
# ------------------------------
with col_right:
    st.subheader("Watching the global mean emerge")

    st.markdown(
        """
        Move the slider to increase the number of random samples we include.
        As \\(N\\) grows, the **running average** (mean of the first \\(N\\) samples)
        stabilises for each period.
        """,
        unsafe_allow_html=True,
    )

    max_n = samples["n_samples"]
    n = st.slider(
        "Number of samples used in the running mean",
        min_value=10,
        max_value=max_n,
        value=200,
        step=10,
    )

    x = np.arange(1, n + 1)
    mu_p = samples["running_mean_p"][:n]
    mu_r = samples["running_mean_r"][:n]

    fig_rm = go.Figure()

    fig_rm.add_trace(
        go.Scatter(
            x=x,
            y=mu_p,
            mode="lines",
            name="Past period mean",
            line=dict(
                color="rgba(33,113,181,1.0)",
                width=2,
                shape="spline",
            ),
        )
    )

    fig_rm.add_trace(
        go.Scatter(
            x=x,
            y=mu_r,
            mode="lines",
            name="Recent period mean",
            line=dict(
                color="rgba(215,25,28,1.0)",
                width=2,
                shape="spline",
            ),
        )
    )

    # Horizontal lines at final means
    final_p = float(samples["running_mean_p"][-1])
    final_r = float(samples["running_mean_r"][-1])

    fig_rm.add_trace(
        go.Scatter(
            x=[1, max_n],
            y=[final_p, final_p],
            mode="lines",
            name="Past asymptotic mean",
            line=dict(
                color="rgba(33,113,181,0.5)",
                width=1,
                dash="dash",
            ),
            showlegend=False,
        )
    )

    fig_rm.add_trace(
        go.Scatter(
            x=[1, max_n],
            y=[final_r, final_r],
            mode="lines",
            name="Recent asymptotic mean",
            line=dict(
                color="rgba(215,25,28,0.5)",
                width=1,
                dash="dash",
            ),
            showlegend=False,
        )
    )

    fig_rm.update_layout(
        height=450,
        margin=dict(l=40, r=20, t=10, b=40),
        xaxis_title="Number of samples N",
        yaxis_title="Running mean temperature (°C)",
    )

    st.plotly_chart(fig_rm, width="stretch", config={"displayModeBar": False})

    st.markdown(
        f"""
        With **{n} samples**, our toy running means are:

        * Past period: **{mu_p[-1]:.2f}°C**
        * Recent period: **{mu_r[-1]:.2f}°C**

        The gap between these converges towards about **{final_r - final_p:.2f}°C**,
        which is how a global warming signal can emerge from many local measurements.
        """
    )
