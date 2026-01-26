# climate/datasets/sources/ecmwf_bulletin.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, List

import requests


BULLETIN_ROOT = "https://sites.ecmwf.int/data/c3sci/bulletin/"
_RE_HREF = re.compile(r'href="([^"]+)"')
_RE_YYYYMM_DIR = re.compile(r'href="(\d{6})/"')


# Default matchers used by scripts (can be overridden by caller)
DEFAULT_GLOBAL_SERIES_CSV_PATTERNS: list[re.Pattern[str]] = [
    # Prefer the "Fig2 ... monthly global surface temperature anomaly preindustrial" CSV
    re.compile(
        r"Fig2_.*monthly_global_surface_temperature_anomaly_preindustrial.*\.csv$", re.I
    ),
    re.compile(r"Monthly global temperature anomalies since 1940\.csv$", re.I),
    re.compile(r"timeseries_era5_monthly_2t_global.*\.csv$", re.I),
]

PAT_FIG3_NC = re.compile(r"Fig3_.*map_surface_temperature_anomaly_global.*\.nc$", re.I)
PAT_FIG3_PNG = re.compile(
    r"Fig3_.*map_surface_temperature_anomaly_global.*\.png$", re.I
)


@dataclass(frozen=True)
class BulletinListing:
    """Represents a listing for a bulletin subdirectory (e.g. press_release/)."""

    url: str
    files: list[str]


def list_months(timeout_s: int = 60) -> list[str]:
    html = http_get_text(BULLETIN_ROOT, timeout_s=timeout_s)
    months = sorted({m.group(1) for m in _RE_YYYYMM_DIR.finditer(html)})
    if not months:
        raise RuntimeError("No YYYYMM months found")
    return months


def find_latest_fig3_global_anomaly_map(
    timeout_s: int = 60,
) -> tuple[str, str, str | None, str | None]:
    """
    Returns (yyyymm, section_url, nc_filename_or_None, png_filename_or_None)
    Searches months newest -> oldest across press_release and press-release.
    """
    months = list_months(timeout_s=timeout_s)
    for yyyymm in reversed(months):
        sections = list_month_sections(yyyymm, timeout_s=timeout_s)
        for section in ("press_release", "press-release"):
            if section not in sections:
                continue
            section_url, files = list_section_files(
                yyyymm, section, timeout_s=timeout_s
            )
            nc = next((f for f in files if PAT_FIG3_NC.search(f)), None)
            png = next((f for f in files if PAT_FIG3_PNG.search(f)), None)
            if nc or png:
                return yyyymm, section_url, nc, png

    raise RuntimeError(
        "Could not find Fig3 global anomaly map files in any bulletin month"
    )


def http_get_text(url: str, timeout_s: int = 60) -> str:
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    return r.text


def latest_bulletin_dir(timeout_s: int = 60) -> str:
    html = http_get_text(BULLETIN_ROOT, timeout_s=timeout_s)
    dirs = sorted({m.group(1) for m in _RE_YYYYMM_DIR.finditer(html)})
    if not dirs:
        raise RuntimeError(f"Could not find any YYYYMM directories at {BULLETIN_ROOT}")
    return dirs[-1]


def press_release_section(yyyymm: str, timeout_s: int = 60) -> str:
    """Return the correct press release section name for this month."""
    sections = list_month_sections(yyyymm, timeout_s=timeout_s)
    if "press_release" in sections:
        return "press_release"
    if "press-release" in sections:
        return "press-release"
    # Some older layouts might not have a press release folder at all
    raise RuntimeError(
        f"No press release folder found for {yyyymm}. Sections: {sections}"
    )


def press_release_url(yyyymm: str, timeout_s: int = 60) -> str:
    section = press_release_section(yyyymm, timeout_s=timeout_s)
    return f"{BULLETIN_ROOT}{yyyymm}/{section}/"


def list_press_release(yyyymm: str, timeout_s: int = 60) -> BulletinListing:
    url = press_release_url(yyyymm, timeout_s=timeout_s)
    html = http_get_text(url, timeout_s=timeout_s)
    hrefs = [m.group(1) for m in _RE_HREF.finditer(html)]
    files = [h for h in hrefs if h and not h.endswith("/") and h != "../"]
    return BulletinListing(url=url, files=files)


def pick_first_matching(
    files: Iterable[str], patterns: Iterable[re.Pattern[str]]
) -> Optional[str]:
    """Return the first filename matching any of patterns, in priority order."""
    files = list(files)
    for pat in patterns:
        for f in files:
            if pat.search(f):
                return f
    return None


def list_month_sections(yyyymm: str, timeout_s: int = 60) -> list[str]:
    url = f"{BULLETIN_ROOT}{yyyymm}/"
    html = http_get_text(url, timeout_s=timeout_s)
    hrefs = [m.group(1) for m in _RE_HREF.finditer(html)]
    dirs = [h[:-1] for h in hrefs if h.endswith("/") and h not in ("../",)]
    return sorted(set(dirs))


def list_section_files(
    yyyymm: str, section: str, timeout_s: int = 60
) -> tuple[str, list[str]]:
    url = f"{BULLETIN_ROOT}{yyyymm}/{section}/"
    html = http_get_text(url, timeout_s=timeout_s)
    hrefs = [m.group(1) for m in _RE_HREF.finditer(html)]
    files = [h for h in hrefs if h and not h.endswith("/") and h != "../"]
    return url, files


def find_best_global_series_csv(
    yyyymm: str,
    preferred_patterns: list[re.Pattern[str]],
    timeout_s: int = 60,
) -> tuple[str, str, str]:
    """
    Returns (section_url, filename, section_name).
    Tries press-release variants, then temperature/.
    """
    # Order matters
    candidate_sections = ["press_release", "press-release", "temperature"]

    for section in candidate_sections:
        # Skip sections that don't exist for this month
        if section not in list_month_sections(yyyymm, timeout_s=timeout_s):
            continue
        section_url, files = list_section_files(yyyymm, section, timeout_s=timeout_s)
        csvs = [f for f in files if f.lower().endswith(".csv")]
        if not csvs:
            continue

        # preferred match
        for pat in preferred_patterns:
            for f in csvs:
                if pat.search(f):
                    return section_url, f, section

        # fallback: first csv
        return section_url, csvs[0], section

    raise RuntimeError(
        f"No CSV files found for {yyyymm} in press-release/press_release/temperature/"
    )


def find_best_press_release_csv(
    yyyymm: str,
    preferred_patterns: Optional[list[re.Pattern[str]]] = None,
    timeout_s: int = 60,
) -> Tuple[str, str]:
    """
    Returns (press_release_url, filename) of best-matching CSV.
    Falls back to first CSV found.
    """
    preferred_patterns = preferred_patterns or DEFAULT_GLOBAL_SERIES_CSV_PATTERNS
    listing = list_press_release(yyyymm, timeout_s=timeout_s)

    csvs = [f for f in listing.files if f.lower().endswith(".csv")]
    if not csvs:
        raise RuntimeError(f"No CSV files found at {listing.url}")

    best = pick_first_matching(csvs, preferred_patterns)
    if best is None:
        best = csvs[0]
    return listing.url, best


def find_fig3_global_anomaly_map_files(
    yyyymm: str,
    timeout_s: int = 60,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (press_release_url, nc_filename_or_None, png_filename_or_None)."""
    listing = list_press_release(yyyymm, timeout_s=timeout_s)
    nc = next((f for f in listing.files if PAT_FIG3_NC.search(f)), None)
    png = next((f for f in listing.files if PAT_FIG3_PNG.search(f)), None)
    return listing.url, nc, png
