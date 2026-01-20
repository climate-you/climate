import os
from datetime import date, datetime
from pathlib import Path

import plotly.express as px
import pandas as pd
import streamlit as st
import xarray as xr

CLIM_DIR = Path("data/story_climatology")

# ############################################


def last_full_quarter_end(today: date) -> date:
    q_end_month = ((today.month - 1) // 3) * 3
    if q_end_month == 0:
        return date(today.year - 1, 12, 31)
    # last day of q_end_month
    if q_end_month in (1, 3, 5, 7, 8, 10, 12):
        last_day = 31
    elif q_end_month in (4, 6, 9, 11):
        last_day = 30
    else:
        # Feb
        y = today.year
        last_day = 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
    return date(today.year, q_end_month, last_day)


def status_for_slug(slug: str) -> str:
    path = CLIM_DIR / f"clim_{slug}.nc"
    if not os.path.exists(path):
        return "missing"
    try:
        ds = xr.open_dataset(path)
        end_str = ds.attrs.get("data_end_date") or ds.attrs.get("end_date")
        ds.close()
        if not end_str:
            return "stale"
        end_date = datetime.fromisoformat(str(end_str)).date()
        return "fresh" if end_date >= target_end else "stale"
    except Exception:
        return "stale"


# ############################################
st.set_page_config(page_title="Locations map", layout="wide")

st.title("locations.csv — city distribution")

# Adjust path if needed
CSV_PATH = "locations/locations.csv"

df = pd.read_csv(CSV_PATH)

# Expect columns like: lat, lon (or latitude, longitude). Adapt if yours differ.
if "lat" in df.columns and "lon" in df.columns:
    plot_df = df.rename(columns={"lat": "latitude", "lon": "longitude"})
elif "latitude" in df.columns and "longitude" in df.columns:
    plot_df = df.copy()
else:
    st.error(f"Couldn't find lat/lon columns in {CSV_PATH}. Found: {list(df.columns)}")
    st.stop()

st.caption(f"{len(plot_df):,} locations")

# Optional: quick filters
with st.sidebar:
    st.header("Filters (optional)")
    if "country_code" in df.columns:
        countries = ["(all)"] + sorted(df["country_code"].dropna().unique().tolist())
        cc = st.selectbox("Country code", countries, index=0)
        if cc != "(all)":
            plot_df = (
                plot_df[df["country_code"] == cc].rename(
                    columns={"lat": "latitude", "lon": "longitude"}
                )
                if "lat" in df.columns
                else df[df["country_code"] == cc]
            )
    st.write("")

target_end = last_full_quarter_end(date.today())

plot_df = plot_df.copy()
plot_df["status"] = (
    plot_df["slug"].apply(status_for_slug) if "slug" in plot_df.columns else "missing"
)

total = len(plot_df)
counts = plot_df["status"].value_counts().to_dict()

missing = int(counts.get("missing", 0))
stale = int(counts.get("stale", 0))  # or "out_of_date" if that's your label
fresh = int(counts.get("fresh", 0))  # or "up_to_date"

st.subheader("Precompute coverage")
c1, c2, c3 = st.columns(3)

with c1:
    st.write(f"Missing: **{missing}/{total}**")
    st.progress(0 if total == 0 else missing / total)

with c2:
    st.write(f"Out of date: **{stale}/{total}**")
    st.progress(0 if total == 0 else stale / total)

with c3:
    st.write(f"Up to date: **{fresh}/{total}**")
    st.progress(0 if total == 0 else fresh / total)

fig = px.scatter_geo(
    plot_df,
    lat="latitude",
    lon="longitude",
    color="status",
    hover_name="name" if "name" in plot_df.columns else None,
    hover_data={c: True for c in plot_df.columns if c not in ("latitude", "longitude")},
    projection="natural earth",
    title=f"Precompute status (target end: {target_end.isoformat()})",
    color_discrete_map={
        "missing": "gray",
        "stale": "gold",
        "fresh": "green",
    },
)
# Make it big on load
fig.update_layout(
    height=720,
    margin=dict(l=0, r=0, t=20, b=0),
)
st.plotly_chart(fig, width="stretch")

# Streamlit's built-in map (fast + simple)
# st.map(plot_df[["latitude", "longitude"]], zoom=1)
