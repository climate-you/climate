from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from datetime import date

@dataclass(frozen=True)
class PanelPaths:
    svg: Path
    caption_md: Path
    meta_json: Path | None = None

def live_slug_dir(root: Path, asof: date, slug: str) -> Path:
    # root = web/public/data/live
    return root / asof.isoformat() / slug

def story_slug_dir(root: Path, slug: str) -> Path:
    # root = web/public/data/story
    return root / slug

def panel_paths(base_dir: Path, panel: str, unit: str) -> PanelPaths:
    """
    We generate:
      <panel>.<unit>.svg
      <panel>.<unit>.caption.md
    (Optional) <panel>.meta.json (shared between units)
    """
    unit = unit.upper()
    return PanelPaths(
        svg=base_dir / f"{panel}.{unit}.svg",
        caption_md=base_dir / f"{panel}.{unit}.caption.md",
        meta_json=None,
    )
