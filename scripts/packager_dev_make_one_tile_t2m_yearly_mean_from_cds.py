from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import xarray as xr

from climate.datasets.products.era5 import download_monthly_means
from climate.tiles.layout import GridSpec, cell_center_latlon, tile_path
from climate.tiles.spec import write_tile


@dataclass(frozen=True)
class Era5MonthlyRequest:
    """
    Minimal request spec for a single ERA5 monthly-means download from CDS.
    """

    start_year: int
    end_year: int
    area: tuple[float, float, float, float]  # (north, west, south, east)
    grid_deg: float = 0.25
    variable: str = "2m_temperature"


def _write_yearly_axis_json(
    out_root: Path, grid: GridSpec, metric: str, years: list[int]
) -> Path:
    p = out_root / grid.grid_id / metric / "time" / "yearly.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(years, indent=2) + "\n", encoding="utf-8")
    return p


def _find_lat_lon_names(ds: xr.Dataset) -> tuple[str, str]:
    # ERA5 monthly means from CDS commonly uses "latitude"/"longitude"
    for lat_name in ("latitude", "lat", "y"):
        if lat_name in ds.coords:
            break
    else:
        raise RuntimeError(f"Could not find latitude coord in {list(ds.coords)}")

    for lon_name in ("longitude", "lon", "x"):
        if lon_name in ds.coords:
            break
    else:
        raise RuntimeError(f"Could not find longitude coord in {list(ds.coords)}")

    return lat_name, lon_name


def _ensure_lon_pm180(ds: xr.Dataset, lon_name: str) -> xr.Dataset:
    """
    Normalize longitude to [-180, 180) if it is in [0, 360).
    Keeps sorted order.
    """
    lon = np.asarray(ds[lon_name].values, dtype=np.float64)
    if lon.min() >= 0.0 and lon.max() > 180.0:
        lon_pm180 = ((lon + 180.0) % 360.0) - 180.0
        ds = ds.assign_coords({lon_name: lon_pm180})
        ds = ds.sortby(lon_name)
    return ds


def _get_single_data_var(ds: xr.Dataset) -> str:
    vars_ = list(ds.data_vars)
    if len(vars_) != 1:
        raise RuntimeError(f"Expected 1 data var in ERA5 file, got {vars_}")
    return vars_[0]


def _open_monthly_file(nc_path: Path) -> xr.Dataset:
    return xr.open_dataset(nc_path)


def _monthly_k_to_c(da: xr.DataArray) -> xr.DataArray:
    # ERA5 t2m is Kelvin from CDS; convert to Celsius
    return da - 273.15


def _find_time_dim(da: xr.DataArray) -> str:
    for name in ("time", "valid_time", "forecast_time"):
        if name in da.dims:
            return name
    raise RuntimeError(f"Could not find a time dimension in dims={da.dims}")


def _n_tiles(n: int, tile_size: int) -> int:
    return (int(n) + int(tile_size) - 1) // int(tile_size)


def _clamp_cds_area(
    area: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """
    CDS expects area as (north, west, south, east), with:
      -90 <= south <= north <= 90
      -180 <= west <= east <= 180  (for our pm180 convention)
    """
    north, west, south, east = area

    # clamp lat strictly
    north = min(90.0, max(-90.0, float(north)))
    south = min(90.0, max(-90.0, float(south)))

    # ensure ordering
    if south > north:
        south, north = north, south

    # clamp lon too (defensive)
    west = min(180.0, max(-180.0, float(west)))
    east = min(180.0, max(-180.0, float(east)))

    return (north, west, south, east)


def _compute_tile_bbox_clamped(
    grid: GridSpec, tile_r: int, tile_c: int
) -> tuple[list[float], list[float], tuple[float, float, float, float], int, int]:
    """
    Compute:
      - expected lat centers (north->south) for the VALID rows in this tile
      - expected lon centers (west->east) for the VALID cols in this tile
      - (north, west, south, east) for CDS 'area'
      - valid_h, valid_w (<= tile_size)
    """
    ts = grid.tile_size
    i_lat0 = tile_r * ts
    i_lon0 = tile_c * ts

    valid_h = max(0, min(ts, grid.nlat - i_lat0))
    valid_w = max(0, min(ts, grid.nlon - i_lon0))
    if valid_h <= 0 or valid_w <= 0:
        raise RuntimeError(
            f"Tile (r={tile_r}, c={tile_c}) is outside grid: "
            f"i_lat0={i_lat0}, i_lon0={i_lon0}, grid=({grid.nlat},{grid.nlon})"
        )

    lats: list[float] = []
    lons: list[float] = []
    for j in range(valid_h):
        latc, _ = cell_center_latlon(i_lat0 + j, i_lon0, grid)
        lats.append(float(latc))
    for j in range(valid_w):
        _, lonc = cell_center_latlon(i_lat0, i_lon0 + j, grid)
        lons.append(float(lonc))

    north = lats[0]
    south = lats[-1]
    west = lons[0]
    east = lons[-1]
    area = _clamp_cds_area((north, west, south, east))
    return lats, lons, area, valid_h, valid_w


def _compute_batch_bbox(
    grid: GridSpec, tile_r0: int, tile_c0: int, tile_r1: int, tile_c1: int
) -> tuple[tuple[float, float, float, float], int, int]:
    """
    Compute a CDS area for a batch of tiles (inclusive range).
    Returns:
      - (north, west, south, east)
      - total_valid_h, total_valid_w (number of lat/lon points expected in download)
    """
    ts = grid.tile_size
    i_lat0 = tile_r0 * ts
    i_lon0 = tile_c0 * ts

    # Clamp end to grid extents
    i_lat1 = min((tile_r1 + 1) * ts - 1, grid.nlat - 1)
    i_lon1 = min((tile_c1 + 1) * ts - 1, grid.nlon - 1)

    total_h = i_lat1 - i_lat0 + 1
    total_w = i_lon1 - i_lon0 + 1
    if total_h <= 0 or total_w <= 0:
        raise RuntimeError(
            f"Batch tiles outside grid: r{tile_r0}-{tile_r1}, c{tile_c0}-{tile_c1}"
        )

    north, _ = cell_center_latlon(i_lat0, i_lon0, grid)
    south, _ = cell_center_latlon(i_lat1, i_lon0, grid)
    _, west = cell_center_latlon(i_lat0, i_lon0, grid)
    _, east = cell_center_latlon(i_lat0, i_lon1, grid)

    area = _clamp_cds_area((float(north), float(west), float(south), float(east)))
    return (area, int(total_h), int(total_w))


def _iter_batches(
    r0: int, r1: int, c0: int, c1: int, batch_tiles: int
) -> Iterable[tuple[int, int, int, int]]:
    bt = int(batch_tiles)
    if bt <= 0:
        raise ValueError("--batch-tiles must be >= 1")
    for rr0 in range(r0, r1 + 1, bt):
        rr1 = min(rr0 + bt - 1, r1)
        for cc0 in range(c0, c1 + 1, bt):
            cc1 = min(cc0 + bt - 1, c1)
            yield rr0, rr1, cc0, cc1


def _tile_output_exists(
    out_root: Path, grid: GridSpec, metric: str, tr: int, tc: int
) -> bool:
    p = tile_path(out_root, grid, metric=metric, tile_r=tr, tile_c=tc, ext=".bin.zst")
    return p.exists()


def _batch_missing_tiles(
    out_root: Path, grid: GridSpec, metric: str, r0: int, r1: int, c0: int, c1: int
) -> list[tuple[int, int]]:
    missing: list[tuple[int, int]] = []
    for tr in range(r0, r1 + 1):
        for tc in range(c0, c1 + 1):
            if not _tile_output_exists(out_root, grid, metric, tr, tc):
                missing.append((tr, tc))
    return missing


def _download_batch_monthly_means(
    *,
    grid: GridSpec,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    tile_r0: int,
    tile_r1: int,
    tile_c0: int,
    tile_c1: int,
    overwrite_download: bool,
    debug: bool,
) -> Path:
    years_int = list(range(int(start_year), int(end_year) + 1))
    years_str = [str(y) for y in years_int]

    area, total_h, total_w = _compute_batch_bbox(
        grid, tile_r0, tile_c0, tile_r1, tile_c1
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    dl_path = (
        cache_dir
        / f"era5_monthly_t2m_{grid.grid_id}_r{tile_r0:03d}-{tile_r1:03d}_c{tile_c0:03d}-{tile_c1:03d}_{start_year}-{end_year}.nc"
    )

    if dl_path.exists() and not overwrite_download:
        try:
            # validate cached file (handles previously interrupted downloads)
            _ = _open_monthly_file(dl_path)
            _.close()
            print(f"Using cached download: {dl_path}")
            return dl_path
        except Exception as e:
            print(f"[warn] Cached download is invalid, deleting: {dl_path} ({e})")
            try:
                dl_path.unlink()
            except Exception:
                pass

    if debug:
        print(
            f"Downloading ERA5 monthly means batch: years={years_str[0]}..{years_str[-1]} "
            f"tiles r{tile_r0}-{tile_r1} c{tile_c0}-{tile_c1} "
            f"area={area} expected_points=({total_h} lat x {total_w} lon) grid={grid.deg}"
        )
    else:
        print(
            f"Downloading ERA5 monthly means: years={years_str[0]}..{years_str[-1]} "
            f"area={area} grid={grid.deg}"
        )

    n, w, s, e = area
    if s < -90.0 or n > 90.0:
        raise RuntimeError(f"Invalid CDS area: {area}")
    download_monthly_means(
        out_nc=dl_path,
        years=years_str,
        grid_deg=float(grid.deg),
        area=area,
    )
    print(f"Downloaded: {dl_path}")
    return dl_path


def _tiles_from_download(
    *,
    out_root: Path,
    grid: GridSpec,
    metric: str,
    years_int: list[int],
    dl_path: Path,
    tile_r0: int,
    tile_r1: int,
    tile_c0: int,
    tile_c1: int,
    debug: bool,
    resume: bool,
) -> int:
    years_str = [str(y) for y in years_int]

    ds = _open_monthly_file(dl_path)
    try:
        lat_name, lon_name = _find_lat_lon_names(ds)
        ds = _ensure_lon_pm180(ds, lon_name)

        var_name = _get_single_data_var(ds)
        da = ds[var_name]

        # Convert K->C if needed (heuristic: ERA5 t2m will be ~250..320K)
        vmax = float(da.max().values)
        if vmax > 200.0:
            da = _monthly_k_to_c(da)

        # Compute annual means (year x lat x lon)
        tname = _find_time_dim(da)

        # groupby needs datetime-like coord
        if not np.issubdtype(da[tname].dtype, np.datetime64):
            da = xr.decode_cf(da.to_dataset(name="v"))["v"]

        da_ann = da.groupby(f"{tname}.year").mean(tname, keep_attrs=False)
        da_ann = da_ann.sel(year=years_int)

        written = 0

        for tr in range(tile_r0, tile_r1 + 1):
            for tc in range(tile_c0, tile_c1 + 1):
                lats_expected, lons_expected, _area, valid_h, valid_w = (
                    _compute_tile_bbox_clamped(grid, tr, tc)
                )

                # Robust: align to our expected tile centers using nearest-neighbor within ~half a cell.
                # This avoids KeyError when CDS coords are on 0.25 multiples but our centers are half-step.
                tol = grid.deg * 0.51  # slightly > 0.5*deg to tolerate float rounding
                da_tile = da_ann.reindex(
                    {lat_name: lats_expected, lon_name: lons_expected},
                    method="nearest",
                    tolerance=tol,
                )

                if debug:
                    lat_sel = np.asarray(da_tile[lat_name].values, dtype=np.float64)
                    lon_sel = np.asarray(da_tile[lon_name].values, dtype=np.float64)
                    lat_exp = np.asarray(lats_expected, dtype=np.float64)
                    lon_exp = np.asarray(lons_expected, dtype=np.float64)

                    max_lat_err = (
                        float(np.max(np.abs(lat_sel - lat_exp)))
                        if lat_sel.size
                        else 0.0
                    )
                    max_lon_err = (
                        float(np.max(np.abs(lon_sel - lon_exp)))
                        if lon_sel.size
                        else 0.0
                    )
                    print(
                        f"tile r{tr:03d} c{tc:03d}: max coord error "
                        f"lat={max_lat_err:.6f}, lon={max_lon_err:.6f}"
                    )

                arr = da_tile.transpose(lat_name, lon_name, "year").values  # (h,w,ny)

                tile = np.full(
                    (grid.tile_size, grid.tile_size, len(years_str)),
                    np.nan,
                    dtype=np.float32,
                )
                tile[:valid_h, :valid_w, :] = np.asarray(arr, dtype=np.float32)

                out_path = tile_path(
                    out_root, grid, metric=metric, tile_r=tr, tile_c=tc, ext=".bin.zst"
                )
                if resume and out_path.exists():
                    if debug:
                        print(f"Skip existing tile: {out_path}")
                    continue
                write_tile(
                    out_path,
                    tile,
                    dtype=np.dtype("float32"),
                    nyears=len(years_str),
                    tile_h=grid.tile_size,
                    tile_w=grid.tile_size,
                    compress_level=10,
                )
                written += 1
                if debug:
                    print(
                        f"Wrote {out_path} (tile r{tr:03d} c{tc:03d} valid={valid_h}x{valid_w})"
                    )

        if not debug:
            print(f"Wrote {written} tile(s) from {dl_path}")

        return written
    finally:
        ds.close()


def run(
    *,
    out_root: Path,
    grid: GridSpec,
    metric: str = "t2m_yearly_mean_c",
    start_year: int = 1979,
    end_year: int = 2025,
    cache_dir: Path = Path("data/cache/cds"),
    overwrite_download: bool = False,
    debug: bool = False,
    tile_r0: int,
    tile_r1: int,
    tile_c0: int,
    tile_c1: int,
    batch_tiles: int = 1,
    resume: bool = False,
    max_downloads: int | None = None,
) -> None:
    years_int = list(range(int(start_year), int(end_year) + 1))
    years_str = [str(y) for y in years_int]
    axis_path = _write_yearly_axis_json(out_root, grid, metric, years_int)
    print(
        f"Year axis: {axis_path} ({years_str[0]}..{years_str[-1]}, n={len(years_str)})"
    )

    total_written = 0
    n_batches_processed = 0
    for br0, br1, bc0, bc1 in _iter_batches(
        tile_r0, tile_r1, tile_c0, tile_c1, batch_tiles
    ):
        if debug:
            print(f"Batch tiles: r{br0}-{br1} c{bc0}-{bc1}")

        if resume:
            missing = _batch_missing_tiles(out_root, grid, metric, br0, br1, bc0, bc1)
            if not missing:
                if debug:
                    print(f"Skip batch (all tiles exist): r{br0}-{br1} c{bc0}-{bc1}")
                continue
            if debug:
                print(
                    f"Batch missing {len(missing)} tile(s): {missing[:8]}{'...' if len(missing) > 8 else ''}"
                )

        if max_downloads is not None and n_batches_processed >= int(max_downloads):
            print(f"Stopping early due to --max-downloads={max_downloads}")
            break

        dl_path = _download_batch_monthly_means(
            grid=grid,
            cache_dir=cache_dir,
            start_year=start_year,
            end_year=end_year,
            tile_r0=br0,
            tile_r1=br1,
            tile_c0=bc0,
            tile_c1=bc1,
            overwrite_download=overwrite_download,
            debug=debug,
        )

        total_written += _tiles_from_download(
            out_root=out_root,
            grid=grid,
            metric=metric,
            years_int=years_int,
            dl_path=dl_path,
            tile_r0=br0,
            tile_r1=br1,
            tile_c0=bc0,
            tile_c1=bc1,
            debug=debug,
            resume=resume,
        )

        n_batches_processed += 1

    print(
        f"DONE: wrote {total_written} tile(s) for metric={metric} "
        f"tiles r{tile_r0}-{tile_r1} c{tile_c0}-{tile_c1} (batch_tiles={batch_tiles})"
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        "Build t2m_yearly_mean_c tile(s) from ERA5 monthly means via CDS"
    )
    p.add_argument("--out-root", type=Path, default=Path("data/releases/dev/series"))
    p.add_argument("--metric", type=str, default="t2m_yearly_mean_c")
    p.add_argument("--tile-size", type=int, default=64)

    # Modes:
    p.add_argument("--tile-r", type=int, help="Single tile row (legacy mode)")
    p.add_argument("--tile-c", type=int, help="Single tile col (legacy mode)")

    p.add_argument("--tile-r0", type=int, help="First tile row (inclusive)")
    p.add_argument("--tile-r1", type=int, help="Last tile row (inclusive)")
    p.add_argument("--tile-c0", type=int, help="First tile col (inclusive)")
    p.add_argument("--tile-c1", type=int, help="Last tile col (inclusive)")
    p.add_argument(
        "--batch-tiles",
        type=int,
        default=1,
        help="Download & process tiles in NxN batches (reduces CDS requests).",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Generate all tiles for the grid (0..max) using --batch-tiles batching.",
    )

    p.add_argument("--start-year", type=int, default=1979)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--cache-dir", type=Path, default=Path("data/cache/cds"))
    p.add_argument("--overwrite-download", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip writing tiles that already exist; if an entire batch exists, skip the batch (and download).",
    )
    p.add_argument(
        "--max-downloads",
        type=int,
        default=None,
        help="Stop after processing N tile-batches (useful for smoke tests). Batches skipped by --resume do not count.",
    )

    args = p.parse_args()

    grid = GridSpec.global_0p25(tile_size=args.tile_size)
    ntr = _n_tiles(grid.nlat, grid.tile_size)
    ntc = _n_tiles(grid.nlon, grid.tile_size)

    # Determine tile range
    if args.all:
        r0, r1, c0, c1 = 0, ntr - 1, 0, ntc - 1
    elif (
        args.tile_r0 is not None
        or args.tile_r1 is not None
        or args.tile_c0 is not None
        or args.tile_c1 is not None
    ):
        if None in (args.tile_r0, args.tile_r1, args.tile_c0, args.tile_c1):
            raise SystemExit(
                "When using --tile-r0/--tile-r1/--tile-c0/--tile-c1, you must provide all four."
            )
        r0, r1, c0, c1 = (
            int(args.tile_r0),
            int(args.tile_r1),
            int(args.tile_c0),
            int(args.tile_c1),
        )
    else:
        if args.tile_r is None or args.tile_c is None:
            raise SystemExit(
                "Provide either --tile-r/--tile-c, or a range via --tile-r0..--tile-c1, or --all."
            )
        r0 = r1 = int(args.tile_r)
        c0 = c1 = int(args.tile_c)

    # Basic bounds guard
    if not (0 <= r0 <= r1 < ntr and 0 <= c0 <= c1 < ntc):
        raise SystemExit(
            f"Tile range out of bounds for grid {grid.grid_id}: "
            f"r0..r1 must be within [0,{ntr-1}] and c0..c1 within [0,{ntc-1}]. "
            f"Got r{r0}-{r1} c{c0}-{c1}."
        )

    run(
        out_root=args.out_root,
        grid=grid,
        metric=args.metric,
        start_year=args.start_year,
        end_year=args.end_year,
        cache_dir=args.cache_dir,
        overwrite_download=args.overwrite_download,
        debug=args.debug,
        tile_r0=r0,
        tile_r1=r1,
        tile_c0=c0,
        tile_c1=c1,
        batch_tiles=int(args.batch_tiles),
        resume=bool(args.resume),
        max_downloads=args.max_downloads,
    )
