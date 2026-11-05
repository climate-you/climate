from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climate.datasets.products.era5 import (
    build_daily_stats_request,
    build_monthly_means_request,
)
from climate.packager import registry
from climate.packager.registry import (
    TileRange,
    _download_batch_daily_stats,
    _download_batch_monthly_means,
    package_registry,
    roll_native_to_pm180,
)
from climate.tiles.layout import grid_from_id


def _globe(lon: np.ndarray, lat: np.ndarray | None = None) -> xr.Dataset:
    if lat is None:
        lat = 90.0 - 0.25 * np.arange(721)
    # Value = longitude, so a correct roll is checkable cell by cell.
    data = np.broadcast_to(lon[None, None, :], (1, lat.size, lon.size)).astype(
        np.float32
    )
    return xr.Dataset(
        {"t2m": (("valid_time", "latitude", "longitude"), data.copy())},
        coords={
            "valid_time": pd.to_datetime(["2021-01-01"]),
            "latitude": lat,
            "longitude": lon,
        },
    )


CDS_LON = 0.25 * np.arange(1440)  # what CDS returns with no area key


class TestRequests:
    def test_no_grid_key_when_grid_deg_none(self):
        req = build_daily_stats_request(
            years=["2021"], grid_deg=None, area=None, months=["01"]
        )
        assert "grid" not in req and "area" not in req
        req = build_monthly_means_request(years=["2021"], grid_deg=None, area=None)
        assert "grid" not in req and "area" not in req

    def test_cell_grid_requests_unchanged(self):
        req = build_daily_stats_request(
            years=["2021"], grid_deg=0.25, area=(1, 2, 3, 4), months=["01"]
        )
        assert req["grid"] == [0.25, 0.25]
        assert req["area"] == [1, 2, 3, 4]


class TestRollNativeToPm180:
    def test_rolls_longitudes_exactly(self, tmp_path: Path):
        _globe(CDS_LON).to_netcdf(tmp_path / "f.nc", format="NETCDF4")
        with xr.open_dataset(tmp_path / "f.nc") as raw:
            ds = roll_native_to_pm180(raw).load()
        lon = ds["longitude"].values
        assert lon[0] == -180.0 and lon[-1] == 179.75
        np.testing.assert_array_equal(np.diff(lon), 0.25)
        assert ds["latitude"].size == 721
        assert ds["latitude"].values[0] == 90.0
        # data moved with its coordinate: value 180 now sits at lon -180
        vals = ds["t2m"].isel(valid_time=0, latitude=0).values
        np.testing.assert_array_equal(vals, np.where(lon < 0, lon + 360, lon))

    def test_rejects_cell_centre_grid(self):
        lat = 89.875 - 0.25 * np.arange(720)
        with pytest.raises(ValueError, match="latitude"):
            roll_native_to_pm180(_globe(CDS_LON + 0.125, lat=lat))

    def test_rejects_two_decimal_longitudes(self):
        with pytest.raises(ValueError, match="longitude"):
            roll_native_to_pm180(_globe(np.round(CDS_LON + 0.005, 2)))

    def test_refuses_to_roll_twice(self):
        with pytest.raises(ValueError, match="longitude"):
            roll_native_to_pm180(roll_native_to_pm180(_globe(CDS_LON)))


class _FakeRetrieve:
    def __init__(self, ds: xr.Dataset):
        self.ds = ds
        self.calls: list[tuple[str, dict]] = []
        self.payloads: list[bytes] = []

    def __call__(self, dataset, request, target, *, overwrite=False):
        self.calls.append((dataset, request))
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.ds.to_netcdf(target, format="NETCDF4")
        self.payloads.append(Path(target).read_bytes())
        return target


@pytest.fixture
def fake_retrieve(monkeypatch):
    fake = _FakeRetrieve(_globe(CDS_LON))
    monkeypatch.setattr(registry, "retrieve", fake)
    return fake


GRID = grid_from_id("global_0p25", tile_size=64)
BATCH = TileRange(0, 3, 0, 3)  # any batch: native requests ignore it


def _daily(cache: Path, **kw) -> Path:
    return _download_batch_daily_stats(
        grid=GRID,
        cache_dir=cache,
        start_year=2021,
        end_year=2021,
        tile_range=BATCH,
        overwrite_download=False,
        debug=False,
        variable="2m_temperature",
        params=kw.pop("params", None),
        months=["01"],
        download_tile_range=TileRange(0, 11, 0, 22),
        native=True,
        **kw,
    )


class TestNativeDownload:
    def test_daily_whole_globe_no_slicing(self, tmp_path: Path, fake_retrieve):
        path = _daily(tmp_path)
        assert path == (
            tmp_path
            / "era5_daily_2m_temperature_daily_mean_native_globe"
            / "era5_daily_2m_temperature_daily_mean_native_globe_2021-2021_m01-01.nc"
        )
        (dataset, req) = fake_retrieve.calls[0]
        assert "area" not in req and "grid" not in req
        assert req["daily_statistic"] == "daily_mean"
        assert req["time_zone"] == "utc+00:00" and req["frequency"] == "1_hourly"
        # only the final file and its directory: no payload, no sliced copies
        assert [p.name for p in tmp_path.rglob("*")] == [path.parent.name, path.name]
        # kept exactly as CDS returned it
        assert path.read_bytes() == fake_retrieve.payloads[0]

    def test_non_native_payload_kept_and_nothing_written(
        self, tmp_path: Path, monkeypatch
    ):
        lat = 89.875 - 0.25 * np.arange(720)
        fake = _FakeRetrieve(_globe(CDS_LON + 0.125, lat=lat))
        monkeypatch.setattr(registry, "retrieve", fake)
        with pytest.raises(RuntimeError, match="non-native"):
            _daily(tmp_path)
        files = [p.name for p in tmp_path.rglob("*") if p.is_file()]
        assert files == [
            "era5_daily_2m_temperature_daily_mean_native_globe_2021-2021_m01-01.cds"
        ]

    def test_statistic_in_name(self, tmp_path: Path, fake_retrieve):
        path = _daily(tmp_path, params={"daily_statistic": "daily_maximum"})
        assert "_daily_maximum_native_globe_" in path.name
        assert fake_retrieve.calls[0][1]["daily_statistic"] == "daily_maximum"

    def test_reuses_cached_file(self, tmp_path: Path, fake_retrieve):
        first = _daily(tmp_path)
        mtime = first.stat().st_mtime_ns
        assert _daily(tmp_path) == first
        assert len(fake_retrieve.calls) == 1
        assert first.stat().st_mtime_ns == mtime

    def test_bad_cached_file_raises_and_is_kept(self, tmp_path: Path, fake_retrieve):
        path = _daily(tmp_path)
        lat = 89.875 - 0.25 * np.arange(720)
        _globe(CDS_LON + 0.125 - 180, lat=lat).to_netcdf(path)
        with pytest.raises(RuntimeError, match="not native"):
            _daily(tmp_path)
        assert path.exists()
        assert len(fake_retrieve.calls) == 1

    def test_rolled_cached_file_is_rejected(self, tmp_path: Path, fake_retrieve):
        # the November 4-5 files were rolled on write; they must not pass as raw
        path = _daily(tmp_path)
        roll_native_to_pm180(_globe(CDS_LON)).to_netcdf(path)
        with pytest.raises(RuntimeError, match="not native"):
            _daily(tmp_path)

    def test_leftover_payload_kept_without_refetch(
        self, tmp_path: Path, fake_retrieve, monkeypatch
    ):
        target = (
            tmp_path
            / "era5_daily_2m_temperature_daily_mean_native_globe"
            / "era5_daily_2m_temperature_daily_mean_native_globe_2021-2021_m01-01.nc"
        )
        target.parent.mkdir(parents=True)
        _globe(CDS_LON).to_netcdf(target.with_suffix(".cds"), format="NETCDF4")
        payload = target.with_suffix(".cds").read_bytes()
        # the real retrieve returns an existing target untouched
        monkeypatch.setattr(
            registry, "retrieve", lambda d, r, t, overwrite=False: Path(t)
        )
        assert _daily(tmp_path) == target
        assert not target.with_suffix(".cds").exists()
        assert target.read_bytes() == payload

    def test_monthly_request_and_name(self, tmp_path: Path, fake_retrieve):
        path = _download_batch_monthly_means(
            dataset="reanalysis-era5-single-levels-monthly-means",
            grid=GRID,
            cache_dir=tmp_path,
            start_year=2026,
            end_year=2026,
            tile_range=BATCH,
            overwrite_download=False,
            debug=False,
            variable="2m_temperature",
            params=None,
            months=["01", "02"],
            native=True,
        )
        assert path.name == (
            "cds_monthly_reanalysis_era5_single_levels_monthly_means_2m_temperature"
            "_native_globe_2026-2026_m01-02.nc"
        )
        req = fake_retrieve.calls[0][1]
        assert "area" not in req and "grid" not in req

    def test_monthly_rejects_non_era5(self, tmp_path: Path, fake_retrieve):
        with pytest.raises(ValueError, match="ERA5 only"):
            _download_batch_monthly_means(
                dataset="projections-cmip6",
                grid=GRID,
                cache_dir=tmp_path,
                start_year=2000,
                end_year=2000,
                tile_range=BATCH,
                overwrite_download=False,
                debug=False,
                variable="tas",
                params=None,
                native=True,
            )


class TestPackageRegistryGuards:
    def test_requires_download_only(self, tmp_path: Path):
        with pytest.raises(ValueError, match="download_only"):
            package_registry(out_root=tmp_path, native_download=True)

    def test_refuses_overwrite(self, tmp_path: Path):
        with pytest.raises(ValueError, match="never overwrites"):
            package_registry(
                out_root=tmp_path,
                native_download=True,
                download_only=True,
                overwrite_download=True,
            )
