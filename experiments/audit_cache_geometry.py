#!/usr/bin/env python3
"""Classify the grid registration of every cached NetCDF file.

Motivation: the March/April 2026 CDS area-extraction change left the cache
spanning two latitude registrations - cell-centre (.125 offsets, what we ask
for) and native (multiples of 0.25, what ERA5 actually stores). Everything we
know about that was established from a handful of sampled files, and one
mismatched band (monthly t2m, r008-011) was found only because it happened to
render as a visible black stripe.

This audits rather than samples: it opens every file, reads only the coordinate
variables, and classifies each one. The point is to find out whether the
two-state model is complete before a migration plan is built on it - or to find
the third state now rather than halfway through.

Reads coordinates only, never data, so it is I/O-light despite the file count.

Usage:
    python experiments/audit_cache_geometry.py --sample 3      # fast pass
    python experiments/audit_cache_geometry.py                 # every file
    python experiments/audit_cache_geometry.py --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

CACHE = Path("/Volumes/LaCie/Climate/cache")


def offset_in_cells(v: np.ndarray) -> float:
    """Signed distance of the axis from the nearer of the two registrations,
    in cells: 0.0 = exactly native, 0.5 = exactly cell-centre.

    Reported alongside the label because the label alone hides how close a call
    it was. The ERA5 daily t2m globe files from 1979-2020 record longitude to
    two decimals (-179.88 for the cell centre -179.875), putting them 0.02 of a
    cell off - which the original tol=0.02 accepted as "cell" by a margin of
    2e-14 and so reported as a clean two-state cache.
    """
    if v.size < 2:
        return float("nan")
    step = abs(float(v[-1]) - float(v[0])) / (v.size - 1)
    if step <= 0:
        return float("nan")
    return float(v[0] / step) % 1.0


def noise_in_cells(v: np.ndarray) -> float:
    """How far, in cells, the axis wanders from a perfectly regular ramp.

    This is the axis's own precision floor, and it has to be measured rather
    than assumed: a float64 0.25 deg axis is exact (~0), while a float32 0.05
    deg axis drifts by ~0.005 of a cell. One fixed tolerance cannot serve both
    - loose enough for the 0.05 deg products is loose enough to swallow the
    0.02-cell longitude rounding on the ERA5 t2m globe files.
    """
    if v.size < 2:
        return float("nan")
    step = (float(v[-1]) - float(v[0])) / (v.size - 1)
    if step == 0:
        return float("nan")
    ideal = float(v[0]) + step * np.arange(v.size, dtype=np.float64)
    return float(np.max(np.abs(v - ideal)) / abs(step))


def frac_uncertainty(v: np.ndarray) -> float:
    """Uncertainty of `offset_in_cells`, in cells, from the axis's own noise.

    `offset_in_cells` divides `v[0]` by a step estimated from the endpoints, so
    coordinate noise enters twice and the second term is amplified: a relative
    error in `step` is multiplied by however many steps `v[0]` sits from zero.
    At 0.05 deg and longitude -71 that factor is ~1400 against only 127
    intervals to average over, which turns 1e-4 of coordinate noise into ~2e-3
    of offset - larger than any sane fixed tolerance, and the reason the CRW DHW
    longitudes keep landing just outside one.
    """
    if v.size < 2:
        return float("nan")
    noise = noise_in_cells(v)
    step = abs(float(v[-1]) - float(v[0])) / (v.size - 1)
    if step <= 0 or not np.isfinite(noise):
        return float("nan")
    index0 = abs(float(v[0])) / step
    return noise * (1.0 + 2.0 * index0 / (v.size - 1))


def classify(v: np.ndarray, tol: float | None = None) -> str:
    """native = first coordinate on a multiple of the spacing; cell = offset by
    half a spacing; other = neither.

    Judged on the FIRST coordinate only, against the spacing. Testing every
    element instead lets float32 rounding drift accumulate across a long axis
    and misreport a perfectly regular grid; and the spacing has to be measured
    per axis, since some sources are anisotropic (CMIP6 is 1.25 x 1.875 deg).
    Tolerance is a fraction of one cell. By default it is derived from the
    axis's own precision (`noise_in_cells`) rather than fixed, because the only
    thing it should absorb is that axis's coordinate noise. The original fixed
    0.02 was loose enough to swallow a real third state - the ERA5 t2m globe
    files' two-decimal longitudes, 0.02 of a cell off, which it accepted as
    "cell" by a margin of 2e-14.

    The spacing comes from the axis SPAN, not the median of the diffs. The test
    is `v[0] / step`, so any relative error in `step` is amplified by however
    many steps `v[0]` sits from zero - and a single diff of float32 coordinates
    carries ~1e-5 relative error. At 0.25 deg that never bit, because multiples
    of 0.25 are exact in float32; at 0.05 deg the error is amplified by ~1400 at
    longitude -71 and pushes a perfectly good cell grid (frac 0.5) out to 0.59,
    reporting the ERDDAP CRW DHW products as a third registration. Dividing the
    span by n-1 averages that noise over every interval and puts them back at
    0.5.
    """
    if v.size < 2:
        return "empty"
    step = abs(float(v[-1]) - float(v[0])) / (v.size - 1)
    if step <= 0:
        return "empty"
    # The span only stands in for the spacing on a uniformly spaced axis. If the
    # two estimates disagree, the axis has a gap or a wrap and neither
    # registration label would mean anything.
    median_step = float(np.median(np.abs(np.diff(v))))
    if median_step > 0 and abs(step - median_step) / median_step > 0.01:
        return "irregular"
    if tol is None:
        # 3 sigma of the axis's own noise, floored so an exactly-regular float64
        # axis still gets a non-zero tolerance.
        tol = max(3.0 * frac_uncertainty(v), 1e-3)
    frac = float(v[0] / step) % 1.0
    if min(frac, 1.0 - frac) < tol:
        return "native"
    if abs(frac - 0.5) < tol:
        return "cell"
    return "other"


def coords(path: Path):
    from netCDF4 import Dataset  # local import: only needed here

    with Dataset(path) as ds:
        lat = lon = None
        for name in ("latitude", "lat", "y"):
            if name in ds.variables:
                lat = np.asarray(ds.variables[name][:], dtype=np.float64)
                break
        for name in ("longitude", "lon", "x"):
            if name in ds.variables:
                lon = np.asarray(ds.variables[name][:], dtype=np.float64)
                break
    return lat, lon


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="check only N files per directory (0 = all)",
    )
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument(
        "--include-backup",
        action="store_true",
        help="also audit backup-aug26 (excluded by default)",
    )
    args = ap.parse_args()

    dirs = sorted(p for p in args.cache.rglob("*") if p.is_dir())
    rows = []
    per_dir: dict[str, Counter] = defaultdict(Counter)
    span: dict[str, set] = defaultdict(set)
    errors = []

    total = 0
    for d in dirs:
        # Exclude the whole backup subtree, not just directories literally named
        # "backup*": backup-aug26/ holds subdirectories with names IDENTICAL to
        # the live ones, so testing d.name alone lets them through - and keying
        # results by name then merges live and backup files into one bucket,
        # manufacturing a spurious "mixed registration" flag.
        rel = d.relative_to(args.cache)
        if not args.include_backup and any("backup" in part for part in rel.parts):
            continue
        files = sorted(d.glob("*.nc"))
        if not files:
            continue
        if args.sample:
            files = files[: args.sample]
        for f in files:
            total += 1
            if total % 2000 == 0:
                print(f"   ...{total} files", flush=True)
            try:
                lat, lon = coords(f)
            except Exception as exc:  # noqa: BLE001
                errors.append((str(f), f"{type(exc).__name__}: {exc}"))
                continue
            if lat is None:
                errors.append((str(f), "no latitude variable"))
                continue
            # Infer the spacing from the coordinates themselves rather than
            # from the directory name: some cache directories (erddap_masks)
            # carry no resolution tag, and guessing 0.25 for 0.05 data reports a
            # perfectly good grid as a third registration.
            # Each axis needs its own spacing: lat and lon differ on some
            # sources (CMIP6 is 1.25 x 1.875), so using the latitude step to
            # classify longitude reports good grids as a third registration.
            cl_lat = classify(lat)
            cl_lon = classify(lon) if lon is not None else "-"
            key = f"{cl_lat}/{cl_lon}"
            per_dir[str(rel)][key] += 1
            span[str(rel)].add(
                (round(float(lat[0]), 4), round(float(lat[-1]), 4), lat.size)
            )
            rows.append(
                {
                    "dir": str(rel),
                    "file": f.name,
                    "lat_class": cl_lat,
                    "lon_class": cl_lon,
                    "lat0": float(lat[0]),
                    "lat1": float(lat[-1]),
                    "nlat": int(lat.size),
                    "lat_frac": offset_in_cells(lat),
                    "lat_unc": frac_uncertainty(lat),
                    "lon_frac": (
                        offset_in_cells(lon) if lon is not None else float("nan")
                    ),
                    "lon_unc": (
                        frac_uncertainty(lon) if lon is not None else float("nan")
                    ),
                    "lon0": float(lon[0]) if lon is not None else float("nan"),
                }
            )

    print(f"\naudited {total} file(s) across {len(per_dir)} directories\n")

    print("=" * 92)
    print("PER-DIRECTORY REGISTRATION (lat/lon)")
    print("=" * 92)
    mixed = []
    for name in sorted(per_dir):
        c = per_dir[name]
        parts = "  ".join(f"{k}={v}" for k, v in sorted(c.items()))
        flag = ""
        if len(c) > 1:
            flag = "   <-- MIXED WITHIN DIRECTORY"
            mixed.append(name)
        print(f"  {name[-62:]:62s} {parts}{flag}")

    print()
    print("=" * 92)
    print("SUMMARY")
    print("=" * 92)
    overall = Counter()
    for c in per_dir.values():
        overall.update(c)
    for k, v in sorted(overall.items(), key=lambda kv: -kv[1]):
        print(f"  {k:20s} {v:7d} file(s)")
    print(f"\n  directories with mixed registration: {len(mixed)}")
    for m in mixed:
        print(f"     {m}")

    others = [r for r in rows if r["lat_class"] == "other" or r["lon_class"] == "other"]
    if others:
        print(
            f"\n  !! {len(others)} file(s) on a THIRD registration (neither native nor cell):"
        )
        seen: set = set()
        for r in others:
            key = (r["dir"], round(r["lat_frac"], 4), round(r["lon_frac"], 4))
            if key in seen:
                continue
            seen.add(key)
            print(f"     {r['dir'][-52:]}")
            print(f"       e.g. {r['file'][-56:]}")
            print(
                f"       lat0={r['lat0']:>12} off {r['lat_frac']:.5f} cells "
                f"({r['lat_class']}) | lon0={r['lon0']:>12} off "
                f"{r['lon_frac']:.5f} cells ({r['lon_class']})"
            )
    else:
        print("\n  no files outside the native/cell two-state model")

    # The label is a threshold decision; the distribution of measured offsets is
    # what shows whether any group sits near that threshold.
    print()
    print("=" * 92)
    print("MEASURED OFFSETS (fraction of a cell; 0.0 = native, 0.5 = cell-centre)")
    print("=" * 92)
    buckets: dict[tuple, int] = Counter()
    for r in rows:
        buckets[(round(r["lat_frac"], 4), round(r["lon_frac"], 4))] += 1
    for (lf, nf), n in sorted(buckets.items(), key=lambda kv: -kv[1]):
        print(f"  lat {lf:+.4f}   lon {nf:+.4f}   {n:7d} file(s)")

    if errors:
        print(f"\n  {len(errors)} unreadable file(s):")
        for f, e in errors[:10]:
            print(f"     {f[-70:]}: {e}")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  per-file detail -> {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
