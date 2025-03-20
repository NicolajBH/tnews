import logging
import gzip
import time
import asyncio
from typing import List, Tuple, Any, Set, Union
from sqlmodel import Session, select
from src.clients.redis import RedisClient
from src.models.db_models import Articles, Categories
from src.clients.http import HTTPClient
from src.clients.connection import ConnectionPool
from src.core.exceptions import RSSFeedError
from src.parsers.xml import XMLFeedParser
from src.parsers.json import JSONFeedParser
from src.parsers.base import FeedParser
from src.core.config import settings


logger = logging.getLogger(__name__)


class NewsClient:
    def __init__(self, session: Session, redis_client: RedisClient):
        self.connection_pool = ConnectionPool(
            pool_size=settings.POOL_SIZE,
            max_concurrent_requests=settings.MAX_CONCURRENT_REQUEST,
        )
        self.http_client = HTTPClient(self.connection_pool)
        self.session = session
        self.redis = redis_client
        self._semaphore = asyncio.Semaphore(min(settings.MAX_CONCURRENT_REQUEST, 10))
        self._parser_cache = {}
        self._category_cache = {}

    async def fetch_multiple_feeds(
        self, feeds: List[Tuple[int, int, str]]
    ) -> List[Union[Tuple[int, int], BaseException]]:
        await self._prefetch_categories([cat_id for _, cat_id, _ in feeds])

        async def fetch_with_semaphore(source_id, category_id, url):
            async with self._semaphore:
                try:
                    return await self.fetch_headlines(source_id, category_id, url)
                except Exception as e:
                    logger.error(f"Error fetching {url}: {str(e)}")
                    return 0, 0

        tasks = [
            fetch_with_semaphore(source_id, category_id, url)
            for source_id, category_id, url in feeds
        ]

        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _prefetch_categories(self, category_ids: List[int]) -> None:
        unique_ids = list(set(category_ids))
        categories = self.session.exec(
            select(Categories).where(Categories.id.in_(unique_ids))
        ).all()

        for category in categories:
            self._category_cache[category.id] = category

    async def fetch_headlines(
        self, source_id: int, category_id: int, url: str
    ) -> Tuple[int, int]:
        start_time = time.time()
        try:
            timeout = 1.0 if "longread" in url else settings.REQUEST_TIMEOUT
            raw_feed = await asyncio.wait_for(self._fetch_feed(url), timeout=timeout)
            articles = await self._process_feed(raw_feed, source_id)
            stats = await self._save_articles(articles, category_id)
            logger.debug(
                f"Feed fetch completed in {time.time() - start_time:.2f}s for {url}"
            )
            return stats
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching feed: {url}")
            await self._log_error(
                RSSFeedError("Timeout fetching feed"),
                start_time,
                source_id,
                category_id,
            )
            return 0, 0
        except Exception as e:
            await self._log_error(e, start_time, source_id, category_id)
            return 0, 0

    async def _fetch_feed(self, url: str) -> Tuple[Any, bytes]:
        try:
            return await asyncio.wait_for(
                self.http_client.request("GET", url), timeout=settings.REQUEST_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching feed: {url}")
            raise RSSFeedError(f"Timeout fetching feed: {url}")

    def _get_parser(self, content_type: str, source_id: int) -> FeedParser:
        cache_key = f"{content_type}_{source_id}"

        if cache_key in self._parser_cache:
            return self._parser_cache[cache_key]

        if "xml" in content_type.lower():
            parser = XMLFeedParser(source_id)
        elif "json" in content_type.lower():
            parser = JSONFeedParser(source_id)
        else:
            logger.warning(
                f"Unknown content type: {content_type}, defaulting to XML parser. Source: {source_id}"
            )
            parser = XMLFeedParser(source_id)

        self._parser_cache[cache_key] = parser
        return parser

    async def _process_feed(
        self, raw_feed: Tuple[Any, bytes], source_id: int
    ) -> List[Articles]:
        headers, body = raw_feed
        content_type = headers.headers.get("Content-Type", "").lower()

        try:
            if "gzip" in headers.headers.get("Content-Encoding", "").lower():
                body = gzip.decompress(body)

            content = (
                body.decode("utf-8", errors="replace")
                if isinstance(body, bytes)
                else body
            )

            parser = self._get_parser(content_type, source_id)
            return await parser.parse_content(content)
        except Exception as e:
            logger.error(f"Error processing feed content: {e}")
            return []

    async def _save_articles(
        self, articles: List[Articles], category_id: int
    ) -> Tuple[int, int]:
        if not articles:
            return 0, 0

        successful_articles = 0
        new_category_associations = 0

        category = self._get_category(category_id)
        if not category:
            logger.warning(f"Category not found: {category_id}")
            return 0, 0

        content_hashes = {
            article.content_hash for article in articles if article.content_hash
        }

        if not content_hashes:
            return 0, 0

        redis_hash_results = {}
        try:
            redis_hash_results = await self.redis.pipeline_check_hashes(
                list(content_hashes)
            )
        except Exception as e:
            logger.warning(f"Redis hash check failed, falling back to DB: {e}")

        content_hashes_to_check = {
            h
            for h in content_hashes
            if h not in redis_hash_results or not redis_hash_results[h]
        }

        existing_db_hashes = set()
        if content_hashes_to_check:
            existing_db_hashes = await self._check_articles_exist_in_db(
                content_hashes_to_check
            )

        existing_hashes = {
            h
            for h in content_hashes
            if (
                h in redis_hash_results
                and redis_hash_results[h]
                or h in existing_db_hashes
            )
        }

        new_articles = [
            article
            for article in articles
            if article.content_hash and article.content_hash not in existing_hashes
        ]

        unique_articles = {}
        for article in new_articles:
            if article.content_hash not in unique_articles:
                unique_articles[article.content_hash] = article
            else:
                if article.pub_date < unique_articles[article.content_hash].pub_date:
                    unique_articles[article.content_hash] = article

        new_articles = list(unique_articles.values())

        if new_articles:
            try:
                new_hashes = []
                for article in new_articles:
                    article.categories.append(category)
                    self.session.add(article)
                    new_hashes.append(article.content_hash)
                    successful_articles += 1

                self.session.commit()
                logger.info(f"Saved {successful_articles} new articles to database")
                try:
                    asyncio.create_task(self.redis.pipeline_add_hashes(new_hashes))
                except Exception as e:
                    logger.error(f"Failed to add hashes to Redis: {e}")
            except Exception as e:
                logger.error(f"Error commiting new articles: {e}")
                self.session.rollback()
                successful_articles = 0

        return successful_articles, new_category_associations

    async def _check_articles_exist_in_db(self, content_hashes: Set[str]) -> Set[str]:
        if not content_hashes:
            return set()

        results = self.session.exec(
            select(Articles.content_hash).where(
                Articles.content_hash.in_(content_hashes)
            )
        ).all()

        return set(results)

    def _get_category(self, category_id: int) -> Categories | None:
        if category_id in self._category_cache:
            return self._category_cache[category_id]

        category = self.session.get(Categories, category_id)
        if category:
            self._category_cache[category_id] = category

        return category

    async def _log_error(
        self, error: Exception, start_time: float, source_id: int, category_id: int
    ) -> None:
        fetch_time = time.time() - start_time
        logger.error(
            f"Error fetching feed: {str(error)}",
            extra={
                "metrics": {
                    "fetch_time_seconds": round(fetch_time, 2),
                    "source_id": source_id,
                    "category_id": category_id,
                }
            },
        )
