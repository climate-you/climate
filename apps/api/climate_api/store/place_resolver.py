from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import numpy as np
import pandas as pd

from ..cache import Cache


@dataclass(frozen=True)
class Place:
    slug: str
    label: str
    lat: float
    lon: float
    distance_km: float


def _haversine_km_vec(
    lat: float, lon: float, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    rlat1 = math.radians(float(lat))
    rlon1 = math.radians(float(lon))
    rlat2 = np.radians(lats.astype(np.float64))
    rlon2 = np.radians(lons.astype(np.float64))

    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(rlat1) * np.cos(rlat2) * np.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * np.arcsin(np.sqrt(a))
    return 6371.0 * c


class PlaceResolver:
    """
    (lat,lon) -> nearest row in locations.csv (for human-friendly labels)

    Cache key cardinality is controlled with rounding.
    TTL should reuse settings.ttl_resolve_s.
    """

    def __init__(
        self,
        locations_csv: Path,
        *,
        cache: Cache | None = None,
        ttl_resolve_s: int = 86400,
        round_decimals: int = 2,
    ):
        self.locations_csv = Path(locations_csv)
        self.cache = cache
        self.ttl_resolve_s = int(ttl_resolve_s)
        self.round_decimals = int(round_decimals)

        df = pd.read_csv(self.locations_csv)

        for col in ("slug", "lat", "lon"):
            if col not in df.columns:
                raise ValueError(f"locations.csv missing required column: {col}")

        df["lat"] = df["lat"].astype(float)
        df["lon"] = df["lon"].astype(float)

        self._df = df
        self._lats = df["lat"].to_numpy(dtype=np.float64)
        self._lons = df["lon"].to_numpy(dtype=np.float64)
        self._slugs = df["slug"].astype(str).to_numpy()

        # Prefer explicit label column if present; otherwise build a fallback
        if "label" in df.columns:
            labels = df["label"].fillna("").astype(str).to_numpy()
        else:
            city = (
                df["city_name"].fillna("").astype(str).to_numpy()
                if "city_name" in df.columns
                else None
            )
            country = (
                df["country_name"].fillna("").astype(str).to_numpy()
                if "country_name" in df.columns
                else None
            )
            labels = np.array([""] * len(df), dtype=object)
            if city is not None and country is not None:
                labels = np.array(
                    [
                        f"{c}, {co}" if c and co else (c or co or "")
                        for c, co in zip(city, country)
                    ],
                    dtype=object,
                )

        self._labels = labels

    def resolve_place(self, lat: float, lon: float) -> Place:
        qlat = round(float(lat), self.round_decimals)
        qlon = round(float(lon), self.round_decimals)
        cache_key = f"place:{qlat}:{qlon}"

        if self.cache is not None:
            hit = self.cache.get_json(cache_key)
            if hit is not None:
                return Place(
                    slug=str(hit["slug"]),
                    label=str(hit["label"]),
                    lat=float(hit["lat"]),
                    lon=float(hit["lon"]),
                    distance_km=float(hit["distance_km"]),
                )

        d = _haversine_km_vec(lat, lon, self._lats, self._lons)
        i = int(np.argmin(d))
        slug = str(self._slugs[i])
        dist = float(d[i])

        label = str(self._labels[i]).strip() if i < len(self._labels) else ""
        if not label:
            label = slug

        place = Place(
            slug=slug,
            label=label,
            lat=float(self._lats[i]),
            lon=float(self._lons[i]),
            distance_km=dist,
        )

        if self.cache is not None:
            self.cache.set_json(
                cache_key,
                {
                    "slug": place.slug,
                    "label": place.label,
                    "lat": place.lat,
                    "lon": place.lon,
                    "distance_km": place.distance_km,
                },
                ttl_s=self.ttl_resolve_s,
            )

        return place
