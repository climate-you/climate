import os
from pathlib import Path
import xarray as xr
import numpy as np
from datetime import date  # , datetime, timedelta
import folium

import pandas as pd
import matplotlib.pyplot as plt

# streamlit
import streamlit as st
from streamlit_folium import st_folium

# climate package
from climate.models import StoryFacts, StoryContext
from climate.units import default_unit_for_country, fmt_temp, fmt_delta
from climate.io import discover_locations, dataset_coverage_text
from climate.openmeteo import (
    fetch_openmeteo_current_temp_c,
    fetch_openmeteo_window,
    fetch_recent_7d,
    fetch_recent_30d,
)
from climate.analytics import estimate_30d_trend, season_phrase, compute_story_facts

# panels
from climate.panels.intro import build_intro_data, intro_caption
from climate.panels.zoomout import (
    build_last_week_data,
    build_last_week_figure,
    last_week_caption,
    build_last_month_data,
    build_last_month_figure,
    last_month_caption,
    build_last_year_data,
    build_last_year_figure,
    last_year_caption,
    build_five_year_data,
    build_five_year_figure,
    five_year_caption,
    build_fifty_year_data,
    build_fifty_year_figure,
    fifty_year_caption,
    build_twenty_five_years_data,
    build_twenty_five_years_figure,
    twenty_five_years_caption,
)
from climate.panels.seasons import (
    build_seasons_then_now_data,
    build_seasons_then_now_figure,
    build_seasons_then_now_separate_figures,
    seasons_then_now_caption,
    seasons_then_now_separate_caption,
)
from climate.panels.world import (
    build_you_vs_world_data,
    build_you_vs_world_figures,
    you_vs_world_caption,
)
from climate.panels.worldmap import (
    build_world_map_data,
    build_world_map_figure,
    world_map_caption,
    build_local_inset_data,
    build_local_inset_figure,
    local_inset_caption,
)

#
DATA_DIR = Path("data")
CLIMATOLOGY_DIR = DATA_DIR / "story_climatology"


# Discover all available locations from precomputed files
@st.cache_data(
    ttl=30
)  # keeps widget options stable while precompute is writing new files
def _discover_cached(clim_dir: str):
    return discover_locations(clim_dir)


LOCATIONS = _discover_cached(clim_dir=CLIMATOLOGY_DIR)

if not LOCATIONS:
    st.error(
        "No climatology files found in story_climatology/. "
        "Run precompute_story_cities.py first."
    )
    st.stop()

# -----------------------------------------------------------
# 2. Sidebar: location + stepper
# -----------------------------------------------------------

st.set_page_config(page_title="Your Climate Story", layout="wide")

# Sort slugs to have stable ordering
slug_list = sorted(LOCATIONS.keys())
labels_by_slug = {s: LOCATIONS[s]["label"] for s in slug_list}

# Favorites (optional): put favorites at the top of the one selectbox
FAVORITES_FILE = Path("locations/favorites.txt")
favorites = []
if FAVORITES_FILE.exists():
    favorites = [
        ln.strip()
        for ln in FAVORITES_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
favorite_set = {s for s in favorites if s in labels_by_slug}

# Build ordered list: favorites first (in favorites.txt order), then the rest by label
fav_slugs = [s for s in favorites if s in favorite_set]
nonfav_slugs = sorted(
    [s for s in slug_list if s not in favorite_set], key=lambda s: labels_by_slug[s]
)
ordered_slugs = fav_slugs + nonfav_slugs

# Optional: if you still want a default slug, keep this
DEFAULT_SLUG = "city_mu_port_louis"

default_index = 0
if DEFAULT_SLUG in ordered_slugs:
    default_index = ordered_slugs.index(DEFAULT_SLUG)


def _format_unit(unit: str) -> str:
    return "º" + unit


def _format_location_slug(slug: str) -> str:
    star = "★ " if slug in favorite_set else ""
    return star + labels_by_slug.get(slug, slug)


def _on_location_change():
    if not st.session_state["unit_locked"]:
        st.session_state["unit"] = _default_unit_for_slug(
            st.session_state["location_slug"]
        )


def _default_unit_for_slug(slug: str) -> str:
    # however you decide this (US -> °F, else °C)
    cc = LOCATIONS[slug]["country_code"]
    return default_unit_for_country(cc)


def _on_unit_change():
    st.session_state["unit_locked"] = True


st.session_state.setdefault("unit_locked", False)
st.session_state.setdefault("location_slug", DEFAULT_SLUG)
st.session_state.setdefault(
    "unit", _default_unit_for_slug(st.session_state["location_slug"])
)

with st.sidebar:
    st.header("Location")
    chosen_slug = st.selectbox(
        "Choose a city:",
        options=ordered_slugs,
        index=default_index,
        format_func=_format_location_slug,
        key="location_slug",
        on_change=_on_location_change,
    )

    st.subheader("Story step")
    step = st.radio(
        "Go to",
        [
            "Intro",
            "Zoom out",
            "Seasons then vs now",
            "You vs the world",
            "Ocean Stress",
            "World map",
            "Monte Carlo: how global warming is estimated",
        ],
    )

    st.subheader("Time snapshot")
    today = st.date_input(
        "Pretend 'today' is:",
        value=date.today(),
        help="Use this to see how the page would look in a different season.",
    )

    unit = st.radio(
        "Units",
        ["C", "F"],
        format_func=_format_unit,
        key="unit",
        on_change=_on_unit_change,
    )

    grid_deg = st.radio("World Map Resolution", ["0.25", "0.5", "1.0"], key="grid_deg")

# Map label back to slug + meta
slug = chosen_slug
loc_meta = LOCATIONS[slug]

location_label = loc_meta["label"]
location_lat = loc_meta["lat"]
location_lon = loc_meta["lon"]
clim_path = loc_meta["path"]
city_name = loc_meta["city_name"]
country_code = loc_meta["country_code"]

# Load dataset for this location
try:
    ds = xr.open_dataset(clim_path)
except Exception as e:
    st.warning(
        f"Couldn't load data for {slug_to_label.get(slug, slug)} yet "
        f"(file may be updating). Please retry in a moment.\n\n{e!r}"
    )
    st.stop()

# Compute high-level facts once
facts = compute_story_facts(ds, lat=location_lat)

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
# STEP: INTRO
# -----------------------------------------------------------
ctx = StoryContext(
    today, slug, location_label, city_name, location_lat, location_lon, unit, ds
)

if step == "Intro":
    st.markdown(
        f"""
        <div class="hero-title">Your climate story</div>
        <div class="hero-subtitle">How temperatures have changed where you live</div>
        """,
        unsafe_allow_html=True,
    )

    # Generate data and captions
    intro_data = build_intro_data(ctx)
    intro_caption = intro_caption(ctx, facts, intro_data)

    col_map, col_text = st.columns([2.2, 1.3])
    with col_map:
        st.write("")
        m = folium.Map(
            location=[ctx.location_lat, ctx.location_lon],
            zoom_start=4,
            tiles="CartoDB positron",
        )
        folium.CircleMarker(
            location=[ctx.location_lat, ctx.location_lon],
            radius=8,
            color="#d73027",
            fill=True,
            fill_opacity=0.9,
        ).add_to(m)
        st_folium(m, width="stretch", height=420)

    with col_text:
        now_line = ""
        temp_now_c = intro_data["temp_now_c"]
        temp_now_time = intro_data["temp_now_time"]
        if temp_now_c is not None:
            now_line = f"It is currently **{fmt_temp(temp_now_c, ctx.unit)}** in {ctx.city_name} (latest reading: {temp_now_time})."
        else:
            now_line = f"Current temperature is temporarily unavailable for {ctx.city_name} (rate limited or network issue)."
        intro_text = f"""
        {now_line}
        {intro_caption}
        """
        st.markdown(intro_text, unsafe_allow_html=True)

# -----------------------------------------------------------
# STEP: ZOOM OUT
# -----------------------------------------------------------
if step == "Zoom out":
    loc_name = ds.attrs.get("name_long", "this location")

    st.header("1. Zooming out: from days to decades")

    # ################################################################################
    # 1A. Last 7 days — hourly + daily mean
    st.subheader("Last week — the daily cycle")
    last_week_data = build_last_week_data(ctx)
    if last_week_data:
        fig_week, fig_week_caption = build_last_week_figure(ctx, facts, last_week_data)
        st.plotly_chart(fig_week, width="stretch", config={"displayModeBar": False})
        st.caption(fig_week_caption)
        st.markdown(last_week_caption(ctx, facts, last_week_data))
    else:
        st.info(
            "Not enough recent daily data available to show the last week for this location."
        )
    # ################################################################################

    # ################################################################################
    # 1B. Last 30 days — daily + 3-day mean + min/max
    st.subheader("Last month — daily temperatures")
    last_month_data = build_last_month_data(ctx)
    if last_month_data:
        fig_month, fig_month_caption = build_last_month_figure(
            ctx, facts, last_month_data
        )
        st.plotly_chart(fig_month, width="stretch", config={"displayModeBar": False})
        st.caption(fig_month_caption)
        st.markdown(last_month_caption(ctx, facts, last_month_data))
    else:
        st.info(
            "Not enough recent daily data available to show the last month for this location."
        )
    # ################################################################################

    # ################################################################################
    # 1C. Last year — the seasonal cycle
    st.subheader("Last year — the seasonal cycle")
    last_year_data = build_last_year_data(ctx)
    if last_year_data:
        fig_year, fig_year_caption = build_last_year_figure(ctx, facts, last_year_data)
        st.plotly_chart(fig_year, width="stretch", config={"displayModeBar": False})
        st.caption(fig_year_caption)
        st.markdown(last_year_caption(ctx, facts, last_year_data))
    else:
        st.info(
            "Not enough recent daily data available to show the last year for this location."
        )
    # ################################################################################

    # ################################################################################
    # 1D. Last 5 years — 7-day mean and monthly mean
    st.subheader("Last 5 years — zoom from seasons to climate")
    last_five_year_data = build_five_year_data(ctx)
    if last_five_year_data:
        fig_five_year, fig_five_year_caption = build_five_year_figure(
            ctx, facts, last_five_year_data
        )
        st.plotly_chart(
            fig_five_year, width="stretch", config={"displayModeBar": False}
        )
        st.caption(fig_five_year_caption)
        st.markdown(five_year_caption(ctx, facts, last_five_year_data))
    else:
        st.info(
            "Not enough recent daily data available to show the last five years for this location."
        )
    # ################################################################################

    # ################################################################################
    # 1E. Last ~50 years — monthly averages and trend
    st.subheader("Last 50 years — monthly averages and trend")
    last_fifty_year_data = build_fifty_year_data(ctx)
    if last_fifty_year_data:
        fig_fifty_year, fig_fifty_year_caption = build_fifty_year_figure(
            ctx, facts, last_fifty_year_data
        )
        st.plotly_chart(
            fig_fifty_year, width="stretch", config={"displayModeBar": False}
        )
        st.caption(fig_fifty_year_caption)
        st.markdown(fifty_year_caption(ctx, facts, last_fifty_year_data))
    else:
        st.info(
            "Not enough recent daily data available to show the last fifty years for this location."
        )
    # ################################################################################

    # ################################################################################
    # 1F. A simple 25-year projection, assuming the same trend continues
    st.subheader("Looking 25 years ahead (simple trend extension)")
    twenty_five_years_data = build_twenty_five_years_data(ctx)
    if twenty_five_years_data:
        fig_twenty_five_years, fig_twenty_five_years_caption = (
            build_twenty_five_years_figure(ctx, facts, twenty_five_years_data)
        )
        st.plotly_chart(
            fig_twenty_five_years, width="stretch", config={"displayModeBar": False}
        )
        st.caption(fig_twenty_five_years_caption)
        st.markdown(twenty_five_years_caption(ctx, facts, twenty_five_years_data))
    else:
        st.info("Not enough yearly data to draw a simple trend extension here.")
    # ################################################################################

# -----------------------------------------------------------
# STEP: SEASONS THEN VS NOW
# -----------------------------------------------------------
if step == "Seasons then vs now":
    st.header("2. How your seasons have shifted")

    # ################################################################################
    # 2A. Recent
    seasons_data = build_seasons_then_now_data(ctx)
    if seasons_data:
        fig_seasons, fig_seasons_caption = build_seasons_then_now_figure(
            ctx, facts, seasons_data
        )
        st.plotly_chart(fig_seasons, width="stretch", config={"displayModeBar": False})
        st.caption(fig_seasons_caption)
        st.markdown(seasons_then_now_caption(ctx, facts, seasons_data))
    else:
        st.info("Monthly climatologies are not available for this location.")
    # ################################################################################

    # ################################################################################
    # 2B. Min–max envelopes for early vs recent climates
    st.subheader("How the range of monthly temperatures has changed")
    fig_env_past, fig_env_recent = build_seasons_then_now_separate_figures(
        ctx, facts, seasons_data
    )
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_env_past, width="stretch", config={"displayModeBar": False})
    with c2:
        st.plotly_chart(
            fig_env_recent, width="stretch", config={"displayModeBar": False}
        )
    st.markdown(seasons_then_now_separate_caption(ctx, facts, seasons_data))
    # ################################################################################

# -----------------------------------------------------------
# STEP: YOU VS THE WORLD (ANOMALIES)
# -----------------------------------------------------------
if step == "You vs the world":
    # ################################################################################
    # 3A. Local vs Global anomalies
    st.header("3. Your warming vs global warming")
    data = build_you_vs_world_data(ctx)
    fig_local, fig_global, tiny = build_you_vs_world_figures(ctx, facts, data)
    col_local, col_global = st.columns(2)
    with col_local:
        st.plotly_chart(fig_local, width="stretch", config={"displayModeBar": False})
    with col_global:
        st.plotly_chart(fig_global, width="stretch", config={"displayModeBar": False})
    st.caption(tiny)
    st.markdown(you_vs_world_caption(ctx, facts, data))
    # ################################################################################

# -----------------------------------------------------------
# STEP: OCEAN STRESS
# -----------------------------------------------------------

# -----------------------------------------------------------
# STEP: OCEAN STRESS
# -----------------------------------------------------------
if step == "Ocean Stress":
    st.header("Ocean Stress")

    st.markdown(
        """
This step is for **coastal ocean indicators** (Phase 1: tested on `city_mu_tamarin`).

We’ll show:
- **SST anomaly** (vs 1981–2010 baseline)
- **SST hot days** (days above baseline P90)
- **Coral heat stress** (DHW: annual max + days above thresholds)

Once `climate/panels/ocean.py` exists, this section will render the real figures + captions using the standard panel pattern.
"""
    )

    try:
        from climate.panels.ocean import (
            build_sst_anom_data,
            build_sst_anom_figure,
            sst_anom_caption,
            build_sst_hotdays_data,
            build_sst_hotdays_figure,
            sst_hotdays_caption,
            build_dhw_data,
            build_dhw_figure,
            build_dhw_figure_with_trend,
            build_dhw_heatmap_figure,
            dhw_caption,
            build_ocean_context_map_figure,
        )

        sst_anom_data = build_sst_anom_data(ctx)
        sst_hot_data = build_sst_hotdays_data(ctx)
        dhw_data = build_dhw_data(ctx)

        col_map, col_right = st.columns([1, 4], gap="large")
        with col_map:
            fig_map, tiny_map = build_ocean_context_map_figure(ctx, facts, dhw_data)
            st.pyplot(fig_map, clear_figure=False)
            st.caption(tiny_map)

        with col_right:
            # -------------------------
            # 1) SST anomaly
            st.subheader("Sea surface temperature anomaly")
            if sst_anom_data:
                fig, tiny = build_sst_anom_figure(ctx, facts, sst_anom_data)
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                st.caption(tiny)
                st.markdown(sst_anom_caption(ctx, facts, sst_anom_data))
            else:
                st.info("SST anomaly data not available for this location yet.")

            # -------------------------
            # 2) SST hot days (baseline P90)
            st.subheader("SST hot days (above baseline P90)")
            if sst_hot_data:
                fig, tiny = build_sst_hotdays_figure(ctx, facts, sst_hot_data)
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                st.caption(tiny)
                st.markdown(sst_hotdays_caption(ctx, facts, sst_hot_data))
            else:
                st.info("SST hot-day data not available for this location yet.")

            # -------------------------
            # 3) DHW (coral heat stress)
            st.subheader("Coral heat stress (DHW)")
            if dhw_data:
                # Prototype the front-end UX in Streamlit:
                # - default = bars (no trend)
                # - optional toggle = bars + trend (dual-axis)
                # - optional toggle = heatmap (Design 2)
                mode = st.radio(
                    "DHW view",
                    ["📊 Bars", "〰️ Bars + trend", "🟧 Heatmap"],
                    horizontal=True,
                    label_visibility="collapsed",
                    key=f"dhw_view_{ctx.slug}",
                )

                if mode == "📊 Bars":
                    fig, tiny = build_dhw_figure(ctx, facts, dhw_data)
                    st.plotly_chart(
                        fig, width="stretch", config={"displayModeBar": False}
                    )
                    st.caption(tiny)

                elif mode == "〰️ Bars + trend":
                    fig, tiny = build_dhw_figure_with_trend(ctx, facts, dhw_data)
                    st.plotly_chart(
                        fig, width="stretch", config={"displayModeBar": False}
                    )
                    st.caption(tiny)

                else:
                    fig_hm, tiny_hm = build_dhw_heatmap_figure(
                        ctx, facts, dhw_data, use_threshold_jumps=True
                    )
                    if fig_hm is not None:
                        st.pyplot(fig_hm, clear_figure=False)
                        st.caption(tiny_hm)
                        plt.close(fig_hm)
                    else:
                        st.info("Daily DHW not available for heatmap yet.")

                # Keep the story text stable regardless of view
                st.markdown(dhw_caption(ctx, facts, dhw_data))
            else:
                st.info("DHW data not available for this location yet.")

    except Exception as e:
        st.warning(
            "Ocean Stress panels aren’t implemented yet (expected until `climate/panels/ocean.py` is added)."
        )
        st.caption(f"Import/wiring error: {type(e).__name__}: {e}")


# -----------------------------------------------------------
# STEP: WORLD MAP IDEA
# -----------------------------------------------------------
if step == "World map":
    st.header("4. Where you fit on the world map")

    if grid_deg == "0.25":
        grid_deg_f = 0.25
    elif grid_deg == "0.5":
        grid_deg_f = 0.5
    else:
        grid_deg_f = 1.0
    world_data = build_world_map_data(ctx, grid_deg=grid_deg_f)
    m, tiny = build_world_map_figure(ctx, facts, world_data)
    st.caption(tiny)
    st.markdown(world_map_caption(ctx, facts, world_data))
    st_folium(m, width="stretch", height=520)

    inset_data = build_local_inset_data(ctx, world_data)
    fig_inset, tiny_inset = build_local_inset_figure(ctx, facts, inset_data)
    st.caption(tiny_inset)
    st.plotly_chart(
        fig_inset, use_container_width=False, config={"displayModeBar": False}
    )
    st.markdown(local_inset_caption(ctx, facts, inset_data))

# -----------------------------------------------------------
# STEP: MONTE CARLO
# -----------------------------------------------------------
if step == "Monte Carlo: how global warming is estimated":
    st.header("5. Monte Carlo: estimating global warming by random sampling")

    from climate.panels.montecarlo import (
        build_montecarlo_data,
        build_montecarlo_figures,
        montecarlo_caption,
    )
    import time

    # ---- UI controls (no slider)
    col_a, col_b, col_c = st.columns([1, 1, 2])

    if "mc_running" not in st.session_state:
        st.session_state["mc_running"] = False
    if "mc_n" not in st.session_state:
        st.session_state["mc_n"] = 0
    if "mc_experiment_id" not in st.session_state:
        st.session_state["mc_experiment_id"] = 1

    with col_a:
        if st.button(
            "Start" if not st.session_state["mc_running"] else "Pause",
            use_container_width=True,
        ):
            st.session_state["mc_running"] = not st.session_state["mc_running"]

    with col_b:
        if st.button("Reset", use_container_width=True):
            st.session_state["mc_running"] = False
            st.session_state["mc_n"] = 0

    with col_c:
        exp_id = st.number_input(
            "Experiment",
            min_value=1,
            max_value=99,
            value=st.session_state["mc_experiment_id"],
            step=1,
        )
        st.session_state["mc_experiment_id"] = int(exp_id)

    # ---- Load data (cached at streamlit level)
    @st.cache_data(show_spinner=False)
    def _load_exp(experiment_id: int) -> dict:
        return build_montecarlo_data(
            ctx, experiment_id=experiment_id, data_dir=DATA_DIR
        )

    base = _load_exp(st.session_state["mc_experiment_id"])
    n_total = int(base["n_total"])

    # ---- Progress / speed ramp
    n = int(st.session_state["mc_n"])
    n = max(0, min(n, n_total))

    st.progress(n / max(1, n_total), text=f"{n} / {n_total} samples")

    # Speed ramp (tweak freely)
    if n < 50:
        step_n = 1
        tick_sleep = 0.25
    elif n < 500:
        step_n = 5
        tick_sleep = 0.15
    elif n < 2000:
        step_n = 20
        tick_sleep = 0.10
    else:
        step_n = 100
        tick_sleep = 0.06

    # ---- Build figures for current n
    data = dict(base)
    data["n"] = n

    fig_map, fig_time, fig_mean, tiny = build_montecarlo_figures(ctx, facts, data)

    st.plotly_chart(fig_map, use_container_width=True, config={"displayModeBar": False})
    st.plotly_chart(
        fig_time, use_container_width=True, config={"displayModeBar": False}
    )
    st.plotly_chart(
        fig_mean, use_container_width=True, config={"displayModeBar": False}
    )

    st.caption(tiny)
    st.markdown(montecarlo_caption(ctx, facts, data))

    # Optional: show details early
    if n > 0:
        df_first = base["df"][base["df"]["seq"] < min(n, 50)].copy()
        df_first["time"] = pd.to_datetime(df_first["time"]).dt.strftime("%Y-%m-%d")
        st.markdown("**First samples (details)**")
        st.dataframe(
            df_first[["seq", "era", "time", "lat", "lon", "t_c"]],
            use_container_width=True,
        )

    # ---- Playback loop
    if st.session_state["mc_running"] and n < n_total:
        st.session_state["mc_n"] = min(n + step_n, n_total)
        time.sleep(tick_sleep)
        st.rerun()
