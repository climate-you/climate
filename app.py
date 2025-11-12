# app.py
import streamlit as st, xarray as xr, numpy as np
import earthkit.data as ekd

st.title("Temperature trends by region (ERA5 monthly)")
bbox = st.text_input("Bounding box [N,W,S,E]", "60,-20,20,40")
start = st.text_input("Start year", "1980")
end   = st.text_input("End year", "2025")

@st.cache_data(show_spinner=False)
def load_era5(bbox, start, end):
    N,W,S,E = map(float, bbox.split(","))
    req = {
      "product_type": "monthly_averaged_reanalysis",
      "variable": ["2m_temperature"],
      "year": [str(y) for y in range(int(start), int(end)+1)],
      "month": [f"{m:02d}" for m in range(1,13)],
      "time": "00:00",
      "area": [N, W, S, E],
      "format": "netcdf",
    }
    data = ekd.from_source("cds","reanalysis-era5-single-levels-monthly-means", req)
    return data.to_xarray()

def standardise_time(ds: xr.Dataset) -> xr.Dataset:
    """
    Make sure the dataset uses a single time coordinate named 'time'.
    Handles common cases where CFGRIB exposes 'valid_time'.
    """
    # If the dim is 'valid_time', rename it to 'time'
    if "valid_time" in ds.dims and "time" not in ds.dims:
        ds = ds.rename({"valid_time": "time"})

    # If there is both a 'time' dim and an extra 'valid_time' coord, align/drop it
    if "time" in ds.dims and "valid_time" in ds.coords:
        # If lengths match, promote valid_time to be the time coord; otherwise just drop it
        if ds.sizes.get("time") == ds.sizes.get("valid_time"):
            ds = ds.assign_coords(time=ds["valid_time"]).drop_vars("valid_time")
        else:
            ds = ds.drop_vars("valid_time")

    # final sanity: ensure 'time' exists as a coord
    if "time" not in ds.coords and "time" in ds:
        ds = ds.set_coords("time")

    return ds

def normalise_dims(ds: xr.Dataset) -> xr.Dataset:
    # Handle ERA5 expver streams
    if "expver" in ds.dims:
        ds = ds.sortby("expver").ffill("expver").isel(expver=-1, drop=True)
    # Handle ensemble members if present
    if "number" in ds.dims:
        ds = ds.mean("number", keep_attrs=True)
    return ds

def main():
    ds = load_era5(bbox, start, end)
    ds = normalise_dims(ds)
    ds = standardise_time(ds)

    t2m = ds["t2m"] - 273.15
    weights = np.cos(np.deg2rad(t2m["latitude"])); weights /= weights.mean()
    ts = t2m.weighted(weights).mean(("latitude", "longitude")).sortby("time")

    # Plot
    st.line_chart(ts.to_series(), height=320)

    # Trend using the now-canonical 'time'
    years = ts["time"].dt.year.values
    X = np.vstack([np.ones_like(years), years]).T
    slope = np.linalg.lstsq(X, ts.values, rcond=None)[0][1] * 10.0
    st.write(f"Trend: **{slope:.2f} °C/decade**")

    # Debug line (optional)
    st.caption(f"time coord: {ts['time'].values[0]} → {ts['time'].values[-1]}  |  n={ts.sizes['time']}")

main()