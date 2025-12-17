import os
from pathlib import Path
import xarray as xr
import numpy as np
from datetime import date #, datetime, timedelta
import folium

#import glob
#import pandas as pd
#import plotly.graph_objs as go
#import requests
#from dataclasses import dataclass
#from typing import Optional

# streamlit
import streamlit as st
from streamlit_folium import st_folium

# climate package
from climate.models import StoryFacts, StoryContext
from climate.units import default_unit_for_country, fmt_temp, fmt_delta
from climate.io import discover_locations, dataset_coverage_text
from climate.openmeteo import fetch_openmeteo_current_temp_c, fetch_openmeteo_window, fetch_recent_7d, fetch_recent_30d
from climate.analytics import estimate_30d_trend, season_phrase, compute_story_facts

# panels
from climate.panels.intro import build_intro_data, intro_caption
from climate.panels.zoomout import (
    build_last_week_data, build_last_week_figure, last_week_caption,
    build_last_month_data, build_last_month_figure, last_month_caption,
    build_last_year_data, build_last_year_figure, last_year_caption,
    build_five_year_data, build_five_year_figure, five_year_caption,
    build_fifty_year_data, build_fifty_year_figure, fifty_year_caption,
    build_twenty_five_years_data, build_twenty_five_years_figure, twenty_five_years_caption
)
from climate.panels.seasons import (
    build_seasons_then_now_data, build_seasons_then_now_figure, build_seasons_then_now_separate_figures,
    seasons_then_now_caption, seasons_then_now_separate_caption 
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
)

# TO BE REMOVED
from climate.fake import make_fake_daily_series, make_fake_hourly_from_daily, fake_local_and_global

# 
DATA_DIR = Path("data/story_climatology")

# Discover all available locations from precomputed files
@st.cache_data(ttl=30)  # keeps widget options stable while precompute is writing new files
def _discover_cached(clim_dir: str):
    return discover_locations(clim_dir)

LOCATIONS = _discover_cached(clim_dir=DATA_DIR)

if not LOCATIONS:
    st.error("No climatology files found in story_climatology/. "
             "Run precompute_story_cities.py first.")
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
        ln.strip() for ln in FAVORITES_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
favorite_set = {s for s in favorites if s in labels_by_slug}

# Build ordered list: favorites first (in favorites.txt order), then the rest by label
fav_slugs = [s for s in favorites if s in favorite_set]
nonfav_slugs = sorted([s for s in slug_list if s not in favorite_set], key=lambda s: labels_by_slug[s])
ordered_slugs = fav_slugs + nonfav_slugs

# Optional: if you still want a default slug, keep this
DEFAULT_SLUG = "city_mu_port_louis"

default_index = 0
if DEFAULT_SLUG in ordered_slugs:
    default_index = ordered_slugs.index(DEFAULT_SLUG)

def _format_location_slug(slug: str) -> str:
    star = "★ " if slug in favorite_set else ""
    return star + labels_by_slug.get(slug, slug)

def _on_location_change():
    if not st.session_state["unit_locked"]:
        st.session_state["unit"] = _default_unit_for_slug(st.session_state["location_slug"])

def _default_unit_for_slug(slug: str) -> str:
    # however you decide this (US -> °F, else °C)
    cc = LOCATIONS[slug]["country_code"]
    return default_unit_for_country(cc)

def _on_unit_change():
    st.session_state["unit_locked"] = True

st.session_state.setdefault("unit_locked", False)
st.session_state.setdefault("location_slug", DEFAULT_SLUG)
st.session_state.setdefault("unit", _default_unit_for_slug(st.session_state["location_slug"]))

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
            "World map",
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
        ["°C", "°F"],
        key="unit",
        on_change=_on_unit_change,
    )

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
# STEP: INTRO
# -----------------------------------------------------------
ctx = StoryContext(today, slug, location_label, city_name, location_lat, location_lon, unit, ds)

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
        m = folium.Map(location=[ctx.location_lat, ctx.location_lon], zoom_start=4, tiles="CartoDB positron")
        folium.CircleMarker(
            location=[ctx.location_lat, ctx.location_lon],
            radius=8,
            color="#d73027",
            fill=True,
            fill_opacity=0.9,
        ).add_to(m)
        st_folium(m, width="stretch", height=420)

    with col_text:
        st.markdown(intro_caption, unsafe_allow_html=True)

# -----------------------------------------------------------
# STEP: ZOOM OUT
# -----------------------------------------------------------
if step == "Zoom out":
    loc_name = ds.attrs.get("name_long", "this location")
    
    st.header("1. Zooming out: from days to decades")

    # ################################################################################
    # 1A. Last 7 days — hourly + daily mean
    st.subheader("Last week — the daily cycle")
    last_week_data = build_last_week_data(ctx)
    if last_week_data:
        fig_week, fig_week_caption = build_last_week_figure(ctx, facts, last_week_data)
        st.plotly_chart(fig_week, width="stretch", config={"displayModeBar": False})
        st.caption(fig_week_caption)       
        st.markdown(last_week_caption(ctx, facts, last_week_data))
    else:
        st.info("Not enough recent daily data available to show the last week for this location.")
    # ################################################################################

    # ################################################################################
    # 1B. Last 30 days — daily + 3-day mean + min/max
    st.subheader("Last month — daily temperatures")
    last_month_data = build_last_month_data(ctx)
    if last_month_data:
        fig_month, fig_month_caption = build_last_month_figure(ctx, facts, last_month_data)
        st.plotly_chart(fig_month, width="stretch", config={"displayModeBar": False})
        st.caption(fig_month_caption)
        st.markdown(last_month_caption(ctx, facts, last_month_data))
    else:
        st.info("Not enough recent daily data available to show the last month for this location.")
    # ################################################################################

    # ################################################################################
    # 1C. Last year — the seasonal cycle
    st.subheader("Last year — the seasonal cycle")
    last_year_data = build_last_year_data(ctx)
    if last_year_data:
        fig_year, fig_year_caption = build_last_year_figure(ctx, facts, last_year_data)
        st.plotly_chart(fig_year, width="stretch", config={"displayModeBar": False})
        st.caption(fig_year_caption)       
        st.markdown(last_year_caption(ctx, facts, last_year_data))
    else:
        st.info("Not enough recent daily data available to show the last year for this location.")
    # ################################################################################

    # ################################################################################
    # 1D. Last 5 years — 7-day mean and monthly mean
    st.subheader("Last 5 years — zoom from seasons to climate")
    last_five_year_data = build_five_year_data(ctx)
    if last_five_year_data:
        fig_five_year, fig_five_year_caption = build_five_year_figure(ctx, facts, last_five_year_data)
        st.plotly_chart(fig_five_year, width="stretch", config={"displayModeBar": False})
        st.caption(fig_five_year_caption)
        st.markdown(five_year_caption(ctx, facts, last_five_year_data))
    else:
        st.info("Not enough recent daily data available to show the last five years for this location.")
    # ################################################################################

    # ################################################################################
    # 1E. Last ~50 years — monthly averages and trend
    st.subheader("Last 50 years — monthly averages and trend")
    last_fifty_year_data = build_fifty_year_data(ctx)
    if last_fifty_year_data:
        fig_fifty_year, fig_fifty_year_caption = build_fifty_year_figure(ctx, facts, last_fifty_year_data)
        st.plotly_chart(fig_fifty_year, width="stretch", config={"displayModeBar": False})
        st.caption(fig_fifty_year_caption)
        st.markdown(fifty_year_caption(ctx, facts, last_fifty_year_data))
    else:
        st.info("Not enough recent daily data available to show the last fifty years for this location.")
    # ################################################################################

    # ################################################################################
    # 1F. A simple 25-year projection, assuming the same trend continues
    st.subheader("Looking 25 years ahead (simple trend extension)")
    twenty_five_years_data = build_twenty_five_years_data(ctx)
    if twenty_five_years_data:
        fig_twenty_five_years, fig_twenty_five_years_caption = build_twenty_five_years_figure(ctx, facts, twenty_five_years_data)
        st.plotly_chart(fig_twenty_five_years, width="stretch", config={"displayModeBar": False})
        st.caption(fig_twenty_five_years_caption)
        st.markdown(twenty_five_years_caption(ctx, facts, twenty_five_years_data))
    else:
        st.info("Not enough yearly data to draw a simple trend extension here.")
    # ################################################################################

# -----------------------------------------------------------
# STEP: SEASONS THEN VS NOW
# -----------------------------------------------------------
if step == "Seasons then vs now":
    st.header("2. How your seasons have shifted")

    # ################################################################################
    # 2A. Recent
    seasons_data = build_seasons_then_now_data(ctx)
    if seasons_data:
        fig_seasons, fig_seasons_caption = build_seasons_then_now_figure(ctx, facts, seasons_data)
        st.plotly_chart(fig_seasons, width="stretch", config={"displayModeBar": False})
        st.caption(fig_seasons_caption)
        st.markdown(seasons_then_now_caption(ctx, facts, seasons_data))
    else:
        st.info("Monthly climatologies are not available for this location.")
    # ################################################################################

    # ################################################################################
    # 2B. Min–max envelopes for early vs recent climates
    st.subheader("How the range of monthly temperatures has changed")
    fig_env_past, fig_env_recent = build_seasons_then_now_separate_figures(ctx, facts, seasons_data)
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_env_past, width="stretch", config={"displayModeBar": False})
    with c2:
        st.plotly_chart(fig_env_recent, width="stretch", config={"displayModeBar": False})
    st.markdown(seasons_then_now_separate_caption(ctx, facts, seasons_data))
    # ################################################################################

# -----------------------------------------------------------
# STEP: YOU VS THE WORLD (ANOMALIES)
# -----------------------------------------------------------
if step == "You vs the world":
    # ################################################################################
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
    # ################################################################################

# -----------------------------------------------------------
# STEP: WORLD MAP IDEA
# -----------------------------------------------------------
if step == "World map":
    st.header("4. Where you fit on the world map")

    data = build_world_map_data(ctx)
    m, tiny = build_world_map_figure(ctx, facts, data)

    st.caption(tiny)
    st.markdown(world_map_caption(ctx, facts, data))

    st_folium(m, width="stretch", height=520)
