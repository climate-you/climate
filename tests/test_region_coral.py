"""Coral heat stress for a sea: the region panel's graph, headline and wording."""

from __future__ import annotations

from types import SimpleNamespace

from climate.registry.panels import load_panels
from climate_api.services import panels as panels_module

YEARS = [2014, 2015, 2016, 2017]


def _fraction(values_by_region: dict[str, list]) -> dict:
    return {
        "time_axis": YEARS,
        "regions": {
            rid: {"name": rid, "type": "ocean", "reef_cell_count": 900, "values": v}
            for rid, v in values_by_region.items()
        },
    }


def _store() -> SimpleNamespace:
    aggregation = panels_module.REGION_CORAL_AGGREGATION
    return SimpleNamespace(
        aggregates={
            # Listed first on purpose: its reef cell count must not stand in for
            # the sea's footprint.
            ("dhw_severe_risk_days_per_year", aggregation): _fraction(
                {"ocean:coral_sea": [0, 40, 60, None]}
            ),
            ("dhw_moderate_risk_days_per_year", aggregation): _fraction(
                {"ocean:coral_sea": [5, 60, 40, None]}
            ),
            ("t2m_yearly_mean_c", "mean"): {
                "time_axis": YEARS,
                "regions": {
                    "ocean:coral_sea": {
                        "name": "Coral Sea",
                        "type": "ocean",
                        "cell_count": 5644,
                        "values": [25.0] * 4,
                    }
                },
            },
        }
    )


def _headlines(region_id: str) -> dict:
    return {
        h.key: h
        for h in panels_module._compute_coral_region_headlines(
            tile_store=_store(), region_id=region_id
        )
    }


def test_a_seas_worst_year_counts_moderate_and_severe_days_together() -> None:
    headlines = _headlines("ocean:coral_sea")
    # 2015 and 2016 both total 100 days; the earlier year wins, as for a point.
    assert headlines["dhw_worst_year_local"].value == 2015
    assert headlines["dhw_worst_year_days_local"].value == 100
    assert headlines["dhw_severe_local"].value == 1.0


def test_a_sea_without_reef_data_gets_no_coral_headline() -> None:
    # The frontend explains the gap when the keys are missing.
    assert _headlines("ocean:north_sea") == {}


def test_the_seas_footprint_is_not_taken_from_its_reef_cells() -> None:
    assert panels_module._region_cell_count(_store(), "ocean:coral_sea") == 5644


def _coral_graph() -> dict:
    manifest = load_panels(validate=False)
    return next(
        g
        for panel in manifest["panels"].values()
        for g in panel.get("graphs", [])
        if g.get("id") == "dhw_risk_days"
    )


def test_the_coral_chart_text_names_the_sea_instead_of_the_globe() -> None:
    # Pins the phrase the rewording looks for to the registry text: if the
    # registry is reworded, this fails rather than the region silently reading
    # "globally".
    graph = _coral_graph()
    assert panels_module._CORAL_GLOBAL_PHRASE in graph["ui"]["info_text"]

    ui = panels_module._region_graph_ui(graph, "the Coral Sea")
    assert "of the coral reef cells in the Coral Sea" in ui["info_text"]
    assert "globally" not in ui["info_text"]


def test_the_coral_headline_bubbles_describe_a_share_of_the_seas_reefs() -> None:
    spec = panels_module._with_region_coral_texts(
        _coral_graph()["headline"], "the Coral Sea"
    )
    text = spec["info_bubble_texts"]["coral_worst_year"]
    assert "at least 10% of the coral reef cells in the Coral Sea" in text
    # Only the coral headline is touched.
    assert panels_module._with_region_coral_texts({"type": "trend"}, "x") == {
        "type": "trend"
    }
