"""
Regression tests for the chat question tree (`climate_api/chat/question_tree.json`).

Two layers:

* **Structural** — navigation integrity, schema conformance, and answer-text
  formatting. These run everywhere; they only need the repo.
* **Data-backed** — every canned answer's `chart_spec` is executed against a
  real release through `build_canned_charts`, asserting it actually produces a
  chart with data. These skip when no release is present.

The data-backed layer exists because `build_canned_charts` swallows failures:
a renamed metric or region silently yields *no chart* while the answer text
still streams, so a broken chart spec is invisible without an explicit check.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from climate_api.chat.canned import CANNED, build_canned_charts
from climate_api.chat.question_tree import (
    QUESTION_TREE,
    ROOT_IDS,
    TREE_VERSION,
    QuestionNode,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = REPO_ROOT / "registry" / "metrics.json"
RELEASE_SERIES = REPO_ROOT / "data" / "releases" / "dev" / "series"

VALID_SCOPES = {"global", "country", "city", "local"}
VALID_DATASETS = {"temperature", "sea_temperature", "precipitation", "coral"}
VALID_LOCATION_FILTERS = {"any", "coastal", "tropical_coastal"}
VALID_REGION_PREFIXES = ("country:", "continent:", "ocean:")

_TOKEN_RE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")
_UNBALANCED_RE = re.compile(r"\[\[(?:(?!\]\]).)*$")

ACTIVE_NODES = {nid: n for nid, n in QUESTION_TREE.items() if n.status == "active"}
# Nodes carrying a pre-written answer *and* a chart to draw with it.
CHARTED_NODES = sorted(
    nid for nid, n in ACTIVE_NODES.items() if n.answer is not None and n.chart_spec
)


def _registry_metric_ids() -> set[str]:
    data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    return {k for k in data if k != "version"}


def _spec_metric_ids(spec: dict) -> list[str]:
    """All metric_ids a chart_spec references (single or multi-series form)."""
    if spec.get("series"):
        return [sub["metric_id"] for sub in spec["series"] if sub.get("metric_id")]
    return [spec["metric_id"]] if spec.get("metric_id") else []


def _spec_region_ids(spec: dict) -> list[str]:
    if spec.get("series"):
        return [r for sub in spec["series"] for r in sub.get("region_ids", [])]
    return list(spec.get("region_ids") or [])


def _spec_region_requests(spec: dict) -> list[tuple[str, str, str]]:
    """Flatten a chart_spec into (region_id, metric_id, aggregation) triples."""
    subs = spec.get("series") or [spec]
    return [
        (region_id, sub["metric_id"], sub.get("aggregation", "mean"))
        for sub in subs
        if sub.get("metric_id")
        for region_id in sub.get("region_ids") or []
    ]


# ---------------------------------------------------------------------------
# Structural integrity
# ---------------------------------------------------------------------------


def test_tree_version_is_a_date():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", TREE_VERSION), (
        f"TREE_VERSION {TREE_VERSION!r} should be an ISO date so analytics rows "
        "can be attributed to a dated revision of the tree"
    )


def test_node_ids_match_their_keys():
    for node_id, node in QUESTION_TREE.items():
        assert node.id == node_id


def test_root_ids_resolve():
    for root_id in ROOT_IDS:
        assert root_id in QUESTION_TREE, f"root_id {root_id!r} has no node"
        assert QUESTION_TREE[root_id].status == "active"


def test_follow_ups_resolve_to_active_nodes():
    dangling = [
        (node_id, fid)
        for node_id, node in ACTIVE_NODES.items()
        for fid in node.follow_up_ids
        if fid not in ACTIVE_NODES
    ]
    assert not dangling, f"follow-up chips point at missing/deferred nodes: {dangling}"


def test_every_node_is_reachable():
    reachable = set(ROOT_IDS)
    for node in ACTIVE_NODES.values():
        reachable.update(node.follow_up_ids)
    orphans = sorted(set(ACTIVE_NODES) - reachable)
    assert not orphans, f"nodes unreachable from any root or follow-up: {orphans}"


def test_no_node_lists_itself_as_follow_up():
    self_refs = [nid for nid, n in ACTIVE_NODES.items() if nid in n.follow_up_ids]
    assert not self_refs, f"nodes offering themselves as a follow-up: {self_refs}"


def test_tree_is_a_dag_not_a_tree():
    """Most questions are offered as a follow-up by more than one parent.

    This is deliberate, but it means anything walking the tree must dedupe by
    question id. Expanding once per distinct root→node path is combinatorial:
    the admin analytics view did exactly that and produced millions of rows,
    which was enough to crash the browser tab. This test pins the property so
    the next person to write a tree walker knows a plain recursive expansion
    is not safe here.
    """
    parents: dict[str, list[str]] = {}
    for node_id, node in ACTIVE_NODES.items():
        for child in node.follow_up_ids:
            parents.setdefault(child, []).append(node_id)

    shared = {c: p for c, p in parents.items() if len(p) > 1}
    assert shared, (
        "the tree is now a strict tree — if that is intentional this test can "
        "go, but check the admin question view first"
    )

    # Bound the cost of the dedupe-by-id walk the UI performs.
    edges = sum(len(n.follow_up_ids) for n in ACTIVE_NODES.values())
    assert edges < 1000, (
        f"{edges} follow-up edges — the admin view renders one row per edge, "
        "so this growing unbounded will bloat that page"
    )


@pytest.mark.parametrize("node_id", sorted(ACTIVE_NODES))
def test_node_schema(node_id: str):
    node: QuestionNode = ACTIVE_NODES[node_id]
    assert node.question.strip(), "question text must not be empty"
    assert node.scope in VALID_SCOPES
    assert node.datasets, "every node must declare at least one dataset"
    assert set(node.datasets) <= VALID_DATASETS
    assert node.location_filter in VALID_LOCATION_FILTERS


@pytest.mark.parametrize("node_id", sorted(ACTIVE_NODES))
def test_location_scope_and_placeholder_agree(node_id: str):
    """`{location}` may only appear where a location is actually required."""
    node = ACTIVE_NODES[node_id]
    has_placeholder = "{location}" in node.question
    if has_placeholder:
        assert (
            node.requires_location
        ), f"{node_id} substitutes {{location}} but does not require a location"
    if node.requires_location:
        assert node.scope == "local", (
            f"{node_id} requires a location so its scope should be 'local', "
            f"got {node.scope!r}"
        )


def test_local_nodes_defer_to_the_live_pipeline():
    """Location-specific nodes must not ship a hardcoded answer or chart."""
    for node_id, node in ACTIVE_NODES.items():
        if node.requires_location:
            assert node.answer is None, (
                f"{node_id} is location-specific but carries a canned answer, "
                "which would be wrong for every location but one"
            )
            assert (
                not node.chart_spec
            ), f"{node_id} is location-specific but carries a fixed chart_spec"


@pytest.mark.parametrize("node_id", sorted(ACTIVE_NODES))
def test_answer_text_is_finished(node_id: str):
    """No placeholder content should reach users."""
    answer = ACTIVE_NODES[node_id].answer
    if answer is None:
        return
    assert answer.strip(), f"{node_id} has an empty answer string"
    assert "TODO" not in answer, f"{node_id} still holds placeholder answer text"


@pytest.mark.parametrize("node_id", sorted(ACTIVE_NODES))
def test_temperature_tokens_are_well_formed(node_id: str):
    """[[C|F]] tokens must be balanced and carry both unit variants."""
    answer = ACTIVE_NODES[node_id].answer
    if answer is None:
        return
    assert not _UNBALANCED_RE.search(
        answer
    ), f"{node_id} has an unterminated [[C|F]] token — it would render raw"
    for celsius, fahrenheit in _TOKEN_RE.findall(answer):
        assert (
            celsius.strip() and fahrenheit.strip()
        ), f"{node_id} has a [[C|F]] token with an empty side"
        assert "[[" not in celsius and "[[" not in fahrenheit


def test_canned_lookup_covers_every_answered_node():
    """The question→answer lookup must not lose nodes to duplicate wording."""
    answered = {nid for nid, n in ACTIVE_NODES.items() if n.answer is not None}
    assert len(CANNED) == len(answered), (
        "CANNED has fewer entries than answered nodes — two nodes probably "
        "normalise to the same question text and one is shadowing the other"
    )


def test_question_wording_is_unique():
    seen: dict[str, str] = {}
    for node_id, node in ACTIVE_NODES.items():
        key = " ".join(node.question.strip().lower().split())
        assert (
            key not in seen
        ), f"{node_id} and {seen[key]} share the question text {node.question!r}"
        seen[key] = node_id


# ---------------------------------------------------------------------------
# Chart specs — static validation against the registry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("node_id", CHARTED_NODES)
def test_chart_spec_shape(node_id: str):
    spec = ACTIVE_NODES[node_id].chart_spec
    assert _spec_metric_ids(
        spec
    ), f"{node_id} has a chart_spec with no metric_id (neither direct nor in 'series')"

    # Aggregation names are open-ended (metrics may ship custom ones such as
    # "fraction_5pct"); availability is checked against the release below.
    aggregations = [spec.get("aggregation")] + [
        sub.get("aggregation") for sub in spec.get("series") or []
    ]
    for aggregation in aggregations:
        if aggregation is not None:
            assert (
                isinstance(aggregation, str) and aggregation
            ), f"{node_id} has an empty aggregation"

    start_year, end_year = spec.get("start_year"), spec.get("end_year")
    if start_year is not None and end_year is not None:
        assert start_year <= end_year, f"{node_id} has start_year after end_year"


@pytest.mark.parametrize("node_id", CHARTED_NODES)
def test_chart_metrics_exist_in_registry(node_id: str):
    known = _registry_metric_ids()
    for metric_id in _spec_metric_ids(ACTIVE_NODES[node_id].chart_spec):
        assert (
            metric_id in known
        ), f"{node_id} charts metric {metric_id!r}, which is not in registry/metrics.json"


@pytest.mark.parametrize("node_id", CHARTED_NODES)
def test_chart_region_ids_are_well_formed(node_id: str):
    for region_id in _spec_region_ids(ACTIVE_NODES[node_id].chart_spec):
        assert region_id == "globe" or region_id.startswith(VALID_REGION_PREFIXES), (
            f"{node_id} references region {region_id!r}; expected 'globe' or one of "
            f"{VALID_REGION_PREFIXES}"
        )


@pytest.mark.parametrize("node_id", CHARTED_NODES)
def test_location_charts_have_locations(node_id: str):
    """A chart_spec without region_ids plots the node's own `locations` list."""
    node = ACTIVE_NODES[node_id]
    if _spec_region_ids(node.chart_spec):
        return
    assert (
        node.locations
    ), f"{node_id} has no region_ids and no locations, so it would render no chart"
    for loc in node.locations:
        assert {"lat", "lon", "label"} <= set(
            loc
        ), f"{node_id} has a location missing lat/lon/label: {loc}"
        assert -90 <= loc["lat"] <= 90 and -180 <= loc["lon"] <= 180


# ---------------------------------------------------------------------------
# Chart specs — executed against real release data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tile_store():
    if not RELEASE_SERIES.is_dir():
        pytest.skip(f"no release data at {RELEASE_SERIES}")
    from climate_api.store.tile_data_store import TileDataStore

    return TileDataStore.discover(RELEASE_SERIES, metrics_path=METRICS_PATH)


@pytest.mark.parametrize("node_id", CHARTED_NODES)
def test_canned_chart_actually_renders(node_id: str, tile_store):
    """
    Every canned answer that promises a chart must produce one with data.

    This is the check that catches a metric or region being renamed in the
    registry without the question tree following: the answer keeps streaming,
    but the chart quietly disappears.
    """
    node = ACTIVE_NODES[node_id]
    charts = build_canned_charts(node.locations, node.chart_spec, tile_store)

    assert charts, (
        f"{node_id} produced no chart — its metric_id/region_ids likely no longer "
        f"resolve against the release (spec: {node.chart_spec})"
    )
    for chart in charts:
        series = chart.get("series") or []
        assert series, f"{node_id} produced a chart with no series"
        for s in series:
            assert s.get("x") and s.get(
                "y"
            ), f"{node_id} produced an empty series {s.get('label')!r}"
            assert len(s["x"]) == len(
                s["y"]
            ), f"{node_id} series {s.get('label')!r} has mismatched x/y lengths"


@pytest.mark.parametrize(
    "node_id",
    [nid for nid in CHARTED_NODES if _spec_region_ids(ACTIVE_NODES[nid].chart_spec)],
)
def test_every_requested_region_resolves(node_id: str, tile_store):
    """
    Partial resolution is a failure too: `build_canned_charts` drops regions
    that error, so a chart of seven continents silently becomes six. Checking
    each region at the source names the exact one that broke.
    """
    from climate_api.chat import tools as _tools

    for region_id, metric_id, aggregation in _spec_region_requests(
        ACTIVE_NODES[node_id].chart_spec
    ):
        assert (metric_id, aggregation) in tile_store.aggregates, (
            f"{node_id} needs aggregate ({metric_id}, {aggregation}), which the "
            "release does not provide"
        )
        result = _tools.get_region_metric_series(
            region_id=region_id,
            metric_id=metric_id,
            aggregation=aggregation,
            tile_store=tile_store,
        )
        assert "error" not in result, (
            f"{node_id}: region {region_id!r} failed to resolve for metric "
            f"{metric_id!r}: {result['error']}"
        )
        assert result.get(
            "data"
        ), f"{node_id}: region {region_id!r} resolved but returned no data points"


@pytest.mark.parametrize(
    "node_id",
    [
        nid
        for nid in CHARTED_NODES
        if not _spec_region_ids(ACTIVE_NODES[nid].chart_spec)
    ],
)
def test_every_pinned_location_resolves(node_id: str, tile_store):
    """Same check for the nodes that plot fixed city pins instead of regions."""
    from climate_api.chat import tools as _tools

    node = ACTIVE_NODES[node_id]
    spec = node.chart_spec
    for loc in node.locations:
        result = _tools._get_metric_series(
            lat=loc["lat"],
            lon=loc["lon"],
            metric_id=spec["metric_id"],
            tile_store=tile_store,
            start_year=spec.get("start_year"),
            end_year=spec.get("end_year"),
            month_filter=spec.get("month_filter"),
            aggregate_by_year=bool(spec.get("aggregate_by_year", False)),
        )
        assert "error" not in result, (
            f"{node_id}: pinned location {loc['label']!r} failed for metric "
            f"{spec['metric_id']!r}: {result['error']}"
        )
        assert result.get(
            "data"
        ), f"{node_id}: pinned location {loc['label']!r} returned no data points"
