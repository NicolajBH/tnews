from typing import Annotated
from fastapi import Path, Query, Request
from datetime import datetime, timedelta
from src.clients.redis import RedisClient
from src.core.degradation import HealthService
from src.models.article import ArticleQueryParameters


def get_date_filters(
    start_date: datetime | None = Query(
        None, description="Filter for articles after this date"
    ),
    end_date: datetime | None = Query(
        None, description="Filter for articles before this data"
    ),
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Number of items per page"),
) -> ArticleQueryParameters:
    """Get date filters and pagination parameters for article queries"""
    # default to recent articles if no date
    if not start_date and not end_date:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

    return ArticleQueryParameters(
        start_date=start_date, end_date=end_date, cursor=cursor, limit=limit
    )


async def get_redis_client() -> RedisClient:
    """
    Get a Redis client instance

    Returns:
        RedisClient: A configured redis client
    """
    from src.core.container import get_health_service

    health_service = get_health_service()

    redis_client = RedisClient(health_service=health_service)
    await redis_client.initialize()
    return redis_client


async def get_health_service(request: Request) -> HealthService:
    """
    Get the health service from the application state

    Args:
        request: The FastAPI request

    Returns:
        The health service instance
    """
    return request.app.state.health_service
