from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
from typing import Optional


@dataclass(frozen=True)
class Settings:
    release: str
    locations_csv: Path
    kdtree_path: Optional[Path]
    locations_index_csv: Path
    ocean_mask_npz: Optional[Path]
    ocean_names_json: Optional[Path]
    ocean_off_city_max_km: float
    ocean_city_override_max_km: float
    tiles_series_root: Path
    maps_root: Path
    redis_url: Optional[str]
    ttl_resolve_s: int
    ttl_panel_s: int
    score_map_preload: bool


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    # Defaults match your repo layout
    repo_root = Path(os.environ.get("REPO_ROOT", ".")).resolve()

    release = os.environ.get("RELEASE", "dev")
    locations_csv = Path(
        os.environ.get(
            "LOCATIONS_CSV", repo_root / "data" / "locations" / "locations.csv"
        )
    )
    kdtree_env = os.environ.get("KDTREE_PATH")
    if kdtree_env is not None and kdtree_env.strip().lower() in {
        "",
        "none",
        "null",
        "0",
        "false",
    }:
        kdtree_path = None
    elif kdtree_env:
        kdtree_path = Path(kdtree_env)
    else:
        kdtree_path = repo_root / "data" / "locations" / "locations.kdtree.pkl"

    locations_index_csv = Path(
        os.environ.get(
            "LOCATIONS_INDEX_CSV",
            repo_root / "data" / "locations" / "locations.index.csv",
        )
    )
    ocean_mask_env = os.environ.get("OCEAN_MASK_NPZ")
    if ocean_mask_env is not None and ocean_mask_env.strip().lower() in {
        "",
        "none",
        "null",
        "0",
        "false",
    }:
        ocean_mask_npz = None
    elif ocean_mask_env:
        ocean_mask_npz = Path(ocean_mask_env)
    else:
        ocean_mask_npz = repo_root / "data" / "locations" / "ocean_mask.npz"

    ocean_names_env = os.environ.get("OCEAN_NAMES_JSON")
    if ocean_names_env is not None and ocean_names_env.strip().lower() in {
        "",
        "none",
        "null",
        "0",
        "false",
    }:
        ocean_names_json = None
    elif ocean_names_env:
        ocean_names_json = Path(ocean_names_env)
    else:
        ocean_names_json = repo_root / "data" / "locations" / "ocean_names.json"

    ocean_off_city_max_km = float(os.environ.get("OCEAN_OFF_CITY_MAX_KM", "80.0"))
    ocean_city_override_max_km = float(
        os.environ.get("OCEAN_CITY_OVERRIDE_MAX_KM", "2.0")
    )
    tiles_series_root = Path(
        os.environ.get(
            "TILES_SERIES_ROOT",
            repo_root / "data" / "releases" / release / "series",
        )
    )
    maps_root = Path(
        os.environ.get(
            "MAPS_ROOT",
            repo_root / "data" / "releases" / release / "maps",
        )
    )
    redis_url = os.environ.get("REDIS_URL")  # e.g. redis://localhost:6379/0
    ttl_resolve_s = int(os.environ.get("TTL_RESOLVE_S", "86400"))  # 1 day
    ttl_panel_s = int(os.environ.get("TTL_PANEL_S", "86400"))  # 1 day
    score_map_preload = _env_bool("SCORE_MAP_PRELOAD", False)

    return Settings(
        release=release,
        locations_csv=locations_csv,
        kdtree_path=kdtree_path,
        locations_index_csv=locations_index_csv,
        ocean_mask_npz=ocean_mask_npz,
        ocean_names_json=ocean_names_json,
        ocean_off_city_max_km=ocean_off_city_max_km,
        ocean_city_override_max_km=ocean_city_override_max_km,
        tiles_series_root=tiles_series_root,
        maps_root=maps_root,
        redis_url=redis_url,
        ttl_resolve_s=ttl_resolve_s,
        ttl_panel_s=ttl_panel_s,
        score_map_preload=score_map_preload,
    )
