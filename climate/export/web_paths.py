from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from datetime import date


@dataclass(frozen=True)
class PanelPaths:
    svg: Path
    caption_md: Path
    caption_json: Path
    meta_json: Path | None = None


def panel_paths(base_dir: Path, panel: str, unit: str) -> PanelPaths:
    """
    We generate:
      <panel>.<unit>.svg
      <panel>.<unit>.caption.md
      <panel>.<unit>.caption.json
    (Optional) <panel>.meta.json (shared between units)
    """
    unit = unit.upper()
    return PanelPaths(
        svg=base_dir / f"{panel}.{unit}.svg",
        caption_md=base_dir / f"{panel}.{unit}.caption.md",
        caption_json=base_dir / f"{panel}.{unit}.caption.json",
        meta_json=None,
    )


def live_slug_dir(root: Path, asof: date, slug: str) -> Path:
    # root = web/public/data/live
    return root / asof.isoformat() / slug


def story_slug_dir(root: Path, slug: str) -> Path:
    # root = web/public/data/story
    return root / slug
