from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.api import router, setup_error_handlers, auth_router
from src.api.middleware import RateLimitHeaderMiddleware
from src.core import setup_logging
from src.core.config import settings
from src.db.operations import initialize_db
from src.clients.redis import RedisClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_db()
    redis_client = RedisClient()
    await redis_client.initialize()

    yield

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

    setup_error_handlers(app)
    app.include_router(router, prefix=settings.API_V1_STR)
    app.include_router(auth_router, prefix=settings.API_V1_STR)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )
    app.add_middleware(RateLimitHeaderMiddleware)
    return app


app = create_app()
