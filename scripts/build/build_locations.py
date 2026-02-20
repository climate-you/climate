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
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, TypedDict
import unicodedata
import requests

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


def cities_zip_url(source: str) -> str:
    if source not in CITIES_SOURCES:
        raise ValueError(
            f"Unknown source {source!r}. Choose from: {', '.join(sorted(CITIES_SOURCES))}"
        )
    return CITIES_SOURCES[source]


def _http_download(url: str, dest: Path, timeout: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)


def download_cached(url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rstrip("/").split("/")[-1]
    dest = cache_dir / filename
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    print(f"[download] {url} -> {dest}", file=sys.stderr)
    _http_download(url, dest)
    return dest


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


def parse_admin2_codes(path_txt: Path) -> Dict[str, str]:
    """
    admin2Codes.txt is tab-delimited.
    Column 0 is '<CC>.<ADMIN1>.<ADMIN2>', column 1 is admin2 name.
    """
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


def parse_admin1_codes(path_txt: Path) -> Dict[str, str]:
    """
    admin1CodesASCII.txt is tab-delimited.
    Column 0 is '<CC>.<ADMIN1>', column 1 is admin1 name.
    """
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


def _iter_geonames_rows(
    zip_path: Path, *, excluded_feature_codes: set[str]
) -> Iterable[Tuple[str, str, str, str, str, str, str, str, str, int, str]]:
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
                    alt_names = parts[IDX_ALTERNATE_NAMES] if len(parts) > 3 else ""
                    alias_count = (
                        len([n for n in alt_names.split(",") if n.strip()])
                        if alt_names
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
                )


def _norm_index(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"[^a-z0-9\\s]+", " ", s)
    s = re.sub(r"\\s+", " ", s)
    return s.strip()


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
                }
            )

    if index_writer is not None:
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
                }
            )

    if index_file is not None:
        index_file.close()

    return total, points


def write_kdtree(points: List[Tuple[float, float]], out_path: Path) -> None:
    try:
        import numpy as np
        from scipy.spatial import cKDTree
    except Exception as exc:
        raise RuntimeError(
            "scipy is required to build the KD-tree. "
            "Install scipy and re-run with --write-kdtree."
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(points, dtype=np.float64)
    tree = cKDTree(data)

    import pickle

    with open(out_path, "wb") as f:
        pickle.dump(tree, f, protocol=pickle.HIGHEST_PROTOCOL)


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
    if args.write_index:
        index_csv = Path(args.index_path)

    count, points = write_locations_csv(
        out_csv,
        zpath,
        country_names,
        admin1_names,
        admin2_names,
        excluded_feature_codes=excluded_feature_codes,
        collect_points=bool(args.write_kdtree),
        index_csv=index_csv,
    )

    if args.write_kdtree:
        if points is None:
            raise RuntimeError("KD-tree requested but no points were collected.")
        write_kdtree(points, Path(args.kdtree_path))

    excluded_msg = ",".join(sorted(excluded_feature_codes)) or "(none)"
    print(
        f"[ok] wrote {out_csv} ({count} locations); excluded feature codes: {excluded_msg}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
