#!/usr/bin/env python3
"""Generate data/world/global_series.csv (global mean temperature anomalies).

Source: Copernicus/ECMWF C3S climate bulletin (ERA5).
This script auto-detects the latest bulletin directory, downloads the monthly
global surface air temperature anomaly time series CSV, and writes a simplified
CSV for the app.

Output columns (best-effort):
- date (YYYY-MM-01)
- year, month
- t2m (monthly absolute temperature, degC)
- clim_91_20 (1991–2020 climatology, degC)
- ano_91_20 (anomaly vs 1991–2020, degC)
- offset_pi (offset between 1850–1900 and 1991–2020, degC)
- ano_pi (anomaly vs 1850–1900, degC)

The upstream CSV includes comment lines starting with '#'.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Optional
import requests

import pandas as pd

from climate.datasets.sources.ecmwf_bulletin import (
    latest_bulletin_dir,
    find_best_global_series_csv,
)

PREFERRED_FILENAMES = [
    re.compile(
        r"Fig2_.*monthly_global_surface_temperature_anomaly_preindustrial.*\.csv$", re.I
    ),
    re.compile(
        r"Fig2b_.*ref1850-1900.*global_allmonths.*_DATA\.csv$", re.I
    ),  # <- add this
    re.compile(r"Monthly global temperature anomalies since 1940\.csv$", re.I),
    re.compile(r"timeseries_era5_monthly_2t_global.*\.csv$", re.I),
]


def _read_upstream_csv(url: str) -> pd.DataFrame:
    # keep this as-is (no caching in this script yet)
    text = requests.get(url, timeout=120).text
    df = pd.read_csv(pd.io.common.StringIO(text), comment="#")
    df.columns = [c.strip() for c in df.columns]
    return df


def _coerce_year_month(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "year" in df.columns and "month" in df.columns:
        y = df["year"]
        m = df["month"]

        # If either column looks like a date string (contains '-') parse as datetime
        y_str = y.astype(str)
        m_str = m.astype(str)

        if y_str.str.contains("-", regex=False).any():
            dt = pd.to_datetime(y_str, errors="coerce")
            if dt.notna().any():
                df["year"] = dt.dt.year
                df["month_num"] = dt.dt.month
            else:
                df["year"] = pd.to_numeric(y, errors="coerce")
                df["month_num"] = pd.to_numeric(m, errors="coerce")
        elif m_str.str.contains("-", regex=False).any():
            dt = pd.to_datetime(m_str, errors="coerce")
            if dt.notna().any():
                df["year"] = dt.dt.year
                df["month_num"] = dt.dt.month
            else:
                df["year"] = pd.to_numeric(y, errors="coerce")
                df["month_num"] = pd.to_numeric(m, errors="coerce")
        else:
            df["year"] = pd.to_numeric(y, errors="coerce")
            df["month_num"] = pd.to_numeric(m, errors="coerce")

        df["date"] = pd.to_datetime(
            dict(year=df["year"], month=df["month_num"], day=1),
            errors="coerce",
        )
        df = df[df["date"].notna()]
        return df

    if "month" in df.columns:
        dt = pd.to_datetime(df["month"], errors="coerce")
        if dt.notna().any():
            df["year"] = dt.dt.year
            df["month_num"] = dt.dt.month
            df["date"] = pd.to_datetime(
                dict(year=df["year"], month=df["month_num"], day=1)
            )
            df = df[df["date"].notna()]
            return df

    if "date" in df.columns:
        dt = pd.to_datetime(df["date"], errors="coerce")
        df["year"] = dt.dt.year
        df["month_num"] = dt.dt.month
        df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month_num"], day=1))
        df = df[df["date"].notna()]
        return df

    raise RuntimeError(
        f"Upstream CSV missing year/month or date columns. Columns: {list(df.columns)}"
    )


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    return None


def _to_app_schema(df: pd.DataFrame) -> pd.DataFrame:
    df = _coerce_year_month(df)

    col_t2m = _pick_column(df, ["2t", "t2m", "t2m_mean", "temperature"])
    col_clim = _pick_column(df, ["clim_91-20", "clim_91_20", "clim_1991-2020"])
    col_ano_91_20 = _pick_column(
        df, ["ano_91-20", "ano_91_20", "anomaly_91-20", "anomaly_1991-2020"]
    )
    col_offset = _pick_column(df, ["offset_pi", "offset_preindustrial"])
    col_ano_pi = _pick_column(df, ["ano_pi", "anomaly_pi", "anomaly_preindustrial"])

    out = pd.DataFrame({"date": df["date"], "year": df["year"], "month": df["month"]})

    def _add(out_name: str, col: Optional[str]) -> None:
        if col is None:
            return
        out[out_name] = pd.to_numeric(df[col], errors="coerce")

    _add("t2m", col_t2m)
    _add("clim_91_20", col_clim)
    _add("ano_91_20", col_ano_91_20)
    _add("offset_pi", col_offset)
    _add("ano_pi", col_ano_pi)

    # Keep chronological order
    out = out.sort_values("date").reset_index(drop=True)
    # Store as ISO string to avoid timezone surprises
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/world/global_series.csv"))
    ap.add_argument(
        "--meta-out", type=Path, default=Path("data/world/global_series.meta.json")
    )
    ap.add_argument(
        "--yyyymm", type=str, default=None, help="Override bulletin directory (YYYYMM)"
    )
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    yyyymm = args.yyyymm or latest_bulletin_dir(timeout_s=args.timeout)
    base_url, fname, section = find_best_global_series_csv(
        yyyymm,
        preferred_patterns=PREFERRED_FILENAMES,
        timeout_s=args.timeout,
    )
    src_url = base_url + fname

    df_up = _read_upstream_csv(src_url)
    df_out = _to_app_schema(df_up)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(args.out, index=False)

    meta = {
        "source_url": src_url,
        "bulletin_dir": yyyymm,
        "retrieved_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "rows": int(len(df_out)),
        "columns": list(df_out.columns),
        "generated_by": "scripts/make_global_series.py",
        "source_name": "ECMWF C3S Climate Pulse / global temperature anomaly series (ERA5-based)",
        "notes": "Monthly global mean 2m temperature anomaly series; app rebases anomalies to the chosen baseline.",
    }
    args.meta_out.parent.mkdir(parents=True, exist_ok=True)
    args.meta_out.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"Wrote {args.out} ({len(df_out)} rows)")
    print(f"Meta  {args.meta_out}")


if __name__ == "__main__":
    main()
