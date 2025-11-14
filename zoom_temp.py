# zoom_temp.py
import streamlit as st
import numpy as np
import pandas as pd
import xarray as xr
from datetime import datetime, timedelta
from pathlib import Path
import requests
import concurrent.futures as cf

# Plotting / Map
import plotly.graph_objs as go
import folium
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

# Earthkit
import earthkit.data as ekd
from earthkit.data import config as ek_config, cache as ek_cache

# ---------------- Streamlit page config ----------------
st.set_page_config(page_title="Your Place, Warming Over Time", layout="wide")

# ---------------- Debug helper ----------------
def dbg(*args):
    print("[DEBUG]", *args)

# ---------------- Small helpers for sticky state ----------------
def get_state(key, default=None):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

def scroll_to(element_id: str):
    st.components.v1.html(
        f"""<script>
        var el = document.getElementById("{element_id}");
        if (el) {{ el.scrollIntoView({{behavior: "smooth", block: "start"}}); }}
        </script>""",
        height=0,
    )

# ---------------- Earthkit persistent cache ----------------
ek_config.set({
    "cache-policy": "user",
    "user-cache-directory": str(Path("~/ek-cache").expanduser()),
    "maximum-cache-size": "200G",
    "maximum-cache-disk-usage": "99%",
})
st.sidebar.caption(f"EK cache: {ek_cache.directory()}")

# ---------------- Sidebar toggles ----------------
with st.sidebar:
    st.header("Options")
    fast_mode   = st.toggle("Fast mode for recent windows (Open-Meteo)", value=True)
    cache_only  = st.toggle("Cache-only for CDS (don’t submit new jobs)", value=False)
    max_workers = st.slider("Max parallel jobs", 1, 3, 2)
    timeout_sec = st.slider("Per-chunk timeout (s)", 30, 240, 120, step=10)

# ---------------- Helpers: xarray/ERA5 quirks ----------------
def normalise_dims(ds: xr.Dataset) -> xr.Dataset:
    if "expver" in ds.dims:
        ds = ds.sortby("expver").ffill("expver").isel(expver=-1, drop=True)
    if "number" in ds.dims:
        ds = ds.mean("number", keep_attrs=True)
    return ds

def standardise_time(ds: xr.Dataset) -> xr.Dataset:
    """Canonicalise to a single coordinate named 'time'."""
    if "valid_time" in ds.dims and "time" not in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    if "time" in ds.dims and "valid_time" in ds.coords:
        if ds.sizes.get("time") == ds.sizes.get("valid_time"):
            ds = ds.assign_coords(time=ds["valid_time"]).drop_vars("valid_time")
        else:
            ds = ds.drop_vars("valid_time")
    if "time" not in ds.dims and "forecast_reference_time" in ds.dims:
        ds = ds.rename({"forecast_reference_time": "time"})
    if "time" not in ds.coords and "time" in ds:
        ds = ds.set_coords("time")
    return ds

def get_temp_da(ds: xr.Dataset) -> xr.DataArray:
    """
    Return 2m air temperature in °C.

    - ERA5 (CDS): 't2m' (monthly) or '2t' (hourly) are in Kelvin → convert.
    - Open-Meteo: 'temperature_2m' (or aliases '*_c') already °C → leave as is.
    """
    var = None
    for candidate in ("t2m", "2t", "temperature_2m", "2t_c", "t2m_c"):
        if candidate in ds.data_vars:
            var = candidate
            break
    if var is None:
        raise KeyError(f"No temperature variable found. Available: {list(ds.data_vars)}")

    da = ds[var]
    units = (da.attrs.get("units") or "").lower()
    if "c" in units:  # 'c', '°c', 'degc', 'celsius'
        return da

    # Heuristic fallback
    vmin = float(np.nanmin(da.values))
    vmax = float(np.nanmax(da.values))
    looks_kelvin = vmax > 200.0
    return da - 273.15 if looks_kelvin else da

def small_bbox(lat, lon, buf=0.25):
    return [lat + buf, lon - buf, lat - buf, lon + buf]  # [N, W, S, E]

# ---------------- CDS helper (we will fully skip when cache_only=True) ----------------
def cds_from_source(dataset: str, req: dict):
    return ekd.from_source("cds", dataset, req)

# ---------------- ERA5 fetchers (CDS) ----------------
def _req_hourly(area, years, months, hours, fmt="grib"):
    return {
        "product_type": "reanalysis",
        "variable": ["2m_temperature"],
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in months],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in hours],
        "area": area,
        "format": fmt,
    }

def fetch_hourly_range(lat, lon, start_dt, end_dt, buf=0.25, fmt="grib") -> xr.Dataset:
    area = small_bbox(lat, lon, buf=buf)
    months = []
    y, m = start_dt.year, start_dt.month
    while True:
        months.append((y, m))
        if y == end_dt.year and m == end_dt.month:
            break
        if m == 12: y, m = y + 1, 1
        else:       m += 1
    years = sorted(set(y for y, _ in months))
    months_only = sorted(set(m for _, m in months))
    hours = list(range(24))
    req = _req_hourly(area, years, months_only, hours, fmt=fmt)

    d = cds_from_source("reanalysis-era5-single-levels", req)
    ds = d.to_xarray()
    ds = normalise_dims(standardise_time(ds)).sortby("time")
    return ds.sel(time=slice(np.datetime64(start_dt), np.datetime64(end_dt)))

def fetch_monthly(lat, lon, years, buf=0.25, fmt="grib") -> xr.Dataset:
    area = small_bbox(lat, lon, buf=buf)
    req = {
        "product_type": "monthly_averaged_reanalysis",
        "variable": ["2m_temperature"],
        "year": [str(y) for y in years],
        "month": [f"{m:02d}" for m in range(1, 13)],
        "time": "00:00",
        "area": area,
        "format": fmt,
    }
    d = cds_from_source("reanalysis-era5-single-levels-monthly-means", req)
    ds = d.to_xarray()
    ds = normalise_dims(standardise_time(ds)).sortby("time")
    return ds

# ---------------- Fast mode (Open-Meteo ERA5 hourly) ----------------
def fetch_openmeteo_hourly(lat, lon, start_dt, end_dt) -> xr.Dataset:
    start = start_dt.strftime("%Y-%m-%d")
    end   = end_dt.strftime("%Y-%m-%d")
    url = (
        "https://archive-api.open-meteo.com/v1/era5"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        "&hourly=temperature_2m&timezone=UTC"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    j = r.json()
    ts = pd.to_datetime(j["hourly"]["time"])
    vals = np.array(j["hourly"]["temperature_2m"], dtype=float)  # already °C
    da = xr.DataArray(
        vals, coords={"time": ts}, dims=["time"],
        name="temperature_2m", attrs={"units": "degC", "source": "open-meteo ERA5"}
    )
    return xr.Dataset({"temperature_2m": da})

# ---------------- Feature computations ----------------
def hourly_to_daily_mean(ds: xr.Dataset) -> xr.DataArray:
    da = get_temp_da(ds)
    if "latitude" in da.dims and "longitude" in da.dims:
        da = da.mean(["latitude", "longitude"])
    return da.resample(time="1D").mean()

def monthly_point_series(ds: xr.Dataset) -> xr.DataArray:
    da = get_temp_da(ds)
    if "latitude" in da.dims and "longitude" in da.dims:
        da = da.mean(["latitude", "longitude"])
    return da

def annotate_extremes(fig, series):
    if series.size == 0 or np.all(np.isnan(series.values)): return
    max_idx = int(np.nanargmax(series.values))
    min_idx = int(np.nanargmin(series.values))
    for idx, lab in [(max_idx, "record high"), (min_idx, "record low")]:
        fig.add_annotation(x=series.time.values[idx], y=series.values[idx],
                           text=lab, showarrow=True, arrowhead=2)

# ---------------- Location: Browser → IP → Fallback, single map ----------------
STATE_KEY = "user_loc"

def ip_geo() -> tuple | None:
    if "ip_geo" in st.session_state:
        return st.session_state["ip_geo"]
    providers = [
        "https://ipapi.co/json/",
        "https://ipinfo.io/json",
        "https://ipwho.is/",
        "https://freegeoip.app/json/"
    ]
    for url in providers:
        try:
            r = requests.get(url, timeout=5)
            if not r.ok:
                dbg(f"ip geo http {r.status_code} at {url}")
                continue
            j = r.json()
            if "latitude" in j and "longitude" in j:
                lat, lon = float(j["latitude"]), float(j["longitude"])
            elif "loc" in j:  # ipinfo
                lat, lon = map(float, j["loc"].split(","))
            elif j.get("success") and "latitude" in j:
                lat, lon = float(j["latitude"]), float(j["longitude"])
            else:
                dbg(f"ip geo missing lat/lon from {url}, keys={list(j.keys())}")
                continue
            st.session_state["ip_geo"] = (lat, lon)
            return lat, lon
        except Exception as e:
            dbg(f"ip geo error at {url}: {e}")
    return None

# Initialize location once
if STATE_KEY not in st.session_state:
    g = streamlit_geolocation()
    if g and g.get("latitude") and g.get("longitude"):
        st.session_state[STATE_KEY] = (float(g["latitude"]), float(g["longitude"]))
    else:
        st.session_state[STATE_KEY] = ip_geo() or (51.5074, -0.1278)  # London fallback

lat, lon = st.session_state[STATE_KEY]

st.title("Your location, your warming story")
st.markdown("**Step 1 — Select your location.** We try your browser location; you can also click the map to move the pin.")

# One Leaflet map with a single pin; clicking moves the pin and refreshes
m = folium.Map(location=[lat, lon], zoom_start=7, tiles="OpenStreetMap")
folium.Marker(location=[lat, lon], draggable=False).add_to(m)
map_out = st_folium(m, height=360, width="stretch")  # one map only

clicked = map_out.get("last_clicked") if map_out else None
if clicked and "lat" in clicked and "lng" in clicked:
    st.session_state[STATE_KEY] = (float(clicked["lat"]), float(clicked["lng"]))
    st.rerun()

# Button to (re)ask the browser for location
if st.button("Use browser location"):
    g = streamlit_geolocation()
    if g and g.get("latitude") and g.get("longitude"):
        st.session_state[STATE_KEY] = (float(g["latitude"]), float(g["longitude"]))
        st.rerun()
    else:
        st.info("Couldn’t read your browser location yet — if you just allowed it, click again.")

st.caption(f"Location: lat={st.session_state[STATE_KEY][0]:.4f}, lon={st.session_state[STATE_KEY][1]:.4f}")

# ---------------- Start/Clear controls (sticky) ----------------
started = get_state("started", False)
params_sig = (round(lat, 4), round(lon, 4), bool(fast_mode), bool(cache_only))

col_start, col_clear = st.columns([1, 1])
with col_start:
    if st.button("Start (fetch data)", key="start_fetch_btn"):
        st.session_state["started"] = True
        started = True

with col_clear:
    if st.button("Clear fetched data", key="clear_btn"):
        for k in ("ds_7d", "ds_5m", "ds_m_recent", "ds_m_past", "fetch_params",
                  "typical_ready", "typical_recent", "typical_past"):
            st.session_state.pop(k, None)
        st.session_state["started"] = False
        started = False

# ---------------- Data fetch orchestration (runs only after Start) ----------------
if started:
    # (re)fetch only if inputs changed or first run
    if get_state("fetch_params") != params_sig:
        st.session_state["fetch_params"] = params_sig

        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        five_months_ago = now - timedelta(days=150)
        recent_years = list(range(now.year - 4, now.year + 1))
        past_years   = [y - 50 for y in recent_years]

        progress = st.empty()
        bar = st.progress(0.0)

        def get_recent_hourly(start_dt, end_dt):
            if fast_mode:
                try:
                    return fetch_openmeteo_hourly(lat, lon, start_dt, end_dt)  # °C already
                except Exception as e:
                    dbg("Open-Meteo error:", e)
                    if cache_only:
                        return None
            return fetch_hourly_range(lat, lon, start_dt, end_dt, 0.25, "grib")

        futures: dict[str, cf.Future | None] = {}
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures["hourly_7d"]  = ex.submit(get_recent_hourly, seven_days_ago, now)
            futures["hourly_5mo"] = ex.submit(get_recent_hourly, five_months_ago, now)

            if cache_only:
                futures["monthly_recent"] = None
                futures["monthly_past"]   = None
                total = 2
            else:
                futures["monthly_recent"] = ex.submit(fetch_monthly, lat, lon, recent_years, 0.25, "grib")
                futures["monthly_past"]   = ex.submit(fetch_monthly, lat, lon, past_years,   0.25, "grib")
                total = 4

            done = 0
            for name in ("hourly_7d", "hourly_5mo", "monthly_recent", "monthly_past"):
                fut = futures.get(name)
                if fut is None:
                    continue
                try:
                    futures[name] = fut.result(timeout=timeout_sec)
                except cf.TimeoutError:
                    dbg(f"{name} timed out after {timeout_sec}s"); futures[name] = None
                except Exception as e:
                    dbg(f"{name} failed:", e); futures[name] = None
                done += 1
                bar.progress(done/total)
                progress.markdown(
                    f"Fetched **{done}/{total}**" + (" (CDS monthly skipped in Cache-only)" if cache_only else "")
                )

        bar.empty(); progress.empty()

        # persist datasets
        st.session_state["ds_7d"]       = futures["hourly_7d"]
        st.session_state["ds_5m"]       = futures["hourly_5mo"]
        st.session_state["ds_m_recent"] = futures.get("monthly_recent")
        st.session_state["ds_m_past"]   = futures.get("monthly_past")

    # read from state (always)
    ds_7d       = get_state("ds_7d")
    ds_5m       = get_state("ds_5m")
    ds_m_recent = get_state("ds_m_recent")
    ds_m_past   = get_state("ds_m_past")

    # ---------- PLOTS (use config= and set height in layout) ----------
    if ds_7d is not None:
        st.header("Past 7 days — hourly average")
        ts_hourly = get_temp_da(ds_7d)
        if "latitude" in ts_hourly.dims and "longitude" in ts_hourly.dims:
            ts_hourly = ts_hourly.mean(["latitude", "longitude"])
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=ts_hourly.time.values, y=ts_hourly.values, mode="lines", name="°C"))
        fig1.update_layout(height=360, yaxis_title="°C", xaxis_title="Time (UTC)")
        annotate_extremes(fig1, ts_hourly)
        st.plotly_chart(fig1, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("7-day hourly window not available yet.")

    if ds_5m is not None:
        st.header("Last ~5 months — daily average")
        ts_daily_5m = hourly_to_daily_mean(ds_5m)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=ts_daily_5m.time.values, y=ts_daily_5m.values, mode="lines", name="Daily mean °C"))
        annotate_extremes(fig2, ts_daily_5m)
        fig2.update_layout(height=360, yaxis_title="°C", xaxis_title="Date")
        st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("5-month daily window not available yet.")

    if ds_m_recent is not None:
        st.header("Past 5 years — monthly average")
        ts_m_recent = monthly_point_series(ds_m_recent)
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=ts_m_recent.time.values, y=ts_m_recent.values, mode="lines+markers", name="Recent 5y"))
        fig3.update_layout(height=360, yaxis_title="°C", xaxis_title="Month")
        st.plotly_chart(fig3, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("Recent monthly window not available. (CDS monthly skipped in Cache-only mode)")

    if ds_m_recent is not None and ds_m_past is not None:
        st.header("Overlay: past 5 years vs same months 50 years earlier")
        ts_m_past = monthly_point_series(ds_m_past)
        rec_m = ts_m_recent.groupby("time.month").mean()
        pas_m = ts_m_past.groupby("time.month").mean()
        months = list(range(1, 13))
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=months, y=rec_m.values, mode="lines+markers",
                                  name=f"{ts_m_recent.time.dt.year.min().item()}–{ts_m_recent.time.dt.year.max().item()}"))
        fig4.add_trace(go.Scatter(x=months, y=pas_m.values, mode="lines+markers",
                                  name=f"{ts_m_past.time.dt.year.min().item()}–{ts_m_past.time.dt.year.max().item()}"))
        fig4.update_layout(height=360, xaxis=dict(tickmode="array", tickvals=months),
                           yaxis_title="°C", xaxis_title="Month")
        st.plotly_chart(fig4, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("Overlay not available. (CDS monthly skipped in Cache-only mode)")

    # ---------- Typical year (sticky; no state loss; auto-scroll back) ----------
    st.markdown('<div id="typical"></div>', unsafe_allow_html=True)
    st.header("“Typical” year: daily average (recent vs 50y earlier)")

    if cache_only:
        st.caption("Disabled in **Cache-only** mode to avoid CDS requests.")
    else:
        st.caption("Click to compute two representative years (fast).")
        typical_ready = get_state("typical_ready", False)
        recent_daily  = get_state("typical_recent")
        past_daily    = get_state("typical_past")

        if st.button("Compute typical year (fast 2-year version)", key="typical_btn"):
            now = datetime.utcnow()
            recent_refs = [now.year - 1, now.year - 2]
            past_refs   = [y - 50 for y in recent_refs]

            def daily_series_for_year(y):
                ds_y = fetch_hourly_range(lat, lon, datetime(y,1,1), datetime(y,12,31), 0.25, "grib")
                return hourly_to_daily_mean(ds_y)

            with cf.ThreadPoolExecutor(max_workers=2) as ex:
                r1 = ex.submit(daily_series_for_year, recent_refs[0]).result(timeout=timeout_sec)
                r2 = ex.submit(daily_series_for_year, recent_refs[1]).result(timeout=timeout_sec)
            recent_daily = xr.concat([r1, r2], dim="time")

            p1 = daily_series_for_year(past_refs[0])
            p2 = daily_series_for_year(past_refs[1])
            past_daily = xr.concat([p1, p2], dim="time")

            st.session_state["typical_recent"] = recent_daily
            st.session_state["typical_past"]   = past_daily
            st.session_state["typical_ready"]  = True
            scroll_to("typical")

        # Render if available (persisted)
        if get_state("typical_ready", False):
            clim_recent = st.session_state["typical_recent"].groupby("time.dayofyear").mean()
            clim_past   = st.session_state["typical_past"].groupby("time.dayofyear").mean()
            days = np.arange(1, len(clim_recent) + 1)
            fig5 = go.Figure()
            fig5.add_trace(go.Scatter(x=days, y=clim_recent.values, mode="lines", name="Typical recent"))
            fig5.add_trace(go.Scatter(x=days, y=clim_past.values,   mode="lines", name="Typical past"))
            fig5.update_layout(height=360, xaxis_title="Day of year", yaxis_title="°C")
            st.plotly_chart(fig5, width="stretch", config={"displayModeBar": False})

else:
    st.info("Set your location (map or browser button), then press **Start** to fetch data.")
