from __future__ import annotations

import time
import logging

from fastapi import Request
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.logging import AccessFormatter

from .config import load_settings
from .services.panels import build_panel_tiles_registry
from climate.registry.panels import load_panels
from .schemas import PanelResponse, GraphListResponse, LocationInfo
from .cache import Cache, make_redis_client
from .logging import configure_access_logger, format_access_line

from .store.place_resolver import PlaceResolver
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
        cache=cache,
        ttl_resolve_s=settings.ttl_resolve_s,
        round_decimals=2,
    )

    tile_store = TileDataStore.discover(
        settings.tiles_series_root,
        start_year_fallback=1979,
    )
    panels_manifest = load_panels()

    app = FastAPI(title="Climate API", version="0.1")
    access_logger = configure_access_logger()

    # expose for next step (routes can use these later)
    app.state.place_resolver = place_resolver
    app.state.tile_store = tile_store
    app.state.panels_manifest = panels_manifest

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

    @app.get("/api/v/{release}/panel", response_model=PanelResponse)
    def get_panel(
        release: str,
        lat: float = Query(...),
        lon: float = Query(...),
        panel_id: str = Query("overview"),
        unit: str = Query("C", pattern="^(C|F|c|f)$"),
    ):
        if release != settings.release and settings.release != "dev":
            # v0: simple guard; later you can support multiple releases on disk
            raise HTTPException(status_code=404, detail=f"Unknown release: {release}")

        try:
            panels_manifest = app.state.panels_manifest
            return build_panel_tiles_registry(
                place_resolver=place_resolver,
                tile_store=tile_store,
                cache=cache,
                ttl_panel_s=settings.ttl_panel_s,
                release=settings.release,
                lat=lat,
                lon=lon,
                unit=unit,
                panel_id=panel_id,
                panels_manifest=panels_manifest,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except KeyError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v/{release}/location/graphs", response_model=GraphListResponse)
    def list_graphs(
        release: str,
        lat: float = Query(...),
        lon: float = Query(...),
        panel_id: str = Query("overview"),
        unit: str = Query("C", pattern="^(C|F|c|f)$"),
    ):
        # Reuse panel assembly but return just graph ids (simple v0)
        resp = get_panel(
            release=release, lat=lat, lon=lon, panel_id=panel_id, unit=unit
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
