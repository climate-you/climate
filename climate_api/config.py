from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
from typing import Optional


@dataclass(frozen=True)
class Settings:
    release: str
    releases_root: Path
    latest_release_file: Path
    locations_csv: Path
    kdtree_path: Optional[Path]
    locations_index_csv: Path
    ocean_mask_npz: Optional[Path]
    ocean_names_json: Optional[Path]
    ocean_off_city_max_km: float
    ocean_city_override_max_km: float
    redis_url: Optional[str]
    ttl_resolve_s: int
    ttl_panel_s: int
    score_map_preload: bool
    cors_allow_origins: list[str]
    cors_allow_credentials: bool
    rate_limit_enabled: bool
    rate_limit_sustained_rps: int
    rate_limit_burst: int
    rate_limit_window_s: int
    repo_root: Path = Path(".")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    values = [item.strip() for item in raw.split(",")]
    return [item for item in values if item]


def load_settings() -> Settings:
    # Defaults match your repo layout
    repo_root = Path(os.environ.get("REPO_ROOT", ".")).resolve()

    release = os.environ.get("RELEASE", "latest")
    releases_root = Path(
        os.environ.get("RELEASES_ROOT", repo_root / "data" / "releases")
    )
    latest_release_file = Path(
        os.environ.get("LATEST_RELEASE_FILE", releases_root / "LATEST")
    )
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
    redis_url = os.environ.get("REDIS_URL")  # e.g. redis://localhost:6379/0
    ttl_resolve_s = int(os.environ.get("TTL_RESOLVE_S", "86400"))  # 1 day
    ttl_panel_s = int(os.environ.get("TTL_PANEL_S", "86400"))  # 1 day
    score_map_preload = _env_bool("SCORE_MAP_PRELOAD", False)
    cors_allow_origins = _env_list("CORS_ALLOW_ORIGINS", ["*"])
    cors_allow_credentials = _env_bool(
        "CORS_ALLOW_CREDENTIALS",
        "*" not in cors_allow_origins,
    )
    rate_limit_enabled = _env_bool("RATE_LIMIT_ENABLED", True)
    rate_limit_sustained_rps = int(os.environ.get("RATE_LIMIT_SUSTAINED_RPS", "5"))
    rate_limit_burst = int(os.environ.get("RATE_LIMIT_BURST", "20"))
    rate_limit_window_s = int(os.environ.get("RATE_LIMIT_WINDOW_S", "10"))

    return Settings(
        release=release,
        releases_root=releases_root,
        latest_release_file=latest_release_file,
        locations_csv=locations_csv,
        kdtree_path=kdtree_path,
        locations_index_csv=locations_index_csv,
        ocean_mask_npz=ocean_mask_npz,
        ocean_names_json=ocean_names_json,
        ocean_off_city_max_km=ocean_off_city_max_km,
        ocean_city_override_max_km=ocean_city_override_max_km,
        redis_url=redis_url,
        ttl_resolve_s=ttl_resolve_s,
        ttl_panel_s=ttl_panel_s,
        score_map_preload=score_map_preload,
        cors_allow_origins=cors_allow_origins,
        cors_allow_credentials=cors_allow_credentials,
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_sustained_rps=rate_limit_sustained_rps,
        rate_limit_burst=rate_limit_burst,
        rate_limit_window_s=rate_limit_window_s,
        repo_root=repo_root,
    )
