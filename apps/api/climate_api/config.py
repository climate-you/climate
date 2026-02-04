from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
from typing import Optional


@dataclass(frozen=True)
class Settings:
    release: str
    locations_csv: Path
    tiles_series_root: Path
    redis_url: Optional[str]
    ttl_resolve_s: int
    ttl_panel_s: int


def load_settings() -> Settings:
    # Defaults match your repo layout
    repo_root = Path(os.environ.get("REPO_ROOT", ".")).resolve()

    release = os.environ.get("RELEASE", "dev")
    locations_csv = Path(
        os.environ.get("LOCATIONS_CSV", repo_root / "locations" / "locations.csv")
    )
    tiles_series_root = Path(
        os.environ.get(
            "TILES_SERIES_ROOT",
            repo_root / "data" / "releases" / release / "series",
        )
    )
    redis_url = os.environ.get("REDIS_URL")  # e.g. redis://localhost:6379/0
    ttl_resolve_s = int(os.environ.get("TTL_RESOLVE_S", "86400"))  # 1 day
    ttl_panel_s = int(os.environ.get("TTL_PANEL_S", "86400"))  # 1 day

    return Settings(
        release=release,
        locations_csv=locations_csv,
        tiles_series_root=tiles_series_root,
        redis_url=redis_url,
        ttl_resolve_s=ttl_resolve_s,
        ttl_panel_s=ttl_panel_s,
    )
