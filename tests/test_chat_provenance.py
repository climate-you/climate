"""
Tests for the tool-call provenance shown in the chat transcript.

Each completed tool call reports the dataset, metric, and *resolved* place it
read, so a mis-resolution is visible in the UI rather than hidden behind the
name the model happened to ask for.
"""

from __future__ import annotations

import json

import pytest

from climate_api.chat.canned import build_chart_provenance
from climate_api.chat.orchestrator import (
    ChatOrchestrator,
    _dataset_family,
    _describe_months,
    _humanise_region_id,
    describe_metric_source,
)


class _FakeTileStore:
    def __init__(self, metrics: dict):
        self.metrics = metrics


METRICS = {
    "t2m_yearly_mean_c": {
        "id": "t2m_yearly_mean_c",
        "title": "2m temperature yearly mean",
        "source": {"type": "cds", "_dataset_ref": "era5_daily_t2m"},
    },
    "tp_annual_total_mm": {
        "id": "tp_annual_total_mm",
        "title": "Total precipitation yearly sum",
        "source": {"type": "cds", "_dataset_ref": "era5_daily_tp"},
    },
    "sst_yearly_mean_c": {
        "id": "sst_yearly_mean_c",
        "title": "SST yearly mean",
        "source": {"type": "erddap", "_dataset_ref": "oisst_sst_v21_daily"},
    },
    "dhw_severe_risk_days_per_year": {
        "id": "dhw_severe_risk_days_per_year",
        "title": "Coral reef DHW severe-risk days",
        "source": {"type": "erddap", "_dataset_ref": "crw_dhw_daily"},
    },
    "no_source_metric": {"id": "no_source_metric", "title": "Odd one out"},
}

DATASET_TITLES = {
    "era5_daily_t2m": "ERA5 daily 2m temperature",
    "era5_daily_tp": "ERA5 daily total precipitation",
    "oisst_sst_v21_daily": "OISST v2.1 daily SST",
    "crw_dhw_daily": "NOAA Coral Reef Watch daily Degree Heating Week",
}


@pytest.fixture
def orchestrator():
    return ChatOrchestrator(
        tiers=[],
        tile_store=_FakeTileStore(METRICS),
        location_index=None,
        dataset_titles=DATASET_TITLES,
    )


# ---------------------------------------------------------------------------
# Dataset family (drives which icon the UI draws)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metric_id,expected",
    [
        ("t2m_yearly_mean_c", "temperature"),
        ("tp_annual_total_mm", "precipitation"),
        ("sst_yearly_mean_c", "sea_temperature"),
        ("dhw_severe_risk_days_per_year", "coral"),
    ],
)
def test_dataset_family(metric_id, expected):
    assert _dataset_family(METRICS[metric_id]) == expected


def test_dataset_family_defaults_to_temperature():
    assert _dataset_family({}) == "temperature"


# ---------------------------------------------------------------------------
# Region id humanising
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("globe", "Global"),
        ("ocean:indian_ocean", "Indian Ocean"),
        ("continent:north_america", "North America"),
        ("country:FR", "FR"),
        ("Köln, Germany", "Köln, Germany"),
        ("London, United Kingdom", "London, United Kingdom"),
    ],
)
def test_humanise_region_id(raw, expected):
    assert _humanise_region_id(raw) == expected


# ---------------------------------------------------------------------------
# Provenance assembly
# ---------------------------------------------------------------------------


def test_provenance_reports_resolved_location_not_requested(orchestrator):
    """The whole point: show where the call landed, not what was asked for."""
    result = json.dumps({"location": "Köln, Germany", "data": [1]})
    prov = orchestrator._provenance(
        "get_metric_series",
        {"metric_id": "t2m_yearly_mean_c", "location": "Cologne"},
        result,
    )
    assert prov["location"] == "Köln, Germany"
    assert prov["dataset_title"] == "ERA5 daily 2m temperature"
    assert prov["provider"] == "CDS"
    assert prov["metric_title"] == "2m temperature yearly mean"
    assert prov["datasets"] == "temperature"


def test_provenance_falls_back_to_requested_location_on_error(orchestrator):
    """A failed lookup still names what was attempted."""
    prov = orchestrator._provenance(
        "get_metric_series",
        {"metric_id": "t2m_yearly_mean_c", "location": "Nowhereville"},
        json.dumps({"error": "Location not found"}),
    )
    assert prov["location"] == "Nowhereville"


def test_provenance_humanises_region_calls(orchestrator):
    prov = orchestrator._provenance(
        "get_region_metric_series",
        {"metric_id": "sst_yearly_mean_c", "region_id": "ocean:indian_ocean"},
        json.dumps({"region_id": "ocean:indian_ocean", "data": [1]}),
    )
    assert prov["location"] == "Indian Ocean"
    assert prov["provider"] == "ERDDAP"


def test_provenance_is_none_without_a_metric(orchestrator):
    """Tools that read no dataset (e.g. list_available_metrics) show nothing."""
    assert orchestrator._provenance("list_available_metrics", {}, "{}") is None


def test_provenance_is_none_for_unknown_metric(orchestrator):
    assert (
        orchestrator._provenance("get_metric_series", {"metric_id": "nope"}, "{}")
        is None
    )


def test_provenance_survives_unparseable_result(orchestrator):
    """A non-JSON tool result must not break the event."""
    prov = orchestrator._provenance(
        "get_metric_series",
        {"metric_id": "t2m_yearly_mean_c", "location": "Paris"},
        "not json at all",
    )
    assert prov["location"] == "Paris"


def test_provenance_without_dataset_titles_falls_back_to_id():
    orch = ChatOrchestrator(
        tiers=[],
        tile_store=_FakeTileStore(METRICS),
        location_index=None,
        dataset_titles=None,
    )
    prov = orch._provenance(
        "get_metric_series",
        {"metric_id": "t2m_yearly_mean_c", "location": "Paris"},
        json.dumps({"location": "Paris, France", "data": [1]}),
    )
    assert prov["dataset_title"] == "era5_daily_t2m"


def test_provenance_handles_metric_without_source(orchestrator):
    prov = orchestrator._provenance(
        "get_metric_series",
        {"metric_id": "no_source_metric", "location": "Paris"},
        json.dumps({"location": "Paris, France", "data": [1]}),
    )
    assert prov["dataset_id"] is None
    assert prov["provider"] is None
    assert prov["metric_title"] == "Odd one out"


# ---------------------------------------------------------------------------
# Derived metrics resolve back to the observational source
# ---------------------------------------------------------------------------

DERIVED_METRICS = {
    **METRICS,
    "t2m_trend": {
        "id": "t2m_trend",
        "title": "2m temperature warming trend",
        "source": {"type": "derived", "inputs": ["t2m_yearly_mean_c"]},
    },
    "twice_derived": {
        "id": "twice_derived",
        "title": "Rolling mean of the trend",
        "source": {"type": "derived", "inputs": ["t2m_trend"]},
    },
    "cyclic_a": {
        "id": "cyclic_a",
        "source": {"type": "derived", "inputs": ["cyclic_b"]},
    },
    "cyclic_b": {
        "id": "cyclic_b",
        "source": {"type": "derived", "inputs": ["cyclic_a"]},
    },
    "orphan_derived": {
        "id": "orphan_derived",
        "title": "From nowhere",
        "source": {"type": "derived", "inputs": []},
    },
}


def test_derived_metric_reports_its_upstream_dataset():
    """A trend computed from ERA5 is still ERA5 — not "DERIVED" with no source."""
    d = describe_metric_source("t2m_trend", DERIVED_METRICS, DATASET_TITLES)
    assert d["provider"] == "CDS"
    assert d["dataset_title"] == "ERA5 daily 2m temperature"
    # The plotted metric keeps its own name.
    assert d["metric_title"] == "2m temperature warming trend"
    assert d["metric_id"] == "t2m_trend"


def test_derived_chain_is_followed_to_the_root():
    d = describe_metric_source("twice_derived", DERIVED_METRICS, DATASET_TITLES)
    assert d["dataset_title"] == "ERA5 daily 2m temperature"


def test_cyclic_derivation_terminates():
    """A malformed registry must not hang the request."""
    d = describe_metric_source("cyclic_a", DERIVED_METRICS, DATASET_TITLES)
    assert d is not None
    assert d["dataset_id"] is None


def test_derived_metric_with_no_inputs_reports_no_provider():
    d = describe_metric_source("orphan_derived", DERIVED_METRICS, DATASET_TITLES)
    assert d["provider"] is None
    assert d["dataset_title"] is None
    assert d["metric_title"] == "From nowhere"


def test_unknown_metric_returns_none():
    assert describe_metric_source("nope", DERIVED_METRICS, DATASET_TITLES) is None


# ---------------------------------------------------------------------------
# Canned-answer provenance (no tool loop to hang it off)
# ---------------------------------------------------------------------------


def _store():
    return _FakeTileStore(METRICS)


def test_canned_provenance_groups_by_metric_not_series():
    """Seven continents on one metric is one source, not seven cards."""
    spec = {
        "metric_id": "t2m_yearly_mean_c",
        "region_ids": [
            "continent:africa",
            "continent:europe",
            "continent:asia",
            "continent:oceania",
        ],
    }
    cards = build_chart_provenance(spec, [], _store(), DATASET_TITLES)
    assert len(cards) == 1
    assert cards[0]["location"] == "Africa · Europe +2 more"


def test_canned_provenance_one_card_per_distinct_metric():
    """A land-vs-sea comparison legitimately has two sources."""
    spec = {
        "series": [
            {"metric_id": "t2m_yearly_mean_c", "region_ids": ["globe"]},
            {"metric_id": "sst_yearly_mean_c", "region_ids": ["globe"]},
        ]
    }
    cards = build_chart_provenance(spec, [], _store(), DATASET_TITLES)
    assert [c["provider"] for c in cards] == ["CDS", "ERDDAP"]
    assert all(c["location"] == "Global" for c in cards)


def test_canned_provenance_uses_pinned_locations_without_regions():
    spec = {"metric_id": "t2m_yearly_mean_c"}
    locations = [
        {"label": "Khartoum", "lat": 15.5, "lon": 32.5},
        {"label": "Niamey", "lat": 13.5, "lon": 2.1},
    ]
    cards = build_chart_provenance(spec, locations, _store(), DATASET_TITLES)
    assert cards[0]["location"] == "Khartoum · Niamey"


def test_canned_provenance_resolves_country_names():
    spec = {"metric_id": "t2m_yearly_mean_c", "region_ids": ["country:UA"]}
    cards = build_chart_provenance(
        spec, [], _store(), DATASET_TITLES, {"UA": "Ukraine"}
    )
    assert cards[0]["location"] == "Ukraine"


def test_canned_provenance_falls_back_to_code_without_country_names():
    spec = {"metric_id": "t2m_yearly_mean_c", "region_ids": ["country:UA"]}
    cards = build_chart_provenance(spec, [], _store(), DATASET_TITLES)
    assert cards[0]["location"] == "UA"


def test_canned_provenance_empty_without_a_chart():
    """LLM-only nodes carry no chart_spec and get no card."""
    assert build_chart_provenance(None, [], _store(), DATASET_TITLES) == []
    assert build_chart_provenance({}, [], _store(), DATASET_TITLES) == []


def test_canned_provenance_skips_unknown_metrics():
    spec = {"metric_id": "not_a_real_metric", "region_ids": ["globe"]}
    assert build_chart_provenance(spec, [], _store(), DATASET_TITLES) == []


def test_canned_provenance_deduplicates_repeated_places():
    spec = {
        "series": [
            {"metric_id": "t2m_yearly_mean_c", "region_ids": ["globe", "globe"]},
        ]
    }
    cards = build_chart_provenance(spec, [], _store(), DATASET_TITLES)
    assert cards[0]["location"] == "Global"


# ---------------------------------------------------------------------------
# Month labelling in chart titles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "months,expected",
    [
        ([6], "June"),
        ([12, 1, 2], "December–February"),  # winter wraps the year end
        ([6, 7, 8], "June–August"),
        ([3, 4, 5], "March–May"),
        ([2, 1, 12], "December–February"),  # order must not matter
        ([1, 7], "January, July"),  # non-contiguous stays a list
        (list(range(1, 13)), None),  # a full year needs no qualifier
        ([], None),
        (None, None),
    ],
)
def test_describe_months(months, expected):
    assert _describe_months(months) == expected


def test_describe_months_ignores_out_of_range():
    assert _describe_months([6, 0, 13]) == "June"


def test_describe_months_deduplicates():
    assert _describe_months([6, 6, 6]) == "June"
