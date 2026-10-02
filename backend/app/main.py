from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api.v1.router import api_v1_router, health_check, readiness_check
from app.core.config import get_settings
from app.core.cache import CacheGenerationMiddleware
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.hardening import (
    AccessLogMiddleware,
    ApiRateLimitMiddleware,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.observability import init_error_tracking
from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import ClientGateMiddleware, RequestIDMiddleware
from app.core.database import check_database_on_startup, get_db
from app.modules.admin.bootstrap import ensure_configured_accounts, ensure_loan_catalogue
from app.core.redis import check_redis_on_startup, get_redis, get_redis_pool


class ProductionConfigError(RuntimeError):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger = structlog.get_logger()
    logger.info("starting_api", app=settings.app_name, env=settings.app_env)
    # Honour a swapped-in Redis (the in-memory dev server, tests) instead of the configured URL.
    override = app.dependency_overrides.get(get_redis)
    await check_redis_on_startup(await override() if override else None)
    # The in-memory dev server and tests swap in their own database.
    if get_db not in app.dependency_overrides:
        await check_database_on_startup()
        await ensure_loan_catalogue()
        await ensure_configured_accounts()
    yield
    await get_redis_pool().aclose()
    logger.info("shutdown_api")


def create_app() -> FastAPI:
    settings = get_settings()

    problems = settings.production_config_errors()
    if problems:
        raise ProductionConfigError(
            "Refusing to start with APP_ENV=production:\n  - " + "\n  - ".join(problems)
        )

    configure_logging(json_logs=settings.app_env != "development", debug=settings.debug)
    init_error_tracking(settings)

    docs = settings.enable_api_docs
    app = FastAPI(
        title=settings.app_name,
        description="GH Trust International Ltd — Microfinance Banking API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    register_exception_handlers(app)

    # Starlette runs the LAST-added middleware first. Effective order per request:
    # RequestID → AccessLog → SecurityHeaders → GZip → CORS → RateLimit → BodySize
    #   → ClientGate (version/maintenance) → Idempotency → CacheGeneration → routes.
    # CORS wraps the rate/size limiters so browsers can read their 429/413 replies.
    app.add_middleware(CacheGenerationMiddleware)  # innermost: sees the route's real status
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(ClientGateMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(ApiRateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After", "X-Total-Count", "Idempotent-Replayed"],
    )
    # Compress the final response (JSON lists/dashboards shrink 5-10x); outside the
    # idempotency cache so stored replays stay uncompressed.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    # Outermost, so every response — including CORS preflights and errors —
    # carries a request ID (and every access-log line has one).
    app.add_middleware(RequestIDMiddleware)

    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    # Unversioned aliases, the paths hosting platforms (Railway, load balancers) probe by default.
    app.add_api_route("/health", health_check, methods=["GET"], tags=["Health"])
    app.add_api_route(
        "/health/ready", readiness_check, methods=["GET"], tags=["Health"],
        summary="Readiness: database and Redis reachable",
    )

    @app.get("/", tags=["Root"])
    async def root():
        return {
            "message": "GH Trust MFB API",
            "tagline": "Secure Today. Grow Tomorrow.",
            "docs": "/docs" if docs else None,
            "health": "/health",
        }

    return app


app = create_app()
