from fastapi import FastAPI
from src.api import router, setup_error_handlers
from src.core import setup_logging
from src.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="API for fetching and managing RSS news feeds",
        version="1.0.0",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
    )

    setup_logging()
    setup_error_handlers(app)
    app.include_router(router, prefix=settings.API_V1_STR)
    return app


app = create_app()
