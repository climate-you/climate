from __future__ import annotations

import numpy as np

from climate.packager.maps import _apply_palette, _stitch_longitude_edges, _warp_lat_to_mercator


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


def test_apply_palette_supports_transparent_nan() -> None:
    values = np.array([[0.0, np.nan], [1.0, 2.0]], dtype=np.float64)
    out = _apply_palette(
        values,
        vmin=0.0,
        vmax=2.0,
        colors=["#000000", "#ffffff"],
        nan_color="#112233",
        nan_alpha=0.0,
    )

    assert out.shape == (2, 2, 4)
    # NaN pixel should use configured color + transparent alpha.
    np.testing.assert_array_equal(out[0, 1], np.array([0x11, 0x22, 0x33, 0], dtype=np.uint8))
    # Finite pixels should be fully opaque.
    assert int(out[0, 0, 3]) == 255
    assert int(out[1, 0, 3]) == 255
    assert int(out[1, 1, 3]) == 255
