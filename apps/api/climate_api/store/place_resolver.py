from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pickle
import math
import logging

import numpy as np
import pandas as pd

from ..cache import Cache
from .ocean_classifier import OceanClassifier


@dataclass(frozen=True)
class Place:
    geonameid: int
    label: str
    lat: float
    lon: float
    distance_km: float
    country_code: str | None = None
    population: int | None = None


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


def _haversine_km_pair(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(float(lat1))
    rlon1 = math.radians(float(lon1))
    rlat2 = math.radians(float(lat2))
    rlon2 = math.radians(float(lon2))

    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.asin(math.sqrt(a))
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
        kdtree_path: Path | None = None,
        ocean_classifier: OceanClassifier | None = None,
        ocean_off_city_max_km: float = 80.0,
        ocean_city_override_max_km: float = 2.0,
        cache: Cache | None = None,
        ttl_resolve_s: int = 86400,
        round_decimals: int = 2,
    ):
        self.locations_csv = Path(locations_csv)
        self.cache = cache
        self.ttl_resolve_s = int(ttl_resolve_s)
        self.round_decimals = int(round_decimals)
        self.ocean_classifier = ocean_classifier
        self.ocean_off_city_max_km = float(ocean_off_city_max_km)
        self.ocean_city_override_max_km = float(ocean_city_override_max_km)
        self._logger = logging.getLogger("uvicorn.error")

        df = pd.read_csv(self.locations_csv)

        for col in ("geonameid", "lat", "lon"):
            if col not in df.columns:
                raise ValueError(f"locations.csv missing required column: {col}")

        df["lat"] = df["lat"].astype(float)
        df["lon"] = df["lon"].astype(float)

        self._df = df
        self._lats = df["lat"].to_numpy(dtype=np.float64)
        self._lons = df["lon"].to_numpy(dtype=np.float64)
        self._ids = df["geonameid"].astype(int).to_numpy()
        if "country_code" in df.columns:
            self._country_codes = df["country_code"].fillna("").astype(str).to_numpy()
        else:
            self._country_codes = np.array([""] * len(df), dtype=object)
        if "population" in df.columns:
            self._populations = (
                pd.to_numeric(df["population"], errors="coerce")
                .fillna(0)
                .astype(np.int64)
                .to_numpy()
            )
        else:
            self._populations = np.zeros(len(df), dtype=np.int64)
        self._kdtree = None
        self._kdtree_ready = False

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

        if kdtree_path is not None:
            try:
                with open(kdtree_path, "rb") as f:
                    self._kdtree = pickle.load(f)
                self._kdtree_ready = True
                tree_n = getattr(self._kdtree, "n", None)
                if tree_n is None and hasattr(self._kdtree, "data"):
                    tree_n = len(self._kdtree.data)
                self._logger.info(
                    "PlaceResolver: KD-tree loaded from %s (%s points)",
                    kdtree_path,
                    tree_n if tree_n is not None else "unknown",
                )
            except Exception:
                self._kdtree = None
                self._kdtree_ready = False
                self._logger.warning(
                    "PlaceResolver: KD-tree failed to load from %s; "
                    "falling back to linear scan.",
                    kdtree_path,
                )
        else:
            self._logger.info("PlaceResolver: KD-tree not configured.")

        self._logger.info(
            "PlaceResolver: locations loaded from %s (%s rows)",
            self.locations_csv,
            len(df),
        )
        if self.ocean_classifier is not None:
            self._logger.info(
                "PlaceResolver: ocean labeling enabled (city override <= %.1f km, off-city <= %.1f km)",
                self.ocean_city_override_max_km,
                self.ocean_off_city_max_km,
            )

    def resolve_place(self, lat: float, lon: float) -> Place:
        qlat = round(float(lat), self.round_decimals)
        qlon = round(float(lon), self.round_decimals)
        cache_key = f"place:{qlat}:{qlon}"

        if self.cache is not None:
            hit = self.cache.get_json(cache_key)
            if hit is not None:
                return Place(
                    geonameid=int(hit["geonameid"]),
                    label=str(hit["label"]),
                    lat=float(hit["lat"]),
                    lon=float(hit["lon"]),
                    distance_km=float(hit["distance_km"]),
                    country_code=(
                        str(hit.get("country_code")).strip().upper()
                        if hit.get("country_code")
                        else None
                    ),
                    population=(
                        int(hit["population"])
                        if hit.get("population") is not None
                        else None
                    ),
                )

        if self._kdtree_ready and self._kdtree is not None:
            _, i = self._kdtree.query([lat, lon], k=1)
            i = int(i)
            dist = None
        else:
            d = _haversine_km_vec(lat, lon, self._lats, self._lons)
            i = int(np.argmin(d))
            dist = float(d[i])

        geonameid = int(self._ids[i])

        city_label = str(self._labels[i]).strip() if i < len(self._labels) else ""
        if not city_label:
            city_label = str(geonameid)

        label = city_label
        if self.ocean_classifier is not None:
            ocean = self.ocean_classifier.classify(lat, lon)
            if ocean.in_water:
                if dist is None:
                    dist = _haversine_km_pair(lat, lon, self._lats[i], self._lons[i])
                use_city_override = (
                    self.ocean_city_override_max_km > 0.0
                    and dist <= self.ocean_city_override_max_km
                )
                if not use_city_override:
                    ocean_name = ocean.ocean_name or "Open Ocean"
                    if dist <= self.ocean_off_city_max_km:
                        label = f"{ocean_name} off {city_label}"
                    else:
                        label = ocean_name
            elif dist is None:
                # Land point with KD-tree: skip distance computation for speed.
                dist = 0.0
        elif dist is None:
            # No ocean classifier configured: keep accurate distance for API payload.
            dist = _haversine_km_pair(lat, lon, self._lats[i], self._lons[i])

        place = Place(
            geonameid=geonameid,
            label=label,
            lat=float(self._lats[i]),
            lon=float(self._lons[i]),
            distance_km=float(dist),
            country_code=(
                str(self._country_codes[i]).strip().upper()
                if i < len(self._country_codes)
                and str(self._country_codes[i]).strip()
                else None
            ),
            population=(
                int(self._populations[i])
                if i < len(self._populations) and int(self._populations[i]) > 0
                else None
            ),
        )

        if self.cache is not None:
            self.cache.set_json(
                cache_key,
                {
                    "geonameid": place.geonameid,
                    "label": place.label,
                    "lat": place.lat,
                    "lon": place.lon,
                    "distance_km": place.distance_km,
                    "country_code": place.country_code,
                    "population": place.population,
                },
                ttl_s=self.ttl_resolve_s,
            )

        return place
