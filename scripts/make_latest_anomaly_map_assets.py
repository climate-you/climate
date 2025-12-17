#!/usr/bin/env python3
"""Download the latest Copernicus/ECMWF C3S bulletin global temperature anomaly map.

This is a *quick* way to make the World panel real without computing your own
baseline-to-baseline warming raster yet.

It downloads (from the latest bulletin press_release directory):
- Fig3 map netCDF (DATA.nc) if present
- Fig3 map PNG if present
and writes a small JSON manifest.

Note: This is an anomaly map for the latest month (relative to a reference
period), NOT a multi-year baseline warming difference map.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Optional, Tuple

import requests

BULLETIN_ROOT = "https://sites.ecmwf.int/data/c3sci/bulletin/"

PAT_NC = re.compile(r"Fig3_.*map_surface_temperature_anomaly_global.*\.nc$", re.I)
PAT_PNG = re.compile(r"Fig3_.*map_surface_temperature_anomaly_global.*\.png$", re.I)


def _http_get(url: str, timeout_s: int = 60) -> requests.Response:
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    return r


def _find_latest_bulletin_dir(timeout_s: int = 60) -> str:
    html = _http_get(BULLETIN_ROOT, timeout_s=timeout_s).text
    dirs = sorted({m.group(1) for m in re.finditer(r'href="(\d{6})/"', html)})
    if not dirs:
        raise RuntimeError(f"Could not find any YYYYMM directories at {BULLETIN_ROOT}")
    return dirs[-1]


def _find_files(yyyymm: str, timeout_s: int = 60) -> Tuple[str, Optional[str], Optional[str]]:
    press_url = f"{BULLETIN_ROOT}{yyyymm}/press_release/"
    html = _http_get(press_url, timeout_s=timeout_s).text
    files = [m.group(1) for m in re.finditer(r'href="([^"]+)"', html)]
    nc = next((f for f in files if PAT_NC.search(f)), None)
    png = next((f for f in files if PAT_PNG.search(f)), None)
    return press_url, nc, png


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=Path("data/world"))    
    ap.add_argument("--yyyymm", type=str, default=None)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    yyyymm = args.yyyymm or _find_latest_bulletin_dir(timeout_s=args.timeout)
    press_url, nc, png = _find_files(yyyymm, timeout_s=args.timeout)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "bulletin_dir": yyyymm,
        "press_release_url": press_url,
        "retrieved_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "files": {},
    }

    if nc:
        nc_url = press_url + nc
        out_nc = args.out_dir / "latest_global_temp_anomaly_map.nc"
        out_nc.write_bytes(_http_get(nc_url, timeout_s=120).content)
        manifest["files"]["netcdf"] = {"url": nc_url, "path": str(out_nc)}

    if png:
        png_url = press_url + png
        out_png = args.out_dir / "latest_global_temp_anomaly_map.png"
        out_png.write_bytes(_http_get(png_url, timeout_s=120).content)
        manifest["files"]["png"] = {"url": png_url, "path": str(out_png)}

    out_manifest = args.out_dir / "latest_global_temp_anomaly_map.manifest.json"
    out_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if not nc and not png:
        raise RuntimeError(f"Could not find Fig3 global anomaly map files in {press_url}")

    print(f"Wrote {out_manifest}")
    for k, v in manifest["files"].items():
        print(f"- {k}: {v['path']}")    


if __name__ == "__main__":
    main()
