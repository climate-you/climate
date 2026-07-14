from __future__ import annotations

from climate.packager.registry import (
    TileRange,
    _covering_download_range,
    _resolve_batch_tiles,
    _resolve_download_batch_tiles,
)


class TestResolveDownloadBatchTiles:
    def test_override_does_not_shrink_downloads(self):
        # Dataset batches at 24; metric shrinks compute to 4. Downloads must
        # stay at the dataset's 24 so requests are not multiplied.
        src = {"batch_tiles": 24, "batch_tiles_override": 4}
        compute = _resolve_batch_tiles(None, src)
        download = _resolve_download_batch_tiles(None, src, compute)
        assert compute == 4
        assert download == 24

    def test_no_override_download_equals_compute(self):
        src = {"batch_tiles": 4}
        compute = _resolve_batch_tiles(None, src)
        assert _resolve_download_batch_tiles(None, src, compute) == 4

    def test_cli_override_wins_for_downloads(self):
        src = {"batch_tiles": 24, "batch_tiles_override": 4}
        assert _resolve_download_batch_tiles(8, src, 8) == 8

    def test_download_never_below_compute(self):
        # Pathological: dataset batch smaller than compute batch.
        src = {"batch_tiles": 2, "batch_tiles_override": 6}
        compute = _resolve_batch_tiles(None, src)  # 6
        assert _resolve_download_batch_tiles(None, src, compute) == 6

    def test_missing_dataset_batch_falls_back_to_compute(self):
        src = {"batch_tiles_override": 4}
        assert _resolve_download_batch_tiles(None, src, 4) == 4


class TestCoveringDownloadRange:
    def test_whole_globe_maps_to_single_coarse_range(self):
        # Globe = 12 tile-rows x 23 tile-cols; download batch 24 covers it all.
        metric_range = TileRange(0, 11, 0, 22)
        ranges = set()
        for r0 in range(0, 12, 4):
            for c0 in range(0, 23, 4):
                fine = TileRange(r0, min(r0 + 3, 11), c0, min(c0 + 3, 22))
                cov = _covering_download_range(fine, metric_range, 24)
                ranges.add(
                    (cov.tile_r0, cov.tile_r1, cov.tile_c0, cov.tile_c1)
                )
        assert ranges == {(0, 11, 0, 22)}

    def test_covering_range_contains_the_fine_batch(self):
        metric_range = TileRange(0, 47, 0, 47)
        for r0 in range(0, 48, 4):
            for c0 in range(0, 48, 4):
                fine = TileRange(r0, r0 + 3, c0, c0 + 3)
                cov = _covering_download_range(fine, metric_range, 24)
                assert cov.tile_r0 <= fine.tile_r0 <= fine.tile_r1 <= cov.tile_r1
                assert cov.tile_c0 <= fine.tile_c0 <= fine.tile_c1 <= cov.tile_c1

    def test_two_coarse_blocks_when_range_exceeds_batch(self):
        # 48 rows with download batch 24 -> two coarse row-blocks.
        metric_range = TileRange(0, 47, 0, 23)
        blocks = set()
        for r0 in range(0, 48, 4):
            fine = TileRange(r0, r0 + 3, 0, 23)
            cov = _covering_download_range(fine, metric_range, 24)
            blocks.add((cov.tile_r0, cov.tile_r1))
        assert blocks == {(0, 23), (24, 47)}

    def test_no_override_range_equals_batch(self):
        metric_range = TileRange(0, 11, 0, 22)
        fine = TileRange(4, 7, 4, 7)
        assert _covering_download_range(fine, metric_range, 4) == fine
