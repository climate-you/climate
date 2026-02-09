from __future__ import annotations

import time
import logging

from fastapi import Request
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.logging import AccessFormatter

from .config import load_settings
from .services.panels import build_panel_tiles_registry, build_scored_panels_tiles_registry
from climate.registry.panels import load_panels
from climate.registry.maps import load_maps
from .schemas import (
    PanelListResponse,
    GraphListResponse,
    LocationInfo,
    LocationAutocompleteResponse,
    LocationAutocompleteItem,
    LocationResolveResponse,
    LocationNearestResponse,
    QueryPoint,
    PlaceInfo,
)
from .cache import Cache, make_redis_client
from .logging import configure_access_logger, format_access_line

from .store.place_resolver import PlaceResolver
from .store.location_index import LocationIndex
from .store.tile_data_store import TileDataStore

logging.getLogger("uvicorn.access").disabled = True


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

    cache = Cache(prefix=f"climate_api:{settings.release}")
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if settings.redis_url:
        cache.redis = make_redis_client(settings.redis_url)
        uvicorn_logger.info(f"Redis cache enabled: {settings.redis_url}")
    else:
        uvicorn_logger.warning(
            "Redis cache disabled (REDIS_URL not set); using in-process cache only."
        )

    place_resolver = PlaceResolver(
        locations_csv=settings.locations_csv,
        kdtree_path=settings.kdtree_path,
        cache=cache,
        ttl_resolve_s=settings.ttl_resolve_s,
        round_decimals=2,
    )
    location_index = LocationIndex(settings.locations_index_csv)

    tile_store = TileDataStore.discover(
        settings.tiles_series_root,
        start_year_fallback=1979,
    )
    panels_manifest = load_panels()
    maps_manifest = load_maps()

    app = FastAPI(title="Climate API", version="0.1")
    access_logger = configure_access_logger()

    # expose for next step (routes can use these later)
    app.state.place_resolver = place_resolver
    app.state.location_index = location_index
    app.state.tile_store = tile_store
    app.state.panels_manifest = panels_manifest
    app.state.maps_manifest = maps_manifest

    @app.middleware("http")
    async def access_log_with_timing(request: Request, call_next):
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
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v/{release}/panel", response_model=PanelListResponse)
    def get_panel(
        release: str,
        lat: float = Query(...),
        lon: float = Query(...),
        unit: str = Query("C", pattern="^(C|F|c|f)$"),
    ):
        if release != settings.release and settings.release != "dev":
            # v0: simple guard; later you can support multiple releases on disk
            raise HTTPException(status_code=404, detail=f"Unknown release: {release}")

        try:
            panels_manifest = app.state.panels_manifest
            maps_manifest = app.state.maps_manifest
            return build_scored_panels_tiles_registry(
                place_resolver=place_resolver,
                tile_store=tile_store,
                cache=cache,
                ttl_panel_s=settings.ttl_panel_s,
                release=settings.release,
                lat=lat,
                lon=lon,
                unit=unit,
                panels_manifest=panels_manifest,
                maps_manifest=maps_manifest,
                maps_root=settings.maps_root,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except KeyError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/api/v/{release}/locations/autocomplete",
        response_model=LocationAutocompleteResponse,
    )
    def autocomplete_locations(
        release: str,
        q: str = Query(..., min_length=2),
        limit: int = Query(10, ge=1, le=50),
    ):
        if release != settings.release and settings.release != "dev":
            raise HTTPException(status_code=404, detail=f"Unknown release: {release}")

        hits = app.state.location_index.autocomplete(q, limit=limit)
        results = [
            LocationAutocompleteItem(
                geonameid=h.geonameid,
                label=h.label,
                lat=h.lat,
                lon=h.lon,
                country_code=h.country_code,
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
        if release != settings.release and settings.release != "dev":
            raise HTTPException(status_code=404, detail=f"Unknown release: {release}")

        idx = app.state.location_index
        hit = None
        if geonameid is not None:
            hit = idx.resolve_by_id(geonameid)
        elif label:
            hit = idx.resolve_by_label(label)
        else:
            raise HTTPException(
                status_code=400, detail="Provide geonameid or label."
            )

        result = None
        if hit is not None:
            result = LocationAutocompleteItem(
                geonameid=hit.geonameid,
                label=hit.label,
                lat=hit.lat,
                lon=hit.lon,
                country_code=hit.country_code,
            )

        return LocationResolveResponse(query=str(geonameid or label or ""), result=result)

    @app.get(
        "/api/v/{release}/location/nearest",
        response_model=LocationNearestResponse,
    )
    def nearest_location(
        release: str,
        lat: float = Query(...),
        lon: float = Query(...),
    ):
        if release != settings.release and settings.release != "dev":
            raise HTTPException(status_code=404, detail=f"Unknown release: {release}")

        place = app.state.place_resolver.resolve_place(lat, lon)
        return LocationNearestResponse(
            query=QueryPoint(lat=float(lat), lon=float(lon)),
            result=PlaceInfo(
                geonameid=int(place.geonameid),
                label=place.label,
                lat=float(place.lat),
                lon=float(place.lon),
                distance_km=float(place.distance_km),
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
        if release != settings.release and settings.release != "dev":
            raise HTTPException(status_code=404, detail=f"Unknown release: {release}")

        resp = build_panel_tiles_registry(
            place_resolver=place_resolver,
            tile_store=tile_store,
            cache=cache,
            ttl_panel_s=settings.ttl_panel_s,
            release=settings.release,
            lat=lat,
            lon=lon,
            unit=unit,
            panel_id=panel_id,
            panels_manifest=app.state.panels_manifest,
        )
        return GraphListResponse(
            release=resp.release,
            unit=resp.unit,
            location=resp.location,
            panel_id=panel_id,
            graph_ids=[g.id for g in resp.panel.graphs],
        )

    return app


app = create_app()
