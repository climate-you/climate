from __future__ import annotations

import pytest

from climate.datasets.products.era5 import build_monthly_means_request
from climate.packager.registry import (
    _cap_months_for_block,
    _month_blocks,
    _partial_block_months,
    _resolve_partial_end,
    _year_blocks,
)


class TestYearBlocks:
    def test_full_years_unchanged(self):
        blocks = _year_blocks(2023, 2025, 1, dataset_start=None)
        assert [b[2] for b in blocks] == [[2023], [2024], [2025]]
        assert blocks[-1][1] == "2025-12-31"

    def test_partial_final_year_caps_end_date(self):
        blocks = _year_blocks(2024, 2026, 1, dataset_start=None, partial_end=(2026, 6))
        assert [b[2] for b in blocks] == [[2024], [2025], [2026]]
        assert blocks[-1] == ("2026-01-01", "2026-06-30", [2026])
        # complete years keep December end dates
        assert blocks[0][1] == "2024-12-31"

    def test_partial_year_isolated_from_multi_year_block(self):
        blocks = _year_blocks(2020, 2026, 5, dataset_start=None, partial_end=(2026, 6))
        # 2026 must not share a block with complete years
        assert [2026] in [b[2] for b in blocks]
        for _s, _e, years in blocks:
            if 2026 in years:
                assert years == [2026]

    def test_partial_end_month_day_count(self):
        blocks = _year_blocks(2026, 2026, 1, dataset_start=None, partial_end=(2026, 2))
        assert blocks[0][1] == "2026-02-28"

    def test_no_partial_matches_legacy_behaviour(self):
        legacy = _year_blocks(1979, 2025, 5, dataset_start=None)
        with_none = _year_blocks(1979, 2025, 5, dataset_start=None, partial_end=None)
        assert legacy == with_none


class TestMonthCapping:
    def test_caps_only_partial_year(self):
        month_blocks = _month_blocks(1)
        capped = _cap_months_for_block(month_blocks, [2026], (2026, 6))
        assert capped == [["01"], ["02"], ["03"], ["04"], ["05"], ["06"]]

    def test_complete_year_not_capped(self):
        month_blocks = _month_blocks(1)
        assert _cap_months_for_block(month_blocks, [2025], (2026, 6)) == month_blocks

    def test_no_partial_no_capping(self):
        month_blocks = _month_blocks(3)
        assert _cap_months_for_block(month_blocks, [2026], None) == month_blocks

    def test_multi_month_block_truncated(self):
        month_blocks = _month_blocks(4)  # [01-04], [05-08], [09-12]
        capped = _cap_months_for_block(month_blocks, [2026], (2026, 6))
        assert capped == [["01", "02", "03", "04"], ["05", "06"]]

    def test_partial_block_months(self):
        assert _partial_block_months([2026], (2026, 6)) == [
            "01", "02", "03", "04", "05", "06",
        ]
        assert _partial_block_months([2025], (2026, 6)) is None
        assert _partial_block_months([2026], None) is None


class TestResolvePartialEnd:
    def test_metric_level_end_month(self):
        source = {"_analysis_time_range": {"start_year": 1979, "end_year": 2026, "end_month": 6}}
        assert _resolve_partial_end(source, None, 2026, 2026) == (2026, 6)

    def test_dataset_level_end_month(self):
        source = {"time_range": {"start_year": 1979, "end_year": 2026, "end_month": 6}}
        assert _resolve_partial_end(source, None, 2026, 2026) == (2026, 6)

    def test_ignored_when_final_year_is_earlier(self):
        # Metric ends 2025 while the dataset extends to a partial 2026:
        # the metric's download does not reach the partial year.
        source = {
            "time_range": {"start_year": 1979, "end_year": 2026, "end_month": 6},
            "_analysis_time_range": {"start_year": 1979, "end_year": 2025},
        }
        assert _resolve_partial_end(source, None, 2025, 2025) is None

    def test_december_means_complete(self):
        source = {"time_range": {"start_year": 1979, "end_year": 2026, "end_month": 12}}
        assert _resolve_partial_end(source, None, 2026, 2026) is None

    def test_cli_override(self):
        assert _resolve_partial_end({}, 6, 2026, 2026) == (2026, 6)

    def test_invalid_month_rejected(self):
        source = {"time_range": {"start_year": 1979, "end_year": 2026, "end_month": 13}}
        with pytest.raises(ValueError):
            _resolve_partial_end(source, None, 2026, 2026)

    def test_no_end_month_returns_none(self):
        source = {"time_range": {"start_year": 1979, "end_year": 2025}}
        assert _resolve_partial_end(source, None, 2025, 2025) is None


class TestMonthlyMeansRequest:
    def test_default_requests_all_months(self):
        req = build_monthly_means_request(years=["2025"], grid_deg=0.25, area=None)
        assert req["month"] == [f"{m:02d}" for m in range(1, 13)]

    def test_months_override(self):
        req = build_monthly_means_request(
            years=["2026"], grid_deg=0.25, area=None, months=["01", "02"]
        )
        assert req["month"] == ["01", "02"]


class TestRegistryLoads:
    def test_metrics_registry_validates_with_end_month(self):
        from climate.registry.metrics import load_metrics

        manifest = load_metrics(path="registry/metrics.json", validate=True)
        tr = manifest["t2m_monthly_mean_c"]["source"]["_analysis_time_range"]
        assert tr["end_year"] == 2026 and tr["end_month"] == 6
        # Yearly metrics remain capped at the last complete year
        yearly_tr = manifest["t2m_yearly_mean_c"]["source"]["_analysis_time_range"]
        assert yearly_tr["end_year"] == 2025
