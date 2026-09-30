from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from climate_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]
API_E2E_RELEASE = os.environ.get("API_E2E_RELEASE", "dev")
RUN_API_E2E = os.environ.get("RUN_API_E2E", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _missing_data_reason() -> str | None:
    release_metrics_path = (
        REPO_ROOT / "registry" / "metrics.json"
        if API_E2E_RELEASE == "dev"
        else REPO_ROOT
        / "data"
        / "releases"
        / API_E2E_RELEASE
        / "registry"
        / "metrics.json"
    )
    required_paths = [
        REPO_ROOT / "data" / "locations" / "locations.csv",
        REPO_ROOT / "data" / "locations" / "locations.index.csv",
        REPO_ROOT / "data" / "releases" / API_E2E_RELEASE / "series",
        REPO_ROOT / "data" / "releases" / API_E2E_RELEASE / "maps",
        release_metrics_path,
    ]
    missing = [
        str(path.relative_to(REPO_ROOT)) for path in required_paths if not path.exists()
    ]
    if missing:
        return f"Missing API e2e runtime data for release '{API_E2E_RELEASE}': {', '.join(missing)}"
    return None


_skip_reason = (
    None if RUN_API_E2E else "API e2e tests are opt-in; set RUN_API_E2E=1 to run."
)
if _skip_reason is None:
    _skip_reason = _missing_data_reason()
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(_skip_reason is not None, reason=_skip_reason or "skip"),
]


async def _asgi_get_json(
    app: Any, path: str, query: dict[str, Any] | None = None
) -> tuple[int, dict]:
    status: int | None = None
    body_chunks: list[bytes] = []
    query_string = urllib.parse.urlencode(query or {}).encode("utf-8")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    sent_once = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_once
        if not sent_once:
            sent_once = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    if status is None:
        raise AssertionError("ASGI response did not include status code.")
    return status, json.loads(b"".join(body_chunks).decode("utf-8"))


def _first_nonempty_autocomplete(app: Any, release: str) -> tuple[str, list[dict]]:
    for query in ("par", "new", "san", "lon", "tok"):
        status, data = asyncio.run(
            _asgi_get_json(
                app,
                f"/api/v/{release}/locations/autocomplete",
                query={"q": query},
            )
        )
        assert status == 200
        results = data.get("results", [])
        if results:
            return query, results
    raise AssertionError("Autocomplete returned no results for fallback queries.")


def test_panel_returns_graphs_and_series_payloads() -> None:
    app = create_app()
    release = API_E2E_RELEASE
    _, suggestions = _first_nonempty_autocomplete(app, release)
    first = suggestions[0]
    status, data = asyncio.run(
        _asgi_get_json(
            app,
            f"/api/v/{release}/panel",
            query={"lat": first["lat"], "lon": first["lon"]},
        )
    )
    assert status == 200

    panels = data.get("panels", [])
    assert panels, "Expected /panel to return at least one panel."

    graphs = [
        graph
        for scored_panel in panels
        for graph in scored_panel.get("panel", {}).get("graphs", [])
    ]
    assert graphs, "Expected /panel to return at least one graph."

    series_payload = data.get("series", {})
    assert series_payload, "Expected /panel to include series payloads."

    referenced_series_keys = {
        key for graph in graphs for key in graph.get("series_keys", [])
    }
    assert (
        referenced_series_keys
    ), "Expected at least one graph with non-empty series_keys."

    for key in referenced_series_keys:
        assert key in series_payload, f"Graph references missing series key: {key}"

    nonempty_series = [
        s
        for s in series_payload.values()
        if len(s.get("x", [])) > 0 and len(s.get("y", [])) > 0
    ]
    assert nonempty_series, "Expected at least one non-empty series in /panel response."

    for s in nonempty_series:
        assert len(s["x"]) == len(s["y"]), "Series x/y lengths should match."


def test_location_endpoints_return_suggestions_and_results() -> None:
    app = create_app()
    release = API_E2E_RELEASE
    query, suggestions = _first_nonempty_autocomplete(app, release)
    assert suggestions, f"Expected autocomplete suggestions for query={query!r}."

    first = suggestions[0]
    geonameid = int(first["geonameid"])
    lat = float(first["lat"])
    lon = float(first["lon"])

    status, resolved = asyncio.run(
        _asgi_get_json(
            app,
            f"/api/v/{release}/locations/resolve",
            query={"geonameid": geonameid},
        )
    )
    assert status == 200
    assert resolved.get("result") is not None, "Expected non-null resolve result."
    assert int(resolved["result"]["geonameid"]) == geonameid

    status, nearest = asyncio.run(
        _asgi_get_json(
            app,
            f"/api/v/{release}/locations/nearest",
            query={"lat": lat, "lon": lon},
        )
    )
    assert status == 200
    assert nearest.get("result") is not None, "Expected non-null nearest result."
    assert int(nearest["result"]["geonameid"]) > 0


def test_release_endpoint_resolves_requested_and_latest_alias() -> None:
    app = create_app()
    release = API_E2E_RELEASE

    status, resolved = asyncio.run(
        _asgi_get_json(
            app,
            f"/api/v/{release}/release",
        )
    )
    assert status == 200
    assert resolved.get("requested_release") == release
    assert isinstance(resolved.get("release"), str) and bool(resolved["release"])
    assert "layers" in resolved
    assert isinstance(resolved.get("version"), dict)
    assert resolved["version"].get("assets_release") == resolved["release"]
    assert isinstance(resolved["version"].get("app_version"), str) and bool(
        resolved["version"]["app_version"]
    )

    status, latest = asyncio.run(
        _asgi_get_json(
            app,
            "/api/v/latest/release",
        )
    )
    assert status == 200
    assert latest.get("requested_release") == "latest"
    assert isinstance(latest.get("release"), str) and bool(latest["release"])
    assert "layers" in latest
    assert isinstance(latest.get("version"), dict)


def _region_panel(app: Any, region_id: str) -> tuple[int, dict]:
    return asyncio.run(
        _asgi_get_json(
            app,
            f"/api/v/{API_E2E_RELEASE}/panel/region",
            {"region_id": region_id, "unit": "C"},
        )
    )


def test_country_search_hands_back_a_region_the_panel_endpoint_serves() -> None:
    app = create_app()
    status, data = asyncio.run(
        _asgi_get_json(
            app,
            f"/api/v/{API_E2E_RELEASE}/locations/autocomplete",
            {"q": "France", "limit": 1},
        )
    )
    assert status == 200
    (france,) = data["results"]
    assert france["kind"] == "country"
    assert france["region_id"] == "country:FR"

    status, panel = _region_panel(app, france["region_id"])
    assert status == 200
    assert panel["location"]["region_id"] == "country:FR"
    assert panel["location"]["place"]["label"] == "France"
    assert panel["location"]["region_cell_count"] > 0
    assert panel["location"]["place"]["population"] is None


def test_country_region_panel_has_no_sea_temperature_data() -> None:
    status, panel = _region_panel(create_app(), "country:FR")
    assert status == 200
    by_id = {p["panel"]["id"]: p["panel"] for p in panel["panels"]}
    assert {"air_temperature", "precipitation"} <= set(by_id)
    # Kept as a stub, so the frontend can say "not available here".
    sea = by_id["sea_temperature"]
    assert all(g["series_keys"] == [] for g in sea["graphs"])
    assert all(g["title"] for g in sea["graphs"])
    keys = {h["key"] for h in panel["headlines"]}
    assert "precip_global" in keys
    assert not keys & {"sst_recent_global", "sst_hotdays_global"}


def test_sea_region_panel_includes_sea_temperature() -> None:
    status, panel = _region_panel(create_app(), "ocean:north_sea")
    assert status == 200
    ids = {p["panel"]["id"] for p in panel["panels"]}
    assert "sea_temperature" in ids


@pytest.mark.parametrize(
    "region_id",
    [
        # Aggregates exist, but nothing in search can select them.
        "continent:europe",
        "globe",
        # Searchable, but too small or erased in the mask, so no aggregate.
        "country:MC",
        "ocean:great_barrier_reef",
        # Not a region at all.
        "country:ZZ",
        "../../etc/passwd",
    ],
)
def test_region_panel_refuses_anything_search_cannot_select(region_id: str) -> None:
    status, _ = _region_panel(create_app(), region_id)
    assert status == 404


def test_global_panel_carries_no_region_fields() -> None:
    status, panel = asyncio.run(
        _asgi_get_json(
            create_app(), f"/api/v/{API_E2E_RELEASE}/panel/global", {"unit": "C"}
        )
    )
    assert status == 200
    assert panel["location"]["region_id"] is None
    assert panel["location"]["region_cell_count"] is None


def _region_shape(app: Any, region_id: str) -> tuple[int, dict]:
    return asyncio.run(
        _asgi_get_json(
            app,
            f"/api/v/{API_E2E_RELEASE}/regions/shape",
            {"region_id": region_id},
        )
    )


def test_a_selectable_region_has_an_outline() -> None:
    status, shape = _region_shape(create_app(), "country:FR")
    assert status == 200
    assert shape["type"] == "MultiPolygon"
    assert shape["coordinates"]


@pytest.mark.parametrize(
    "region_id",
    [
        "continent:europe",
        "globe",
        "country:MC",
        "ocean:great_barrier_reef",
        "../../etc/passwd",
    ],
)
def test_no_outline_for_a_region_search_cannot_select(region_id: str) -> None:
    status, _ = _region_shape(create_app(), region_id)
    assert status == 404
