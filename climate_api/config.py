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
    country_mask_npz: Optional[Path]
    country_codes_json: Optional[Path]
    country_names_json: Optional[Path]
    country_constrained_max_km: float
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
    analytics_db_path: Path = Path("data/analytics/events.db")
    analytics_ip_blocklist: Path = Path("data/analytics/ip_blocklist.txt")
    analytics_enabled: bool = False
    geoip_cache_ttl_s: int = 3600
    artifacts_root: Optional[Path] = None
    # Chat / LLM provider config
    chat_enabled: bool = False
    chat_dev_mode: bool = True   # safe default — set CHAT_DEV_MODE=0 in production
    chat_max_steps: int = 5
    # Groq keys — free key is used for Tier 1 (70b free in prod, 8b in dev) and Tier 3 (8b fallback in prod).
    # Paid key is used only in prod for Tier 2 (70b paid). Never used in dev mode.
    groq_api_key_free: Optional[str] = None
    groq_api_key_paid: Optional[str] = None
    groq_model_primary: str = "llama-3.3-70b-versatile"
    groq_model_fallback: str = "llama-3.1-8b-instant"
    # Local Ollama (dev chain Tier 2)
    ollama_base_url: str = ""
    ollama_model: str = "qwen2.5:14b"


_FALSY_STRINGS = {"", "none", "null", "0", "false"}


def _env_optional_path(name: str, default: Optional[Path]) -> Optional[Path]:
    raw = os.environ.get(name)
    if raw is not None and raw.strip().lower() in _FALSY_STRINGS:
        return None
    if raw:
        return Path(raw)
    return default


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
    kdtree_path = _env_optional_path(
        "KDTREE_PATH", repo_root / "data" / "locations" / "locations.kdtree.pkl"
    )

    locations_index_csv = Path(
        os.environ.get(
            "LOCATIONS_INDEX_CSV",
            repo_root / "data" / "locations" / "locations.index.csv",
        )
    )
    ocean_mask_npz = _env_optional_path(
        "OCEAN_MASK_NPZ", repo_root / "data" / "locations" / "ocean_mask.npz"
    )

    ocean_names_json = _env_optional_path(
        "OCEAN_NAMES_JSON", repo_root / "data" / "locations" / "ocean_names.json"
    )

    ocean_off_city_max_km = float(os.environ.get("OCEAN_OFF_CITY_MAX_KM", "80.0"))
    ocean_city_override_max_km = float(
        os.environ.get("OCEAN_CITY_OVERRIDE_MAX_KM", "2.0")
    )
    country_mask_npz = _env_optional_path(
        "COUNTRY_MASK_NPZ", repo_root / "data" / "locations" / "country_mask.npz"
    )
    country_codes_json = _env_optional_path(
        "COUNTRY_CODES_JSON", repo_root / "data" / "locations" / "country_codes.json"
    )
    country_names_json = _env_optional_path(
        "COUNTRY_NAMES_JSON", repo_root / "data" / "locations" / "country_names.json"
    )
    country_constrained_max_km = float(
        os.environ.get("COUNTRY_CONSTRAINED_MAX_KM", "100.0")
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

    analytics_db_path = Path(
        os.environ.get(
            "ANALYTICS_DB_PATH", repo_root / "data" / "analytics" / "events.db"
        )
    )
    analytics_ip_blocklist = Path(
        os.environ.get(
            "ANALYTICS_IP_BLOCKLIST",
            repo_root / "data" / "analytics" / "ip_blocklist.txt",
        )
    )
    analytics_enabled = _env_bool("ANALYTICS_ENABLED", False)
    geoip_cache_ttl_s = int(os.environ.get("GEOIP_CACHE_TTL_S", "3600"))
    # Default: sibling of releases_root (e.g. data/releases/../artifacts = data/artifacts)
    artifacts_root = Path(
        os.environ.get("ARTIFACTS_ROOT", releases_root.parent / "artifacts")
    )

    chat_enabled = _env_bool("CHAT_ENABLED", False)
    chat_dev_mode = _env_bool("CHAT_DEV_MODE", True)
    chat_max_steps = int(os.environ.get("CHAT_MAX_STEPS", "5"))
    # GROQ_API_KEY accepted as a fallback alias for GROQ_API_KEY_FREE (backward compat)
    groq_api_key_free = os.environ.get("GROQ_API_KEY_FREE") or os.environ.get("GROQ_API_KEY") or None
    groq_api_key_paid = os.environ.get("GROQ_API_KEY_PAID") or None
    # GROQ_MODEL accepted as a fallback alias for GROQ_MODEL_PRIMARY (backward compat)
    groq_model_primary = os.environ.get("GROQ_MODEL_PRIMARY") or os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile"
    groq_model_fallback = os.environ.get("GROQ_MODEL_FALLBACK", "llama-3.1-8b-instant")
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "")
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

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
        country_mask_npz=country_mask_npz,
        country_codes_json=country_codes_json,
        country_names_json=country_names_json,
        country_constrained_max_km=country_constrained_max_km,
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
        analytics_db_path=analytics_db_path,
        analytics_ip_blocklist=analytics_ip_blocklist,
        analytics_enabled=analytics_enabled,
        geoip_cache_ttl_s=geoip_cache_ttl_s,
        artifacts_root=artifacts_root,
        chat_enabled=chat_enabled,
        chat_dev_mode=chat_dev_mode,
        chat_max_steps=chat_max_steps,
        groq_api_key_free=groq_api_key_free,
        groq_api_key_paid=groq_api_key_paid,
        groq_model_primary=groq_model_primary,
        groq_model_fallback=groq_model_fallback,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
    )
