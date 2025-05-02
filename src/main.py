from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.api import router, setup_error_handlers, auth_router
from src.api.middleware import (
    ETagMiddleware,
    RateLimitHeaderMiddleware,
    RequestIDMiddleware,
    PrometheusMiddleware,
)
from src.api.degradation_middleware import ServiceDegradationMiddleware
from src.api.routes import health as health_routes
from src.core import setup_logging
from src.core.config import settings
from src.core.degradation import HealthService
from src.db.operations import initialize_db
from src.clients.redis import RedisClient
from prometheus_client import REGISTRY, CONTENT_TYPE_LATEST, generate_latest
from prometheus_client.multiprocess import MultiProcessCollector
from prometheus_fastapi_instrumentator import Instrumentator
from src.core.metrics import (
    service_health_state,
    circuit_breaker_state,
    redis_client_state,
    db_connection_pool_size,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager"""
    # Initialize database
    initialize_db()

    # Initialize Redis
    redis_client = RedisClient(health_service=app.state.health_service)
    await redis_client.initialize()

    # Set initial health service metrics
    service_health_state.labels(service="api").set(2)
    service_health_state.labels(service="redis").set(2)
    service_health_state.labels(service="database").set(2)

    # Set initial circuit breaker states
    circuit_breaker_state.labels(service="redis_client").set(2)

    # set initial redis client state
    redis_client_state.set(1)

    # Set initial db pool size
    db_connection_pool_size.set(settings.POOL_SIZE)

    yield

    # Clean up resources
    await redis_client.close()


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.PROJECT_NAME,
        description="API for fetching and managing news feeds",
        version="1.0.0",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
    )

    # Create health service and store in app state
    health_service = HealthService()
    app.state.health_service = health_service

    # Set up error handlers
    setup_error_handlers(app)

    # Include routers
    app.include_router(router, prefix=settings.API_V1_STR)
    app.include_router(auth_router, prefix=settings.API_V1_STR)
    app.include_router(
        health_routes.router, prefix=f"{settings.API_V1_STR}/health", tags=["health"]
    )

    # Add middleware - order matters!
    # RequestIDMiddleware should be first to assign IDs to all requests
    app.add_middleware(RequestIDMiddleware)

    # Prometheus Middleware
    app.add_middleware(PrometheusMiddleware)

    # ServiceDegradationMiddleware should be early to capture service errors
    app.add_middleware(ServiceDegradationMiddleware, health_service=health_service)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )

    # Other middleware
    app.add_middleware(RateLimitHeaderMiddleware)
    app.add_middleware(ETagMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        from fastapi.responses import Response

        return Response(
            content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST
        )

    return app


app = create_app()
