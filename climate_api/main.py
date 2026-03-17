from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from uvicorn.logging import AccessFormatter

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
    build_panel_tiles_registry,
    build_scored_panels_tiles_registry,
)
from .store.country_classifier import CountryClassifier
from .store.location_index import LocationIndex
from .store.ocean_classifier import OceanClassifier
from .store.place_resolver import PlaceResolver
from .versioning import resolve_app_version

logging.getLogger("uvicorn.access").disabled = True


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

    place_resolver = PlaceResolver(
        locations_csv=settings.locations_csv,
        kdtree_path=settings.kdtree_path,
        ocean_classifier=ocean_classifier,
        ocean_off_city_max_km=settings.ocean_off_city_max_km,
        ocean_city_override_max_km=settings.ocean_city_override_max_km,
        country_classifier=country_classifier,
        country_constrained_max_km=settings.country_constrained_max_km,
        cache=cache,
        ttl_resolve_s=settings.ttl_resolve_s,
        round_decimals=3,
    )
    location_index = LocationIndex(settings.locations_index_csv)

    app = FastAPI(title="Climate API", version="0.1")
    access_logger = configure_access_logger()
    ip_windows: dict[str, deque[float]] = defaultdict(deque)
    ip_windows_lock = Lock()
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

    @app.get("/assets/v/{release}/{asset_path:path}")
    def get_release_asset(release: str, asset_path: str):
        canonical_release = release_resolver.resolve_release_alias(release)
        release_root = release_resolver.release_root(canonical_release)
        relative_path = asset_path.lstrip("/")
        if not relative_path:
            raise HTTPException(status_code=404, detail="Asset path is required.")

        candidate = (release_root / relative_path).resolve()
        try:
            candidate.relative_to(release_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid asset path.") from exc

        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(
                status_code=404, detail=f"Asset not found: {relative_path}"
            )

        if release == "latest":
            cache_control = "no-store"
        elif canonical_release == "dev":
            cache_control = "public, max-age=0, must-revalidate"
        else:
            cache_control = "public, max-age=31536000, immutable"

        headers = {"Cache-Control": cache_control}
        return FileResponse(candidate, headers=headers)

    return app


app = create_app()
