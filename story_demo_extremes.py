import pathlib
from datetime import datetime

import numpy as np
import pandas as pd
import xarray as xr
import streamlit as st
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium

# -------------------------------------------------------------------
# Basic config
# -------------------------------------------------------------------

st.set_page_config(page_title="Your Climate Story", layout="wide")

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent

LOCATIONS = {
    "Mauritius": {
        "lat": -20.2,
        "lon": 57.5,
        "extremes_path": BASE_DIR / "data" / "extremes_mauritius.nc",
    },
    "London": {
        "lat": 51.5074,
        "lon": -0.1278,
        "extremes_path": BASE_DIR / "data" / "extremes_london.nc",
    },
}


# -------------------------------------------------------------------
# Helpers to load & use extremes NetCDFs
# -------------------------------------------------------------------

@st.cache_data
def load_extremes(path: pathlib.Path) -> xr.Dataset:
    ds = xr.open_dataset(path)
    # ensure 'date' coords are datetime64 for the daily series
    for name in [
        "tmean_past", "tmax_past", "tmin_past",
        "tmean_recent", "tmax_recent", "tmin_recent",
    ]:
        if name in ds:
            ds[name]["date"] = pd.to_datetime(ds[name]["date"].values)
    return ds


def daily_series(ds: xr.Dataset, var: str) -> pd.Series:
    """Convert one of tmean_* / tmax_* / tmin_* to a pandas Series."""
    da = ds[var]
    return pd.Series(da.values, index=pd.to_datetime(da["date"].values))


def make_last_year_seasonal_fig(ds: xr.Dataset) -> go.Figure | None:
    """Use tmean_recent to show last available year: daily vs 7-day mean."""
    if "tmean_recent" not in ds:
        return None

    s = daily_series(ds, "tmean_recent").sort_index()
    if s.empty:
        return None

    last_year = int(s.index.year.max())
    s_year = s[s.index.year == last_year]
    if s_year.empty:
        return None

    s_roll = s_year.rolling(window=7, center=True, min_periods=1).mean()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=s_year.index,
            y=s_year.values,
            mode="lines",
            line=dict(color="rgba(0,0,0,0.3)", width=1),
            name="Daily mean",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=s_roll.index,
            y=s_roll.values,
            mode="lines",
            line=dict(color="rgba(33,113,181,1.0)", width=3),
            name="7-day mean",
        )
    )
    fig.update_layout(
        margin=dict(l=40, r=10, t=40, b=40),
        height=350,
        showlegend=True,
        yaxis_title="Temperature (°C)",
        title=f"Last available year ({last_year}) — seasonal cycle",
    )
    return fig


def typical_week_fig(ds: xr.Dataset, kind: str) -> go.Figure | None:
    """
    kind = "summer" or "winter".
    Uses typical_<kind>_past / typical_<kind>_recent (daily max) from extremes NC.
    """
    var_past = f"typical_{kind}_past"
    var_recent = f"typical_{kind}_recent"
    if var_past not in ds or var_recent not in ds:
        return None

    y_past = ds[var_past].values
    y_recent = ds[var_recent].values
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=days,
            y=y_past,
            mode="lines+markers",
            line=dict(color="rgba(166, 189, 219, 1.0)", width=3),
            marker=dict(size=7),
            name="Past",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=days,
            y=y_recent,
            mode="lines+markers",
            line=dict(color="rgba(215, 25, 28, 1.0)", width=3),
            marker=dict(size=7),
            name="Recent",
        )
    )

    title = "Typical summer week" if kind == "summer" else "Typical winter week"
    subtitle = "Daily maximum temperature, Mon–Sun"

    fig.update_layout(
        title=f"{title} — then vs now<br><sup>{subtitle}</sup>",
        margin=dict(l=40, r=10, t=60, b=40),
        height=350,
        yaxis_title="Daily max (°C)",
        xaxis_title="Day of week",
    )
    return fig


def heatwave_text(ds: xr.Dataset) -> str:
    """Build a short paragraph comparing heatwaves then vs now."""
    def get_scalar(name: str, default: float = 0.0) -> float:
        if name not in ds:
            return default
        val = ds[name].item()
        try:
            return float(val)
        except Exception:
            return default

    hw_p_count = get_scalar("heatwave_past_count")
    hw_p_maxlen = get_scalar("heatwave_past_max_length")
    hw_p_total = get_scalar("heatwave_past_total_days")

    hw_r_count = get_scalar("heatwave_recent_count")
    hw_r_maxlen = get_scalar("heatwave_recent_max_length")
    hw_r_total = get_scalar("heatwave_recent_total_days")

    past_win = ds.attrs.get("past_window", "past period")
    recent_win = ds.attrs.get("recent_window", "recent period")

    def ratio(a, b):
        if b <= 0:
            return None
        return a / b

    parts = []

    parts.append(
        f"In your **past window** ({past_win}), we detect **{int(hw_p_count)} heatwave episodes** "
        f"lasting a total of **{int(hw_p_total)} days**, with the longest heatwave lasting "
        f"about **{int(hw_p_maxlen)} days**."
    )

    parts.append(
        f"In the **recent window** ({recent_win}), there are **{int(hw_r_count)} heatwave episodes** "
        f"spanning **{int(hw_r_total)} days** in total, and the longest one lasts "
        f"around **{int(hw_r_maxlen)} days**."
    )

    r_count = ratio(hw_r_count, hw_p_count)
    r_total = ratio(hw_r_total, hw_p_total)

    if r_count is not None and r_count > 1.1:
        parts.append(
            f"That’s roughly **{r_count:.1f}× more heatwave events** than in the earlier period."
        )
    elif r_count is not None and r_count < 0.9:
        parts.append(
            f"That’s actually **fewer heatwave events** than in the earlier period."
        )

    if r_total is not None and r_total > 1.1:
        parts.append(
            f"In terms of days under heatwave conditions, the recent window has "
            f"about **{r_total:.1f}× more heatwave days**."
        )

    if hw_p_count == 0 and hw_r_count > 0:
        parts.append(
            "In the earlier period we did not detect any events crossing the heatwave threshold; "
            "in the recent period, those events start to appear."
        )

    return "\n\n".join(parts)


def headline_warming_text(ds: xr.Dataset) -> str:
    """Short summary of mean warming between past & recent windows."""
    s_p = daily_series(ds, "tmean_past")
    s_r = daily_series(ds, "tmean_recent")
    if s_p.empty or s_r.empty:
        return ""

    mu_p = float(s_p.mean())
    mu_r = float(s_r.mean())
    delta = mu_r - mu_p

    past_win = ds.attrs.get("past_window", "past")
    recent_win = ds.attrs.get("recent_window", "recent")
    loc_name = ds.attrs.get("location_name", "this location")

    sign_word = "warmer" if delta > 0 else "cooler"
    return (
        f"At **{loc_name}**, the daily mean temperature in your recent window "
        f"({recent_win}) is about **{delta:+.1f}°C {sign_word}** than in the earlier window "
        f"({past_win})."
    )


# -------------------------------------------------------------------
# Sidebar: location + stepper
# -------------------------------------------------------------------

st.sidebar.title("Your Climate Story")

loc_name = st.sidebar.selectbox("Location", list(LOCATIONS.keys()))
loc = LOCATIONS[loc_name]

step = st.sidebar.radio(
    "Step",
    [
        "Intro",
        "Seasonal cycle (last year)",
        "Warming between periods",
        "Extremes: typical weeks",
        "Extremes: heatwaves",
    ],
)

# Load extremes NC for this location
extreme_path = loc["extremes_path"]
if not extreme_path.exists():
    st.error(f"Extremes file not found: {extreme_path}")
    st.stop()

ds_ext = load_extremes(extreme_path)


# -------------------------------------------------------------------
# Main layout
# -------------------------------------------------------------------

st.title("Your Climate Story — prototype")

# Shared map for context (shown at least on Intro)
if step == "Intro":
    st.subheader("Where are we looking?")
    col_map, col_text = st.columns([2, 3])

    with col_map:
        m = folium.Map(location=[loc["lat"], loc["lon"]], zoom_start=5, tiles="CartoDB positron")
        folium.CircleMarker(
            location=[loc["lat"], loc["lon"]],
            radius=8,
            color="#d73027",
            fill=True,
            fill_opacity=0.9,
        ).add_to(m)
        st_folium(m, width="stretch", height=420)

    with col_text:
        st.markdown(
            f"""
### {loc_name}

We’ve precomputed a small climate summary for this location, using **ERA5 reanalysis**
served through the **Open-Meteo archive API**.

This includes:

- Daily mean, max and min temperatures for a **past** window (*{ds_ext.attrs.get('past_window', '?')}*)  
  and a **recent** window (*{ds_ext.attrs.get('recent_window', '?')}*).
- A simple detection of **heatwaves** (multi-day periods of unusually high daily maxima).
- “Typical” **summer** and **winter** weeks, based on daily maximum temperature.

Use the steps in the sidebar to move through the story:
- First, see how the **seasonal cycle** looks in the most recent year.
- Then, how the **whole distribution** has shifted between the two windows.
- Finally, zoom into **typical hot and cold weeks** and the **heatwave statistics**.
"""
        )

# -------------------------------------------------------------------
# Step: Seasonal cycle (last year)
# -------------------------------------------------------------------
elif step == "Seasonal cycle (last year)":
    fig = make_last_year_seasonal_fig(ds_ext)
    if fig is None:
        st.warning("No recent daily series available to build the seasonal cycle.")
    else:
        st.plotly_chart(fig, use_container_width=True)
        st.markdown(
            """
This shows the **most recent year** in the “recent” window:

- The pale grey line is the **daily mean temperature**.
- The thicker blue line is a **7-day running mean**, smoothing out day-to-day noise.

As you scroll through the year, you can see how the **seasons** play out at this location today.
"""
        )

# -------------------------------------------------------------------
# Step: Warming between periods
# -------------------------------------------------------------------
elif step == "Warming between periods":
    text = headline_warming_text(ds_ext)
    if not text:
        st.warning("Could not compute mean warming between periods.")
    else:
        st.subheader("How much warmer is it now?")
        st.markdown(text)

        s_p = daily_series(ds_ext, "tmean_past")
        s_r = daily_series(ds_ext, "tmean_recent")
        df = pd.DataFrame(
            {"date": s_p.index.union(s_r.index)}
        ).set_index("date")
        df["past"] = s_p
        df["recent"] = s_r

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["past"],
                mode="lines",
                line=dict(color="rgba(166, 189, 219, 1.0)", width=2),
                name="Past daily mean",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["recent"],
                mode="lines",
                line=dict(color="rgba(215, 25, 28, 1.0)", width=2),
                name="Recent daily mean",
            )
        )
        fig.update_layout(
            title="Daily mean temperature — past vs recent windows",
            yaxis_title="Temperature (°C)",
            xaxis_title="Date",
            margin=dict(l=40, r=10, t=60, b=40),
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown(
            """
Each line here is the **daily mean temperature** for one of the two windows.  
We’re not yet focusing on individual heatwaves — this is the **overall shift** in day-to-day climate.
"""
        )

# -------------------------------------------------------------------
# Step: Extremes — typical weeks
# -------------------------------------------------------------------
elif step == "Extremes: typical weeks":
    st.subheader("What does a typical hot (and cold) week look like now vs then?")

    col1, col2 = st.columns(2)
    with col1:
        fig_summer = typical_week_fig(ds_ext, "summer")
        if fig_summer is None:
            st.warning("No typical summer week information available.")
        else:
            st.plotly_chart(fig_summer, use_container_width=True)

    with col2:
        fig_winter = typical_week_fig(ds_ext, "winter")
        if fig_winter is None:
            st.warning("No typical winter week information available.")
        else:
            st.plotly_chart(fig_winter, use_container_width=True)

    st.markdown(
        """
These “typical weeks” come from many summers (or winters) in each window:

- We look at the **daily maximum temperature**, group by **day of week**, and take a median.
- The **red line** is a typical week in the **recent** climate.
- The **paler blue line** is a typical week in the **earlier** climate.

If the red curve sits consistently above the blue one, then a **normal hot week today**
is simply **hotter** than it used to be.  
Likewise for winter: the whole cold season can shift upwards by a degree or two.
"""
    )

# -------------------------------------------------------------------
# Step: Extremes — heatwaves
# -------------------------------------------------------------------
elif step == "Extremes: heatwaves":
    st.subheader("Heatwaves then vs now")

    st.markdown(
        """
Here we define a **heatwave** as a period of at least three consecutive days where
the daily maximum temperature is above a **very high local threshold** based on the
earlier climate (for example, the top few percent hottest days in the past window).

That’s a simple, local way to say: “a spell of **unusually hot days** for this place,
compared to what used to be normal.”
"""
    )

    st.markdown(heatwave_text(ds_ext))

    st.info(
        "These numbers come from daily maximum ERA5 temperatures for your past and recent "
        "windows at this location, via the Open-Meteo ERA5 archive API."
    )
