import streamlit as st
import numpy as np
import xarray as xr
from datetime import datetime, timedelta
from pathlib import Path
import concurrent.futures as cf
import time
import random

# UI libs
import plotly.graph_objs as go
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

# Earthkit
import earthkit.data as ekd
from earthkit.data import config as ek_config, cache as ek_cache

st.set_page_config(page_title="Your Place, Warming Over Time", layout="wide")

# ---------------- Earthkit persistent cache ----------------
ek_config.set({
    "cache-policy": "user",
    "user-cache-directory": str(Path("~/ek-cache").expanduser()),
    "maximum-cache-size": "200G",
    "maximum-cache-disk-usage": "99%",
})
st.sidebar.caption(f"EK cache: {ek_cache.directory()}")

# ---------------- Helpers ----------------
def normalise_dims(ds: xr.Dataset) -> xr.Dataset:
    if "expver" in ds.dims:
        ds = ds.sortby("expver").ffill("expver").isel(expver=-1, drop=True)
    if "number" in ds.dims:
        ds = ds.mean("number", keep_attrs=True)
    return ds

def standardise_time(ds: xr.Dataset) -> xr.Dataset:
    if "valid_time" in ds.dims and "time" not in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    if "time" in ds.dims and "valid_time" in ds.coords:
        if ds.sizes.get("time") == ds.sizes.get("valid_time"):
            ds = ds.assign_coords(time=ds["valid_time"]).drop_vars("valid_time")
        else:
            ds = ds.drop_vars("valid_time")
    if "time" not in ds.coords and "time" in ds:
        ds = ds.set_coords("time")
    return ds

def nearest_cell(da: xr.DataArray, lat: float, lon: float):
    # ERA5 longitudes are 0..360 sometimes; adjust lon accordingly
    if da.longitude.max() > 180 and lon < 0:
        lon = lon % 360
    return da.sel(latitude=lat, longitude=lon, method="nearest")

def small_bbox(lat, lon, buf=0.5):
    return [lat + buf, lon - buf, lat - buf, lon + buf]  # [N,W,S,E]

# ---------------- ERA5 fetchers ----------------
def _req_common(area, years, months, hours, fmt="grib"):
    return {
        "product_type": "reanalysis",
        "variable": ["2m_temperature"],
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in months],
        "day": [f"{d:02d}" for d in range(1,32)],  # CDS ignores invalid days
        "time": [f"{h:02d}:00" for h in hours],
        "area": area,    # [N,W,S,E]
        "format": fmt,   # prefer GRIB for faster preparation
    }

def fetch_hourly_range(lat, lon, start_dt, end_dt, buf=0.5, fmt="grib") -> xr.Dataset:
    # Compact request: all needed years/months/hours — CDS builds one file
    area = small_bbox(lat, lon, buf=buf)
    dt = start_dt
    years = sorted(set([start_dt.year, end_dt.year]))
    months = sorted(set([(start_dt.month + i - 1) % 12 + 1
                         for i in range((end_dt.year-start_dt.year)*12 + (end_dt.month-start_dt.month) + 1)]))
    hours = list(range(0,24))
    req = _req_common(area, years, months, hours, fmt=fmt)
    # For safety, also pass "date" bounds via slicing after load
    d = ekd.from_source("cds", "reanalysis-era5-single-levels", req)
    ds = d.to_xarray()
    ds = normalise_dims(standardise_time(ds))
    ds = ds.sortby("time").sel(time=slice(np.datetime64(start_dt), np.datetime64(end_dt)))
    return ds

def fetch_monthly(lat, lon, years, buf=0.5, fmt="grib") -> xr.Dataset:
    area = small_bbox(lat, lon, buf=buf)
    req = {
        "product_type": "monthly_averaged_reanalysis",
        "variable": ["2m_temperature"],
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in range(1,13)],
        "time": "00:00",
        "area": area,
        "format": fmt,
    }
    d = ekd.from_source("cds","reanalysis-era5-single-levels-monthly-means", req)
    ds = normalise_dims(standardise_time(d.to_xarray()))
    return ds.sortby("time")

# ------------- Feature computations ----------------
def hourly_to_daily_mean(ds: xr.Dataset) -> xr.DataArray:
    t2m = ds["t2m"] - 273.15
    # Single point selection later; for now mean over small bbox
    return t2m.mean(["latitude","longitude"]).resample(time="1D").mean()

def monthly_point_series(ds: xr.Dataset, lat, lon) -> xr.DataArray:
    t2m = (ds["t2m"] - 273.15).mean(["latitude","longitude"])
    return t2m

def annotate_extremes(fig, series, name=""):
    max_idx = int(np.nanargmax(series.values))
    min_idx = int(np.nanargmin(series.values))
    for idx, lab in [(max_idx,"record high"), (min_idx,"record low")]:
        fig.add_annotation(
            x=series.time.values[idx],
            y=series.values[idx],
            text=lab,
            showarrow=True,
            arrowhead=2
        )

def daily_climatology(ds: xr.Dataset, lat, lon) -> xr.DataArray:
    """Average daily cycle over multiple years."""
    t2m = (ds["t2m"] - 273.15).mean(["latitude","longitude"])
    df = t2m.resample(time="1D").mean()
    clim = df.groupby("time.dayofyear").mean()
    # turn to a fake 365-day index for plotting
    return clim

# ------------- UI: location ----------------
st.title("Your location, your warming story")

st.markdown("**Step 1 — Detect location.** Allow the browser location prompt. No data is fetched until you click Start.")

if "loc" not in st.session_state:
    st.session_state["loc"] = None
if "start_pressed" not in st.session_state:
    st.session_state["start_pressed"] = False

# Map with a placeholder marker
center = [20, 0]
m = folium.Map(location=center, zoom_start=2, tiles="OpenStreetMap")
out = st_folium(m, height=320, use_container_width=True)

# Try to use the browser-provided map click to set location
st.info("Click on the map to set your location, or enter coordinates below.")
clicked = out.get("last_clicked") if out else None
colA, colB = st.columns(2)
if clicked and not st.session_state["loc"]:
    st.session_state["loc"] = (clicked["lat"], clicked["lng"])
lat = colA.number_input("Latitude", value=st.session_state["loc"][0] if st.session_state["loc"] else 51.5074, format="%.5f")
lon = colB.number_input("Longitude", value=st.session_state["loc"][1] if st.session_state["loc"] else -0.1278, format="%.5f")

# Reverse geocode (best-effort)
place = "Unknown"
try:
    geolocator = Nominatim(user_agent="climate-zoomout")
    loc = geolocator.reverse(f"{lat}, {lon}", language="en", timeout=5)
    if loc and loc.address:
        place = loc.address.split(",")[0] + ", " + loc.address.split(",")[-1].strip()
except Exception:
    pass

st.map(data={"lat":[lat], "lon":[lon]}, size=10, zoom=8)
st.caption(f"Location: {place}  (lat={lat:.3f}, lon={lon:.3f})")

start_btn = st.button("Start (fetch data)")
if start_btn:
    st.session_state["start_pressed"] = True

# ------------- Data fetch orchestration -------------
if st.session_state["start_pressed"]:
    # Define windows
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    five_months_ago = now - timedelta(days=150)  # ~5 months
    recent_years = list(range(now.year-4, now.year+1))  # last 5 years
    past_years = [y-50 for y in recent_years]           # 50 years earlier
    recent_range_start = datetime(now.year-5, 1, 1)
    recent_range_end = datetime(now.year, 12, 31)

    # Parallel prefetch: hourly windows for last ~6 months & monthly blocks
    progress = st.empty()
    bar = st.progress(0)
    tasks = {}

    def submit(executor):
        tasks["hourly_7d"] = executor.submit(fetch_hourly_range, lat, lon, seven_days_ago, now, 0.5, "grib")
        tasks["hourly_5mo"] = executor.submit(fetch_hourly_range, lat, lon, five_months_ago, now, 0.5, "grib")
        tasks["monthly_recent"] = executor.submit(fetch_monthly, lat, lon, recent_years, 0.5, "grib")
        tasks["monthly_past"] = executor.submit(fetch_monthly, lat, lon, past_years, 0.5, "grib")

    done_count = 0
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        submit(ex)
        for fut in cf.as_completed(tasks.values()):
            done_count += 1
            bar.progress(done_count/len(tasks))
            progress.markdown(f"Fetching… **{done_count}/{len(tasks)}** chunks ready")

    bar.empty(); progress.empty()

    ds_7d = tasks["hourly_7d"].result()
    ds_5m = tasks["hourly_5mo"].result()
    ds_m_recent = tasks["monthly_recent"].result()
    ds_m_past = tasks["monthly_past"].result()

    # ------------- Sections (“zoom out”) -------------
    st.header("Past 7 days — hourly average")
    ts_hourly = (ds_7d["t2m"] - 273.15).mean(["latitude","longitude"])
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=ts_hourly.time.values, y=ts_hourly.values, mode="lines", name="°C"))
    fig1.update_layout(yaxis_title="°C", xaxis_title="Time (UTC)")
    # Simple extremes
    annotate_extremes(fig1, ts_hourly)
    st.plotly_chart(fig1, use_container_width=True)

    st.header("Last ~5 months — daily average")
    ts_daily_5m = hourly_to_daily_mean(ds_5m)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=ts_daily_5m.time.values, y=ts_daily_5m.values, mode="lines", name="Daily mean °C"))
    annotate_extremes(fig2, ts_daily_5m, "5m")
    fig2.update_layout(yaxis_title="°C", xaxis_title="Date")
    st.plotly_chart(fig2, use_container_width=True)

    st.header("Past 5 years — monthly average")
    ts_m_recent = monthly_point_series(ds_m_recent, lat, lon)
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=ts_m_recent.time.values, y=ts_m_recent.values, mode="lines+markers", name="Recent 5y"))
    fig3.update_layout(yaxis_title="°C", xaxis_title="Month")
    st.plotly_chart(fig3, use_container_width=True)

    st.header("Overlay: past 5 years vs same months 50 years earlier")
    ts_m_past = monthly_point_series(ds_m_past, lat, lon)
    # Align on month-of-year to overlay
    rec = xr.DataArray(ts_m_recent.values, coords={"time": ts_m_recent.time}, dims=["time"])
    pas = xr.DataArray(ts_m_past.values,   coords={"time": ts_m_past.time},   dims=["time"])
    rec_m = rec.groupby("time.month").mean()
    pas_m = pas.groupby("time.month").mean()

    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=list(range(1,13)), y=rec_m.values, mode="lines+markers", name=f"{recent_years[0]}–{recent_years[-1]}"))
    fig4.add_trace(go.Scatter(x=list(range(1,13)), y=pas_m.values, mode="lines+markers", name=f"{past_years[0]}–{past_years[-1]}"))
    fig4.update_layout(xaxis=dict(tickmode="array", tickvals=list(range(1,13))), yaxis_title="°C", xaxis_title="Month")
    st.plotly_chart(fig4, use_container_width=True)

    st.header("“Typical” year: daily average (recent vs 50y earlier)")
    # Build daily climatologies
    ds_recent_daily = fetch_hourly_range(lat, lon,
                                         datetime(recent_years[0],1,1),
                                         datetime(recent_years[-1],12,31),
                                         0.5, "grib")
    ds_past_daily = fetch_hourly_range(lat, lon,
                                       datetime(past_years[0],1,1),
                                       datetime(past_years[-1],12,31),
                                       0.5, "grib")
    clim_recent = daily_climatology(ds_recent_daily, lat, lon)
    clim_past = daily_climatology(ds_past_daily, lat, lon)
    # Align to 365 days
    days = np.arange(1, len(clim_recent)+1)
    fig5 = go.Figure()
    fig5.add_trace(go.Scatter(x=days, y=clim_recent.values, mode="lines", name="Recent typical year"))
    fig5.add_trace(go.Scatter(x=days, y=clim_past.values, mode="lines", name="Past typical year"))
    fig5.update_layout(xaxis_title="Day of year", yaxis_title="°C")
    st.plotly_chart(fig5, use_container_width=True)

else:
    st.info("Set your location (click the map or enter coordinates) and click **Start** to fetch data.")

# ----------------- Sidebar insights & toggles -----------------
with st.sidebar:
    st.header("Insights & options")
    st.markdown("- We use ERA5 reanalysis at the nearest grid cell to your location.")
    st.markdown("- Hourly: derived directly; Daily/Monthly: averaged from hourly or monthly means.")
    st.markdown("- For clearer warming signals, monthly & annual **means** are robust; you can optionally add min/max bands if you like.")
