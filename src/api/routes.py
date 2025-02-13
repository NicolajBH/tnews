import logging
import asyncio
import time
from fastapi import APIRouter, Depends
from typing import List, Dict
from datetime import datetime
from src.models.article import Article, ArticleQueryParameters, CategoryParams
from src.clients.news import NewsClient
from src.utils.formatters import format_articles
from src.api.dependencies import get_news_client, get_date_filters, get_category_params
from src.constants import RSS_FEEDS
from src.core.exceptions import (
    RSSFeedError,
    DateParsingError,
    HTTPClientError,
    InvalidCategoryError,
    InvalidSourceError,
)

logger = logging.getLogger(__name__)
router = APIRouter()
news_client = NewsClient()


@router.get("/articles/latest", response_model=List[Article])
async def get_latest_articles(
    news_client: NewsClient = Depends(get_news_client),
    params: ArticleQueryParameters = Depends(get_date_filters),
) -> List[Article]:
    try:
        start_time = time.time()
        articles = []
        successful_fetches = 0
        failed_fetches = 0

        for source, categories in RSS_FEEDS.items():
            article_tasks = [
                news_client.fetch_headlines(feed_url)
                for category, feed_url in categories.items()
            ]
            try:
                category_articles = await asyncio.gather(*article_tasks)
                for category, fetched_articles in zip(
                    categories.keys(), category_articles
                ):
                    articles.extend(fetched_articles)
                    successful_fetches += 1
                    logger.debug(f"Fetched articles from {source}/{category}")
            except Exception as e:
                failed_fetches += 1
                logger.error(f"Error fetching articles from {source}: {str(e)}")
                raise RSSFeedError(
                    detail=f"Failed to fetch articles from {source}",
                    source=source,
                )

        total_time = time.time() - start_time
        logger.info(
            "Article fetch complete",
            extra={
                "metrics": {
                    "total_articles": len(articles),
                    "successful_fetches": successful_fetches,
                    "failed_fetches": failed_fetches,
                    "fetch_time_seconds": round(total_time, 2),
                }
            },
        )

        if params.start_date is None and params.end_date is None:
            return format_articles(articles)

        filtered_articles = []
        for article in articles:
            try:
                article_date = datetime.strptime(
                    article.pubDate, "%a, %d %b %Y %H:%M:%S %z"
                ).date()
                start_condition = (
                    True
                    if params.start_date is None
                    else article_date >= params.start_date
                )
                end_condition = (
                    True if params.end_date is None else article_date <= params.end_date
                )

                if start_condition and end_condition:
                    filtered_articles.append(article)
            except ValueError as e:
                logger.error(
                    f"Date parsing error for article: {article.title[:30]}... Error: {e}"
                )
                raise DateParsingError(
                    detail="Failed to parse article date", date_string=article.pubDate
                )
        return format_articles(filtered_articles)
    except (RSSFeedError, DateParsingError):
        raise
    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)}", exc_info=True)
        raise HTTPClientError(detail="Unexpected error while fetching articles")


@router.get("/sources/{source}/categories/{category}", response_model=List[Article])
async def get_category_articles(
    news_client: NewsClient = Depends(get_news_client),
    params: CategoryParams = Depends(get_category_params),
) -> List[Article]:
    try:
        if params.source not in RSS_FEEDS:
            raise InvalidSourceError(params.source)

        if params.category not in RSS_FEEDS[params.source]:
            raise InvalidCategoryError(params.source, params.category)

        articles = await news_client.fetch_headlines(
            RSS_FEEDS[params.source][params.category]
        )
        return format_articles(articles)

    except Exception as e:
        logger.error(
            f"Error fetching articles for {params.source}/{params.category}: {str(e)}",
            exc_info=True,
        )
        raise RSSFeedError(
            detail="Failed to fetch articles",
            source=params.source,
            category=params.category,
        )


@router.get("/categories")
async def get_categories() -> Dict[str, List[str]]:
    try:
        return {source: list(cats.keys()) for source, cats in RSS_FEEDS.items()}
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}", exc_info=True)
        raise HTTPClientError(detail="Error fetching categories")


@router.get("/sources")
async def get_sources() -> Dict[str, List[str]]:
    try:
        return {"sources": list(RSS_FEEDS.keys())}
    except Exception as e:
        logger.error(f"Error fetching sources: {str(e)}", exc_info=True)
        raise HTTPClientError(detail="Error fetching sources")
