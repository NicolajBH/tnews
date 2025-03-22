from typing import Annotated
from fastapi import Path, Query
from datetime import date
from src.clients.redis import RedisClient
from src.models.article import ArticleQueryParameters, CategoryParams


async def get_date_filters(
    start_date: Annotated[
        date | None, Query(description="Start date (YYYY-MM-DD)")
    ] = None,
    end_date: Annotated[date | None, Query(description="End date (YYYY-MM-DD)")] = None,
) -> ArticleQueryParameters:
    return ArticleQueryParameters(start_date=start_date, end_date=end_date)


async def get_category_params(
    source: Annotated[str, Path(description="News source identifier")],
    category: Annotated[str, Path(description="Category identifier")],
) -> CategoryParams:
    return CategoryParams(source=source, category=category)


async def get_redis_client() -> RedisClient:
    redis_client = RedisClient()
    await redis_client.initialize()
    try:
        yield redis_client
    finally:
        pass
