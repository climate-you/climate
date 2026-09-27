"""Region panels: the aggregate-backed panel for a country or sea.

The globe panel is the same builder with ``region_id="globe"``, so these tests
also pin that the generalisation left the globe path alone.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from climate_api.schemas import PlaceInfo
from climate_api.services import panels as panels_module
from climate_api.services.panels import build_region_panels

YEARS = [2000, 2001, 2002, 2003, 2004]


def _region(name: str, values: list[float], cell_count: int) -> dict:
    return {"name": name, "type": "x", "cell_count": cell_count, "values": values}


def _tile_store() -> SimpleNamespace:
    """A land metric covering France, and a sea metric that does not."""
    return SimpleNamespace(
        aggregates={
            ("m_air", "mean"): {
                "time_axis": YEARS,
                "regions": {
                    "globe": _region("Globe", [14.0, 14.1, 14.2, 14.3, 14.4], 1000),
                    "country:FR": _region("France", [12.0, 12.2, 12.4, 12.6, 12.8], 42),
                },
            },
            ("m_sea", "mean"): {
                "time_axis": YEARS,
                "regions": {
                    "globe": _region("Globe", [18.0, 18.1, 18.2, 18.3, 18.4], 1000),
                    "ocean:north_sea": _region("North Sea", [10.0] * 5, 7),
                },
            },
        }
    )


def _manifest() -> dict:
    return {
        "panels": {
            "air": {
                "title": "Air",
                "graphs": [
                    {"id": "g_air", "series": [{"metric": "m_air", "unit": "C"}]},
                    # Shares the panel with a metric France has no data for.
                    {"id": "g_air_sea", "series": [{"metric": "m_sea", "unit": "C"}]},
                ],
            },
            "sea": {
                "title": "Sea",
                "graphs": [
                    {"id": "g_sea", "series": [{"metric": "m_sea", "unit": "C"}]}
                ],
            },
        }
    }


def _france_place() -> PlaceInfo:
    return PlaceInfo(
        geonameid=2200000070,
        label="France",
        lat=46.7,
        lon=2.55,
        distance_km=0.0,
        country_code="FR",
        population=None,
    )


def _build(region_id: str = "globe", **kwargs):
    return build_region_panels(
        tile_store=_tile_store(),
        panels_manifest=_manifest(),
        unit="C",
        release="dev",
        region_id=region_id,
        **kwargs,
    )


def _panel_ids(resp) -> list[str]:
    return [p.panel.id for p in resp.panels]


def test_region_panel_reads_the_region_series_not_the_globe() -> None:
    resp = _build("country:FR", region_label="France", place=_france_place())

    (air_key,) = [
        k for g in resp.panels[0].panel.graphs if g.id == "g_air" for k in g.series_keys
    ]
    assert resp.series[air_key].y == pytest.approx([12.0, 12.2, 12.4, 12.6, 12.8])


def test_panel_with_no_region_data_disappears() -> None:
    # France has no sea metric: the sea panel goes, without any rule naming it.
    resp = _build("country:FR", region_label="France", place=_france_place())
    assert _panel_ids(resp) == ["air"]


def test_graph_without_region_data_says_so_in_the_regions_own_words() -> None:
    resp = _build("country:FR", region_label="France", place=_france_place())
    graphs = {g.id: g for g in resp.panels[0].panel.graphs}

    assert graphs["g_air"].error is None
    assert graphs["g_air_sea"].series_keys == []
    assert graphs["g_air_sea"].error == "No France-wide data for this graph."


def test_region_location_carries_its_id_cell_count_and_point() -> None:
    resp = _build("country:FR", region_label="France", place=_france_place())
    loc = resp.location

    assert loc.region_id == "country:FR"
    assert loc.region_cell_count == 42
    assert loc.place.label == "France"
    assert (loc.query.lat, loc.query.lon) == (46.7, 2.55)
    # Population is withheld for regions: the only source is years stale.
    assert loc.place.population is None


def test_globe_panel_is_unchanged_by_the_generalisation() -> None:
    resp = _build()

    assert _panel_ids(resp) == ["air", "sea"]
    assert resp.location.place.label == "Global"
    assert resp.location.place.geonameid == 0
    assert resp.location.region_id is None
    assert resp.location.region_cell_count is None


# ---------------------------------------------------------------------------
# Headlines
# ---------------------------------------------------------------------------


def _headline_store() -> SimpleNamespace:
    years = list(range(1979, 2026))
    rising = [10.0 + 0.03 * (y - 1979) for y in years]
    return SimpleNamespace(
        aggregates={
            # Sea metrics, as in a real release: present, with globe and ocean
            # entries, but nothing for a country.
            ("sst_yearly_mean_c", "mean"): {
                "time_axis": years,
                "regions": {
                    "globe": _region("Globe", rising, 1000),
                    "ocean:north_sea": _region("North Sea", rising, 7),
                },
            },
            ("sst_hotdays_per_year", "mean"): {
                "time_axis": years,
                "regions": {
                    "globe": _region("Globe", rising, 1000),
                    "ocean:north_sea": _region("North Sea", rising, 7),
                },
            },
            ("tp_annual_total_mm", "mean"): {
                "time_axis": years,
                "regions": {
                    "globe": _region("Globe", rising, 1000),
                    "country:FR": _region("France", rising, 42),
                },
            },
        }
    )


def test_headline_is_omitted_for_a_region_the_metric_does_not_cover() -> None:
    h = panels_module._aggregate_recent_delta_headline(
        tile_store=_headline_store(),
        metric="sst_yearly_mean_c",
        key="sst_recent_global",
        label="Sea surface temperature recent change (France)",
        unit_in="C",
        unit_out="C",
        baseline_year=1982,
        region_id="country:FR",
        scope="France",
    )
    assert h is None


def test_globe_headline_still_blanks_rather_than_disappearing() -> None:
    # The omit rule is for regions. The globe keeps the blank tile it always
    # showed when its own entry is missing, so neither the global panel nor the
    # point panel's global comparisons change behaviour.
    store = SimpleNamespace(
        aggregates={
            ("sst_yearly_mean_c", "mean"): {
                "time_axis": [2000],
                "regions": {"country:FR": _region("France", [1.0], 1)},
            }
        }
    )
    h = panels_module._aggregate_recent_delta_headline(
        tile_store=store,
        metric="sst_yearly_mean_c",
        key="sst_recent_global",
        label="x",
        unit_in="C",
        unit_out="C",
        baseline_year=1982,
    )
    assert h is not None and h.value is None


def test_a_metric_missing_from_the_release_blanks_for_regions_too() -> None:
    # Absent metric is a release problem worth surfacing, not "not applicable".
    h = panels_module._aggregate_trend_headline(
        tile_store=_headline_store(),
        metric="no_such_metric",
        key="k",
        label="x",
        unit="days",
        baseline_year=1979,
        region_id="country:FR",
        scope="France",
    )
    assert h is not None and h.value is None


def _headline_keys(resp) -> set[str]:
    return {h.key for h in resp.headlines}


def test_region_panel_drops_headlines_it_cannot_fill() -> None:
    resp = build_region_panels(
        tile_store=_headline_store(),
        panels_manifest={"panels": {}},
        unit="C",
        release="dev",
        region_id="country:FR",
        region_label="France",
        place=_france_place(),
    )
    keys = _headline_keys(resp)
    assert "sst_recent_global" not in keys
    assert "sst_hotdays_global" not in keys


def test_precipitation_headline_is_for_regions_only() -> None:
    # A regional rainfall trend is meaningful; a global one is deliberately
    # not headlined, and the frontend shows a fixed note in its place.
    kwargs = dict(
        tile_store=_headline_store(),
        panels_manifest={"panels": {}},
        unit="C",
        release="dev",
    )

    region = build_region_panels(
        region_id="country:FR", region_label="France", place=_france_place(), **kwargs
    )
    globe = build_region_panels(**kwargs)

    precip = next(h for h in region.headlines if h.key == "precip_global")
    assert precip.label == "Annual precipitation (France)"
    assert precip.unit == "mm"
    assert precip.value is not None
    assert "precip_global" not in _headline_keys(globe)


def test_region_headlines_are_worded_for_the_region() -> None:
    resp = build_region_panels(
        tile_store=_headline_store(),
        panels_manifest={"panels": {}},
        unit="C",
        release="dev",
        region_id="country:FR",
        region_label="France",
        place=_france_place(),
    )
    precip = next(h for h in resp.headlines if h.key == "precip_global")
    assert "France" in precip.method
    assert "global" not in precip.method.lower()
