from __future__ import annotations

from types import SimpleNamespace

from climate_api.services.panels import _series_axis


def test_series_axis_infers_years_when_axis_shorter_than_vector() -> None:
    tile_store = SimpleNamespace(
        axis=lambda _metric: list(range(1999, 2026)),
        start_year_fallback=1979,
    )
    axis = _series_axis(tile_store, "dhw_no_risk_days_per_year", 41)
    assert axis[0] == 1985
    assert axis[-1] == 2025
    assert len(axis) == 41


def test_series_axis_trims_when_axis_longer_than_vector() -> None:
    tile_store = SimpleNamespace(
        axis=lambda _metric: list(range(1979, 2026)),
        start_year_fallback=1979,
    )
    axis = _series_axis(tile_store, "dhw_no_risk_days_per_year", 41)
    assert axis[0] == 1985
    assert axis[-1] == 2025
    assert len(axis) == 41
