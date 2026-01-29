from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import pandas as pd
import xarray as xr

from ..cache import Cache


@dataclass(frozen=True)
class LocationRow:
    slug: str
    lat: float
    lon: float
    label: str | None = None


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    # degrees -> radians
    rlat1 = math.radians(lat1)
    rlon1 = math.radians(lon1)
    rlat2 = math.radians(lat2)
    rlon2 = math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return 6371.0 * c


class NcPointsStore:
    def __init__(
        self,
        locations_csv: Path,
        clim_dir: Path,
        ocean_dir: Path,
        cache: Cache | None = None,
        ttl_resolve_s: int = 86400,
    ):
        self.locations_csv = locations_csv
        self.clim_dir = clim_dir
        self.ocean_dir = ocean_dir
        self.cache = cache
        self.ttl_resolve_s = int(ttl_resolve_s)

        self._loc_df = pd.read_csv(locations_csv)
        # normalize
        self._loc_df["lat"] = self._loc_df["lat"].astype(float)
        self._loc_df["lon"] = self._loc_df["lon"].astype(float)

        # Keep a tiny meta dict by slug
        self._meta = {}
        for _, row in self._loc_df.iterrows():
            self._meta[row["slug"]] = {
                "slug": row["slug"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "label": row.get("label") if "label" in row else None,
                "city_name": row.get("city_name"),
                "country_name": row.get("country_name"),
                "country_code": row.get("country_code"),
                "kind": row.get("kind"),
            }

    def resolve_place(self, lat: float, lon: float) -> tuple[str, float]:
        qlat = round(float(lat), 2)
        qlon = round(float(lon), 2)
        cache_key = f"place:{qlat}:{qlon}"

        if self.cache is not None:
            hit = self.cache.get_json(cache_key)
            if hit is not None:
                return hit["slug"], float(hit["distance_km"])

        # same nearest scan as before
        best_slug = None
        best_d = 1e9
        for _, row in self._loc_df.iterrows():
            d = haversine_km(lat, lon, float(row["lat"]), float(row["lon"]))
            if d < best_d:
                best_d = d
                best_slug = row["slug"]
        assert best_slug is not None

        if self.cache is not None:
            self.cache.set_json(
                cache_key,
                {"slug": str(best_slug), "distance_km": float(best_d)},
                ttl_s=self.ttl_resolve_s,
            )
        return str(best_slug), float(best_d)

    def location_meta(self, slug: str) -> dict:
        if slug not in self._meta:
            raise KeyError(f"Unknown slug: {slug}")
        return self._meta[slug]

    def _clim_path(self, slug: str) -> Path:
        return self.clim_dir / f"clim_{slug}.nc"

    def _ocean_path(self, slug: str) -> Path:
        return self.ocean_dir / f"ocean_{slug}.nc"

    def load_location_dataset(self, slug: str) -> xr.Dataset:
        clim_path = self._clim_path(slug)
        if not clim_path.exists():
            raise FileNotFoundError(f"Missing climatology file: {clim_path}")

        ds_clim = xr.open_dataset(clim_path)

        ocean_path = self._ocean_path(slug)
        if not ocean_path.exists():
            return ds_clim

        ds_ocean = xr.open_dataset(ocean_path)

        # Rename dims in ocean dataset to avoid collisions with climatology dataset
        rename_dims = {}
        if "time" in ds_ocean.dims and "time" in ds_clim.dims:
            rename_dims["time"] = "time_ocean"
        # Optional but future-proof (recommended)
        if "year" in ds_ocean.dims and "year" in ds_clim.dims:
            rename_dims["year"] = "year_ocean"

        if rename_dims:
            ds_ocean = ds_ocean.rename(rename_dims)

        # Manual union of variables (no alignment)
        ds = ds_clim.copy()
        for name, da in ds_ocean.data_vars.items():
            if name in ds.data_vars:
                raise ValueError(
                    f"Variable collision when merging ocean dataset: {name}"
                )
            ds[name] = da

        ds.attrs.update(ds_clim.attrs)
        return ds
