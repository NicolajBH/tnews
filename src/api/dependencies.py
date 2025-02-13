from typing import Annotated
from fastapi import Path, Query
from datetime import date
from src.models.article import ArticleQueryParameters, CategoryParams
from src.clients.news import NewsClient

news_client = NewsClient()


async def get_news_client() -> NewsClient:
    return news_client


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
