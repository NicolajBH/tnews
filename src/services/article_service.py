from zoneinfo import ZoneInfo
from datetime import datetime
from typing import List, Tuple, Dict, Any

from src.core.logging import LogContext, PerformanceLogger, add_correlation_id
from src.models.db_models import Articles, Sources
from src.models.article import Article
from src.models.pagination import PaginationInfo
from src.utils.pagination import encode_cursor, decode_cursor
from src.repositories.article_repository import ArticleRepository
from src.services.cache_service import CacheService

logger = LogContext(__name__)


class ArticleService:
    def __init__(
        self, repository: ArticleRepository, cache_service: CacheService | None = None
    ):
        self.repository = repository
        self.cache_service = cache_service

        logger.debug(
            "ArticleService initialized",
            extra={"has_cache_service": cache_service is not None},
        )

    async def get_paginated_articles(
        self,
        user_id: int,
        cursor: str | None = None,
        limit: int = 20,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        use_cache: bool = True,
    ) -> Tuple[List[Article], PaginationInfo]:
        """
        Get paginated articles for a user

        Args:
            user_id: The user's id
            cursor: Optional cursor for pagination
            limit: Maximum number of articles to return
            start_date: Optional start date filter
            end_date: Optional end date filter
            use_cache: Whether to use cache

        Returns:
            A tuple containing (list of article objects, pagination info)
        """
        # Add operation information to correlation context
        add_correlation_id("operation", "get_paginated_articles")
        add_correlation_id("user_id", user_id)
        add_correlation_id("limit", limit)
        add_correlation_id("cursor", cursor)

        logger.info(
            "Fetching paginated articles",
            extra={
                "user_id": user_id,
                "cursor": cursor,
                "limit": limit,
                "has_start_date": start_date is not None,
                "has_end_date": end_date is not None,
                "use_cache": use_cache,
            },
        )

        # Create a performance logger for the entire operation
        with PerformanceLogger(logger, f"get_articles_user_{user_id}"):
            # create a date range identifier for cache keys
            date_range = "all"
            if start_date or end_date:
                start_str = start_date.isoformat() if start_date else "start"
                end_str = end_date.isoformat() if end_date else "end"
                date_range = f"{start_str}_to_{end_str}"

            # try to get from cache first if enabled
            if use_cache and self.cache_service:
                with PerformanceLogger(logger, "get_article_page_from_cache"):
                    cached_data = await self.cache_service.get_article_page(
                        user_id=user_id,
                        cursor=cursor,
                        limit=limit,
                        date_range=date_range,
                    )

                    if cached_data:
                        logger.info(
                            "Cache hit for article page",
                            extra={
                                "user_id": user_id,
                                "cursor": cursor,
                                "limit": limit,
                                "article_count": len(cached_data.get("articles", [])),
                            },
                        )
                        return self._reconstruct_from_cache(cached_data)
                    else:
                        logger.debug("Cache miss for article page")

            # Parse cursor if provided
            pub_date_lt = None
            id_lt = None
            if cursor:
                try:
                    pub_date_lt, id_lt = decode_cursor(cursor)
                    logger.debug(
                        "Cursor decoded",
                        extra={
                            "pub_date_lt": pub_date_lt.isoformat()
                            if pub_date_lt
                            else None,
                            "id_lt": id_lt,
                        },
                    )
                except ValueError as e:
                    logger.error(
                        "Invalid cursor",
                        extra={
                            "error": str(e),
                            "user_id": user_id,
                            "cursor": cursor,
                            "error_type": e.__class__.__name__,
                        },
                    )
                    raise ValueError(f"Invalid cursor format: {str(e)}")

            # fetch one more item than requested to determine if there are more
            with PerformanceLogger(logger, "get_articles_from_repository"):
                db_articles = self.repository.get_articles_for_user(
                    user_id=user_id,
                    start_date=start_date,
                    end_date=end_date,
                    pub_date_lt=pub_date_lt,
                    id_lt=id_lt,
                    limit=limit + 1,
                )

            # check if there are more items
            has_more = len(db_articles) > limit
            if has_more:
                db_articles = db_articles[:-1]

            # fetch all needed sources
            source_names = list(set(article.source_name for article in db_articles))
            with PerformanceLogger(logger, "get_sources_by_name"):
                sources = self.repository.get_sources_by_name(source_names)

            logger.debug(
                "Retrieved articles and sources",
                extra={
                    "article_count": len(db_articles),
                    "source_count": len(sources),
                    "unique_source_count": len(source_names),
                    "has_more": has_more,
                },
            )

            # convert to response model
            articles = self._convert_to_response_models(db_articles, sources)

            # create pagination info
            pagination_info = PaginationInfo(has_more=has_more)

            if has_more and db_articles:
                last_item = db_articles[-1]
                pagination_info.next_cursor = encode_cursor(
                    last_item.pub_date,
                    last_item.id,
                )
                logger.debug(
                    "Created next cursor",
                    extra={"next_cursor": pagination_info.next_cursor},
                )

            # store in cache if enabled
            if use_cache and self.cache_service and articles:
                with PerformanceLogger(logger, "cache_article_page"):
                    cache_data = {
                        "articles": [article.model_dump() for article in articles],
                        "pagination": pagination_info.model_dump(),
                    }

                    await self.cache_service.set_article_page(
                        user_id=user_id,
                        cursor=cursor,
                        limit=limit,
                        date_range=date_range,
                        data=cache_data,
                    )
                    logger.debug(
                        "Article page cached",
                        extra={
                            "user_id": user_id,
                            "cursor": cursor,
                            "article_count": len(articles),
                        },
                    )

            logger.info(
                "Article retrieval complete",
                extra={
                    "user_id": user_id,
                    "articles_returned": len(articles),
                    "has_more": has_more,
                    "source_count": len(sources),
                },
            )

            return articles, pagination_info

    def _convert_to_response_models(
        self, db_articles: List[Articles], sources: Dict[str, Sources]
    ) -> List[Article]:
        """Convert database models to response models"""
        articles_to_return = []
        missing_sources = set()

        for article in db_articles:
            source = sources.get(article.source_name)
            if source is None:
                missing_sources.add(article.source_name)
                logger.warning(
                    "Missing source for article",
                    extra={
                        "article_id": article.id,
                        "source_name": article.source_name,
                        "article_title": article.title[:30] + "..."
                        if len(article.title) > 30
                        else article.title,
                    },
                )
                continue

            dt_utc = article.pub_date.replace(tzinfo=ZoneInfo("UTC"))

            articles_to_return.append(
                Article(
                    id=article.id,
                    title=article.title,
                    pubDate=dt_utc.isoformat(),
                    feed_symbol=source.feed_symbol,
                    display_name=source.display_name,
                    author=article.author_name if article.author_name else "Unknown",
                    url=article.original_url,
                    description=article.description
                    if article.description
                    else "No description available",
                )
            )

        if missing_sources:
            logger.error(
                "Articles referencing missing sources",
                extra={
                    "missing_source_names": list(missing_sources),
                    "total_missing": len(missing_sources),
                    "affected_articles": len(db_articles) - len(articles_to_return),
                },
            )

        return articles_to_return

    def _reconstruct_from_cache(
        self, cached_data: Dict[str, Any]
    ) -> Tuple[List[Article], PaginationInfo]:
        """Reconstruct article and pagination objects from cached data"""
        with PerformanceLogger(logger, "reconstruct_from_cache"):
            articles = [
                Article(**article_data) for article_data in cached_data["articles"]
            ]
            pagination = PaginationInfo(**cached_data["pagination"])

            logger.debug(
                "Reconstructed objects from cache",
                extra={
                    "article_count": len(articles),
                    "has_more": pagination.has_more,
                    "has_next_cursor": pagination.next_cursor is not None,
                },
            )

            return articles, pagination

    async def invalidate_user_articles_cache(self, user_id: int) -> bool:
        """
        Invalidate all article cache entries for a user

        This should be called whenever a user's feed preferencees change or when
        new articles are fetched that might affect their feed

        Args:
            user_id: The user's ID

        Returns:
            True if successful, False otherwise
        """
        logger.info(
            "Invalidating user article cache",
            extra={
                "user_id": user_id,
                "has_cache_service": self.cache_service is not None,
            },
        )

        if self.cache_service:
            with PerformanceLogger(logger, f"invalidate_user_{user_id}_cache"):
                success = await self.cache_service.invalidate_by_prefix(
                    f"articles:user:{user_id}"
                )

                logger.info(
                    "Cache invalidation complete",
                    extra={"user_id": user_id, "success": success},
                )
                return success

        return False
