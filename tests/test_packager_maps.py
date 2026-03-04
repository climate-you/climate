from __future__ import annotations

import numpy as np
import pytest

from climate.packager.maps import (
    _apply_palette,
    _downsample_half_preserve_alpha,
    _mobile_texture_output_path,
    _resolve_mobile_size,
    _stitch_longitude_edges,
    _warp_lat_to_mercator,
)


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
    nlat = 720
    nlon = 16
    lat = 90.0 - (np.arange(nlat, dtype=np.float64) + 0.5) * (180.0 / float(nlat))
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


def test_resolve_mobile_size_defaults_to_half_resolution() -> None:
    image = np.zeros((3402, 7200, 4), dtype=np.uint8)
    width, height = _resolve_mobile_size(image=image, output={})
    assert width == 3600
    assert height == 1701


def test_mobile_texture_output_path_requires_matching_format(tmp_path) -> None:
    spec = {
        "file_format": "webp",
        "output": {"filename": "a.webp", "mobile_filename": "a.mobile.png"},
    }
    with pytest.raises(ValueError, match="does not match"):
        _mobile_texture_output_path(map_id="m", out_dir=tmp_path, spec=spec)


def test_downsample_half_preserve_alpha_keeps_sparse_opaque_pixel() -> None:
    img = np.zeros((2, 2, 4), dtype=np.uint8)
    # Exactly one opaque pixel in the 2x2 block.
    img[1, 0] = np.array([200, 10, 10, 255], dtype=np.uint8)
    out = _downsample_half_preserve_alpha(img)
    assert out.shape == (1, 1, 4)
    np.testing.assert_array_equal(out[0, 0], img[1, 0])
