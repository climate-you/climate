#!/usr/bin/env python3
"""
Generate data/locations/locations.csv from GeoNames.

Reads all populated places (feature class "P") from a GeoNames dump
and writes them to the CSV used by the rest of the pipeline.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import pickle
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, TypedDict, Any
import unicodedata

import fiona
import numpy as np
from scipy.spatial import cKDTree

from climate.datasets.sources.http import download_to
from climate.geo.country import (
    COUNTRY_CODE_FIELD,
    NATURAL_EARTH_COUNTRIES_FALLBACK_URLS,
)
from climate.geo.marine import (
    MARINE_SOURCE_NATURAL_EARTH,
    NATURAL_EARTH_MARINE_POLYS_MIRROR_URL,
    normalize_marine_name,
)

GEONAMES_DUMP_BASE = "https://download.geonames.org/export/dump"
COUNTRYINFO_TXT = f"{GEONAMES_DUMP_BASE}/countryInfo.txt"
ADMIN1_CODES_TXT = f"{GEONAMES_DUMP_BASE}/admin1CodesASCII.txt"
ADMIN2_CODES_TXT = f"{GEONAMES_DUMP_BASE}/admin2Codes.txt"

# Allow selecting different GeoNames dumps.
CITIES_SOURCES: Dict[str, str] = {
    "all": f"{GEONAMES_DUMP_BASE}/allCountries.zip",
    "cities500": f"{GEONAMES_DUMP_BASE}/cities500.zip",
    "cities1000": f"{GEONAMES_DUMP_BASE}/cities1000.zip",
    "cities5000": f"{GEONAMES_DUMP_BASE}/cities5000.zip",
    "cities15000": f"{GEONAMES_DUMP_BASE}/cities15000.zip",
}

OUT_COLS = [
    "city_name",
    "country_name",
    "country_code",
    "lat",
    "lon",
    "timezone",
    "population",
    "kind",
    "label",
    "geonameid",
    "capital",
    "alt_names",
]


# GeoNames geoname table columns (index-based for speed)
IDX_GEONAMEID = 0
IDX_NAME = 1
IDX_ALTERNATE_NAMES = 3
IDX_LAT = 4
IDX_LON = 5
IDX_FEATURE_CLASS = 6
IDX_FEATURE_CODE = 7
IDX_COUNTRY_CODE = 8
IDX_ADMIN1_CODE = 10
IDX_ADMIN2_CODE = 11
IDX_POPULATION = 14
IDX_TIMEZONE = 17
GEONAMES_COLS_LEN = 19

FEATURE_CLASS_CITY = "P"
DEFAULT_EXCLUDED_FEATURE_CODES = {"PPLX", "PPLA5"}
MARINE_SOURCES = {
    MARINE_SOURCE_NATURAL_EARTH: NATURAL_EARTH_MARINE_POLYS_MIRROR_URL,
}
MARINE_SYNTHETIC_ID_START = 2_000_000_000


class _LocationRow(TypedDict):
    geonameid: str
    name: str
    cc: str
    admin1: str
    admin2: str
    lat: str
    lon: str
    timezone: str
    population: str
    alias_count: int
    feature_code: str
    alt_names: str


class _IndexCandidate(TypedDict):
    geonameid: str
    label: str
    city_name: str
    country_name: str
    country_code: str
    lat: str
    lon: str
    population: str
    alias_count: int
    feature_code: str
    alt_names: str


class _MarineNameAggregate(TypedDict):
    label: str
    weighted_lat_sum: float
    weighted_lon_x_sum: float
    weighted_lon_y_sum: float
    weight_sum: int


def cities_zip_url(source: str) -> str:
    if source not in CITIES_SOURCES:
        raise ValueError(
            f"Unknown source {source!r}. Choose from: {', '.join(sorted(CITIES_SOURCES))}"
        )
    return CITIES_SOURCES[source]


def download_cached(url: str, cache_dir: Path) -> Path:
    filename = url.rstrip("/").split("/")[-1]
    dest = cache_dir / filename
    return download_to(url, dest, retries=3)


def parse_country_info(path_txt: Path) -> Dict[str, str]:
    """
    countryInfo.txt is tab-delimited, with comment lines starting with '#'.
    Column 0 is ISO (2-letter). Column 4 is country name (per GeoNames docs).
    """
    out: Dict[str, str] = {}
    with open(path_txt, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            cc = parts[0].strip()
            name = parts[4].strip()
            if cc and name:
                out[cc] = name
    return out


def _parse_key_name_tsv(path_txt: Path) -> Dict[str, str]:
    """Parse a tab-delimited file where column 0 is a key and column 1 is a name."""
    out: Dict[str, str] = {}
    with open(path_txt, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            key = parts[0].strip()
            name = parts[1].strip()
            if key and name:
                out[key] = name
    return out


def parse_admin2_codes(path_txt: Path) -> Dict[str, str]:
    """
    admin2Codes.txt is tab-delimited.
    Column 0 is '<CC>.<ADMIN1>.<ADMIN2>', column 1 is admin2 name.
    """
    return _parse_key_name_tsv(path_txt)


def parse_admin1_codes(path_txt: Path) -> Dict[str, str]:
    """
    admin1CodesASCII.txt is tab-delimited.
    Column 0 is '<CC>.<ADMIN1>', column 1 is admin1 name.
    """
    return _parse_key_name_tsv(path_txt)


def _iter_geonames_rows(
    zip_path: Path, *, excluded_feature_codes: set[str]
) -> Iterable[Tuple[str, str, str, str, str, str, str, str, str, int, str, str]]:
    """
    Yield minimal fields for populated places from a GeoNames dump.

    Returns tuples:
      (
        geonameid,
        name,
        country_code,
        admin1_code,
        admin2_code,
        lat,
        lon,
        timezone,
        population,
        alias_count,
        feature_code,
        alt_names,
      )
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        txt_names = [n for n in z.namelist() if n.endswith(".txt")]
        if not txt_names:
            raise RuntimeError(f"No .txt file found inside {zip_path}")
        inner = txt_names[0]
        with z.open(inner, "r") as bf:
            tf = io.TextIOWrapper(bf, encoding="utf-8", newline="")
            for line in tf:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < GEONAMES_COLS_LEN:
                    continue
                if parts[IDX_FEATURE_CLASS] != FEATURE_CLASS_CITY:
                    continue
                feature_code = parts[IDX_FEATURE_CODE]
                if feature_code in excluded_feature_codes:
                    continue
                try:
                    geonameid = parts[IDX_GEONAMEID]
                    name = parts[IDX_NAME]
                    cc = parts[IDX_COUNTRY_CODE]
                    admin1 = parts[IDX_ADMIN1_CODE] or ""
                    admin2 = parts[IDX_ADMIN2_CODE] or ""
                    lat = parts[IDX_LAT]
                    lon = parts[IDX_LON]
                    timezone = parts[IDX_TIMEZONE] or ""
                    population = parts[IDX_POPULATION] or "0"
                    alt_names_raw = parts[IDX_ALTERNATE_NAMES] if len(parts) > 3 else ""
                    alias_count = (
                        len([n for n in alt_names_raw.split(",") if n.strip()])
                        if alt_names_raw
                        else 0
                    )
                except Exception:
                    continue
                yield (
                    geonameid,
                    name,
                    cc,
                    admin1,
                    admin2,
                    lat,
                    lon,
                    timezone,
                    population,
                    alias_count,
                    feature_code,
                    alt_names_raw,
                )


def _norm_index(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"[^a-z0-9\\s]+", " ", s)
    s = re.sub(r"\\s+", " ", s)
    return s.strip()


def _iter_lon_lat_pairs(coords: Any) -> Iterable[Tuple[float, float]]:
    """
    Recursively yield (lon, lat) coordinate pairs from GeoJSON-like geometry coords.
    """
    if not isinstance(coords, (list, tuple)):
        return
    if len(coords) >= 2 and all(isinstance(v, (int, float)) for v in coords[:2]):
        yield float(coords[0]), float(coords[1])
        return
    for part in coords:
        yield from _iter_lon_lat_pairs(part)


def _feature_center_from_geometry(geometry: dict) -> Optional[Tuple[float, float, int]]:
    """
    Returns feature center as:
      (mean_lat, circular_mean_lon, point_count)
    """
    if not geometry:
        return None
    coords = geometry.get("coordinates")
    if coords is None:
        return None

    lats: List[float] = []
    lon_x_sum = 0.0
    lon_y_sum = 0.0
    count = 0
    for lon, lat in _iter_lon_lat_pairs(coords):
        lats.append(lat)
        lon_rad = math.radians(lon)
        lon_x_sum += math.cos(lon_rad)
        lon_y_sum += math.sin(lon_rad)
        count += 1

    if count == 0:
        return None

    mean_lat = sum(lats) / float(count)
    mean_lon = math.degrees(math.atan2(lon_y_sum, lon_x_sum))
    mean_lon = ((mean_lon + 180.0) % 360.0) - 180.0
    return mean_lat, mean_lon, count


def _prepare_marine_input(
    *,
    marine_input: Optional[Path],
    marine_source: str,
    marine_cache_dir: Path,
) -> Path:
    if marine_input is not None:
        return marine_input
    if marine_source not in MARINE_SOURCES:
        raise ValueError(
            f"Unknown marine source {marine_source!r}. "
            f"Choose from: {', '.join(sorted(MARINE_SOURCES))}"
        )
    return download_cached(MARINE_SOURCES[marine_source], marine_cache_dir)


def load_marine_index_rows(
    *,
    input_path: Path,
    name_field: str,
    existing_ids: set[int],
) -> List[_IndexCandidate]:
    read_path: str | Path
    if input_path.suffix.lower() == ".zip":
        read_path = f"zip://{input_path}"
    else:
        read_path = input_path

    by_norm_name: Dict[str, _MarineNameAggregate] = {}
    with fiona.open(str(read_path), "r") as src:
        for feat in src:
            geometry = feat.get("geometry")
            if not geometry:
                continue

            props = feat.get("properties") or {}
            raw_name = str(props.get(name_field) or "").strip()
            name = normalize_marine_name(raw_name)
            if not name:
                continue

            center = _feature_center_from_geometry(geometry)
            if center is None:
                continue
            mean_lat, mean_lon, point_count = center
            if point_count <= 0:
                continue

            norm_name = _norm_index(name)
            if not norm_name:
                continue

            agg = by_norm_name.get(norm_name)
            lon_rad = math.radians(mean_lon)
            if agg is None:
                by_norm_name[norm_name] = {
                    "label": name,
                    "weighted_lat_sum": mean_lat * point_count,
                    "weighted_lon_x_sum": math.cos(lon_rad) * point_count,
                    "weighted_lon_y_sum": math.sin(lon_rad) * point_count,
                    "weight_sum": point_count,
                }
            else:
                if len(name) > len(agg["label"]):
                    agg["label"] = name
                agg["weighted_lat_sum"] += mean_lat * point_count
                agg["weighted_lon_x_sum"] += math.cos(lon_rad) * point_count
                agg["weighted_lon_y_sum"] += math.sin(lon_rad) * point_count
                agg["weight_sum"] += point_count

    if not by_norm_name:
        raise RuntimeError(
            f"No marine polygons with valid names found in {input_path} "
            f"using --marine-name-field={name_field!r}."
        )

    used_ids = set(existing_ids)
    next_id = MARINE_SYNTHETIC_ID_START
    out: List[_IndexCandidate] = []
    for norm_name in sorted(by_norm_name.keys()):
        while next_id in used_ids:
            next_id += 1
        agg = by_norm_name[norm_name]
        weight = max(int(agg["weight_sum"]), 1)
        lat = agg["weighted_lat_sum"] / float(weight)
        lon = math.degrees(
            math.atan2(agg["weighted_lon_y_sum"], agg["weighted_lon_x_sum"])
        )
        lon = ((lon + 180.0) % 360.0) - 180.0
        synthetic_id = next_id
        used_ids.add(synthetic_id)
        next_id += 1

        label = agg["label"]
        out.append(
            {
                "geonameid": str(synthetic_id),
                "label": label,
                "city_name": label,
                "country_name": "Ocean",
                "country_code": "OC",
                "lat": f"{lat:.5f}",
                "lon": f"{lon:.5f}",
                "population": "0",
                "alias_count": 0,
                "feature_code": "MARINE",
                "alt_names": "",
            }
        )
    return out


def _is_better_row(candidate: _LocationRow, current: _LocationRow) -> bool:
    """
    Decide which duplicate to keep.
    Preference order:
      1) higher population
      2) more specific/popular place type
      3) lower geonameid as stable tie-breaker
    """
    cand_pop = int(float(candidate["population"]) or 0)
    curr_pop = int(float(current["population"]) or 0)
    if cand_pop != curr_pop:
        return cand_pop > curr_pop

    feature_rank = {"PPLC": 0, "PPLA": 1, "PPLA2": 2, "PPLA3": 3, "PPLA4": 4}
    cand_rank = feature_rank.get(candidate["feature_code"], 9)
    curr_rank = feature_rank.get(current["feature_code"], 9)
    if cand_rank != curr_rank:
        return cand_rank < curr_rank

    return int(candidate["geonameid"]) < int(current["geonameid"])


def _is_better_label_candidate(
    candidate: _IndexCandidate, current: _IndexCandidate
) -> bool:
    """
    Pick the representative row for a shared display label in the index.
    Preference order:
      1) higher population
      2) higher alias_count (richer alternatenames)
      3) more specific/popular place type
      4) lower geonameid as stable tie-breaker
    """
    cand_pop = int(float(candidate["population"]) or 0)
    curr_pop = int(float(current["population"]) or 0)
    if cand_pop != curr_pop:
        return cand_pop > curr_pop

    if candidate["alias_count"] != current["alias_count"]:
        return candidate["alias_count"] > current["alias_count"]

    feature_rank = {"PPLC": 0, "PPLA": 1, "PPLA2": 2, "PPLA3": 3, "PPLA4": 4}
    cand_rank = feature_rank.get(candidate["feature_code"], 9)
    curr_rank = feature_rank.get(current["feature_code"], 9)
    if cand_rank != curr_rank:
        return cand_rank < curr_rank

    return int(candidate["geonameid"]) < int(current["geonameid"])


def write_locations_csv(
    out_csv: Path,
    zip_path: Path,
    country_names: Dict[str, str],
    admin1_names: Dict[str, str],
    admin2_names: Dict[str, str],
    *,
    excluded_feature_codes: set[str],
    collect_points: bool = False,
    index_csv: Optional[Path] = None,
    marine_index_rows: Optional[List[_IndexCandidate]] = None,
) -> Tuple[int, Optional[List[Tuple[float, float]]]]:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    points: Optional[List[Tuple[float, float]]] = [] if collect_points else None
    index_writer = None
    dedupe_map: Dict[Tuple[str, str, str, str], _LocationRow] = {}

    if index_csv is not None:
        index_csv.parent.mkdir(parents=True, exist_ok=True)
        index_file = open(index_csv, "w", encoding="utf-8", newline="")
        index_writer = csv.DictWriter(
            index_file,
            fieldnames=[
                "geonameid",
                "label",
                "city_name",
                "country_name",
                "country_code",
                "lat",
                "lon",
                "population",
                "norm_label",
                "norm_city",
                "capital",
                "alt_names",
            ],
        )
        index_writer.writeheader()
    else:
        index_file = None

    for (
        geonameid,
        name,
        cc,
        admin1,
        admin2,
        lat,
        lon,
        tz,
        pop,
        alias_count,
        feature_code,
        alt_names_raw,
    ) in _iter_geonames_rows(
        zip_path, excluded_feature_codes=excluded_feature_codes
    ):
        # Prune true duplicates emitted by GeoNames for the same named place and coordinates.
        lat_f = float(lat)
        lon_f = float(lon)
        key = (_norm_index(name), cc, f"{lat_f:.5f}", f"{lon_f:.5f}")
        candidate: _LocationRow = {
            "geonameid": geonameid,
            "name": name,
            "cc": cc,
            "admin1": admin1,
            "admin2": admin2,
            "lat": f"{lat_f:.5f}",
            "lon": f"{lon_f:.5f}",
            "timezone": tz,
            "population": str(int(float(pop) or 0)),
            "alias_count": int(alias_count),
            "feature_code": feature_code,
            "alt_names": alt_names_raw,
        }
        current = dedupe_map.get(key)
        if current is None or _is_better_row(candidate, current):
            dedupe_map[key] = candidate

    indexed_rows: List[_IndexCandidate] = []
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        us_state_name_counts: Dict[Tuple[str, str], int] = {}
        non_us_name_counts: Dict[Tuple[str, str], int] = {}
        for row in dedupe_map.values():
            norm_name = _norm_index(row["name"])
            if row["cc"] == "US":
                key = (norm_name, row["admin1"])
                us_state_name_counts[key] = us_state_name_counts.get(key, 0) + 1
                continue
            key = (row["cc"], norm_name)
            non_us_name_counts[key] = non_us_name_counts.get(key, 0) + 1
        for row in dedupe_map.values():
            geonameid = row["geonameid"]
            name = row["name"]
            cc = row["cc"]
            admin1 = row["admin1"]
            admin2 = row["admin2"]
            ctry = country_names.get(cc, cc)
            if cc == "US":
                if admin1:
                    key = (_norm_index(name), admin1)
                    count_in_state = us_state_name_counts.get(key, 0)
                    if count_in_state > 1:
                        admin2_key = f"{cc}.{admin1}.{admin2}" if admin2 else ""
                        county_name = admin2_names.get(admin2_key, "")
                        if county_name:
                            label = f"{name} ({county_name}), {admin1}, USA"
                        else:
                            label = f"{name} {admin1}, USA"
                    else:
                        label = f"{name} {admin1}, USA"
                else:
                    label = f"{name}, USA"
            elif cc == "FR":
                # France policy: for duplicate city names, use department (admin2) only.
                dup_key = (cc, _norm_index(name))
                if non_us_name_counts.get(dup_key, 0) > 1:
                    admin2_key = f"{cc}.{admin1}.{admin2}" if admin1 and admin2 else ""
                    department = admin2_names.get(admin2_key, "")
                    if department:
                        label = f"{name}, {department}, {ctry}"
                    else:
                        label = f"{name}, {ctry}"
                else:
                    label = f"{name}, {ctry}"
            else:
                # Non-US policy: for duplicate city names, use admin1 only.
                dup_key = (cc, _norm_index(name))
                if non_us_name_counts.get(dup_key, 0) > 1:
                    admin1_key = f"{cc}.{admin1}" if admin1 else ""
                    admin1_label = admin1_names.get(admin1_key, "")
                    if admin1_label:
                        label = f"{name}, {admin1_label}, {ctry}"
                    else:
                        label = f"{name}, {ctry}"
                else:
                    label = f"{name}, {ctry}"
            lat_f = float(row["lat"])
            lon_f = float(row["lon"])
            pop_i = int(float(row["population"]) or 0)
            tz = row["timezone"]
            w.writerow(
                {
                    "city_name": name,
                    "country_name": ctry,
                    "country_code": cc,
                    "lat": f"{lat_f:.5f}",
                    "lon": f"{lon_f:.5f}",
                    "timezone": tz,
                    "population": str(pop_i),
                    "geonameid": geonameid,
                    "kind": "city",
                    "label": label,
                    "capital": "true" if row["feature_code"] == "PPLC" else "false",
                    "alt_names": row["alt_names"],
                }
            )
            if points is not None:
                points.append((lat_f, lon_f))
            total += 1
            indexed_rows.append(
                {
                    "geonameid": geonameid,
                    "label": label,
                    "city_name": name,
                    "country_name": ctry,
                    "country_code": cc,
                    "lat": f"{lat_f:.5f}",
                    "lon": f"{lon_f:.5f}",
                    "population": str(pop_i),
                    "alias_count": int(row["alias_count"]),
                    "feature_code": row["feature_code"],
                    "alt_names": row["alt_names"],
                }
            )

    if index_writer is not None:
        if marine_index_rows:
            used_ids = {
                int(row["geonameid"])
                for row in indexed_rows
                if str(row.get("geonameid", "")).strip()
            }
            next_id = MARINE_SYNTHETIC_ID_START
            for marine_row in sorted(
                marine_index_rows, key=lambda r: _norm_index(r["label"])
            ):
                while next_id in used_ids:
                    next_id += 1
                assigned_row: _IndexCandidate = {
                    "geonameid": str(next_id),
                    "label": marine_row["label"],
                    "city_name": marine_row["city_name"],
                    "country_name": marine_row["country_name"],
                    "country_code": marine_row["country_code"],
                    "lat": marine_row["lat"],
                    "lon": marine_row["lon"],
                    "population": marine_row["population"],
                    "alias_count": marine_row["alias_count"],
                    "feature_code": marine_row["feature_code"],
                    "alt_names": marine_row.get("alt_names", ""),
                }
                used_ids.add(next_id)
                next_id += 1
                indexed_rows.append(assigned_row)
        # Build-time dedupe by final display label for autocomplete/resolve/index lookups.
        best_by_label: Dict[str, _IndexCandidate] = {}
        for row in indexed_rows:
            label = row["label"]
            current = best_by_label.get(label)
            if current is None or _is_better_label_candidate(row, current):
                best_by_label[label] = row
        for _label, row in best_by_label.items():
            index_writer.writerow(
                {
                    "geonameid": row["geonameid"],
                    "label": row["label"],
                    "city_name": row["city_name"],
                    "country_name": row["country_name"],
                    "country_code": row["country_code"],
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "population": row["population"],
                    "norm_label": _norm_index(row["label"]),
                    "norm_city": _norm_index(row["city_name"]),
                    "capital": "true" if row.get("feature_code") == "PPLC" else "false",
                    "alt_names": row.get("alt_names", ""),
                }
            )

    if index_file is not None:
        index_file.close()

    return total, points


def write_kdtree(points: List[Tuple[float, float]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(points, dtype=np.float64)
    tree = cKDTree(data)
    with open(out_path, "wb") as f:
        pickle.dump(tree, f, protocol=pickle.HIGHEST_PROTOCOL)


def build_country_mask(
    *,
    output_npz: Path,
    output_codes_json: Path,
    deg: float = 0.1,
    cache_dir: Path,
    input_path: Optional[Path] = None,
    code_field: str = COUNTRY_CODE_FIELD,
) -> None:
    """
    Download Natural Earth country polygons and rasterize them into a country_mask.npz
    for fast point-in-polygon country lookup at runtime.

    NPZ layout (mirrors ocean_mask.npz):
      - data: 2D uint16 array (nlat × nlon), 0 = unknown/ocean, >0 = country id
      - deg, lat_max, lon_min: grid parameters

    Companion JSON maps integer ids to ISO 3166-1 alpha-2 codes:
      {"1": "FR", "2": "BE", ...}
    """
    try:
        from rasterio.features import rasterize
        from rasterio.transform import from_origin
    except Exception as exc:
        raise RuntimeError(
            "rasterio is required to build the country mask. "
            "Install with: pip install rasterio"
        ) from exc

    if input_path is None:
        zip_name = "ne_50m_admin_0_countries.zip"
        zip_path = cache_dir / zip_name
        if not zip_path.exists() or zip_path.stat().st_size == 0:
            last_err: Optional[Exception] = None
            for url in NATURAL_EARTH_COUNTRIES_FALLBACK_URLS:
                try:
                    print(f"[download] {url} -> {zip_path}", file=sys.stderr)
                    download_cached(url, cache_dir)
                    last_err = None
                    break
                except Exception as exc:
                    last_err = exc
            if last_err is not None:
                raise RuntimeError(
                    "Failed to download Natural Earth country polygons from all sources."
                ) from last_err
        input_path = zip_path

    read_path: str | Path = (
        f"zip://{input_path}" if input_path.suffix.lower() == ".zip" else input_path
    )

    # Assign stable integer ids to each unique ISO country code encountered.
    code_to_id: Dict[str, int] = {}
    id_to_code: Dict[int, str] = {}
    shapes: List[Tuple[Any, int]] = []
    next_id = 1

    with fiona.open(str(read_path), "r") as src:
        for feat in src:
            geom = feat.get("geometry")
            if not geom:
                continue
            props = feat.get("properties") or {}
            raw_code = str(props.get(code_field) or "").strip().upper()
            # Natural Earth uses "-99" as a sentinel for unassigned ISO codes.
            if not raw_code or raw_code == "-99":
                continue
            country_id = code_to_id.get(raw_code)
            if country_id is None:
                country_id = next_id
                next_id += 1
                code_to_id[raw_code] = country_id
                id_to_code[country_id] = raw_code
            shapes.append((geom, country_id))

    if not shapes:
        raise RuntimeError(
            f"No country shapes loaded from {input_path}. "
            f"Check --country-code-field (currently {code_field!r})."
        )

    lat_max = 90.0
    lon_min = -180.0
    nlat = int(round((2.0 * lat_max) / deg))
    nlon = int(round(360.0 / deg))
    transform = from_origin(lon_min, lat_max, deg, deg)

    mask = rasterize(
        shapes=shapes,
        out_shape=(nlat, nlon),
        transform=transform,
        fill=0,
        dtype="uint16",
        all_touched=False,
    )

    output_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_npz,
        data=mask.astype(np.uint16, copy=False),
        deg=np.float64(deg),
        lat_max=np.float64(lat_max),
        lon_min=np.float64(lon_min),
    )

    output_codes_json.parent.mkdir(parents=True, exist_ok=True)
    codes_payload = {str(k): v for k, v in sorted(id_to_code.items())}
    output_codes_json.write_text(
        json.dumps(codes_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"[ok] wrote {output_npz} shape={mask.shape} deg={deg} countries={len(id_to_code)}",
        file=sys.stderr,
    )
    print(f"[ok] wrote {output_codes_json}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=str,
        default="data/locations/locations.csv",
        help='Output CSV path (default: "data/locations/locations.csv").',
    )
    ap.add_argument(
        "--cache-dir",
        type=str,
        default="data/cache/geonames",
        help='GeoNames cache directory (default: "data/cache/geonames").',
    )
    ap.add_argument(
        "--write-kdtree",
        action="store_true",
        help="Build a KD-tree for nearest-location queries.",
    )
    ap.add_argument(
        "--kdtree-path",
        type=str,
        default="data/locations/locations.kdtree.pkl",
        help='KD-tree output path (default: "data/locations/locations.kdtree.pkl").',
    )
    ap.add_argument(
        "--write-index",
        action="store_true",
        help="Write an autocomplete/resolve index CSV.",
    )
    ap.add_argument(
        "--index-path",
        type=str,
        default="data/locations/locations.index.csv",
        help='Index output path (default: "data/locations/locations.index.csv").',
    )
    ap.add_argument(
        "--marine-input",
        type=str,
        default=None,
        help=(
            "Optional local marine polygons input for index entries "
            "(GeoJSON/Shapefile/zip). If omitted, a Natural Earth source is used."
        ),
    )
    ap.add_argument(
        "--marine-source",
        type=str,
        default=MARINE_SOURCE_NATURAL_EARTH,
        choices=sorted(MARINE_SOURCES.keys()),
        help='Built-in marine source when --marine-input is omitted (default: "natural_earth").',
    )
    ap.add_argument(
        "--marine-cache-dir",
        type=str,
        default="data/cache/geodata",
        help='Marine input cache directory (default: "data/cache/geodata").',
    )
    ap.add_argument(
        "--marine-name-field",
        type=str,
        default="name",
        help='Marine polygon property field for display name (default: "name").',
    )
    ap.add_argument(
        "--source",
        type=str,
        default="cities500",
        choices=sorted(CITIES_SOURCES.keys()),
        help='Which GeoNames dump to use (default: "cities500"; all is largest).',
    )
    ap.add_argument(
        "--exclude-feature-codes",
        type=str,
        default=",".join(sorted(DEFAULT_EXCLUDED_FEATURE_CODES)),
        help=(
            "Comma-separated GeoNames feature codes to exclude within class P "
            f"(default: {','.join(sorted(DEFAULT_EXCLUDED_FEATURE_CODES))})."
        ),
    )
    ap.add_argument(
        "--write-country-mask",
        action="store_true",
        help="Build a country raster mask for country-constrained nearest-location queries.",
    )
    ap.add_argument(
        "--country-mask-path",
        type=str,
        default="data/locations/country_mask.npz",
        help='Country mask NPZ output path (default: "data/locations/country_mask.npz").',
    )
    ap.add_argument(
        "--country-codes-path",
        type=str,
        default="data/locations/country_codes.json",
        help='Country codes JSON output path (default: "data/locations/country_codes.json").',
    )
    ap.add_argument(
        "--country-mask-deg",
        type=float,
        default=0.1,
        help="Grid resolution in degrees for the country mask (default: 0.1 ≈ 11 km).",
    )
    ap.add_argument(
        "--country-input",
        type=str,
        default=None,
        help=(
            "Optional local country polygons input (GeoJSON/Shapefile/zip). "
            "If omitted, Natural Earth 50m countries are downloaded."
        ),
    )
    ap.add_argument(
        "--country-cache-dir",
        type=str,
        default="data/cache/geodata",
        help='Country polygons download cache directory (default: "data/cache/geodata").',
    )
    ap.add_argument(
        "--country-code-field",
        type=str,
        default=COUNTRY_CODE_FIELD,
        help=f'Property field for ISO country code (default: "{COUNTRY_CODE_FIELD}").',
    )
    ap.add_argument(
        "--write-country-names",
        action="store_true",
        help="Write a country code → name JSON for countries with no populated places.",
    )
    ap.add_argument(
        "--country-names-path",
        type=str,
        default="data/locations/country_names.json",
        help='Country names JSON output path (default: "data/locations/country_names.json").',
    )
    args = ap.parse_args()
    excluded_feature_codes = {
        code.strip().upper()
        for code in args.exclude_feature_codes.split(",")
        if code.strip()
    }

    cache_dir = Path(args.cache_dir)
    zpath = download_cached(cities_zip_url(args.source), cache_dir)
    cpath = download_cached(COUNTRYINFO_TXT, cache_dir)
    a1path = download_cached(ADMIN1_CODES_TXT, cache_dir)
    a2path = download_cached(ADMIN2_CODES_TXT, cache_dir)

    country_names = parse_country_info(cpath)
    admin1_names = parse_admin1_codes(a1path)
    admin2_names = parse_admin2_codes(a2path)
    out_csv = Path(args.out)
    index_csv = None
    marine_index_rows: Optional[List[_IndexCandidate]] = None
    if args.write_index:
        index_csv = Path(args.index_path)
        marine_input_path = _prepare_marine_input(
            marine_input=Path(args.marine_input) if args.marine_input else None,
            marine_source=args.marine_source,
            marine_cache_dir=Path(args.marine_cache_dir),
        )
        marine_index_rows = load_marine_index_rows(
            input_path=marine_input_path,
            name_field=args.marine_name_field,
            existing_ids=set(),
        )

    count, points = write_locations_csv(
        out_csv,
        zpath,
        country_names,
        admin1_names,
        admin2_names,
        excluded_feature_codes=excluded_feature_codes,
        collect_points=bool(args.write_kdtree),
        index_csv=index_csv,
        marine_index_rows=marine_index_rows,
    )

    if args.write_kdtree:
        if points is None:
            raise RuntimeError("KD-tree requested but no points were collected.")
        kdtree_path = Path(args.kdtree_path)
        write_kdtree(points, kdtree_path)

    if args.write_country_mask:
        build_country_mask(
            output_npz=Path(args.country_mask_path),
            output_codes_json=Path(args.country_codes_path),
            deg=args.country_mask_deg,
            cache_dir=Path(args.country_cache_dir),
            input_path=Path(args.country_input) if args.country_input else None,
            code_field=args.country_code_field,
        )

    if args.write_country_names:
        country_names_path = Path(args.country_names_path)
        country_names_path.parent.mkdir(parents=True, exist_ok=True)
        country_names_path.write_text(
            json.dumps(country_names, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"[ok] wrote {country_names_path}", file=sys.stderr)

    excluded_msg = ",".join(sorted(excluded_feature_codes)) or "(none)"
    print(
        f"[ok] wrote {out_csv} ({count} locations); excluded feature codes: {excluded_msg}",
        file=sys.stderr,
    )
    if index_csv is not None:
        print(f"[ok] wrote {index_csv}", file=sys.stderr)
    if args.write_kdtree:
        print(f"[ok] wrote {kdtree_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
