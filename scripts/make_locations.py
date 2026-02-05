#!/usr/bin/env python3
"""
Generate locations/locations.csv from GeoNames without filtering.

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
from typing import Dict, Iterable, List, Optional, Tuple
import unicodedata
import requests

GEONAMES_DUMP_BASE = "https://download.geonames.org/export/dump"
COUNTRYINFO_TXT = f"{GEONAMES_DUMP_BASE}/countryInfo.txt"

# Allow selecting different GeoNames dumps.
CITIES_SOURCES: Dict[str, str] = {
    "all": f"{GEONAMES_DUMP_BASE}/allCountries.zip",
    "cities500": f"{GEONAMES_DUMP_BASE}/cities500.zip",
    "cities1000": f"{GEONAMES_DUMP_BASE}/cities1000.zip",
    "cities5000": f"{GEONAMES_DUMP_BASE}/cities5000.zip",
    "cities15000": f"{GEONAMES_DUMP_BASE}/cities15000.zip",
}

OUT_COLS = [
    "slug",
    "city_name",
    "country_name",
    "country_code",
    "lat",
    "lon",
    "timezone",
    "population",
    "geonameid",
    "kind",
    "label",
]

# GeoNames geoname table columns (index-based for speed)
IDX_GEONAMEID = 0
IDX_NAME = 1
IDX_LAT = 4
IDX_LON = 5
IDX_FEATURE_CLASS = 6
IDX_FEATURE_CODE = 7
IDX_COUNTRY_CODE = 8
IDX_POPULATION = 14
IDX_TIMEZONE = 17
GEONAMES_COLS_LEN = 19

FEATURE_CLASS_CITY = "P"


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


def _iter_geonames_rows(zip_path: Path) -> Iterable[Tuple[str, str, str, str, str, str]]:
    """
    Yield minimal fields for populated places from a GeoNames dump.

    Returns tuples:
      (geonameid, name, country_code, lat, lon, timezone, population)
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
                try:
                    geonameid = parts[IDX_GEONAMEID]
                    name = parts[IDX_NAME]
                    cc = parts[IDX_COUNTRY_CODE]
                    lat = parts[IDX_LAT]
                    lon = parts[IDX_LON]
                    timezone = parts[IDX_TIMEZONE] or ""
                    population = parts[IDX_POPULATION] or "0"
                except Exception:
                    continue
                yield geonameid, name, cc, lat, lon, timezone, population


_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("&", " and ")
    s = _slug_re.sub("_", s)
    s = s.strip("_")
    return s or "unknown"


def make_slug(country_code: str, city_name: str) -> str:
    return f"city_{country_code.lower()}_{slugify(city_name)}"


def _norm_index(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"[^a-z0-9\\s]+", " ", s)
    s = re.sub(r"\\s+", " ", s)
    return s.strip()


def build_slug_counts(zip_path: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for _, name, cc, _, _, _, _ in _iter_geonames_rows(zip_path):
        base_slug = make_slug(cc, name)
        counts[base_slug] = counts.get(base_slug, 0) + 1
    return counts


def write_locations_csv(
    out_csv: Path,
    zip_path: Path,
    country_names: Dict[str, str],
    *,
    collect_points: bool = False,
    index_csv: Optional[Path] = None,
) -> Tuple[int, Optional[List[Tuple[float, float]]]]:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    slug_counts = build_slug_counts(zip_path)
    total = 0
    points: Optional[List[Tuple[float, float]]] = [] if collect_points else None
    index_writer = None

    if index_csv is not None:
        index_csv.parent.mkdir(parents=True, exist_ok=True)
        index_file = open(index_csv, "w", encoding="utf-8", newline="")
        index_writer = csv.DictWriter(
            index_file,
            fieldnames=[
                "geonameid",
                "slug",
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

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        for geonameid, name, cc, lat, lon, tz, pop in _iter_geonames_rows(zip_path):
            base_slug = make_slug(cc, name)
            if slug_counts.get(base_slug, 0) > 1:
                slug = f"{base_slug}_{geonameid}"
            else:
                slug = base_slug

            ctry = country_names.get(cc, cc)
            label = f"{name}, {ctry}"
            lat_f = float(lat)
            lon_f = float(lon)
            pop_i = int(float(pop) or 0)
            w.writerow(
                {
                    "slug": slug,
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
            if index_writer is not None:
                index_writer.writerow(
                    {
                        "geonameid": geonameid,
                        "slug": slug,
                        "label": label,
                        "city_name": name,
                        "country_name": ctry,
                        "country_code": cc,
                        "lat": f"{lat_f:.5f}",
                        "lon": f"{lon_f:.5f}",
                        "population": str(pop_i),
                        "norm_label": _norm_index(label),
                        "norm_city": _norm_index(name),
                    }
                )
            if points is not None:
                points.append((lat_f, lon_f))
            total += 1

    if index_file is not None:
        index_file.close()

    return total, points


def write_kdtree(points: List[Tuple[float, float]], out_dir: Path) -> None:
    try:
        import numpy as np
        from scipy.spatial import cKDTree
    except Exception as exc:
        raise RuntimeError(
            "scipy is required to build the KD-tree. "
            "Install scipy and re-run with --write-kdtree."
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    data = np.asarray(points, dtype=np.float64)
    tree = cKDTree(data)

    import pickle

    with open(out_dir / "kdtree.pkl", "wb") as f:
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
        default="cache/geonames",
        help='GeoNames cache directory (default: "cache/geonames").',
    )
    ap.add_argument(
        "--write-kdtree",
        action="store_true",
        help="Build a KD-tree for nearest-location queries.",
    )
    ap.add_argument(
        "--kdtree-dir",
        type=str,
        default="data/locations/kdtree",
        help='KD-tree output directory (default: "data/locations/kdtree").',
    )
    ap.add_argument(
        "--write-index",
        action="store_true",
        help="Write an autocomplete/resolve index CSV.",
    )
    ap.add_argument(
        "--index-dir",
        type=str,
        default="data/locations/index",
        help='Index output directory (default: "data/locations/index").',
    )
    ap.add_argument(
        "--source",
        type=str,
        default="cities500",
        choices=sorted(CITIES_SOURCES.keys()),
        help='Which GeoNames dump to use (default: "cities500"; all is largest).',
    )
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    zpath = download_cached(cities_zip_url(args.source), cache_dir)
    cpath = download_cached(COUNTRYINFO_TXT, cache_dir)

    country_names = parse_country_info(cpath)
    out_csv = Path(args.out)
    index_csv = None
    if args.write_index:
        index_csv = Path(args.index_dir) / "locations_index.csv"

    count, points = write_locations_csv(
        out_csv,
        zpath,
        country_names,
        collect_points=bool(args.write_kdtree),
        index_csv=index_csv,
    )

    if args.write_kdtree:
        if points is None:
            raise RuntimeError("KD-tree requested but no points were collected.")
        write_kdtree(points, Path(args.kdtree_dir))

    print(f"[ok] wrote {out_csv} ({count} locations)", file=sys.stderr)


if __name__ == "__main__":
    main()
