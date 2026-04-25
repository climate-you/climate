from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

QuestionScope = Literal["global", "country", "city", "local"]
QuestionDataset = Literal["temperature", "sea_temperature", "precipitation", "coral"]
QuestionStatus = Literal["active", "deferred"]
LocationFilter = Literal["any", "coastal", "tropical_coastal"]


@dataclass
class QuestionNode:
    id: str
    question: str
    scope: QuestionScope
    datasets: list[QuestionDataset]
    follow_up_ids: list[str] = field(default_factory=list)
    requires_location: bool = False
    location_filter: LocationFilter = "any"
    answer: str | None = None
    locations: list[dict] = field(default_factory=list)
    chart_spec: dict | None = None
    status: QuestionStatus = "active"


def load_question_tree(
    json_path: Path,
) -> tuple[dict[str, QuestionNode], list[str], str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    version: str = data["version"]
    root_ids: list[str] = data["root_ids"]
    nodes: dict[str, QuestionNode] = {}
    for node_id, nd in data["nodes"].items():
        nodes[node_id] = QuestionNode(
            id=nd["id"],
            question=nd["question"],
            scope=nd["scope"],
            datasets=nd["datasets"],
            follow_up_ids=nd.get("follow_up_ids", []),
            requires_location=nd.get("requires_location", False),
            location_filter=nd.get("location_filter", "any"),
            answer=nd.get("answer"),
            locations=nd.get("locations", []),
            chart_spec=nd.get("chart_spec"),
            status=nd.get("status", "active"),
        )
    return nodes, root_ids, version


_JSON_PATH = Path(__file__).parent / "question_tree.json"
QUESTION_TREE, ROOT_IDS, TREE_VERSION = load_question_tree(_JSON_PATH)


def get_tree_metadata() -> dict:
    """Return API-safe dict: no answers, no chart specs, no deferred nodes."""
    return {
        "version": TREE_VERSION,
        "root_ids": ROOT_IDS,
        "questions": {
            node_id: {
                "id": node.id,
                "question": node.question,
                "scope": node.scope,
                "datasets": node.datasets,
                "follow_up_ids": node.follow_up_ids,
                "requires_location": node.requires_location,
                "location_filter": node.location_filter,
            }
            for node_id, node in QUESTION_TREE.items()
            if node.status == "active"
        },
    }
