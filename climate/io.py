import streamlit as st
import xarray as xr
import os
import glob
import numpy as np

# -----------------------------------------------------------
# Helpers to load precomputed caches
# -----------------------------------------------------------

def discover_locations(clim_dir: str) -> dict:
    """
    Scan story_climatology/clim_*.nc and build a dict:
      slug -> {slug, label, lat, lon, path}
    Expects precompute_story_cities.py to have stored latitude/longitude and
    optional city_name/country_name in ds.attrs.
    """
    locations = {}
    pattern = os.path.join(clim_dir, "clim_*.nc")
    for path in glob.glob(pattern):
        fname = os.path.basename(path)
        # "clim_<slug>.nc" -> <slug>
        if not fname.startswith("clim_") or not fname.endswith(".nc"):
            continue
        slug = fname[len("clim_") : -len(".nc")]

        try:
            ds_meta = xr.open_dataset(path)
            city_name = ds_meta.attrs.get("name_short", slug)
            country_name = ds_meta.attrs.get("country", "")
            country_code = ds_meta.attrs.get("country_code", "")
            lat_attr = ds_meta.attrs.get("latitude", np.nan)
            lon_attr = ds_meta.attrs.get("longitude", np.nan)
            lat = float(lat_attr) if lat_attr is not None else np.nan
            lon = float(lon_attr) if lon_attr is not None else np.nan
            ds_meta.close()
        except Exception:
            city_name = slug
            country_name = ""
            country_code = ""
            lat = np.nan
            lon = np.nan

        if country_name:
            label = f"{city_name}, {country_name}"
        else:
            label = city_name

        locations[slug] = {
            "slug": slug,
            "label": label,
            "lat": lat,
            "lon": lon,
            "path": path,
            "country_code" : country_code,
        }

    return locations

@st.cache_data
def load_city_climatology(slug: str) -> xr.Dataset:
    """Load precomputed climatology NetCDF for a given location slug."""
    path = DATA_DIR / f"clim_{slug}.nc"
    ds = xr.load_dataset(path)
    return ds

def dataset_coverage_text(ds: xr.Dataset) -> str:
    """Return a short caption like 'Data from 1979 to Sep 2025'."""
    start_year = ds.attrs.get("start_year")
    end_str = ds.attrs.get("data_end_date")

    if not start_year or not end_str:
        return ""

    try:
        end_date = datetime.fromisoformat(str(end_str)).date()
    except Exception:
        # Fallback if the date is weird, but don't crash the UI
        return f"Data starting {start_year}"

    # Example: "Sep 2025"
    end_label = end_date.strftime("%b %Y")
    return f"Range: {start_year} - {end_label}"
