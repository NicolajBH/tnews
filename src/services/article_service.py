import logging
from datetime import datetime
from typing import List, Tuple, Dict, Any

from src.models.db_models import Articles, Sources
from src.models.article import Article
from src.models.pagination import PaginationInfo
from src.utils.pagination import encode_cursor, decode_cursor
from src.repositories.article_repository import ArticleRepository
from src.services.cache_service import CacheService

logger = logging.getLogger(__name__)


class ArticleService:
    def __init__(
        self, repository: ArticleRepository, cache_service: CacheService | None = None
    ):
        self.repository = repository
        self.cache_service = cache_service

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
        # create a date range identifier for cache keys
        date_range = "all"
        if start_date or end_date:
            start_str = start_date.isoformat() if start_date else "start"
            end_str = end_date.isoformat() if end_date else "end"
            date_range = f"{start_str}_to_{end_str}"

        # try to get from cache first if enabled
        if use_cache and self.cache_service:
            cached_data = await self.cache_service.get_article_page(
                user_id=user_id,
                cursor=cursor,
                limit=limit,
                date_range=date_range,
            )
            if cached_data:
                return self._reconstruct_from_cache(cached_data)

        pub_date_lt = None
        id_lt = None
        if cursor:
            try:
                pub_date_lt, id_lt = decode_cursor(cursor)
            except ValueError as e:
                logger.error(f"Invalid cursor: {str(e)}")
                raise ValueError(f"Invalid cursor format: {str(e)}")

        # fetch one more item than requested to determine if there are more
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
        source_ids = [article.source_id for article in db_articles]
        sources = self.repository.get_sources_by_id(source_ids)

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

        # store in cache if enabled
        if use_cache and self.cache_service and articles:
            cache_data = {
                "articles": [article.dict() for article in articles],
                "pagination": pagination_info.dict(),
            }

            await self.cache_service.set_article_page(
                user_id=user_id,
                cursor=cursor,
                limit=limit,
                date_range=date_range,
                data=cache_data,
            )

        return articles, pagination_info

    def _convert_to_response_models(
        self, db_articles: List[Articles], sources: Dict[int, Sources]
    ) -> List[Article]:
        """Convert database models to response models"""
        articles_to_return = []

        for article in db_articles:
            source = sources.get(article.source_id)
            if source is None:
                logger.error(f"No sources with ID {article.source_id}")
                continue

            articles_to_return.append(
                Article(
                    id=article.id,
                    title=article.title,
                    pubDate=article.pub_date_raw,
                    source=source.feed_symbol,
                    formatted_time=datetime.strftime(article.pub_date, "%H:%M"),
                )
            )

        return articles_to_return

    def _reconstruct_from_cache(
        self, cached_data: Dict[str, Any]
    ) -> Tuple[List[Article], PaginationInfo]:
        """Reconstruct article and pagination objects from cached data"""
        articles = [Article(**article_data) for article_data in cached_data["articles"]]
        pagination = PaginationInfo(**cached_data["pagination"])
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
        if self.cache_service:
            return await self.cache_service.invalidate_by_prefix(
                f"articles:user:{user_id}"
            )
        return False
