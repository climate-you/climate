from __future__ import annotations

import json
import logging
import os
import resource
import shutil
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from uvicorn.logging import AccessFormatter

from .analytics.db import AnalyticsDB, IPBlocklist
from .analytics.geo import GeoIPCache
from .cache import Cache, make_redis_client
from .config import load_settings
from .logging import configure_access_logger, format_access_line
from .release import ReleaseResolver
from .schemas import (
    GraphListResponse,
    LocationAutocompleteItem,
    LocationAutocompleteResponse,
    LocationNearestResponse,
    LocationResolveResponse,
    PanelListResponse,
    PlaceInfo,
    QueryPoint,
    ReleaseResolveResponse,
)
from .services.panels import (
    build_global_panels,
    build_panel_tiles_registry,
    build_scored_panels_tiles_registry,
)
from .chat.orchestrator import ChatOrchestrator, ProviderTier
from .chat.canned import lookup as _canned_lookup, stream_canned as _stream_canned, build_canned_charts as _build_canned_charts
from .chat.question_tree import get_tree_metadata as _get_tree_metadata
from .store.country_classifier import CountryClassifier
from .store.location_index import LocationIndex
from .store.ocean_classifier import OceanClassifier
from .store.place_resolver import PlaceResolver
from .system_stats import current_rss_bytes, system_memory
from .versioning import resolve_app_version

logging.getLogger("uvicorn.access").disabled = True


class _ClickBody(BaseModel):
    lat: float
    lon: float


class _MapContext(BaseModel):
    lat: float
    lon: float
    label: str


class _ConversationTurn(BaseModel):
    role: str   # "user" or "assistant"
    text: str


class _ChatRequest(BaseModel):
    question: str
    history: list[_ConversationTurn] | None = None  # prior turns (user+assistant pairs)
    map_context: _MapContext | None = None
    opt_out: bool = False
    session_id: str | None = (
        None  # browser-session UUID (groups all messages from one conversation)
    )
    message_id: str | None = None  # per-Q&A UUID (used for feedback/review endpoints)
    # Optional tier override — used by the dev UI toggle.
    # Valid values are tier names configured on the server (e.g. "groq_8b", "local").
    model_override: str | None = None
    # Temperature unit preference set by the frontend ("C" or "F").
    temperature_unit: str = "C"
    # Question-tree analytics fields (optional; omitted for user-typed questions).
    question_id: str | None = None
    parent_question_id: str | None = None
    question_tree_version: str | None = None


class _FeedbackBody(BaseModel):
    feedback: str | None  # "good", "bad", or null to clear


def _normalize_lon(lon: float) -> float:
    # Normalize wrapped-world longitudes (e.g. 359, 529) into [-180, 180).
    return ((float(lon) + 180.0) % 360.0) - 180.0


def _configure_uvicorn_like_access_logger() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

    # If uvicorn already attached handlers, reuse them; otherwise add one.
    if not access_logger.handlers:
        handler = logging.StreamHandler()
        access_logger.addHandler(handler)

    # Set a uvicorn-style formatter, but add duration at the end
    fmt = '%(client_addr)s - "%(request_line)s" %(status_code)s (%(duration_ms).1f ms)'
    for h in access_logger.handlers:
        h.setFormatter(AccessFormatter(fmt=fmt, use_colors=True))


def _build_chat_tiers(settings, logger) -> list[ProviderTier]:
    """
    Build the ordered list of provider tiers based on settings.

    Dev mode  (CHAT_DEV_MODE=1):
      Tier 1 — Groq 8b-instant free (fast, good enough for dev iteration)
      Tier 2 — Local Ollama qwen2.5:14b (if OLLAMA_BASE_URL is set)
      Tier 3 — Budget exhausted message (implicit, no tier object)

    Prod mode (default):
      Tier 1 — Groq 70b free   (GROQ_API_KEY_FREE)
      Tier 2 — Groq 70b paid   (GROQ_API_KEY_PAID, if set)
      Tier 3 — Groq 8b free    (GROQ_API_KEY_FREE, degraded-model notice shown)
      Tier 4 — Budget exhausted message (implicit, no tier object)
    """
    from groq import Groq

    tiers: list[ProviderTier] = []

    if settings.chat_dev_mode:
        # Dev: 8b first (fast), local Ollama as fallback
        if settings.groq_api_key_free:
            tiers.append(
                ProviderTier(
                    name="groq_8b",
                    client=Groq(api_key=settings.groq_api_key_free),
                    model=settings.groq_model_fallback,
                    is_degraded=False,
                    max_request_tokens=8000,
                )
            )
        if settings.ollama_base_url:
            try:
                from openai import OpenAI

                tiers.append(
                    ProviderTier(
                        name="local",
                        client=OpenAI(
                            base_url=settings.ollama_base_url, api_key="ollama"
                        ),
                        model=settings.ollama_model,
                        is_degraded=False,
                    )
                )
            except ImportError:
                logger.warning(
                    "openai package not installed — local Ollama tier unavailable."
                )
        # Extra dev-only tiers: available as explicit overrides (not in default chain)
        if settings.groq_api_key_free:
            tiers.append(
                ProviderTier(
                    name="groq_70b",
                    client=Groq(api_key=settings.groq_api_key_free),
                    model=settings.groq_model_primary,
                    is_degraded=False,
                    max_request_tokens=11000,
                )
            )
            tiers.append(
                ProviderTier(
                    name="groq_scout",
                    client=Groq(api_key=settings.groq_api_key_free),
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    is_degraded=False,
                    max_request_tokens=27500,
                )
            )
    else:
        # Prod: 70b free → 70b paid → 8b free (degraded)
        if settings.groq_api_key_free:
            tiers.append(
                ProviderTier(
                    name="groq_70b_free",
                    client=Groq(api_key=settings.groq_api_key_free),
                    model=settings.groq_model_primary,
                    is_degraded=False,
                    max_request_tokens=11000,
                )
            )
        if settings.groq_api_key_paid:
            tiers.append(
                ProviderTier(
                    name="groq_70b_paid",
                    client=Groq(api_key=settings.groq_api_key_paid),
                    model=settings.groq_model_primary,
                    is_degraded=False,
                    max_request_tokens=11000,
                )
            )
        if settings.groq_api_key_free:
            tiers.append(
                ProviderTier(
                    name="groq_8b",
                    client=Groq(api_key=settings.groq_api_key_free),
                    model=settings.groq_model_fallback,
                    is_degraded=True,
                    max_request_tokens=8000,
                )
            )

    return tiers


def create_app() -> FastAPI:
    settings = load_settings()
    app_version_info = resolve_app_version(repo_root=settings.repo_root)

    cache = Cache(prefix="climate_api")
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if settings.redis_url:
        cache.redis = make_redis_client(settings.redis_url)
        uvicorn_logger.info("Redis cache enabled: %s", settings.redis_url)
    else:
        uvicorn_logger.warning(
            "Redis cache disabled (REDIS_URL not set); using in-process cache only."
        )

    ocean_classifier = None
    if settings.ocean_mask_npz is not None:
        try:
            ocean_classifier = OceanClassifier(
                settings.ocean_mask_npz,
                settings.ocean_names_json,
            )
            uvicorn_logger.info(
                "Ocean classifier enabled: mask=%s names=%s",
                settings.ocean_mask_npz,
                settings.ocean_names_json,
            )
        except Exception as exc:
            uvicorn_logger.warning("Ocean classifier disabled: %s", exc)

    country_classifier = None
    if settings.country_mask_npz is not None:
        try:
            country_classifier = CountryClassifier(
                settings.country_mask_npz,
                settings.country_codes_json,
            )
            uvicorn_logger.info(
                "Country classifier enabled: mask=%s codes=%s",
                settings.country_mask_npz,
                settings.country_codes_json,
            )
        except Exception as exc:
            uvicorn_logger.warning("Country classifier disabled: %s", exc)

    country_names: dict[str, str] | None = None
    if settings.country_names_json is not None and settings.country_names_json.exists():
        try:
            country_names = json.loads(
                settings.country_names_json.read_text(encoding="utf-8")
            )
        except Exception as exc:
            uvicorn_logger.warning("Country names JSON failed to load: %s", exc)

    place_resolver = PlaceResolver(
        locations_csv=settings.locations_csv,
        kdtree_path=settings.kdtree_path,
        ocean_classifier=ocean_classifier,
        ocean_off_city_max_km=settings.ocean_off_city_max_km,
        ocean_city_override_max_km=settings.ocean_city_override_max_km,
        country_classifier=country_classifier,
        country_constrained_max_km=settings.country_constrained_max_km,
        country_names=country_names,
        cache=cache,
        ttl_resolve_s=settings.ttl_resolve_s,
        round_decimals=3,
    )
    location_index = LocationIndex(settings.locations_index_csv)

    analytics_db = AnalyticsDB(settings.analytics_db_path)
    analytics_db.check_schema()
    geoip_cache = GeoIPCache(ttl_s=settings.geoip_cache_ttl_s)
    ip_blocklist = IPBlocklist(settings.analytics_ip_blocklist)

    app = FastAPI(title="Climate API", version="0.1")
    access_logger = configure_access_logger()
    ip_windows: dict[str, deque[float]] = defaultdict(deque)
    ip_windows_lock = Lock()
    # Rolling CPU samples: (wall_time, cpu_user+sys_seconds). maxlen=20 gives
    # ~5 min history at a 15-second poll interval.
    cpu_samples: deque[tuple[float, float]] = deque(maxlen=20)
    cpu_samples_lock = Lock()
    release_resolver = ReleaseResolver(settings=settings, logger=uvicorn_logger)
    warm_release: str | None = None
    if settings.score_map_preload:
        try:
            warm_context = release_resolver.resolve_release_context("latest")
            warm_release = warm_context.release
            uvicorn_logger.info(
                "Startup score-map warmup completed for release '%s'.",
                warm_context.release,
            )
        except Exception as exc:
            uvicorn_logger.warning(
                "Startup score-map warmup skipped (latest/dev): %s",
                exc,
            )
    uvicorn_logger.info(
        "Startup version info: app_version=%s app_tag=%s app_commit=%s configured_release=%s warm_release=%s",
        app_version_info.app_version,
        app_version_info.app_tag,
        app_version_info.app_commit,
        settings.release,
        warm_release,
    )
    if settings.analytics_enabled:
        uvicorn_logger.info(
            "Analytics enabled: db=%s geoip_cache_ttl=%ds",
            settings.analytics_db_path,
            settings.geoip_cache_ttl_s,
        )
    else:
        uvicorn_logger.info("Analytics disabled (set ANALYTICS_ENABLED=1 to enable).")
    if settings.analytics_enabled:
        blocklist_count = len(ip_blocklist)
        if blocklist_count:
            uvicorn_logger.info(
                "IP blocklist: %d entr%s loaded from %s",
                blocklist_count,
                "y" if blocklist_count == 1 else "ies",
                settings.analytics_ip_blocklist,
            )
        else:
            uvicorn_logger.info(
                "IP blocklist: empty (file not found or blank): %s",
                settings.analytics_ip_blocklist,
            )
    geoip_test_ip = os.environ.get("GEOIP_TEST_IP", "").strip()
    if geoip_test_ip:
        uvicorn_logger.warning(
            "GEOIP_TEST_IP is set (%s) — GeoIP lookups are overridden. "
            "Unset this variable before deploying to production.",
            geoip_test_ip,
        )

    # Chat orchestrator — build provider tiers then initialise
    chat_orchestrator: ChatOrchestrator | None = None
    if settings.chat_enabled:
        chat_tiers = _build_chat_tiers(settings, uvicorn_logger)
        if chat_tiers:
            try:
                chat_ctx = release_resolver.resolve_release_context(settings.release)
                chat_orchestrator = ChatOrchestrator(
                    tiers=chat_tiers,
                    tile_store=chat_ctx.tile_store,
                    location_index=location_index,
                    country_names=country_names,
                    max_steps=settings.chat_max_steps,
                )
                tier_summary = ", ".join(f"{t.name}({t.model})" for t in chat_tiers)
                uvicorn_logger.info(
                    "Chat orchestrator initialised: dev_mode=%s tiers=[%s]",
                    settings.chat_dev_mode,
                    tier_summary,
                )
            except Exception as exc:
                uvicorn_logger.warning(
                    "Chat orchestrator failed to initialise: %s", exc
                )
        else:
            uvicorn_logger.warning(
                "CHAT_ENABLED=1 but no provider keys/URLs configured — chat disabled. "
                "Set GROQ_API_KEY_FREE (or GROQ_API_KEY) and/or OLLAMA_BASE_URL."
            )

    @app.middleware("http")
    async def access_log_with_timing(request: Request, call_next):
        if settings.rate_limit_enabled and request.url.path.startswith("/api/"):
            now = time.time()
            client_host = request.client.host if request.client else "unknown"
            max_events = max(
                settings.rate_limit_burst,
                settings.rate_limit_sustained_rps * settings.rate_limit_window_s,
            )
            window_s = max(1, settings.rate_limit_window_s)
            with ip_windows_lock:
                ip_window = ip_windows[client_host]
                while ip_window and (now - ip_window[0]) > window_s:
                    ip_window.popleft()
                if len(ip_window) >= max_events:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": "Rate limit exceeded. Please retry shortly."
                        },
                        headers={"Retry-After": "1"},
                    )
                ip_window.append(now)

        t0 = time.perf_counter()
        response = await call_next(request)
        dt_ms = (time.perf_counter() - t0) * 1000.0

        client = request.client
        client_addr = f"{client.host}:{client.port}" if client else "-"

        path = request.url.path
        if request.url.query:
            path += "?" + request.url.query
        http_ver = request.scope.get("http_version", "1.1")
        request_line = f"{request.method} {path} HTTP/{http_ver}"

        access_logger.info(
            format_access_line(client_addr, request_line, response.status_code, dt_ms)
        )

        response.headers["X-Response-Time-ms"] = f"{dt_ms:.1f}"
        return response

    # CORS for local dev; tighten for prod
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    def _extract_ip(request: Request) -> str:
        test_ip = os.environ.get("GEOIP_TEST_IP", "").strip()
        if test_ip:
            return test_ip
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else ""

    @app.post("/api/events/session", status_code=204)
    def record_session(request: Request):
        if not settings.analytics_enabled:
            return Response(status_code=204)
        ip = _extract_ip(request)
        if ip and ip_blocklist.is_blocked(ip):
            return Response(status_code=204)
        country, lat, lon = geoip_cache.lookup(ip) if ip else (None, None, None)
        analytics_db.record_session(country, lat, lon)
        return Response(status_code=204)

    @app.post("/api/events/click", status_code=204)
    def record_click(body: _ClickBody, request: Request):
        if not settings.analytics_enabled:
            return Response(status_code=204)
        ip = _extract_ip(request)
        if ip and ip_blocklist.is_blocked(ip):
            return Response(status_code=204)
        analytics_db.record_click(body.lat, body.lon)
        return Response(status_code=204)

    @app.get("/api/admin/events")
    def get_admin_events():
        return {
            "clicks": analytics_db.get_click_aggregates(),
            "origins": analytics_db.get_session_aggregates(),
        }

    @app.get("/api/admin/status")
    def get_admin_status():
        now_wall = time.time()
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        now_cpu = rusage.ru_utime + rusage.ru_stime

        with cpu_samples_lock:
            cpu_samples.append((now_wall, now_cpu))
            cutoff = now_wall - 60.0
            baseline = next(((t, c) for t, c in cpu_samples if t >= cutoff), None)

        cpu_1m_pct: float | None = None
        if baseline is not None and baseline[0] < now_wall:
            wall_delta = now_wall - baseline[0]
            cpu_delta = now_cpu - baseline[1]
            cpu_1m_pct = round(min(100.0, (cpu_delta / wall_delta) * 100.0), 1)

        disk = shutil.disk_usage(settings.repo_root)
        db_size_bytes = (
            settings.analytics_db_path.stat().st_size
            if settings.analytics_db_path.exists()
            else None
        )
        try:
            resolved_release = release_resolver.resolve_release_alias(settings.release)
        except Exception:
            resolved_release = settings.release
        return {
            "app": {
                "version": app_version_info.app_version,
                "tag": app_version_info.app_tag,
                "commit": app_version_info.app_commit,
                "branch": app_version_info.app_branch,
            },
            "release": resolved_release,
            "analytics": {
                "enabled": settings.analytics_enabled,
                "db_size_bytes": db_size_bytes,
                "last_event_ts": analytics_db.get_last_event_ts(),
            },
            "system": {
                "disk_total_bytes": disk.total,
                "disk_used_bytes": disk.used,
                "disk_free_bytes": disk.free,
                "rss_bytes": current_rss_bytes(),
                "cpu_1m_pct": cpu_1m_pct,
                **(
                    {
                        "mem_total_bytes": sys_mem["total"],
                        "mem_available_bytes": sys_mem["available"],
                    }
                    if (sys_mem := system_memory())
                    else {
                        "mem_total_bytes": None,
                        "mem_available_bytes": None,
                    }
                ),
            },
        }

    @app.get("/api/v/{release}/release", response_model=ReleaseResolveResponse)
    def resolve_release(release: str):
        context = release_resolver.resolve_release_context(release)
        return ReleaseResolveResponse(
            requested_release=release,
            release=context.release,
            layers=context.layers,
            version={
                "app_version": app_version_info.app_version,
                "app_tag": app_version_info.app_tag,
                "app_commit": app_version_info.app_commit,
                "assets_release": context.release,
            },
        )

    @app.get("/api/v/{release}/panel/global", response_model=PanelListResponse)
    def get_global_panel(
        release: str,
        unit: str = Query("C", pattern="^(C|F|c|f)$"),
    ):
        context = release_resolver.resolve_release_context(release)
        return build_global_panels(
            tile_store=context.tile_store,
            panels_manifest=context.panels_manifest,
            unit=unit,
            release=context.release,
        )

    @app.get("/api/v/{release}/panel", response_model=PanelListResponse)
    def get_panel(
        release: str,
        lat: float = Query(...),
        lon: float = Query(...),
        unit: str = Query("C", pattern="^(C|F|c|f)$"),
        selected_geonameid: int | None = Query(None, ge=1),
    ):
        context = release_resolver.resolve_release_context(release)
        lon = _normalize_lon(lon)
        selected_place = None
        if selected_geonameid is not None:
            hit = location_index.resolve_by_id(selected_geonameid)
            if hit is not None:
                selected_place = PlaceInfo(
                    geonameid=hit.geonameid,
                    label=hit.label,
                    lat=hit.lat,
                    lon=hit.lon,
                    distance_km=0.0,
                    country_code=hit.country_code,
                    population=hit.population,
                )
        return build_scored_panels_tiles_registry(
            place_resolver=place_resolver,
            tile_store=context.tile_store,
            cache=cache,
            ttl_panel_s=settings.ttl_panel_s,
            release=context.release,
            lat=lat,
            lon=lon,
            unit=unit,
            panels_manifest=context.panels_manifest,
            maps_manifest=context.maps_manifest,
            maps_root=context.maps_root,
            map_artifact_roots=context.map_artifact_roots or None,
            selected_place=selected_place,
            release_root=context.release_root,
        )

    @app.get(
        "/api/v/{release}/locations/autocomplete",
        response_model=LocationAutocompleteResponse,
    )
    def autocomplete_locations(
        release: str,
        q: str = Query(..., min_length=2),
        limit: int = Query(10, ge=1, le=50),
    ):
        release_resolver.resolve_release_context(release)
        hits = location_index.autocomplete(q, limit=limit)
        results = [
            LocationAutocompleteItem(
                geonameid=h.geonameid,
                label=h.label,
                lat=h.lat,
                lon=h.lon,
                country_code=h.country_code,
                population=h.population,
            )
            for h in hits
        ]
        return LocationAutocompleteResponse(query=q, results=results)

    @app.get(
        "/api/v/{release}/locations/resolve",
        response_model=LocationResolveResponse,
    )
    def resolve_location(
        release: str,
        geonameid: int | None = Query(None),
        label: str | None = Query(None),
    ):
        release_resolver.resolve_release_context(release)
        hit = None
        if geonameid is not None:
            hit = location_index.resolve_by_id(geonameid)
        elif label:
            hit = location_index.resolve_by_label(label)
        else:
            raise HTTPException(status_code=400, detail="Provide geonameid or label.")

        result = None
        if hit is not None:
            result = LocationAutocompleteItem(
                geonameid=hit.geonameid,
                label=hit.label,
                lat=hit.lat,
                lon=hit.lon,
                country_code=hit.country_code,
                population=hit.population,
            )

        return LocationResolveResponse(
            query=str(geonameid or label or ""),
            result=result,
        )

    @app.get(
        "/api/v/{release}/locations/nearest",
        response_model=LocationNearestResponse,
    )
    def nearest_location(
        release: str,
        lat: float = Query(...),
        lon: float = Query(...),
    ):
        release_resolver.resolve_release_context(release)
        lon = _normalize_lon(lon)
        place = place_resolver.resolve_place(lat, lon)
        return LocationNearestResponse(
            query=QueryPoint(lat=float(lat), lon=float(lon)),
            result=PlaceInfo(
                geonameid=int(place.geonameid),
                label=place.label,
                lat=float(place.lat),
                lon=float(place.lon),
                distance_km=float(place.distance_km),
                country_code=place.country_code,
                population=place.population,
            ),
        )

    @app.get("/api/v/{release}/location/graphs", response_model=GraphListResponse)
    def list_graphs(
        release: str,
        lat: float = Query(...),
        lon: float = Query(...),
        panel_id: str = Query("air_temperature"),
        unit: str = Query("C", pattern="^(C|F|c|f)$"),
    ):
        context = release_resolver.resolve_release_context(release)
        lon = _normalize_lon(lon)
        resp = build_panel_tiles_registry(
            place_resolver=place_resolver,
            tile_store=context.tile_store,
            cache=cache,
            ttl_panel_s=settings.ttl_panel_s,
            release=context.release,
            lat=lat,
            lon=lon,
            unit=unit,
            panel_id=panel_id,
            panels_manifest=context.panels_manifest,
            release_root=context.release_root,
        )
        return GraphListResponse(
            release=resp.release,
            unit=resp.unit,
            location=resp.location,
            panel_id=panel_id,
            graph_ids=[g.id for g in resp.panel.graphs],
        )

    # ------------------------------------------------------------------
    # Chat endpoints
    # ------------------------------------------------------------------

    @app.get("/api/chat/questions")
    def get_chat_questions():
        return _get_tree_metadata()

    @app.post("/api/chat")
    def chat(body: _ChatRequest, request: Request):
        if chat_orchestrator is None:
            raise HTTPException(
                status_code=503, detail="Chat is not enabled on this server."
            )

        map_ctx = (
            {
                "lat": body.map_context.lat,
                "lon": body.map_context.lon,
                "label": body.map_context.label,
            }
            if body.map_context
            else None
        )

        def _event_stream():
            import json as _json

            answer_text: list[str] = []
            message_id = body.message_id or str(__import__("uuid").uuid4())
            session_id = body.session_id or message_id
            step_count = 0
            tools_called: list[str] = []
            tool_calls_detail: list[dict] = []
            tier_used: str | None = None
            model_used: str | None = None
            rejected_tiers: list[str] = []
            model_override_used: str | None = None
            total_ms: int | None = None
            steps_timing: list[dict] | None = None
            error_text: str | None = None

            canned = _canned_lookup(body.question) if not body.model_override else None
            if canned is not None:
                canned_answer, canned_locs, canned_chart_spec, canned_follow_up_ids = canned
                canned_charts = (
                    _build_canned_charts(canned_locs, canned_chart_spec, chat_orchestrator.tile_store, body.temperature_unit)
                    if canned_chart_spec
                    else []
                )
                event_source = _stream_canned(
                    canned_answer, canned_locs, charts=canned_charts,
                    follow_up_ids=canned_follow_up_ids,
                    temperature_unit=body.temperature_unit,
                )
            else:
                event_source = chat_orchestrator.run(
                    question=body.question,
                    history=[(t.role, t.text) for t in body.history] if body.history else None,
                    map_context=map_ctx,
                    session_id=message_id,
                    model_override=body.model_override,
                    temperature_unit=body.temperature_unit,
                )

            for event in event_source:
                yield f"data: {_json.dumps(event)}\n\n"

                if event["type"] == "tool_call":
                    tools_called.append(event["name"])
                    tool_calls_detail.append(
                        {
                            "name": event["name"],
                            "args": event.get("args", {}),
                            "step": event.get("step"),
                        }
                    )
                elif event["type"] == "answer":
                    answer_text.append(event["text"])
                elif event["type"] == "error":
                    error_text = event.get("detail") or event.get("message")
                elif event["type"] == "done":
                    step_count = event.get("step_count", 0)
                    tier_used = event.get("tier")
                    model_used = event.get("model")
                    rejected_tiers = event.get("rejected_tiers") or []
                    model_override_used = event.get("model_override")
                    total_ms = event.get("total_ms")
                    steps_timing = event.get("steps_timing")

            if settings.chat_enabled and not body.opt_out:
                analytics_db.record_chat_message(
                    message_id=message_id,
                    session_id=session_id,
                    question=body.question,
                    answer=" ".join(answer_text) or None,
                    step_count=step_count,
                    tools_called=tools_called,
                    tool_calls_detail=tool_calls_detail or None,
                    tier=tier_used,
                    opt_out=body.opt_out,
                    map_lat=body.map_context.lat if body.map_context else None,
                    map_lon=body.map_context.lon if body.map_context else None,
                    map_label=body.map_context.label if body.map_context else None,
                    total_ms=total_ms,
                    steps_timing=steps_timing,
                    model=model_used,
                    rejected_tiers=rejected_tiers or None,
                    model_override=model_override_used,
                    error=error_text,
                    question_id=body.question_id,
                    parent_question_id=body.parent_question_id,
                    question_tree_version=body.question_tree_version,
                )

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/chat/{message_id}/feedback", status_code=204)
    def chat_feedback(message_id: str, body: _FeedbackBody):
        if body.feedback not in ("good", "bad", None):
            raise HTTPException(
                status_code=400, detail="feedback must be 'good', 'bad', or null."
            )
        if settings.chat_enabled:
            analytics_db.record_chat_feedback(message_id, body.feedback)
        return Response(status_code=204)

    @app.post("/api/chat/{message_id}/reviewed", status_code=204)
    def mark_chat_reviewed(message_id: str):
        if settings.chat_enabled:
            analytics_db.mark_bad_answer_reviewed(message_id)
        return Response(status_code=204)

    @app.get("/api/admin/chat/sessions")
    def admin_chat_sessions(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        feedback: str | None = Query(None),
    ):
        return {
            "messages": analytics_db.get_chat_messages(
                limit=limit, offset=offset, feedback=feedback
            ),
            "stats": analytics_db.get_chat_stats(),
        }

    @app.get("/api/admin/chat/bad-answers")
    def admin_chat_bad_answers(limit: int = Query(50, ge=1, le=200)):
        return {
            "bad_answers": analytics_db.get_chat_bad_answers(limit=limit),
            "stats": analytics_db.get_chat_stats(),
        }

    @app.get("/assets/v/{release}/{asset_path:path}")
    def get_release_asset(release: str, asset_path: str):
        canonical_release = release_resolver.resolve_release_alias(release)
        release_root = release_resolver.release_root(canonical_release)
        relative_path = asset_path.lstrip("/")
        if not relative_path:
            raise HTTPException(status_code=404, detail="Asset path is required.")

        if release == "latest":
            cache_control = "no-store"
        elif canonical_release == "dev":
            cache_control = "public, max-age=0, must-revalidate"
        else:
            cache_control = "public, max-age=31536000, immutable"

        headers = {"Cache-Control": cache_control}

        # For v2 releases, map assets live in the artifact store, not release_root.
        # Path pattern: maps/<map_id>/<filename>  (no grid_id segment).
        if canonical_release != "dev":
            try:
                context = release_resolver.resolve_release_context(canonical_release)
            except Exception:
                context = None
            if (
                context is not None
                and context.format_version >= 2
                and relative_path.startswith("maps/")
            ):
                parts = relative_path.split("/", 2)  # ["maps", map_id, filename]
                if len(parts) == 3:
                    _, map_id, filename = parts
                    artifact_root = context.map_artifact_roots.get(map_id)
                    if artifact_root is not None:
                        candidate = (artifact_root / filename).resolve()
                        if not candidate.exists() or not candidate.is_file():
                            raise HTTPException(
                                status_code=404,
                                detail=f"Asset not found: {relative_path}",
                            )
                        return FileResponse(candidate, headers=headers)

        candidate = (release_root / relative_path).resolve()
        try:
            candidate.relative_to(release_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid asset path.") from exc

        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(
                status_code=404, detail=f"Asset not found: {relative_path}"
            )

        return FileResponse(candidate, headers=headers)

    return app


app = create_app()
