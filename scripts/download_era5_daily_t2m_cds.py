#!/usr/bin/env python3
"""
Download ERA5 daily mean 2m temperature from CDS, for two eras, to local NetCDFs.

Uses CDS dataset:
  derived-era5-single-levels-daily-statistics
which aggregates hourly ERA5 to daily during retrieval. :contentReference[oaicite:1]{index=1}
"""

from __future__ import annotations

import argparse
import json
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

import cdsapi


def _month_list() -> List[str]:
    return [f"{m:02d}" for m in range(1, 13)]


def _day_list() -> List[str]:
    # CDS will ignore invalid days for a given month.
    return [f"{d:02d}" for d in range(1, 32)]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _is_zip_file(path: Path) -> bool:
    # zipfile.is_zipfile reads signatures safely
    try:
        return zipfile.is_zipfile(path)
    except Exception:
        return False


def _looks_like_netcdf_or_hdf(path: Path) -> bool:
    # NetCDF classic starts with b"CDF", netCDF4 starts with HDF5 signature b"\x89HDF\r\n\x1a\n"
    sig = path.read_bytes()[:8]
    return sig.startswith(b"CDF") or sig.startswith(b"\x89HDF")


def _finalize_cds_output(download_path: Path, out_nc: Path) -> None:
    """
    CDS may return:
      - a ZIP containing a single .nc
      - a raw NetCDF (often netCDF4/HDF5)
    Handle both.
    """
    out_nc.parent.mkdir(parents=True, exist_ok=True)

    if _is_zip_file(download_path):
        _unzip_single_netcdf(download_path, out_nc)
        return

    if _looks_like_netcdf_or_hdf(download_path):
        # It's already a NetCDF file (netCDF4 is HDF5-based)
        out_nc.write_bytes(download_path.read_bytes())
        return

    # Otherwise, give a helpful error
    head = download_path.read_bytes()[:200]
    raise RuntimeError(
        f"Unexpected CDS output (not zip, not NetCDF/HDF). "
        f"path={download_path} head={head!r}"
    )


def _unzip_single_netcdf(zip_path: Path, out_nc: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        ncs = [n for n in zf.namelist() if n.lower().endswith(".nc")]
        if len(ncs) != 1:
            raise RuntimeError(f"Expected exactly 1 .nc in {zip_path}, found {ncs}")
        member = ncs[0]
        out_nc.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(out_nc, "wb") as dst:
            dst.write(src.read())


@dataclass(frozen=True)
class Era:
    name: str
    start_year: int
    end_year: int


def _retrieve_era_daily_mean_t2m(
    *,
    era: Era,
    grid_deg: float,
    out_dir: Path,
    tmp_dir: Path,
    timeout_s: int = 300,
    keep_zip: bool = False,
) -> Path:
    """
    Retrieve ERA5 daily mean t2m, split by year to avoid CDS cost limits.

    Outputs:
      - per-year NetCDFs: era5_daily_t2m_<YEAR>_grid<GRID>.nc
      - era manifest meta: era5_daily_t2m_<START>-<END>_grid<GRID>.meta.json
    """
    dataset = "derived-era5-single-levels-daily-statistics"

    out_meta = out_dir / f"era5_daily_t2m_{era.start_year}-{era.end_year}_grid{grid_deg}.meta.json"
    _ensure_dir(out_dir)
    _ensure_dir(tmp_dir)

    client = cdsapi.Client(timeout=timeout_s)

    year_files: list[str] = []

    years = list(range(era.start_year, era.end_year + 1))
    total = len(years)
    for i, y in enumerate(years, start=1):
        print(f"[cds] {era.name} {i}/{total}: year={y} grid={grid_deg}°", flush=True)

        out_nc_y = out_dir / f"era5_daily_t2m_{y}_grid{grid_deg}.nc"
        out_meta_y = out_dir / f"era5_daily_t2m_{y}_grid{grid_deg}.meta.json"
        out_zip_y = tmp_dir / f"era5_daily_t2m_{y}_grid{grid_deg}.download"

        if out_nc_y.exists() and out_meta_y.exists():
            print(f"[skip] {out_nc_y} already exists")
            year_files.append(str(out_nc_y))
            continue

        request = {
            "product_type": "reanalysis",
            "variable": ["2m_temperature"],
            "year": [str(y)],
            "month": _month_list(),
            "day": _day_list(),
            "daily_statistic": "daily_mean",
            "time_zone": "utc+00:00",
            "frequency": "6_hourly",
            "format": "netcdf",
            "grid": f"{grid_deg}/{grid_deg}",
        }

        print(f"[cds] retrieving {era.name}: year={y} grid={grid_deg}°")
        client.retrieve(dataset, request, str(out_zip_y))

        print(f"[finalize] {out_zip_y} -> {out_nc_y}")
        _finalize_cds_output(out_zip_y, out_nc_y)

        meta_y = {
            "dataset": dataset,
            "era": asdict(era),
            "year": y,
            "grid_deg": grid_deg,
            "request": request,
            "output_netcdf": str(out_nc_y),
        }
        out_meta_y.write_text(json.dumps(meta_y, indent=2), encoding="utf-8")

        if not keep_zip:
            try:
                out_zip_y.unlink(missing_ok=True)
            except Exception:
                pass

        year_files.append(str(out_nc_y))

    meta = {
        "dataset": dataset,
        "era": asdict(era),
        "grid_deg": grid_deg,
        "split_by_year": True,
        "year_files": year_files,
    }
    out_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out_meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-deg", type=float, default=1.0, help="Output grid resolution in degrees (e.g. 1.0, 0.5, 0.25)")
    ap.add_argument("--out-dir", type=Path, default=Path("data/mc"))
    ap.add_argument("--tmp-dir", type=Path, default=Path("data/mc/_tmp"))
    ap.add_argument("--timeout", type=int, default=300, help="CDS client read timeout seconds (default: 300)")
    ap.add_argument("--keep-zip", action="store_true", help="Keep downloaded zip files (default: delete after extraction)")
    args = ap.parse_args()
   
    eras = [
        Era(name="past", start_year=1979, end_year=1988),
        Era(name="recent", start_year=2016, end_year=2025),
    ]

    for j, era in enumerate(eras, start=1):
        print(f"[era] {j}/{len(eras)}: {era.name} ({era.start_year}-{era.end_year})", flush=True)
        _retrieve_era_daily_mean_t2m(
            era=era,
            grid_deg=args.grid_deg,
            out_dir=args.out_dir,
            tmp_dir=args.tmp_dir,
            timeout_s=int(args.timeout),
            keep_zip=bool(args.keep_zip),
        )


if __name__ == "__main__":
    main()
