"""Region outlines for the map overlay, built by scripts/build/build_region_shapes.py.

Each outline is held as ready-to-send JSON text rather than as parsed
coordinates: the API only ever passes it through, and ~3.7 MB of text is far
lighter than the tens of megabytes the same vertices take as Python lists.

The file is optional. Without it the explorer still shows region panels, it
just draws no outline — so a server whose location assets predate this file
keeps working.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("uvicorn.error")


class RegionShapes:
    def __init__(self, path: Path | None) -> None:
        self._shapes: dict[str, str] = {}
        if path is None:
            return
        if not path.exists():
            logger.warning(
                "Region shapes not found at %s; region outlines are disabled", path
            )
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._shapes = {
            region_id: json.dumps(geometry, separators=(",", ":"))
            for region_id, geometry in raw.items()
        }
        logger.info("Loaded %d region outlines from %s", len(self._shapes), path)

    def get(self, region_id: str) -> str | None:
        """The region's GeoJSON geometry as JSON text, or None if it has none."""
        return self._shapes.get(region_id)

    def __len__(self) -> int:
        return len(self._shapes)
