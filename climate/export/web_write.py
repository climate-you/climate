from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text.strip() + "\n", encoding="utf-8")

def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def write_plotly_svg(path: Path, fig) -> None:
    """
    Requires plotly + kaleido.
    Uses fig.to_image() to avoid relying on browser rendering.
    """
    ensure_dir(path.parent)
    svg_bytes = fig.to_image(format="svg")
    path.write_bytes(svg_bytes)

def write_matplotlib_svg(path: Path, fig, *, transparent: bool = True) -> None:
    """
    Write a Matplotlib (or Cartopy-backed Matplotlib) figure to SVG.
    """
    ensure_dir(path.parent)
    fig.savefig(
        path,
        format="svg",
        bbox_inches="tight",
        transparent=transparent,
    )
