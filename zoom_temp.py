import streamlit as st
import numpy as np
import pandas as pd
import xarray as xr
from datetime import datetime, date, timedelta
import requests
import time
import plotly.graph_objs as go
import folium
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

st.set_page_config(page_title="Your Place, Warming Over Time", layout="wide")

# ---------------- tiny utils ----------------
def dbg(*args):
    print("[DEBUG]", *args)


def get_state(key, default=None):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def clamp_openmeteo_end(dt: datetime) -> datetime:
    safe_end = (datetime.utcnow() - timedelta(days=5)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return min(dt, safe_end)


# ---------------- HTTP with retry/backoff ----------------
def http_json(url: str, timeout=45, retries=6, backoff=0.8):
    import random

    last_err = None
    for k in range(retries):
        try:
            r = requests.get(url, timeout=timeout)

            # Handle rate limit / transient HTTP codes explicitly
            if r.status_code in (429, 502, 503, 504):
                last_err = requests.HTTPError(f"{r.status_code} {r.reason}")
                ra = r.headers.get("Retry-After")
                if ra:
                    try:
                        sleep_s = float(ra)
                    except ValueError:
                        sleep_s = backoff * (2 ** k)
                else:
                    sleep_s = backoff * (2 ** k)
                sleep_s += random.uniform(0.2, 0.8)
                time.sleep(sleep_s)
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_err = e
            sleep_s = backoff * (2 ** k) + random.uniform(0.2, 0.8)
            time.sleep(sleep_s)

    if last_err is None:
        raise RuntimeError("http_json failed after retries without a specific error")
    raise last_err


# ---------------- Open-Meteo fetchers (short-term only) ----------------
@st.cache_data(show_spinner=False)
def fetch_openmeteo_hourly(lat, lon, start_dt, end_dt) -> xr.Dataset:
    start = start_dt.strftime("%Y-%m-%d")
    end = end_dt.strftime("%Y-%m-%d")
    url = (
        "https://archive-api.open-meteo.com/v1/era5"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        "&hourly=temperature_2m&timezone=UTC"
    )
    j = http_json(url, timeout=45, retries=6)
    ts = pd.to_datetime(j["hourly"]["time"])
    vals = np.array(j["hourly"]["temperature_2m"], dtype=float)
    da = xr.DataArray(
        vals,
        coords={"time": ts},
        dims=["time"],
        name="temperature_2m",
        attrs={"units": "degC"},
    )
    return xr.Dataset({"temperature_2m": da})


def get_temp_da(ds: xr.Dataset) -> xr.DataArray:
    for c in ("temperature_2m", "t2m_mean_c", "t2m_mon_mean_c"):
        if c in ds.data_vars:
            return ds[c]
    raise KeyError(f"No temperature var in {list(ds.data_vars)}")


def yearly_mean_series_from_monthly(ds_monthly: xr.Dataset) -> xr.DataArray:
    m = ds_monthly["t2m_mon_mean_c"]
    ymean = m.groupby("time.year").mean()
    vals = [ymean.sel(year=int(pd.Timestamp(t).year)).item() for t in m.time.values]
    return xr.DataArray(
        vals,
        coords={"time": m.time},
        dims=["time"],
        name="yearly_mean_c",
        attrs={"units": "degC"},
    )


def annotate_extrema_points(fig: go.Figure, x, y, label_prefix=""):
    """
    Highlight min and max on a series with big markers and vertical lines.
    Markers are hidden from the legend; only the main line appears there.
    """
    if len(y) == 0 or np.all(np.isnan(y)):
        return

    y = np.asarray(y)
    ymax_i = int(np.nanargmax(y))
    ymin_i = int(np.nanargmin(y))
    y_min = float(np.nanmin(y))
    y_max = float(np.nanmax(y))

    extremes = [
        (ymax_i, "max", "rgba(220, 50, 47, 1.0)"),  # red
        (ymin_i, "min", "rgba(38, 139, 210, 1.0)"),  # blue
    ]

    for idx, lab, color in extremes:
        x_val = x[idx]
        y_val = float(y[idx])

        # vertical dashed line at the extreme
        fig.add_shape(
            type="line",
            x0=x_val,
            x1=x_val,
            y0=y_min,
            y1=y_max,
            line=dict(color=color, width=2, dash="dash"),
        )

        # big marker on the curve
        fig.add_trace(
            go.Scatter(
                x=[x_val],
                y=[y_val],
                mode="markers",
                marker=dict(
                    size=18,
                    symbol="circle",
                    line=dict(width=3, color="rgba(0,0,0,0.8)"),
                    color=color,
                ),
                showlegend=False,
                hovertemplate=f"{label_prefix}{lab}: %{{y:.1f}}°C<extra></extra>",
            )
        )

        fig.add_annotation(
            x=x_val,
            y=y_val,
            text=lab,
            showarrow=True,
            arrowhead=2,
            ax=0,
            ay=-25,
        )


# ---------------- Climatology (precomputed ERA5) ----------------
CLIM_FILES = {
    # adjust paths if needed
    "mauritius": "data/era5_t2m_monthly_1975_2024_mauritius.nc",
    "london": "data/era5_t2m_monthly_1975_2024_london.nc",
}


@st.cache_resource(show_spinner=False)
def load_all_climatologies():
    """Load all precomputed ERA5 monthly climatologies for different regions."""
    out = {}
    for name, path in CLIM_FILES.items():
        try:
            ds = xr.open_dataset(path)

            # Normalise time axis: many ERA5 monthly files use 'valid_time'
            if "valid_time" in ds.coords and "time" not in ds.coords:
                ds = ds.rename({"valid_time": "time"})

            if "t2m_mon_mean_c" in ds:
                out[name] = ds
            else:
                dbg("Climatology missing t2m_mon_mean_c:", path)
        except FileNotFoundError:
            dbg("Climatology file not found:", path)
        except Exception as e:
            dbg("Failed to load climatology", name, path, ":", e)
    return out


def pick_climatology_for_location(all_ds: dict, lat: float, lon: float):
    """
    Given a dict of {name: ds_clim}, choose the dataset whose box covers
    the given lat/lon. If none fully covers it, pick the closest center.
    Returns (name, ds) or (None, None).
    """
    if not all_ds:
        return None, None

    best_name = None
    best_ds = None
    best_dist = None

    for name, ds in all_ds.items():
        lat_name = "latitude" if "latitude" in ds.coords else "lat"
        lon_name = "longitude" if "longitude" in ds.coords else "lon"

        lats = ds[lat_name]
        lons = ds[lon_name]

        lat_min = float(lats.min())
        lat_max = float(lats.max())
        lon_min = float(lons.min())
        lon_max = float(lons.max())

        # Adjust user lon if dataset uses 0..360 and user is in -180..180
        if lon_min >= 0.0 and lon_max > 180.0:
            user_lon = lon % 360.0
        else:
            user_lon = lon

        inside = (lat_min <= lat <= lat_max) and (lon_min <= user_lon <= lon_max)

        lat_c = 0.5 * (lat_min + lat_max)
        lon_c = 0.5 * (lon_min + lon_max)
        dist2 = (lat - lat_c) ** 2 + (user_lon - lon_c) ** 2

        if inside:
            return name, ds

        if best_dist is None or dist2 < best_dist:
            best_name = name
            best_ds = ds
            best_dist = dist2

    return best_name, best_ds


def nearest_clim_timeseries(ds_clim: xr.Dataset, lat: float, lon: float) -> xr.DataArray | None:
    """
    Select nearest monthly t2m series from climatology for a given location.
    Returns a 1D DataArray t2m_mon_mean_c(time).
    """
    if ds_clim is None:
        return None

    lat_name = "latitude" if "latitude" in ds_clim.coords else "lat"
    lon_name = "longitude" if "longitude" in ds_clim.coords else "lon"

    lons = ds_clim[lon_name]
    if float(lons.min()) >= 0.0 and float(lons.max()) > 180.0:
        target_lon = lon % 360.0
    else:
        target_lon = lon

    da = ds_clim["t2m_mon_mean_c"].sel(
        {lat_name: lat, lon_name: target_lon}, method="nearest"
    )
    return da  # dims: time


def build_monthly_windows_from_clim(da_mon: xr.DataArray):
    """
    Given a monthly mean series t2m_mon_mean_c(time),
    build three datasets:
      - recent 5y monthly
      - past 5y window 50 years earlier (if available)
      - past 50y monthly (or full available span if shorter)
    Returns (ds_m_recent, ds_m_past, ds_m_50y) as xarray.Datasets or None.
    """
    if da_mon is None:
        return None, None, None

    time = pd.to_datetime(da_mon.time.values)
    years = time.year
    earliest_year = int(years.min())
    last_year = int(years.max())

    # --- recent 5 years ending at last_year ---
    recent_start_y = last_year - 4
    recent_start = f"{recent_start_y}-01-01"
    recent_end = f"{last_year}-12-31"
    da_recent = da_mon.sel(time=slice(recent_start, recent_end))

    ds_recent = xr.Dataset({"t2m_mon_mean_c": da_recent})

    # --- past 5y window 50 years earlier (if we have it) ---
    past_start_y = recent_start_y - 50
    past_end_y = last_year - 50
    past_start = f"{past_start_y}-01-01"
    past_end = f"{past_end_y}-12-31"

    da_past = None
    if earliest_year <= past_end_y:
        # We have at least *some* data overlapping that target window
        da_past_candidate = da_mon.sel(time=slice(past_start, past_end))
        if ("time" in da_past_candidate.dims) and (da_past_candidate.time.size > 0):
            da_past = da_past_candidate

    ds_past = xr.Dataset({"t2m_mon_mean_c": da_past}) if da_past is not None else None

    # --- past ~50 years monthly (or full span if shorter) ---
    fifty_start_y = max(last_year - 49, earliest_year)
    fifty_start = f"{fifty_start_y}-01-01"
    fifty_end = f"{last_year}-12-31"
    da_50 = da_mon.sel(time=slice(fifty_start, fifty_end))

    ds_50y = (
        xr.Dataset({"t2m_mon_mean_c": da_50})
        if ("time" in da_50.dims and da_50.time.size > 0)
        else None
    )

    return ds_recent, ds_past, ds_50y


# ---------------- location (browser → IP → fallback) ----------------
STATE_KEY = "user_loc"


def ip_geo():
    if "ip_geo" in st.session_state:
        return st.session_state["ip_geo"]
    for url in [
        "https://ipapi.co/json/",
        "https://ipinfo.io/json",
        "https://ipwho.is/",
        "https://freegeoip.app/json/",
    ]:
        try:
            j = http_json(url, timeout=6, retries=2)
            if "latitude" in j and "longitude" in j:
                lat, lon = float(j["latitude"]), float(j["longitude"])
            elif "loc" in j:
                lat, lon = map(float, j["loc"].split(","))
            elif j.get("success") and "latitude" in j:
                lat, lon = float(j["latitude"]), float(j["longitude"])
            else:
                continue
            st.session_state["ip_geo"] = (lat, lon)
            return lat, lon
        except Exception as e:
            dbg("ip geo fail:", e)
    return None


if STATE_KEY not in st.session_state:
    g = streamlit_geolocation()
    if g and g.get("latitude") and g.get("longitude"):
        st.session_state[STATE_KEY] = (float(g["latitude"]), float(g["longitude"]))
    else:
        st.session_state[STATE_KEY] = ip_geo() or (51.5074, -0.1278)

lat, lon = st.session_state[STATE_KEY]

# ---------------- UI: title + map ----------------
st.title("Your location, your warming story")
st.markdown("**Click the map to move the pin; data updates automatically.**")

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

st.caption(
    f"Location: lat={st.session_state[STATE_KEY][0]:.4f}, lon={st.session_state[STATE_KEY][1]:.4f}"
)

lat, lon = st.session_state[STATE_KEY]

# ---------------- Fetch short-term hourly data (Open-Meteo) ----------------
def fetch_all(lat, lon):
    out, errors = {}, {}

    # Date-based windows so cache keys are stable for a full day
    today = date.today()
    end_date = today - timedelta(days=1)  # yesterday
    start_7d = end_date - timedelta(days=6)
    start_30d = end_date - timedelta(days=29)
    start_365d = end_date - timedelta(days=364)

    def to_dt(d: date) -> datetime:
        return datetime(d.year, d.month, d.day)

    start_7d_dt = to_dt(start_7d)
    start_30d_dt = to_dt(start_30d)
    start_365d_dt = to_dt(start_365d)
    end_dt = to_dt(end_date)

    bar = st.progress(0.0)
    status = st.empty()
    total = 3
    done = 0

    def step(name, func):
        nonlocal done
        try:
            out[name] = func()
        except Exception as e:
            errors[name] = str(e)
            dbg(name, "failed:", e)
            out[name] = None
        done += 1
        bar.progress(done / total)
        status.text(f"Fetching data… {done}/{total}")

    step("h_7d", lambda: fetch_openmeteo_hourly(lat, lon, start_7d_dt, end_dt))
    step("h_30d", lambda: fetch_openmeteo_hourly(lat, lon, start_30d_dt, end_dt))
    step("h_365d", lambda: fetch_openmeteo_hourly(lat, lon, start_365d_dt, end_dt))

    bar.empty()
    status.empty()
    return out, errors


today = date.today()
sig = (round(lat, 4), round(lon, 4), today.isoformat())

need_fetch = (get_state("fetch_sig") != sig) or any(
    get_state(k) is None for k in ("ds_h_7d", "ds_h_30d", "ds_h_365d")
)

if need_fetch:
    st.session_state["fetch_sig"] = sig
    res, errs = fetch_all(lat, lon)
    st.session_state.update(
        {
            "ds_h_7d": res.get("h_7d"),
            "ds_h_30d": res.get("h_30d"),
            "ds_h_365d": res.get("h_365d"),
            "fetch_errors": errs,
        }
    )

errors = get_state("fetch_errors", {})


def maybe_warn(name, human):
    if name in errors and errors[name]:
        st.warning(f"{human} unavailable. ({errors[name]})")


# ---------------- Inject climatology-based monthly datasets ----------------
all_clim = load_all_climatologies()
clim_name, clim_ds = pick_climatology_for_location(all_clim, lat, lon)

if clim_ds is not None:
    da_clim = nearest_clim_timeseries(clim_ds, lat, lon)
    ds_m_recent, ds_m_past, ds_m_50y = build_monthly_windows_from_clim(da_clim)
    st.session_state["ds_m_recent"] = ds_m_recent
    st.session_state["ds_m_past"] = ds_m_past
    st.session_state["ds_m_50y"] = ds_m_50y
    st.session_state["clim_region"] = clim_name
else:
    st.session_state["ds_m_recent"] = None
    st.session_state["ds_m_past"] = None
    st.session_state["ds_m_50y"] = None
    st.session_state["clim_region"] = None

clim_region = st.session_state.get("clim_region")
if clim_region:
    st.caption(f"Using precomputed climatology: **{clim_region}**")

# ---------------- Charts ----------------
# 1) Past 7 days — hourly with min/max markers
ds = get_state("ds_h_7d")
if ds is not None:
    st.header("Past 7 days — hourly temperature")
    t2m = get_temp_da(ds)
    x = t2m.time.values
    y = t2m.values
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name="Hourly °C"))
    annotate_extrema_points(fig, x, y)
    fig.update_layout(height=360, yaxis_title="°C", xaxis_title="Time (UTC)")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
else:
    maybe_warn("h_7d", "7-day hourly window")

# 2) Past month — hourly and daily temperature
ds = get_state("ds_h_30d")
if ds is not None:
    st.header("Past month — hourly and daily temperature")
    t2m = get_temp_da(ds)
    daily = t2m.resample(time="1D").mean()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=t2m.time.values, y=t2m.values, mode="lines", name="Hourly °C"
        )
    )
    fig.add_trace(
        go.Scatter(
            x=daily.time.values,
            y=daily.values,
            mode="lines+markers",
            name="Daily mean °C",
        )
    )
    annotate_extrema_points(fig, t2m.time.values, t2m.values)
    fig.update_layout(height=360, yaxis_title="°C", xaxis_title="Date")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
else:
    maybe_warn("h_30d", "30-day window")

# 3) Last year — daily temperature
ds = get_state("ds_h_365d")
if ds is not None:
    st.header("Last year — daily temperature")
    t2m = get_temp_da(ds)
    daily = t2m.resample(time="1D").mean()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily.time.values, y=daily.values, mode="lines", name="Daily mean °C"
        )
    )
    fig.update_layout(height=360, yaxis_title="°C", xaxis_title="Date")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
else:
    maybe_warn("h_365d", "1-year window")

# 4) Past 5 years — monthly + yearly mean (from climatology)
ds_m_recent = get_state("ds_m_recent")
if ds_m_recent is not None and "t2m_mon_mean_c" in ds_m_recent:
    st.header("Past 5 years — monthly temperature (climatology)")
    mon = ds_m_recent["t2m_mon_mean_c"]
    yr = yearly_mean_series_from_monthly(ds_m_recent)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=mon.time.values,
            y=mon.values,
            mode="lines+markers",
            name="Monthly mean °C",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=yr.time.values, y=yr.values, mode="lines", name="Yearly mean °C"
        )
    )
    fig.update_layout(height=360, yaxis_title="°C", xaxis_title="Month")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
else:
    st.warning("Recent monthly window (climatology) not available.")

# 5) Past 50 years — monthly + yearly mean (from climatology)
ds_m_50y = get_state("ds_m_50y")
if ds_m_50y is not None and "t2m_mon_mean_c" in ds_m_50y:
    st.header("Past 50 years — monthly temperature (climatology)")
    mon = ds_m_50y["t2m_mon_mean_c"]
    yr = yearly_mean_series_from_monthly(ds_m_50y)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=mon.time.values, y=mon.values, mode="lines", name="Monthly mean °C"
        )
    )
    fig.add_trace(
        go.Scatter(
            x=yr.time.values, y=yr.values, mode="lines", name="Yearly mean °C"
        )
    )
    fig.update_layout(height=360, yaxis_title="°C", xaxis_title="Month")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
else:
    st.warning("50-year monthly window (climatology) not available.")

# 6) Overlay: past 5 years vs same months 50 years earlier (climatology)
ds_m_past = get_state("ds_m_past")
if (
    ds_m_recent is not None
    and "t2m_mon_mean_c" in ds_m_recent
    and ds_m_past is not None
    and "t2m_mon_mean_c" in ds_m_past
    and ds_m_past["t2m_mon_mean_c"].sizes.get("time", 0) > 0
):
    st.header("Overlay: past 5 years vs same months 50 years earlier (climatology)")
    rec = ds_m_recent["t2m_mon_mean_c"].groupby("time.month").mean()
    pas = ds_m_past["t2m_mon_mean_c"].groupby("time.month").mean()
    months = list(range(1, 13))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=months,
            y=rec.sel(month=months).values,
            mode="lines+markers",
            name="Recent 5y mean by month",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=months,
            y=pas.sel(month=months).values,
            mode="lines+markers",
            name="Past 5y mean by month (50y earlier)",
        )
    )
    fig.update_layout(
        height=360,
        yaxis_title="°C",
        xaxis_title="Month",
        xaxis=dict(tickmode="array", tickvals=months),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
else:
    st.warning(
        "Overlay monthly window (climatology) not available (not enough historical data in this precomputed file)."
    )

# 7) Typical year — daily average (recent vs 50y earlier, derived from existing data)
st.markdown('<div id="typical"></div>', unsafe_allow_html=True)
st.header("“Typical” year: daily average (recent vs 50y earlier)")

ds_year = get_state("ds_h_365d")
ds_m_50y = get_state("ds_m_50y")

if ds_year is None or ds_m_50y is None or "t2m_mon_mean_c" not in ds_m_50y:
    st.warning(
        "Typical-year view not available (need both last-year daily data and 50-year monthly climatology)."
    )
else:
    # recent curve: daily climatology from last ~365 days
    t2m_hourly_year = get_temp_da(ds_year)
    recent_daily = t2m_hourly_year.resample(time="1D").mean()

    clim_recent = recent_daily.groupby("time.dayofyear").mean()
    clim_recent = clim_recent.sel(dayofyear=slice(1, 365))
    clim_recent = clim_recent.reindex(dayofyear=np.arange(1, 366))
    y_recent = clim_recent.values

    # past curve: build daily series from 50y monthly climatology
    mon_mean = ds_m_50y["t2m_mon_mean_c"]
    mon_clim = mon_mean.groupby("time.month").mean()  # 12 months

    base_dates = pd.date_range("2001-01-01", "2001-12-31", freq="D")
    months_for_doy = np.array([d.month for d in base_dates])

    past_vals = []
    for mth in months_for_doy:
        past_vals.append(float(mon_clim.sel(month=mth).values))
    past_vals = np.array(past_vals)
    y_past = past_vals

    x = np.arange(1, 366)

    # align / mask NaNs
    valid = ~(np.isnan(y_recent) | np.isnan(y_past))
    y_recent = np.where(valid, y_recent, np.nan)
    y_past = np.where(valid, y_past, np.nan)

    # red/blue segmented fills
    sign = np.sign(np.where(valid, y_recent - y_past, 0))
    segments = []
    start = 0
    for i in range(1, len(sign) + 1):
        if i == len(sign) or sign[i] != sign[i - 1]:
            segments.append((start, i - 1, int(sign[i - 1])))
            start = i

    fig = go.Figure()

    for a, b, s in segments:
        if s == 0:
            continue
        xx = x[a : b + 1]
        upper = (y_recent if s > 0 else y_past)[a : b + 1].copy()
        lower = (y_past if s > 0 else y_recent)[a : b + 1].copy()
        color = (
            "rgba(220, 50, 47, 0.35)" if s > 0 else "rgba(38, 139, 210, 0.35)"
        )
        fig.add_trace(
            go.Scatter(
                x=xx,
                y=upper,
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=xx,
                y=lower,
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor=color,
                showlegend=False,
                hoverinfo="skip",
            )
        )

    fig.add_trace(go.Scatter(x=x, y=y_past, mode="lines", name="Past mean"))
    fig.add_trace(go.Scatter(x=x, y=y_recent, mode="lines", name="Recent mean"))

    fig.update_layout(height=380, xaxis_title="Day of year", yaxis_title="°C")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
