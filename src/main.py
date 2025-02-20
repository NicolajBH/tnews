import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
from src.api import router, setup_error_handlers, auth_router
from src.core import setup_logging
from src.core.config import settings
from src.db.operations import initialize_db
from src.tasks.scheduler import periodic_fetch


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_db()

    task = asyncio.create_task(periodic_fetch())
    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.PROJECT_NAME,
        description="API for fetching and managing RSS news feeds",
        version="1.0.0",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
    )

    setup_error_handlers(app)
    app.include_router(router, prefix=settings.API_V1_STR)
    app.include_router(auth_router, prefix=settings.API_V1_STR)
    return app


app = create_app()
