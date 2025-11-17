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

# Earthkit (used only when Fast mode is OFF for monthly CDS)
import earthkit.data as ekd
from earthkit.data import config as ek_config, cache as ek_cache

# ---------------- Page config ----------------
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

# ---------------- Earthkit persistent cache (for optional CDS) ----------------
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
    fast_mode   = st.toggle("Fast mode (Open-Meteo) for recent & monthly", value=True)
    cache_only  = st.toggle("Cache-only for CDS (don’t submit new jobs)", value=False)
    max_workers = st.slider("Max parallel jobs", 1, 3, 2)
    timeout_sec = st.slider("Per-chunk timeout (s)", 30, 240, 120, step=10)

# ---------------- Xarray/ERA5 helpers ----------------
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
    if "time" not in ds.dims and "forecast_reference_time" in ds.dims:
        ds = ds.rename({"forecast_reference_time": "time"})
    if "time" not in ds.coords and "time" in ds:
        ds = ds.set_coords("time")
    return ds

def get_temp_da(ds: xr.Dataset) -> xr.DataArray:
    """
    Return 2m air temperature in °C.
    ERA5 via CDS: 't2m' (monthly) or '2t' (hourly) in Kelvin → convert.
    Open-Meteo: 'temperature_2m' or *_c already °C → return as is.
    """
    var = None
    for candidate in ("t2m", "2t", "temperature_2m",
                      "t2m_mean_c", "t2m_max_c", "t2m_min_c",
                      "t2m_mon_mean_c", "t2m_mon_max_c", "t2m_mon_min_c"):
        if candidate in ds.data_vars:
            var = candidate
            break
    if var is None:
        raise KeyError(f"No temperature variable found. Available: {list(ds.data_vars)}")

    da = ds[var]
    units = (da.attrs.get("units") or "").lower()
    if "c" in units:
        return da
    vmax = float(np.nanmax(da.values))
    looks_kelvin = vmax > 200.0
    return da - 273.15 if looks_kelvin else da

def small_bbox(lat, lon, buf=0.25):
    return [lat + buf, lon - buf, lat - buf, lon + buf]  # [N, W, S, E]

# ---------------- Open-Meteo fetchers (FAST PATH) ----------------
def fetch_openmeteo_hourly(lat, lon, start_dt, end_dt) -> xr.Dataset:
    start = start_dt.strftime("%Y-%m-%d")
    end   = end_dt.strftime("%Y-%m-%d")
    url = (
        "https://archive-api.open-meteo.com/v1/era5"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        "&hourly=temperature_2m&timezone=UTC"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    j = r.json()
    ts = pd.to_datetime(j["hourly"]["time"])
    vals = np.array(j["hourly"]["temperature_2m"], dtype=float)  # °C already
    da = xr.DataArray(
        vals, coords={"time": ts}, dims=["time"],
        name="temperature_2m", attrs={"units": "degC", "source": "open-meteo ERA5"}
    )
    return xr.Dataset({"temperature_2m": da})

def fetch_openmeteo_daily(lat, lon, start_dt, end_dt,
                          fields=("temperature_2m_mean","temperature_2m_max","temperature_2m_min")) -> xr.Dataset:
    start = start_dt.strftime("%Y-%m-%d"); end = end_dt.strftime("%Y-%m-%d")
    daily = ",".join(fields)
    url = (
        "https://archive-api.open-meteo.com/v1/era5"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&daily={daily}&timezone=UTC"
    )
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    j = r.json()
    idx = pd.to_datetime(j["daily"]["time"])
    ds = xr.Dataset()
    if "temperature_2m_mean" in j["daily"]:
        ds["t2m_mean_c"] = xr.DataArray(j["daily"]["temperature_2m_mean"], coords={"time": idx}, dims=["time"], attrs={"units":"degC"})
    if "temperature_2m_max" in j["daily"]:
        ds["t2m_max_c"]  = xr.DataArray(j["daily"]["temperature_2m_max"],  coords={"time": idx}, dims=["time"], attrs={"units":"degC"})
    if "temperature_2m_min" in j["daily"]:
        ds["t2m_min_c"]  = xr.DataArray(j["daily"]["temperature_2m_min"],  coords={"time": idx}, dims=["time"], attrs={"units":"degC"})
    return ds

def daily_to_monthly(ds_daily: xr.Dataset) -> xr.Dataset:
    """Compute monthly mean/min/max from Open-Meteo daily °C series."""
    out = xr.Dataset()
    if "t2m_mean_c" in ds_daily:
        out["t2m_mon_mean_c"] = ds_daily["t2m_mean_c"].resample(time="1MS").mean()
    if "t2m_max_c" in ds_daily:
        out["t2m_mon_max_c"]  = ds_daily["t2m_max_c"].resample(time="1MS").mean()
    if "t2m_min_c" in ds_daily:
        out["t2m_mon_min_c"]  = ds_daily["t2m_min_c"].resample(time="1MS").mean()
    return out

def daily_series_openmeteo_for_year(lat, lon, year: int) -> xr.DataArray:
    ds = fetch_openmeteo_hourly(lat, lon, datetime(year, 1, 1), datetime(year, 12, 31))
    da = get_temp_da(ds)
    if "latitude" in da.dims and "longitude" in da.dims:
        da = da.mean(["latitude","longitude"])
    return da.resample(time="1D").mean()

# ---------------- Optional CDS fetchers (SLOW PATH for monthly when Fast OFF) ----------------
def cds_from_source(dataset: str, req: dict):
    return ekd.from_source("cds", dataset, req)

def fetch_monthly_cds(lat, lon, years, buf=0.25, fmt="grib") -> xr.Dataset:
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
            elif "loc" in j:
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
        st.session_state[STATE_KEY] = ip_geo() or (51.5074, -0.1278)

lat, lon = st.session_state[STATE_KEY]

st.title("Your location, your warming story")
st.markdown("**Step 1 — Select your location.** We try your browser location; you can also click the map to move the pin.")

# One Folium map; clicking moves the pin and refreshes
m = folium.Map(location=[lat, lon], zoom_start=7, tiles="OpenStreetMap")
folium.Marker(location=[lat, lon], draggable=False).add_to(m)
map_out = st_folium(m, height=360, width="stretch")

clicked = map_out.get("last_clicked") if map_out else None
if clicked and "lat" in clicked and "lng" in clicked:
    st.session_state[STATE_KEY] = (float(clicked["lat"]), float(clicked["lng"]))
    st.rerun()

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

# ---------------- Data fetch orchestration ----------------
if started:
    # (re)fetch only if inputs changed or first run
    if get_state("fetch_params") != params_sig:
        st.session_state["fetch_params"] = params_sig

        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        five_months_ago = now - timedelta(days=150)

        progress = st.empty()
        bar = st.progress(0.0)

        futures: dict[str, cf.Future | None] = {}
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            # Recent hourly windows: Open-Meteo (fast)
            futures["hourly_7d"]  = ex.submit(fetch_openmeteo_hourly, lat, lon, seven_days_ago, now)
            futures["hourly_5mo"] = ex.submit(fetch_openmeteo_hourly, lat, lon, five_months_ago, now)

            # Monthly blocks: Open-Meteo daily→monthly (fast) OR CDS (slow)
            if fast_mode:
                # Clamp end dates to avoid 400 (future/incomplete months)
                safe_end = (datetime.utcnow() - timedelta(days=5)).replace(hour=0, minute=0, second=0, microsecond=0)

                start_recent = datetime(now.year - 4, 1, 1)
                end_recent   = min(datetime(now.year, 12, 31), safe_end)

                start_past = datetime(now.year - 54, 1, 1)
                end_past   = min(datetime(now.year - 50, 12, 31), safe_end)

                futures["monthly_recent"] = ex.submit(
                    lambda: daily_to_monthly(fetch_openmeteo_daily(lat, lon, start_recent, end_recent))
                )
                futures["monthly_past"] = ex.submit(
                    lambda: daily_to_monthly(fetch_openmeteo_daily(lat, lon, start_past, end_past))
                )
                total = 4
            else:
                if cache_only:
                    futures["monthly_recent"] = None
                    futures["monthly_past"]   = None
                    total = 2
                else:
                    recent_years = list(range(now.year - 4, now.year + 1))
                    past_years   = [y - 50 for y in recent_years]
                    futures["monthly_recent"] = ex.submit(fetch_monthly_cds, lat, lon, recent_years, 0.25, "grib")
                    futures["monthly_past"]   = ex.submit(fetch_monthly_cds, lat, lon, past_years,   0.25, "grib")
                    total = 4

            # Gather
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
                    f"Fetched **{done}/{total}**" +
                    (" (CDS monthly skipped in Cache-only)" if (not fast_mode and cache_only) else "")
                )

        bar.empty(); progress.empty()

        st.session_state["ds_7d"]       = futures["hourly_7d"]
        st.session_state["ds_5m"]       = futures["hourly_5mo"]
        st.session_state["ds_m_recent"] = futures.get("monthly_recent")
        st.session_state["ds_m_past"]   = futures.get("monthly_past")

    # read from state (always)
    ds_7d       = get_state("ds_7d")
    ds_5m       = get_state("ds_5m")
    ds_m_recent = get_state("ds_m_recent")
    ds_m_past   = get_state("ds_m_past")

    # ---------- Past 7 days — hourly ----------
    if ds_7d is not None:
        st.header("Past 7 days — hourly temperature")
        show_band_7d = st.toggle("Show daily min–max envelope", value=True, key="band_7d")
        t2m_h = get_temp_da(ds_7d)
        if "latitude" in t2m_h.dims and "longitude" in t2m_h.dims:
            t2m_h = t2m_h.mean(["latitude","longitude"])

        # daily stats and upsample to hourly grid for a proper band
        daily_min = t2m_h.resample(time="1D").min()
        daily_max = t2m_h.resample(time="1D").max()
        min_hr = daily_min.reindex(time=t2m_h.time, method="pad")
        max_hr = daily_max.reindex(time=t2m_h.time, method="pad")

        fig1 = go.Figure()
        if show_band_7d:
            fig1.add_trace(go.Scatter(
                x=max_hr.time.values, y=max_hr.values, mode="lines", line=dict(width=0),
                name="Daily max", showlegend=False
            ))
            fig1.add_trace(go.Scatter(
                x=min_hr.time.values, y=min_hr.values, mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor="rgba(0,0,0,0.18)",
                name="Daily min", showlegend=False
            ))
        fig1.add_trace(go.Scatter(x=t2m_h.time.values, y=t2m_h.values, mode="lines", name="Hourly °C"))
        fig1.update_layout(height=360, yaxis_title="°C", xaxis_title="Time (UTC)")
        st.plotly_chart(fig1, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("7-day hourly window not available yet.")

    # ---------- Last ~5 months — daily ----------
    if ds_5m is not None:
        st.header("Last ~5 months — daily temperature")
        show_band_5m = st.toggle("Show daily min–max envelope", value=True, key="band_5m")
        t2m_h = get_temp_da(ds_5m)
        if "latitude" in t2m_h.dims and "longitude" in t2m_h.dims:
            t2m_h = t2m_h.mean(["latitude","longitude"])
        daily_mean = t2m_h.resample(time="1D").mean()
        daily_min  = t2m_h.resample(time="1D").min()
        daily_max  = t2m_h.resample(time="1D").max()

        fig2 = go.Figure()
        if show_band_5m:
            fig2.add_trace(go.Scatter(
                x=daily_max.time.values, y=daily_max.values, mode="lines", line=dict(width=0),
                name="Daily max", showlegend=False
            ))
            fig2.add_trace(go.Scatter(
                x=daily_min.time.values, y=daily_min.values, mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor="rgba(0,0,0,0.18)",
                name="Daily min", showlegend=False
            ))
        fig2.add_trace(go.Scatter(x=daily_mean.time.values, y=daily_mean.values, mode="lines", name="Daily mean"))
        fig2.update_layout(height=360, yaxis_title="°C", xaxis_title="Date")
        st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("5-month daily window not available yet.")

    # ---------- Past 5 years — monthly (Open-Meteo daily→monthly or CDS) ----------
    def have_openmeteo_monthly(ds) -> bool:
        return isinstance(ds, xr.Dataset) and any(k in ds for k in ("t2m_mon_mean_c","t2m_mon_max_c","t2m_mon_min_c"))

    if ds_m_recent is not None:
        st.header("Past 5 years — monthly temperature")
        show_band_mon = st.toggle("Show min–max envelope (monthly)", value=True, key="band_recent_mon")
        fig3 = go.Figure()
        if have_openmeteo_monthly(ds_m_recent):
            x = ds_m_recent["t2m_mon_mean_c"]["time"].values
            y = ds_m_recent["t2m_mon_mean_c"].values
            ylo = ds_m_recent.get("t2m_mon_min_c")
            yhi = ds_m_recent.get("t2m_mon_max_c")
            if show_band_mon and (ylo is not None) and (yhi is not None):
                fig3.add_trace(go.Scatter(x=x, y=yhi.values, mode="lines", line=dict(width=0), name="Monthly max", showlegend=False))
                fig3.add_trace(go.Scatter(x=x, y=ylo.values, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(0,0,0,0.18)", name="Monthly min", showlegend=False))
            fig3.add_trace(go.Scatter(x=x, y=y, mode="lines+markers", name="Monthly mean"))
        else:
            ts_m_recent = monthly_point_series(ds_m_recent)
            fig3.add_trace(go.Scatter(x=ts_m_recent.time.values, y=ts_m_recent.values, mode="lines+markers", name="Monthly mean"))
        fig3.update_layout(height=360, yaxis_title="°C", xaxis_title="Month")
        st.plotly_chart(fig3, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("Recent monthly window not available." + (" (CDS monthly skipped in Cache-only mode)" if (not fast_mode and cache_only) else ""))

    # ---------- Overlay: recent vs same months 50 years earlier (aligned by month 1..12) ----------
    if ds_m_recent is not None and ds_m_past is not None:
        st.header("Overlay: past 5 years vs same months 50 years earlier")

        show_band_overlay = st.toggle("Show min–max envelopes", value=True, key="band_overlay_mon")
        fig4 = go.Figure()
        months = list(range(1, 13))

        def monthly_by_month(ds):
            """Return mean/min/max grouped by calendar month index (1..12)."""
            if have_openmeteo_monthly(ds):
                mean = ds["t2m_mon_mean_c"].groupby("time.month").mean()
                lo = ds.get("t2m_mon_min_c")
                hi = ds.get("t2m_mon_max_c")
                minv = lo.groupby("time.month").mean() if lo is not None else None
                maxv = hi.groupby("time.month").mean() if hi is not None else None
            else:
                base = monthly_point_series(ds)
                mean = base.groupby("time.month").mean()
                minv = maxv = None
            return mean, minv, maxv

        rec_mean, rec_min, rec_max = monthly_by_month(ds_m_recent)
        pas_mean, pas_min, pas_max = monthly_by_month(ds_m_past)

        # Draw recent band + mean
        if show_band_overlay and (rec_min is not None) and (rec_max is not None):
            fig4.add_trace(go.Scatter(x=months, y=rec_max.sel(month=months).values, mode="lines", line=dict(width=0), name="Recent max", showlegend=False))
            fig4.add_trace(go.Scatter(x=months, y=rec_min.sel(month=months).values, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(0,0,0,0.18)", name="Recent min", showlegend=False))
        fig4.add_trace(go.Scatter(x=months, y=rec_mean.sel(month=months).values, mode="lines+markers", name="Recent mean"))

        # Draw past band + mean
        if show_band_overlay and (pas_min is not None) and (pas_max is not None):
            fig4.add_trace(go.Scatter(x=months, y=pas_max.sel(month=months).values, mode="lines", line=dict(width=0), name="Past max", showlegend=False))
            fig4.add_trace(go.Scatter(x=months, y=pas_min.sel(month=months).values, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(0,0,0,0.14)", name="Past min", showlegend=False))
        fig4.add_trace(go.Scatter(x=months, y=pas_mean.sel(month=months).values, mode="lines+markers", name="Past mean"))

        fig4.update_layout(height=360, yaxis_title="°C", xaxis_title="Month", xaxis=dict(tickmode="array", tickvals=months))
        st.plotly_chart(fig4, width="stretch", config={"displayModeBar": False})
    else:
        st.warning("Overlay not available." + (" (CDS monthly skipped in Cache-only mode)" if (not fast_mode and cache_only) else ""))

    # ---------- Typical year (Open-Meteo only; sticky; envelope toggle) ----------
    st.markdown('<div id="typical"></div>', unsafe_allow_html=True)
    st.header("“Typical” year: daily average (recent vs 50y earlier)")
    st.caption("Uses Open-Meteo ERA5 (fast, no CDS queue).")

    typical_ready = get_state("typical_ready", False)
    recent_daily  = get_state("typical_recent")
    past_daily    = get_state("typical_past")

    if st.button("Compute typical year (fast, no CDS)", key="typical_btn"):
        now = datetime.utcnow()
        recent_refs = [now.year - 1, now.year - 2]
        past_refs   = [y - 50 for y in recent_refs]

        prog = st.progress(0.0); status = st.empty()
        status.markdown(f"Fetching recent {recent_refs[0]}…")
        r1 = daily_series_openmeteo_for_year(lat, lon, recent_refs[0]); prog.progress(0.25)
        status.markdown(f"Fetching recent {recent_refs[1]}…")
        r2 = daily_series_openmeteo_for_year(lat, lon, recent_refs[1]); prog.progress(0.50)
        recent_daily = xr.concat([r1, r2], dim="time")

        status.markdown(f"Fetching past {past_refs[0]}…")
        p1 = daily_series_openmeteo_for_year(lat, lon, past_refs[0]); prog.progress(0.75)
        status.markdown(f"Fetching past {past_refs[1]}…")
        p2 = daily_series_openmeteo_for_year(lat, lon, past_refs[1]); prog.progress(1.0)
        past_daily = xr.concat([p1, p2], dim="time")
        prog.empty(); status.empty()

        st.session_state["typical_recent"] = recent_daily
        st.session_state["typical_past"]   = past_daily
        st.session_state["typical_ready"]  = True
        scroll_to("typical")

    if get_state("typical_ready", False):
        show_band_typ = st.toggle("Show min–max envelope (climatology)", value=True, key="band_typical")
        clim_recent_mean = st.session_state["typical_recent"].groupby("time.dayofyear").mean()
        clim_recent_min  = st.session_state["typical_recent"].groupby("time.dayofyear").min()
        clim_recent_max  = st.session_state["typical_recent"].groupby("time.dayofyear").max()
        clim_past_mean   = st.session_state["typical_past"].groupby("time.dayofyear").mean()
        clim_past_min    = st.session_state["typical_past"].groupby("time.dayofyear").min()
        clim_past_max    = st.session_state["typical_past"].groupby("time.dayofyear").max()

        days = np.arange(1, len(clim_recent_mean) + 1)
        fig5 = go.Figure()
        if show_band_typ:
            fig5.add_trace(go.Scatter(x=days, y=clim_recent_max.values, mode="lines", line=dict(width=0), name="Recent max", showlegend=False))
            fig5.add_trace(go.Scatter(x=days, y=clim_recent_min.values, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(0,0,0,0.10)", name="Recent min", showlegend=False))
        fig5.add_trace(go.Scatter(x=days, y=clim_recent_mean.values, mode="lines", name="Recent mean"))
        if show_band_typ:
            fig5.add_trace(go.Scatter(x=days, y=clim_past_max.values, mode="lines", line=dict(width=0), name="Past max", showlegend=False))
            fig5.add_trace(go.Scatter(x=days, y=clim_past_min.values, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(0,0,0,0.08)", name="Past min", showlegend=False))
        fig5.add_trace(go.Scatter(x=days, y=clim_past_mean.values, mode="lines", name="Past mean"))
        fig5.update_layout(height=360, xaxis_title="Day of year", yaxis_title="°C")
        st.plotly_chart(fig5, width="stretch", config={"displayModeBar": False})

else:
    st.info("Set your location (map or browser button), then press **Start** to fetch data.")
