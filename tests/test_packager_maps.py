from __future__ import annotations

import numpy as np

from climate.packager.maps import _stitch_longitude_edges, _warp_lat_to_mercator


def test_stitch_longitude_edges_averages_finite_edges() -> None:
    values = np.array(
        [
            [0.0, 10.0, 20.0],
            [2.0, 12.0, 6.0],
        ],
        dtype=np.float64,
    )

    stitched = _stitch_longitude_edges(values)

    np.testing.assert_allclose(stitched[:, 0], [10.0, 4.0])
    np.testing.assert_allclose(stitched[:, -1], [10.0, 4.0])
    np.testing.assert_allclose(stitched[:, 1], values[:, 1])


def test_stitch_longitude_edges_fills_missing_edge_from_other_side() -> None:
    values = np.array(
        [
            [np.nan, 1.0, 5.0],
            [3.0, 1.0, np.nan],
            [np.nan, 1.0, np.nan],
        ],
        dtype=np.float64,
    )

    stitched = _stitch_longitude_edges(values)

    assert stitched[0, 0] == 5.0
    assert stitched[0, -1] == 5.0
    assert stitched[1, 0] == 3.0
    assert stitched[1, -1] == 3.0
    assert np.isnan(stitched[2, 0])
    assert np.isnan(stitched[2, -1])


def test_warp_lat_to_mercator_has_no_top_bottom_nans_for_finite_input() -> None:
    nlat = 721
    nlon = 16
    lat = np.linspace(90.0, -90.0, num=nlat, dtype=np.float64)
    values = np.broadcast_to(lat[:, None], (nlat, nlon))

    merc = _warp_lat_to_mercator(values)

    assert np.all(np.isfinite(merc[0, :]))
    assert np.all(np.isfinite(merc[-1, :]))
