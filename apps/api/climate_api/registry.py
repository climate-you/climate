from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any
import json


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    unit_kind: str  # "temp_abs" | "temp_delta" | "count" | ...


@dataclass(frozen=True)
class GraphSpec:
    id: str
    title: str
    series: List[SeriesSpec]


@dataclass(frozen=True)
class PanelSpec:
    id: str
    title: str
    graphs: List[str]  # graph ids


class Registry:
    def __init__(self, manifests_dir: Path):
        self.manifests_dir = manifests_dir
        self._graphs: Dict[str, GraphSpec] = {}
        self._panels: Dict[str, PanelSpec] = {}

    def load(self) -> None:
        graphs_p = self.manifests_dir / "graphs.json"
        panels_p = self.manifests_dir / "panels.json"

        graphs_j = json.loads(graphs_p.read_text("utf-8"))
        panels_j = json.loads(panels_p.read_text("utf-8"))

        graphs: Dict[str, GraphSpec] = {}
        for g in graphs_j.get("graphs", []):
            series = [
                SeriesSpec(key=s["key"], unit_kind=s.get("unit_kind", "raw"))
                for s in g.get("series", [])
            ]
            graphs[g["id"]] = GraphSpec(
                id=g["id"], title=g.get("title", g["id"]), series=series
            )

        panels: Dict[str, PanelSpec] = {}
        for p in panels_j.get("panels", []):
            panels[p["id"]] = PanelSpec(
                id=p["id"],
                title=p.get("title", p["id"]),
                graphs=list(p.get("graphs", [])),
            )

        self._graphs = graphs
        self._panels = panels

    def panel(self, panel_id: str) -> PanelSpec:
        if panel_id not in self._panels:
            raise KeyError(f"Unknown panel_id: {panel_id}")
        return self._panels[panel_id]

    def graph(self, graph_id: str) -> GraphSpec:
        if graph_id not in self._graphs:
            raise KeyError(f"Unknown graph_id: {graph_id}")
        return self._graphs[graph_id]

    def panel_graphs(self, panel_id: str) -> List[GraphSpec]:
        p = self.panel(panel_id)
        return [self.graph(gid) for gid in p.graphs]
