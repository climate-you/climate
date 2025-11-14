# app.py
import streamlit as st
import xarray as xr
import numpy as np
from pathlib import Path
import concurrent.futures as cf
import time
import random


# --- Earthkit cache config (persistent, no auto-clean loop) -------------------
from earthkit.data import config as ek_config, cache as ek_cache
ek_config.set({
    "cache-policy": "user",
    "user-cache-directory": str(Path("~/Documents/Programming/Climate/ek-cache").expanduser()),
    "maximum-cache-size": "20G",
    "maximum-cache-disk-usage": "99%",
})
st.write(f"Earthkit cache dir: {ek_cache.directory()}")

# --- Imports for data fetch and map UI ---------------------------------------
import earthkit.data as ekd
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium

st.set_page_config(page_title="ERA5 Temperature Trends", layout="wide")

# ---------- Helpers for ERA5/xarray quirks ----------
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

# ---------- Per-year fetching (Streamlit-cached) ----------
def _fetch_one_year_nocache(N: float, W: float, S: float, E: float, year: int) -> xr.Dataset:
    """Single-year fetch (no Streamlit cache decorator so it's thread-friendly).
       Earthkit still uses its on-disk cache, so already-downloaded years return fast."""
    req = {
        "product_type": "monthly_averaged_reanalysis",
        "variable": ["2m_temperature"],
        "year": [str(year)],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": "00:00",
        "area": [N, W, S, E],   # [North, West, South, East]
        "format": "netcdf",
    }
    data = ekd.from_source("cds", "reanalysis-era5-single-levels-monthly-means", req)
    ds = data.to_xarray()
    ds = normalise_dims(ds)
    ds = standardise_time(ds)
    return ds

def _fetch_one_year_with_retry(N, W, S, E, year, max_retries=3, base_wait=4.0):
    for attempt in range(1, max_retries + 1):
        try:
            return _fetch_one_year_nocache(N, W, S, E, year)
        except Exception as e:
            if attempt == max_retries:
                raise
            # jittered exponential backoff
            wait = base_wait * (2 ** (attempt - 1)) * (0.7 + 0.6 * random.random())
            time.sleep(wait)

@st.cache_data(show_spinner=True)
def fetch_era5_years_parallel(bbox: str, start: int, end: int, max_workers: int = 3) -> xr.Dataset:
    """Parallel per-year fetch using a small worker pool. Output is cached for identical inputs."""
    N, W, S, E = map(float, bbox.split(","))
    years = list(range(int(start), int(end) + 1))
    # Bound workers (None or <1 -> fallback to sequential)
    workers = max(1, int(max_workers))

    # Progress UI
    progress_text = st.empty()
    progress_bar = st.progress(0)
    done = 0

    parts = [None] * len(years)
    # Submit in order but complete out-of-order; we’ll reassemble by index
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for idx, y in enumerate(years):
            fut = ex.submit(_fetch_one_year_with_retry, N, W, S, E, y)
            futs[fut] = (idx, y)

        for fut in cf.as_completed(futs):
            idx, y = futs[fut]
            parts[idx] = fut.result()
            done += 1
            progress_bar.progress(done / len(years))
            progress_text.markdown(f"Downloading **{done}/{len(years)}** — finished year **{y}**")

    progress_text.empty()
    progress_bar.empty()

    ds = xr.concat(parts, dim="time").sortby("time")
    return ds

# ---------- Map selector ----------
st.title("Temperature trends by region (ERA5 monthly)")

# Session state for bbox & submission
if "bbox" not in st.session_state:
    st.session_state["bbox"] = None  # will hold [N, W, S, E]
if "submitted" not in st.session_state:
    st.session_state["submitted"] = False

with st.container():
    st.subheader("1) Select a region on the map")
    st.caption("Draw a rectangle (the app won’t download anything until you click **Load data**).")

    # Center map: use last bbox center or a neutral default
    if st.session_state["bbox"]:
        N, W, S, E = st.session_state["bbox"]
        center = [(N + S) / 2.0, (W + E) / 2.0]
        zoom = 4
    else:
        center, zoom = [20, 0], 2

    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")
    Draw(
        draw_options={
            "polyline": False, "polygon": False, "circle": False,
            "circlemarker": False, "marker": False, "rectangle": True
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)

    out = st_folium(m, height=420, use_container_width=True,
                    returned_objects=["last_active_drawing"])

    # If a rectangle was drawn, capture bbox as [N, W, S, E]
    if out and out.get("last_active_drawing"):
        feat = out["last_active_drawing"]
        if feat and feat["geometry"]["type"] == "Polygon":
            coords = feat["geometry"]["coordinates"][0]  # [ [lon,lat], ...]
            lats = [pt[1] for pt in coords]
            lons = [pt[0] for pt in coords]
            N, S = max(lats), min(lats)
            E, W = max(lons), min(lons)
            st.session_state["bbox"] = [float(N), float(W), float(S), float(E)]

    st.write("Selected bbox [N, W, S, E]:",
             f"**{st.session_state['bbox'] if st.session_state['bbox'] else 'None'}**")

# ---------- Form: gate the fetch behind a button ----------
st.subheader("2) Set the period and load data")
with st.form("controls", clear_on_submit=False):
    col1, col2 = st.columns(2)
    with col1:
        start = st.number_input("Start year", value=1995, min_value=1940, max_value=2100, step=1)
    with col2:
        end   = st.number_input("End year", value=2000, min_value=1940, max_value=2100, step=1)
    submitted = st.form_submit_button("Load data")

if submitted:
    st.session_state["submitted"] = True

# ---------- Only fetch AFTER explicit submit ----------
if st.session_state["submitted"]:
    if not st.session_state["bbox"]:
        st.warning("Please draw a rectangle on the map first.")
        st.stop()
    if start > end:
        st.warning("Start year must be ≤ End year.")
        st.stop()

    bbox_str = ",".join(map(str, st.session_state["bbox"]))
    with st.spinner("Fetching ERA5 monthly averages (using cache when available)…"):
        ds = fetch_era5_years_parallel(bbox_str, int(start), int(end), max_workers=3)

    # Compute area-weighted regional mean
    t2m = ds["t2m"] - 273.15
    weights = np.cos(np.deg2rad(t2m["latitude"])); weights /= weights.mean()
    ts = t2m.weighted(weights).mean(("latitude", "longitude")).sortby("time")

    st.subheader("3) Result")
    st.line_chart(ts.to_series(), height=320)

    # Trend °C/decade
    years = ts["time"].dt.year.values
    X = np.vstack([np.ones_like(years), years]).T
    slope = np.linalg.lstsq(X, ts.values, rcond=None)[0][1] * 10.0
    st.write(f"Trend: **{slope:.2f} °C/decade**")
    st.caption(f"time: {np.datetime_as_string(ts['time'].values[0], unit='D')} → "
               f"{np.datetime_as_string(ts['time'].values[-1], unit='D')} | n={ts.sizes['time']}")
else:
    st.info("Set your region and years, then click **Load data** to start.")
