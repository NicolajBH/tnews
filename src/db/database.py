import threading
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import Annotated
from fastapi import Depends
from sqlmodel import QueuePool, Session, create_engine, text
from src.core.config import settings
from src.core.logging import LogContext

logger = LogContext(__name__)

_engine_store = threading.local()


class DatabaseConnectionError(Exception):
    """Raised when database connection fails after retries"""

    pass


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def get_engine():
    """Get database engine with retry logic"""
    if not hasattr(_engine_store, "engine"):
        try:
            _engine_store.engine = create_engine(
                settings.DATABASE_URL,
                connect_args={"check_same_thread": False},
                poolclass=QueuePool,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                pool_timeout=settings.DB_POOL_TIMEOUT,
                pool_pre_ping=True,
                echo=False,
            )
            # test connection
            with _engine_store.engine.connect() as conn:
                conn.execute(text("SELECT 1")).scalar()
        except Exception as e:
            logger.warning(
                "Database connection attempt failed",
                extra={"error": str(e), "error_type": e.__class__.__name__},
            )
    return _engine_store.engine


try:
    engine = get_engine()
except Exception as e:
    logger.error(
        "Failed to initialize database engine",
        extra={"error": str(e), "error_type": e.__class__.__name__},
    )
    engine = None


def get_session():
    """Get a database session"""
    if engine is None:
        raise DatabaseConnectionError("Database engine failed to initialize")

    with Session(engine) as session:
        try:
            yield session
        except Exception as e:
            session.rollback()
            logger.error(
                "Database session error",
                extra={"error": str(e), "error_type": e.__class__.__name__},
            )
            raise


SessionDep = Annotated[Session, Depends(get_session)]
