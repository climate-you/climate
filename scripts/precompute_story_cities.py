#!/usr/bin/env python
"""
Precompute multi-decade climate time series for a set of locations
using the Open-Meteo ERA5 archive API.

Each output file contains:

    - Daily series (time: daily)
        * t2m_daily_mean_c
        * t2m_daily_min_c
        * t2m_daily_max_c

    - Monthly series (time_monthly: monthly)
        * t2m_monthly_mean_c  (mean of daily mean)
        * t2m_monthly_min_c   (mean of daily min)
        * t2m_monthly_max_c   (mean of daily max)

    - Yearly series (time_yearly: yearly)
        * t2m_yearly_mean_c   (mean of daily mean)

    - Monthly climatologies for two periods (month: 1..12):
        * t2m_monthly_clim_past_mean_c   (past period)
        * t2m_monthly_clim_recent_mean_c (recent period)

Temperatures are in °C (Open-Meteo ERA5 archive already returns °C,
we just keep that and make it explicit in the variable names).
"""

import argparse
import csv
import os
import time
import sys, random
from datetime import datetime, date
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
import requests
import xarray as xr
from tqdm import tqdm

# -----------------------
# Configuration
# -----------------------

# Prefer your new repo layout if present
_DEFAULT_DATA_DIR = (
    Path("data/story_climatology")
    if Path("data/story_climatology").exists()
    else Path("story_climatology")
)

# ERA5 is conventionally used from 1979 onwards
START_YEAR = 1979

# Define window sizes instead of fixed years
PAST_CLIM_YEARS = 10  # e.g. 10 earliest years
RECENT_CLIM_YEARS = 10  # e.g. 10 most recent years


# -----------------------
# Date helper
# -----------------------


def last_full_quarter_end(today: date | None = None) -> date:
    """Return the last fully completed calendar quarter end date."""
    if today is None:
        today = date.today()

    y = today.year
    m = today.month

    if m <= 3:
        return date(y - 1, 12, 31)
    elif m <= 6:
        return date(y, 3, 31)
    elif m <= 9:
        return date(y, 6, 30)
    else:
        return date(y, 9, 30)


def parse_yyyy_mm_dd(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD, got {s!r}") from e


# -----------------------
# Locations loading
# -----------------------


def load_locations_csv(path: Path) -> list[dict]:
    """
    Load locations from locations.csv.

    Expected columns (minimum):
      - slug
      - city_name
      - country_name
      - country_code
      - lat
      - lon

    Optional:
      - label (used as name_long if present)
      - kind  (defaults to "city")
    """
    if not path.exists():
        raise FileNotFoundError(f"locations csv not found: {path}")

    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise RuntimeError(f"{path} has no header row")

        required = {"slug", "city_name", "country_name", "country_code", "lat", "lon"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise RuntimeError(f"{path} missing required columns: {sorted(missing)}")

        for row in reader:
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue

            city = (row.get("city_name") or "").strip()
            country = (row.get("country_name") or "").strip()
            cc = (row.get("country_code") or "").strip().upper()
            label = (row.get("label") or "").strip()
            kind = (row.get("kind") or "city").strip()

            try:
                lat = float(row.get("lat"))
                lon = float(row.get("lon"))
            except Exception:
                print(f"[warn] skipping {slug}: invalid lat/lon")
                continue

            loc = {
                "slug": slug,
                "name_short": city or slug,
                "name_long": label
                or (f"{city}, {country}" if city and country else slug),
                "country": country or cc,
                "country_code": cc or "",
                "lat": lat,
                "lon": lon,
                "kind": kind,
            }
            out.append(loc)

    return out


def load_favorites_file(path: Path) -> set[str]:
    """
    favorites.txt: one slug per line, allow blank lines and '#' comments.
    """
    if not path.exists():
        return set()

    slugs: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        slugs.add(line)
    return slugs


def filter_locations(
    locs: list[dict],
    *,
    only_favorites: bool,
    favorites: set[str],
    slugs: list[str] | None,
    country_codes: list[str] | None,
    limit: int | None,
) -> list[dict]:
    out = locs

    if only_favorites:
        out = [l for l in out if l["slug"] in favorites]

    if slugs:
        wanted = set(slugs)
        out = [l for l in out if l["slug"] in wanted]

    if country_codes:
        ccset = {c.upper() for c in country_codes}
        out = [l for l in out if (l.get("country_code") or "").upper() in ccset]

    # stable ordering (so reruns are predictable)
    out = sorted(out, key=lambda d: d["slug"])

    if limit is not None and limit > 0:
        out = out[:limit]

    return out


# -----------------------
# Open-Meteo helper
# -----------------------


def fetch_city_daily_history(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    *,
    min_backoff_seconds: float = 0.0,
) -> xr.Dataset:
    """Fetch daily mean/min/max 2m temperature from Open-Meteo ERA5 archive
    for a single point and a given date range, with simple retry/backoff.

    min_backoff_seconds acts as a floor for backoff sleeps (useful to align with --min-gap).
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "UTC",
    }

    url = "https://archive-api.open-meteo.com/v1/era5"
    max_retries = 5
    base_sleep = 10.0

    def _json_to_ds(j: dict) -> xr.Dataset:
        daily = j["daily"]
        times = pd.to_datetime(daily["time"])

        tmean = np.array(daily["temperature_2m_mean"], dtype="float32")
        tmax = np.array(daily["temperature_2m_max"], dtype="float32")
        tmin = np.array(daily["temperature_2m_min"], dtype="float32")

        return xr.Dataset(
            data_vars=dict(
                t2m_daily_mean_c=(["time"], tmean),
                t2m_daily_max_c=(["time"], tmax),
                t2m_daily_min_c=(["time"], tmin),
            ),
            coords=dict(time=times),
        )

    def _request_json(s: date, e: date) -> dict:
        consecutive_429 = 0
        p = dict(params)
        p["start_date"] = s.isoformat()
        p["end_date"] = e.isoformat()

        base_sleep = 10.0
        backoff_floor = max(
            base_sleep, float(min_backoff_seconds or 0.0)
        )  # used only for 429

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                r = requests.get(url, params=p, timeout=60)
                if r.status_code == 429:
                    consecutive_429 += 1
                    last_err = requests.HTTPError("429 Too Many Requests", response=r)
                    wait = backoff_floor * (2**attempt)
                    jitter = random.uniform(0.0, min(0.4, 0.10 * backoff_floor))
                    time.sleep(wait + jitter)
                    if consecutive_429 >= 3:
                        # global cooldown to let the bucket refill
                        time.sleep(120)  # 2 minutes
                    continue

                r.raise_for_status()

                body = r.text or ""
                # Open-Meteo sometimes returns: "Unexpected error while streaming data: timeoutReached"
                if (
                    "timeoutReached" in body
                    or "Unexpected error while streaming data" in body
                ):
                    raise requests.RequestException(
                        f"Open-Meteo backend timeout: {body[:200]!r}"
                    )

                try:
                    return r.json()
                except ValueError as ve:
                    raise requests.RequestException(
                        f"JSON decode failed: status={r.status_code}, "
                        f"content_type={r.headers.get('Content-Type')!r}, "
                        f"body_preview={body[:200]!r}"
                    ) from ve

            except requests.RequestException as ex:
                last_err = ex
                is_429 = (
                    (r.status_code == 429) if "r" in locals() else False
                )  # or set a flag explicitly
                floor = (
                    backoff_floor if is_429 else base_sleep
                )  # don't use --min-gap floor for non-429
                wait = floor * (2**attempt)
                jitter = random.uniform(0.0, min(0.4, 0.10 * floor))
                time.sleep(wait + jitter)

        raise last_err if last_err is not None else RuntimeError("request failed")

    # IMPORTANT: backoff starts at least at min_backoff_seconds (e.g. --min-gap)
    backoff_floor = max(base_sleep, float(min_backoff_seconds or 0.0))

    last_err: Exception | None = None

    try:
        j = _request_json(start_date, end_date)
        return _json_to_ds(j)
    except Exception as e:
        msg = str(e)
        if ("timeoutReached" not in msg) and ("streaming data" not in msg):
            raise

        print(
            f"  [warn] Open-Meteo timed out for full range {start_date}..{end_date}; "
            f"falling back to chunked fetch..."
        )

        # 5-year chunks are a good compromise: fewer timeouts, not too many requests.
        chunk_years = 5

        ds_parts: list[xr.Dataset] = []
        cur = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)

        while cur <= end_ts:
            # inclusive chunk end
            nxt = (cur + pd.DateOffset(years=chunk_years)) - pd.Timedelta(days=1)
            if nxt > end_ts:
                nxt = end_ts

            s = cur.date()
            ee = nxt.date()

            print(f"  [chunk] requesting {s}..{ee}")

            j_part = _request_json(s, ee)
            ds_parts.append(_json_to_ds(j_part))

            cur = nxt + pd.Timedelta(days=1)

        ds = xr.concat(ds_parts, dim="time")
        ds = ds.sortby("time")
        # Drop any duplicates at boundaries (defensive)
        _, idx = np.unique(ds["time"].values, return_index=True)
        ds = ds.isel(time=idx)

        return ds


# -----------------------
# Derived series & climatologies
# -----------------------


def derive_monthly_and_yearly(ds_daily: xr.Dataset):
    """From daily dataset, derive monthly and yearly mean series."""
    monthly_mean = ds_daily["t2m_daily_mean_c"].resample(time="MS").mean()
    monthly_min = ds_daily["t2m_daily_min_c"].resample(time="MS").mean()
    monthly_max = ds_daily["t2m_daily_max_c"].resample(time="MS").mean()

    monthly_mean = monthly_mean.rename(time="time_monthly")
    monthly_min = monthly_min.rename(time="time_monthly")
    monthly_max = monthly_max.rename(time="time_monthly")

    yearly_mean = ds_daily["t2m_daily_mean_c"].resample(time="YS").mean()
    yearly_mean = yearly_mean.rename(time="time_yearly")

    return monthly_mean, monthly_min, monthly_max, yearly_mean


def derive_monthly_climatologies(
    ds_daily: xr.Dataset,
) -> tuple[xr.DataArray | None, xr.DataArray | None]:
    """Compute past vs recent monthly climatology for daily mean temperature."""
    da = ds_daily["t2m_daily_mean_c"]
    years = da["time"].dt.year

    min_year = int(years.min().item())
    max_year = int(years.max().item())
    n_years = max_year - min_year + 1

    min_needed = PAST_CLIM_YEARS + RECENT_CLIM_YEARS
    if n_years < min_needed:
        print(
            f"  [warn] record too short for climatologies: {n_years} years, need at least {min_needed}"
        )
        return None, None

    past_start = min_year
    past_end = min_year + PAST_CLIM_YEARS - 1

    recent_end = max_year
    recent_start = max_year - RECENT_CLIM_YEARS + 1

    print(
        f"  [info] climatology windows: past={past_start}–{past_end}, recent={recent_start}–{recent_end}"
    )

    # Monthly means from daily – 'ME' to avoid xarray warning
    da_mon = da.resample(time="ME").mean()

    mask_past = (da_mon["time"].dt.year >= past_start) & (
        da_mon["time"].dt.year <= past_end
    )
    mon_past = da_mon.where(mask_past, drop=True)

    if mon_past.time.size == 0:
        past_clim = None
    else:
        past_clim = mon_past.groupby("time.month").mean("time")
        past_clim = past_clim.rename(month="month").assign_coords(
            month=np.arange(1, 13)
        )

    mask_recent = (da_mon["time"].dt.year >= recent_start) & (
        da_mon["time"].dt.year <= recent_end
    )
    mon_recent = da_mon.where(mask_recent, drop=True)

    if mon_recent.time.size == 0:
        recent_clim = None
    else:
        recent_clim = mon_recent.groupby("time.month").mean("time")
        recent_clim = recent_clim.rename(month="month").assign_coords(
            month=np.arange(1, 13)
        )

    return past_clim, recent_clim


# -----------------------
# Check existing files
# -----------------------


def is_existing_file_up_to_date(path: Path, slug: str, target_end: date) -> bool:
    """Return True if an existing NetCDF file is up-to-date and complete."""
    if not path.exists():
        return False

    try:
        ds = xr.open_dataset(path)
    except Exception as e:
        print(f"  [info] existing file {path} could not be opened: {e}, will recompute")
        return False

    try:
        attrs = ds.attrs

        if attrs.get("location_slug") != slug:
            print(
                f"  [info] {path} slug mismatch (found {attrs.get('location_slug')}, expected {slug})"
            )
            return False

        start_year_attr = int(attrs.get("start_year", -1))
        if start_year_attr != START_YEAR:
            print(
                f"  [info] {path} start_year mismatch (found {start_year_attr}, expected {START_YEAR})"
            )
            return False

        required_vars = {
            "t2m_daily_mean_c",
            "t2m_daily_min_c",
            "t2m_daily_max_c",
            "t2m_monthly_mean_c",
            "t2m_monthly_min_c",
            "t2m_monthly_max_c",
            "t2m_yearly_mean_c",
        }
        missing = [v for v in required_vars if v not in ds.variables]
        if missing:
            print(f"  [info] {path} missing required variables: {missing}")
            return False

        data_end_str = attrs.get("data_end_date")
        if not data_end_str:
            print(f"  [info] {path} missing data_end_date attr")
            return False

        try:
            existing_end = datetime.fromisoformat(data_end_str).date()
        except Exception:
            print(f"  [info] {path} has invalid data_end_date={data_end_str!r}")
            return False

        if existing_end >= target_end:
            return True

        print(
            f"  [info] {path} only covers up to {existing_end}, need {target_end}, will recompute"
        )
        return False

    finally:
        ds.close()


# -----------------------
# Precompute per location
# -----------------------


def precompute_for_location(
    loc: dict,
    target_end: date,
    data_dir: Path,
    *,
    skip_check: bool = True,
    min_gap: float = 0.0,
) -> tuple[str, str]:
    """
    Returns (status, detail) where status is one of:
      - "skip"      (already up-to-date)
      - "write"     (computed and wrote a file)
      - "recompute" (overwrote an older file)
    """
    slug = loc["slug"]
    lat = float(loc["lat"])
    lon = float(loc["lon"])

    out_path = data_dir / f"clim_{slug}.nc"
    status = "write"

    if skip_check and out_path.exists():
        if is_existing_file_up_to_date(out_path, slug, target_end):
            return "skip", "up-to-date"
        status = "recompute"
    elif out_path.exists():
        status = "recompute"

    start_date = date(START_YEAR, 1, 1)
    end_date = target_end

    ds_daily = fetch_city_daily_history(
        lat, lon, start_date, end_date, min_backoff_seconds=min_gap
    )

    m_mean, m_min, m_max, y_mean = derive_monthly_and_yearly(ds_daily)
    past_clim, recent_clim = derive_monthly_climatologies(ds_daily)

    ds_out = xr.Dataset()
    ds_out["t2m_daily_mean_c"] = ds_daily["t2m_daily_mean_c"]
    ds_out["t2m_daily_min_c"] = ds_daily["t2m_daily_min_c"]
    ds_out["t2m_daily_max_c"] = ds_daily["t2m_daily_max_c"]

    ds_out["t2m_monthly_mean_c"] = m_mean
    ds_out["t2m_monthly_min_c"] = m_min
    ds_out["t2m_monthly_max_c"] = m_max

    ds_out["t2m_yearly_mean_c"] = y_mean

    if past_clim is not None:
        ds_out["t2m_monthly_clim_past_mean_c"] = past_clim
    if recent_clim is not None:
        ds_out["t2m_monthly_clim_recent_mean_c"] = recent_clim

    ds_out.attrs.update(
        location_slug=slug,
        name_short=loc.get("name_short", slug),
        name_long=loc.get("name_long", slug),
        country=loc.get("country", ""),
        country_code=loc.get("country_code", ""),
        latitude=lat,
        longitude=lon,
        kind=loc.get("kind", "city"),
        source="Open-Meteo ERA5 archive (daily mean/min/max 2m_temperature)",
        created_utc=datetime.utcnow().isoformat() + "Z",
        start_year=START_YEAR,
        data_end_date=end_date.isoformat(),
    )

    tmp_path = out_path.with_suffix(".nc.tmp")
    ds_out.to_netcdf(tmp_path, mode="w")
    os.replace(tmp_path, out_path)

    return status, f"wrote {out_path.name}"


# -----------------------
# CLI
# -----------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Precompute story climatology NetCDFs from locations.csv"
    )
    p.add_argument(
        "--locations-csv", type=Path, default=Path("locations/locations.csv")
    )
    p.add_argument(
        "--favorites-file", type=Path, default=Path("locations/favorites.txt")
    )

    p.add_argument(
        "--only-favorites",
        action="store_true",
        help="Only precompute slugs listed in favorites.txt",
    )
    p.add_argument(
        "--slug",
        action="append",
        default=None,
        help="Precompute only this slug (repeatable)",
    )
    p.add_argument(
        "--country",
        action="append",
        default=None,
        help="Filter by country code (repeatable), e.g. --country US",
    )

    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of locations (after filtering)",
    )
    p.add_argument("--out-dir", type=Path, default=_DEFAULT_DATA_DIR)

    p.add_argument(
        "--target-end",
        type=parse_yyyy_mm_dd,
        default=None,
        help="Override target end date (YYYY-MM-DD)",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Print selected slugs and exit"
    )

    p.add_argument(
        "--min-gap",
        type=float,
        default=2.0,
        help="Minimum seconds to wait between cities (helps avoid 429). Default: %(default)s",
    )
    p.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable tqdm progress bar (useful for CI logs)",
    )

    return p


def main():
    args = build_arg_parser().parse_args()

    data_dir: Path = args.out_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    target_end = args.target_end or last_full_quarter_end()

    print(f"Locations CSV: {args.locations_csv}")
    print(f"Output dir:    {data_dir.resolve()}")
    print(
        f"Target end:    {target_end.isoformat()}  (last full quarter unless overridden)"
    )
    print()

    locs = load_locations_csv(args.locations_csv)
    favorites = load_favorites_file(args.favorites_file)

    selected = filter_locations(
        locs,
        only_favorites=args.only_favorites,
        favorites=favorites,
        slugs=args.slug,
        country_codes=args.country,
        limit=args.limit,
    )

    if not selected:
        print("[warn] no locations selected (check filters / favorites).")
        return

    if args.dry_run:
        print(f"[dry-run] {len(selected)} locations selected:")
        for l in selected:
            print(f"  - {l['slug']}  ({l['name_long']})")
        return

    total = len(selected)
    print(f"Will precompute {total} locations.\n")

    start_t = time.time()

    use_tqdm = (
        (not args.no_progress) and hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    )
    if use_tqdm:
        pbar = tqdm(
            selected,
            total=len(selected),
            desc="precompute",
            dynamic_ncols=True,
            smoothing=0.05,
        )
        iter_locs = pbar
    else:
        pbar = None
        iter_locs = selected

    last_done = None

    def _log(msg: str) -> None:
        # Keep progress output stable: use tqdm.write when available, else print.
        if pbar is not None:
            try:
                pbar.write(msg)
            except Exception:
                print(msg)
        else:
            print(msg)

    counts = Counter()
    for loc in iter_locs:
        slug = loc.get("slug", "?")
        out_path = data_dir / f"clim_{slug}.nc"

        # Fast path: skip WITHOUT waiting if already up to date
        try:
            if out_path.exists() and is_existing_file_up_to_date(
                out_path, slug, target_end
            ):
                counts["skip"] += 1
                if pbar is not None:
                    pbar.set_postfix(
                        {
                            "slug": slug,
                            "skip": counts["skip"],
                            "write": counts["write"],
                            "recompute": counts["recompute"],
                            "error": counts["error"],
                        }
                    )
                continue
        except Exception as e:
            # If the up-to-date check itself fails, fall back to recompute path
            _log(f"[warn] up-to-date check failed for {slug}: {e} (will recompute)")

        if last_done is not None:
            # Only rate-limit when we're ACTUALLY about to process a slug
            now = time.monotonic()
            wait = args.min_gap - (now - last_done)
            if wait > 0:
                time.sleep(
                    wait + random.uniform(0, 0.4)
                )  # jitter helps avoid “thundering herd”

        if pbar is not None:
            pbar.set_postfix(
                {
                    "slug": slug,
                    "skip": counts["skip"],
                    "write": counts["write"],
                    "recompute": counts["recompute"],
                    "error": counts["error"],
                }
            )
        try:
            status, detail = precompute_for_location(
                loc, target_end, data_dir, skip_check=False, min_gap=args.min_gap
            )
            counts[status] += 1
            if pbar is not None:
                pbar.set_postfix(
                    {
                        "slug": slug,
                        "skip": counts["skip"],
                        "write": counts["write"],
                        "recompute": counts["recompute"],
                        "error": counts["error"],
                    }
                )
        except Exception as e:
            counts["error"] += 1
            if pbar is not None:
                pbar.set_postfix(
                    {
                        "slug": slug,
                        "skip": counts["skip"],
                        "write": counts["write"],
                        "recompute": counts["recompute"],
                        "error": counts["error"],
                    }
                )
            _log(f"[error] {slug} failed: {e}")
        finally:
            # Update only after a real attempt (so skips don't “consume” the gap)
            last_done = time.monotonic()

    if pbar is not None:
        pbar.close()

    dt = time.time() - start_t
    print(f"\nDone. Total wall time: {dt:.1f}s")


if __name__ == "__main__":
    main()
