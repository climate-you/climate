from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from climate.tiles import spec


def test_tile_header_pack_unpack_and_dtype() -> None:
    hdr = spec.TileHeader(version=1, dtype_code=spec.DT_F32, nyears=2, tile_h=2, tile_w=3)
    packed = hdr.pack()
    parsed = spec.TileHeader.unpack(packed)
    assert parsed.dtype == np.dtype("<f4")
    assert parsed.ncell == 6
    assert parsed.expected_values() == 12


def test_write_and_read_series_tile(tmp_path: Path) -> None:
    tile_path = tmp_path / "r000_c000.bin"
    arr = np.arange(12, dtype=np.float32).reshape(2, 2, 3)
    spec.write_tile(tile_path, arr, dtype=np.float32, nyears=3, tile_h=2, tile_w=2)
    hdr, read_arr = spec.read_tile_array(tile_path)
    assert hdr.nyears == 3
    assert read_arr.shape == (2, 2, 3)
    assert np.allclose(read_arr, arr)

    hdr2, v = spec.read_cell_series(tile_path, o_lat=1, o_lon=0)
    assert hdr2.nyears == 3
    assert np.allclose(v, arr[1, 0, :])


def test_normalize_payload_validation() -> None:
    with pytest.raises(ValueError, match="Scalar tile expects shape"):
        spec._normalize_payload(
            np.ones((2, 2, 2), dtype=np.float32),
            nyears=0,
            tile_h=2,
            tile_w=2,
            dtype=np.dtype("<f4"),
        )
    with pytest.raises(ValueError, match="Series tile expects shape"):
        spec._normalize_payload(
            np.ones((2, 2), dtype=np.float32),
            nyears=2,
            tile_h=2,
            tile_w=2,
            dtype=np.dtype("<f4"),
        )
