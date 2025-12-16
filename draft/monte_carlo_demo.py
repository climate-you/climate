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
    > randomly sampling temperatures around the world, in two different time
    > periods, and watching how their **global mean** emerges.

    We pretend we have a global gridded dataset and:
    * Define a "past" climate (1971–1990).
    * Define a "recent" climate (2001–2020) that is a bit warmer everywhere.
    * Draw random samples of (latitude, longitude, year).
    * Watch the average of those samples converge for each period.
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
    - 'recent' ~ 2001–2020

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

    # Mild zonal variation
    lon_variation = 1.5 * np.sin(2.0 * lon_rad)

    # Tiny pseudo-random pattern based on both lat and lon
    pattern = 0.8 * np.sin(lat_rad * 3.0 + lon_rad * 2.0)

    # Warming offset
    if period == "past":
        warming = 0.0
        year0 = 1971
    elif period == "recent":
        warming = 1.0  # 1°C warmer globally (toy)
        year0 = 2001
    else:
        raise ValueError("period must be 'past' or 'recent'")

    # Very small temporal drift within each 30-year window
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
    """Sample integer years uniformly between start_year and end_year inclusive."""
    return np.random.randint(start_year, end_year + 1, size=n)


@st.cache_data(show_spinner=False)
def generate_samples(n_samples: int = 3000, seed: int = 42):
    """
    Generate Monte Carlo samples for two periods:
    - Past:   1971–1990
    - Recent: 2001–2020

    Returns dict containing past/recent lat, lon, year, temperature,
    and running means.
    """
    rng = np.random.default_rng(seed)

    # --- Past period ------------------------------------------------------
    lat_p, lon_p = sample_lat_lon(n_samples)
    year_p = sample_years(n_samples, 1971, 1990)
    temp_p = np.array(
        [
            fake_global_temperature("past", lat_p[i], lon_p[i], int(year_p[i]))
            for i in range(n_samples)
        ],
        dtype=float,
    )
    cumsum_p = np.cumsum(temp_p)
    running_mean_p = cumsum_p / np.arange(1, n_samples + 1)

    # --- Recent period ----------------------------------------------------
    lat_r, lon_r = sample_lat_lon(n_samples)
    year_r = sample_years(n_samples, 2001, 2020)
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
SAMPLES_TOTAL = 3000
samples = generate_samples(SAMPLES_TOTAL, seed=123)

col_left, col_right = st.columns([1.2, 1.6])

# Slider controls "how far" in the sampling story we’ve gone
with col_right:
    st.subheader("Watching the global mean emerge")

    st.markdown(
        """
        Use the slider to increase the number of samples we include.

        At first, the running average is noisy. As \\(N\\) grows, the
        **running mean** for each period stabilises, and a gap between
        the past and recent climates becomes obvious.
        """,
        unsafe_allow_html=True,
    )

    max_n = samples["n_samples"]
    n = st.slider(
        "Number of samples used so far",
        min_value=10,
        max_value=max_n,
        value=200,
        step=10,
    )

# ------------------------------
# LEFT: World map of first N samples
# ------------------------------
with col_left:
    st.subheader("Where the samples are taken")

    st.markdown(
        """
        Each dot is a random place and time where we "measure" a temperature
        from our toy climate model.  
        Blue-ish dots are from an earlier period, red-ish from a more recent one.

        As you increase **N** on the right, more dots appear here too.
        """
    )

    n_map = min(n, 500)  # don't overplot too densely
    idx_p = np.arange(n_map)
    idx_r = np.arange(n_map)

    fig_map = go.Figure()

    fig_map.add_trace(
        go.Scattergeo(
            lon=samples["lon_p"][idx_p],
            lat=samples["lat_p"][idx_p],
            mode="markers",
            name="Past samples (1971–1990)",
            marker=dict(
                size=4,
                color="rgba(33,113,181,0.7)",  # blue-ish
            ),
            hovertext=[
                f"Past #{i+1}<br>Year: {int(samples['year_p'][i])}<br>T = {samples['temp_p'][i]:.1f}°C"
                for i in idx_p
            ],
        )
    )

    fig_map.add_trace(
        go.Scattergeo(
            lon=samples["lon_r"][idx_r],
            lat=samples["lat_r"][idx_r],
            mode="markers",
            name="Recent samples (2001–2020)",
            marker=dict(
                size=4,
                color="rgba(215,25,28,0.7)",  # red-ish
            ),
            hovertext=[
                f"Recent #{i+1}<br>Year: {int(samples['year_r'][i])}<br>T = {samples['temp_r'][i]:.1f}°C"
                for i in idx_r
            ],
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
# RIGHT: Running mean convergence (uses N)
# ------------------------------
with col_right:
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

    final_p = float(samples["running_mean_p"][-1])
    final_r = float(samples["running_mean_r"][-1])

    # Horizontal lines at final means (the "true" means in this toy world)
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

# ------------------------------
# Optional: sample-by-sample time-series view
# ------------------------------
with st.expander("Sample-by-sample view (first ~200 samples)"):
    st.markdown(
        """
        Here we look at the **first few samples** as points in time.

        The x-axis shows the (toy) year of each sample.  
        The dotted horizontal line is the **mean of the samples currently shown**.
        As you increase the number of samples, that mean line will move.
        """
    )

    max_timeline = min(n, 200)
    if max_timeline < 10:
        st.info("Increase N with the slider above to see at least 10 samples here.")
    else:
        idx_t = np.arange(max_timeline)

        # Past samples: convert year -> a simple date (e.g. mid-year)
        years_p = samples["year_p"][idx_t].astype(int)
        time_p = pd.to_datetime(years_p.astype(str) + "-07-01")
        temp_p = samples["temp_p"][idx_t]
        mean_p = float(temp_p.mean())

        # Recent samples
        years_r = samples["year_r"][idx_t].astype(int)
        time_r = pd.to_datetime(years_r.astype(str) + "-07-01")
        temp_r = samples["temp_r"][idx_t]
        mean_r = float(temp_r.mean())

        # Horizontal line x-span: min to max of the shown times
        xline_p = [time_p.min(), time_p.max()]
        xline_r = [time_r.min(), time_r.max()]

        c1, c2 = st.columns(2)

        with c1:
            st.markdown("**Past period samples (first ~200)**")
            fig_p = go.Figure()
            # Dots: individual samples
            fig_p.add_trace(
                go.Scatter(
                    x=time_p,
                    y=temp_p,
                    mode="markers",
                    name="Sampled temperature",
                    marker=dict(size=6, color="rgba(33,113,181,0.7)"),
                    hovertext=[
                        f"Sample #{i+1}<br>Year: {years_p[i]}<br>T = {temp_p[i]:.1f}°C"
                        for i in range(max_timeline)
                    ],
                    hoverinfo="text",
                )
            )
            # Horizontal mean line
            fig_p.add_trace(
                go.Scatter(
                    x=xline_p,
                    y=[mean_p, mean_p],
                    mode="lines",
                    name=f"Mean of shown samples ({mean_p:.1f}°C)",
                    line=dict(
                        color="rgba(33,113,181,1.0)",
                        width=2,
                        dash="dot",
                    ),
                )
            )
            fig_p.update_layout(
                height=300,
                margin=dict(l=40, r=20, t=10, b=40),
                xaxis_title="Sampled year (toy)",
                yaxis_title="Temperature (°C)",
                showlegend=True,
            )
            st.plotly_chart(fig_p, width="stretch", config={"displayModeBar": False})

        with c2:
            st.markdown("**Recent period samples (first ~200)**")
            fig_r = go.Figure()
            # Dots: individual samples
            fig_r.add_trace(
                go.Scatter(
                    x=time_r,
                    y=temp_r,
                    mode="markers",
                    name="Sampled temperature",
                    marker=dict(size=6, color="rgba(215,25,28,0.7)"),
                    hovertext=[
                        f"Sample #{i+1}<br>Year: {years_r[i]}<br>T = {temp_r[i]:.1f}°C"
                        for i in range(max_timeline)
                    ],
                    hoverinfo="text",
                )
            )
            # Horizontal mean line
            fig_r.add_trace(
                go.Scatter(
                    x=xline_r,
                    y=[mean_r, mean_r],
                    mode="lines",
                    name=f"Mean of shown samples ({mean_r:.1f}°C)",
                    line=dict(
                        color="rgba(215,25,28,1.0)",
                        width=2,
                        dash="dot",
                    ),
                )
            )
            fig_r.update_layout(
                height=300,
                margin=dict(l=40, r=20, t=10, b=40),
                xaxis_title="Sampled year (toy)",
                yaxis_title="Temperature (°C)",
                showlegend=True,
            )
            st.plotly_chart(fig_r, width="stretch", config={"displayModeBar": False})
