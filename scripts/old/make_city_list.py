#!/usr/bin/env python3
"""
Generate locations/locations.csv from GeoNames.

Outputs a CSV compatible with the rest of the pipeline (slug, names, lat/lon, etc.).
Default selection policy:
  - top N cities worldwide by population
  - top K cities per country by population
  - all capitals (PPLC)
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import unicodedata
import requests

GEONAMES_DUMP_BASE = "https://download.geonames.org/export/dump"
COUNTRYINFO_TXT = f"{GEONAMES_DUMP_BASE}/countryInfo.txt"

# Allow selecting different GeoNames "citiesXXXX" dumps.
CITIES_SOURCES: Dict[str, str] = {
    "cities500": f"{GEONAMES_DUMP_BASE}/cities500.zip",
    "cities1000": f"{GEONAMES_DUMP_BASE}/cities1000.zip",
    "cities5000": f"{GEONAMES_DUMP_BASE}/cities5000.zip",
    "cities15000": f"{GEONAMES_DUMP_BASE}/cities15000.zip",
}


def cities_zip_url(source: str) -> str:
    if source not in CITIES_SOURCES:
        raise ValueError(
            f"Unknown source {source!r}. Choose from: {', '.join(sorted(CITIES_SOURCES))}"
        )
    return CITIES_SOURCES[source]


# GeoNames geoname table columns (as per readme.txt)
# geonameid, name, asciiname, alternatenames, latitude, longitude,
# feature class, feature code, country code, cc2, admin1, admin2, admin3, admin4,
# population, elevation, dem, timezone, modification date
GEONAMES_COLS = [
    "geonameid",
    "name",
    "asciiname",
    "alternatenames",
    "latitude",
    "longitude",
    "feature_class",
    "feature_code",
    "country_code",
    "cc2",
    "admin1",
    "admin2",
    "admin3",
    "admin4",
    "population",
    "elevation",
    "dem",
    "timezone",
    "modification_date",
]

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


@dataclass(frozen=True)
class CityRow:
    geonameid: int
    name: str
    country_code: str
    lat: float
    lon: float
    timezone: str
    population: int
    feature_class: str
    feature_code: str


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


def iter_cities_from_cities_zip(zip_path: Path) -> Iterable[CityRow]:
    """
    Reads the single citiesXXXX.txt file inside a GeoNames citiesXXXX.zip.
    Works for cities500/cities1000/cities5000/cities15000.
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        txt_names = [n for n in z.namelist() if n.endswith(".txt")]
        if not txt_names:
            raise RuntimeError(f"No .txt file found inside {zip_path}")
        inner = txt_names[0]
        with z.open(inner, "r") as bf:
            tf = io.TextIOWrapper(bf, encoding="utf-8")
            for line in tf:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < len(GEONAMES_COLS):
                    continue
                row = dict(zip(GEONAMES_COLS, parts))
                try:
                    feature_class = row["feature_class"]
                    feature_code = row["feature_code"]
                    # These dumps should already be populated places, but keep it safe.
                    if feature_class != "P":
                        continue

                    geonameid = int(row["geonameid"])
                    name = row["name"]
                    cc = row["country_code"]
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                    tz = row["timezone"] or ""
                    pop = int(row["population"] or 0)
                except Exception:
                    continue

                yield CityRow(
                    geonameid=geonameid,
                    name=name,
                    country_code=cc,
                    lat=lat,
                    lon=lon,
                    timezone=tz,
                    population=pop,
                    feature_class=feature_class,
                    feature_code=feature_code,
                )


_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("&", " and ")
    s = _slug_re.sub("_", s)
    s = s.strip("_")
    return s or "unknown"


def make_slug(country_code: str, city_name: str) -> str:
    return f"city_{country_code.lower()}_{slugify(city_name)}"


def select_cities(
    rows: List[CityRow],
    top_world: int,
    top_per_country: int,
    include_capitals: bool,
) -> List[CityRow]:
    # Capitals
    capitals: List[CityRow] = []
    if include_capitals:
        capitals = [r for r in rows if r.feature_code == "PPLC"]

    # Top world
    rows_by_pop = sorted(rows, key=lambda r: r.population, reverse=True)
    top_world_rows = rows_by_pop[:top_world]

    # Top per country
    by_country: Dict[str, List[CityRow]] = {}
    for r in rows:
        by_country.setdefault(r.country_code, []).append(r)
    top_country_rows: List[CityRow] = []
    for cc, rr in by_country.items():
        rr_sorted = sorted(rr, key=lambda r: r.population, reverse=True)
        top_country_rows.extend(rr_sorted[:top_per_country])

    # Union by geonameid
    picked: Dict[int, CityRow] = {}
    for r in capitals + top_world_rows + top_country_rows:
        picked[r.geonameid] = r

    # Sort for stable output (country then population desc then name)
    out = sorted(
        picked.values(),
        key=lambda r: (r.country_code, -r.population, r.name.lower(), r.geonameid),
    )
    return out


def _norm(s: str) -> str:
    """
    Normalize for fuzzy-ish matching: lowercase, strip accents, collapse whitespace/punct.
    """
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s\-]", "", s)
    return s.strip()


def _parse_city_country(spec: str) -> Tuple[str, str]:
    """
    Accept:
      - "City, Country"
      - "City | Country"
      - "City\tCountry"
    If multiple commas exist, last comma-separated token is treated as the country.
    """
    s = (spec or "").strip()
    if not s:
        return "", ""
    if "|" in s:
        a, b = s.split("|", 1)
        return a.strip(), b.strip()
    if "\t" in s:
        a, b = s.split("\t", 1)
        return a.strip(), b.strip()

    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) >= 2:
        country = parts[-1]
        city = ",".join(parts[:-1]).strip()
        return city, country
    return s, ""


def load_extras(
    extra_args: List[str], extra_file: Optional[Path]
) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for spec in extra_args or []:
        c, k = _parse_city_country(spec)
        if c:
            out.append((c, k))

    if extra_file is not None:
        if not extra_file.exists():
            raise FileNotFoundError(f"--extra-file not found: {extra_file}")
        with open(extra_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                c, k = _parse_city_country(line)
                if c:
                    out.append((c, k))
    return out


def build_country_name_to_code(country_names: Dict[str, str]) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for cc, name in country_names.items():
        m[_norm(name)] = cc

    # A couple of common aliases (optional, but helps)
    m.setdefault(_norm("United States"), "US")
    m.setdefault(_norm("United States of America"), "US")
    m.setdefault(_norm("USA"), "US")
    m.setdefault(_norm("UK"), "GB")
    m.setdefault(_norm("United Kingdom"), "GB")
    return m


def resolve_country_code(country_token: str, name_to_code: Dict[str, str]) -> str:
    tok = (country_token or "").strip()
    if not tok:
        return ""
    if len(tok) == 2 and tok.isalpha():
        return tok.upper()
    return name_to_code.get(_norm(tok), "")


def resolve_extra_cities(
    rows: List[CityRow],
    extras: List[Tuple[str, str]],
    country_names: Dict[str, str],
) -> List[CityRow]:
    """
    Try to find each (city, country) in the already-loaded `rows`.
    If multiple matches exist, take the highest-population one.
    """
    if not extras:
        return []

    name_to_code = build_country_name_to_code(country_names)

    # Build an index for quick lookups: (cc, norm(city)) -> best CityRow
    index: Dict[Tuple[str, str], CityRow] = {}
    for r in rows:
        key = (r.country_code.upper(), _norm(r.name))
        best = index.get(key)
        if best is None or r.population > best.population:
            index[key] = r

    found: List[CityRow] = []
    for city_name, country_token in extras:
        cc = resolve_country_code(country_token, name_to_code)

        if cc:
            key = (cc, _norm(city_name))
            hit = index.get(key)
            if hit is not None:
                found.append(hit)
                continue

            # If not found with strict cc+name, try "name-only within country" ignoring accents/punct
            candidates = [
                r
                for r in rows
                if r.country_code.upper() == cc and _norm(r.name) == _norm(city_name)
            ]
            if candidates:
                found.append(max(candidates, key=lambda r: r.population))
                continue

            print(
                f"[warn] extra not found in selected source: {city_name!r}, {country_token!r} "
                f"(country code={cc}). Try a broader --source (e.g. cities500).",
                file=sys.stderr,
            )
        else:
            # No country resolved: do a global name match and pick biggest
            candidates = [r for r in rows if _norm(r.name) == _norm(city_name)]
            if candidates:
                found.append(max(candidates, key=lambda r: r.population))
            else:
                print(
                    f"[warn] extra not found (country not resolved and no global match): "
                    f"{city_name!r}, {country_token!r}.",
                    file=sys.stderr,
                )

    # De-dupe by geonameid
    uniq: Dict[int, CityRow] = {c.geonameid: c for c in found}
    return list(uniq.values())


def merge_cities(base: List[CityRow], extra: List[CityRow]) -> List[CityRow]:
    picked: Dict[int, CityRow] = {c.geonameid: c for c in base}
    for c in extra:
        picked[c.geonameid] = c
    return sorted(
        picked.values(),
        key=lambda r: (r.country_code, -r.population, r.name.lower(), r.geonameid),
    )


def write_locations_csv(
    out_csv: Path,
    cities: List[CityRow],
    country_names: Dict[str, str],
) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    # Ensure unique slugs (rare collisions within the same country)
    slug_counts: Dict[str, int] = {}
    records: List[Dict[str, str]] = []
    for c in cities:
        cc = c.country_code
        ctry = country_names.get(cc, cc)
        base_slug = make_slug(cc, c.name)
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        if slug_counts[base_slug] > 1:
            slug = f"{base_slug}_{c.geonameid}"
        else:
            slug = base_slug

        label = f"{c.name}, {ctry}"
        records.append(
            {
                "slug": slug,
                "city_name": c.name,
                "country_name": ctry,
                "country_code": cc,
                "lat": f"{c.lat:.5f}",
                "lon": f"{c.lon:.5f}",
                "timezone": c.timezone,
                "population": str(int(c.population)),
                "geonameid": str(int(c.geonameid)),
                "kind": "city",
                "label": label,
            }
        )

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(records)

    print(f"[ok] wrote {out_csv} ({len(records)} locations)", file=sys.stderr)


def write_favorites(
    favorites_path: Path,
    cities: List[CityRow],
    country_names: Dict[str, str],
    n: int,
) -> None:
    """
    Simple default: take top-n by population from *the selected set*.
    You can later override manually; this just bootstraps favorites.txt.
    """
    # Map geonameid -> slug (using same collision logic as CSV writer)
    slug_counts: Dict[str, int] = {}
    geoname_to_slug: Dict[int, str] = {}
    for c in cities:
        base_slug = make_slug(c.country_code, c.name)
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        if slug_counts[base_slug] > 1:
            slug = f"{base_slug}_{c.geonameid}"
        else:
            slug = base_slug
        geoname_to_slug[c.geonameid] = slug

    top = sorted(cities, key=lambda r: r.population, reverse=True)[:n]
    favorites_path.parent.mkdir(parents=True, exist_ok=True)
    with open(favorites_path, "w", encoding="utf-8") as f:
        for c in top:
            f.write(geoname_to_slug[c.geonameid] + "\n")

    print(f"[ok] wrote {favorites_path} ({len(top)} favorites)", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default="locations/locations.csv")
    ap.add_argument("--favorites", type=str, default="locations/favorites.txt")
    ap.add_argument("--cache-dir", type=str, default="cache/geonames")
    ap.add_argument("--top-world", type=int, default=200)
    ap.add_argument("--top-per-country", type=int, default=3)
    ap.add_argument("--write-favorites", action="store_true")
    ap.add_argument("--no-capitals", action="store_true")
    ap.add_argument("--favorites-n", type=int, default=10)
    ap.add_argument(
        "--source",
        type=str,
        default="cities15000",
        choices=sorted(CITIES_SOURCES.keys()),
        help="Which GeoNames cities dump to use (cities500 is broadest; cities15000 is smallest).",
    )
    ap.add_argument(
        "--extra-file",
        type=str,
        default=None,
        help="Optional path to a text file listing extra locations to force-include (one per line: 'City, Country').",
    )
    ap.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Force-include an extra location (repeatable). Format: 'City, Country' or 'City | Country'.",
    )
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    zpath = download_cached(cities_zip_url(args.source), cache_dir)
    cpath = download_cached(COUNTRYINFO_TXT, cache_dir)

    country_names = parse_country_info(cpath)
    rows = list(iter_cities_from_cities_zip(zpath))

    picked = select_cities(
        rows,
        top_world=args.top_world,
        top_per_country=args.top_per_country,
        include_capitals=(not args.no_capitals),
    )

    extras = load_extras(args.extra, Path(args.extra_file) if args.extra_file else None)
    if extras:
        extra_rows = resolve_extra_cities(rows, extras, country_names)
        picked = merge_cities(picked, extra_rows)

    out_csv = Path(args.out)
    write_locations_csv(out_csv, picked, country_names)

    if args.write_favorites:
        fav_path = Path(args.favorites)
        write_favorites(fav_path, picked, country_names, n=args.favorites_n)


if __name__ == "__main__":
    main()
