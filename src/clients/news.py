import logging
import gzip
import time
import asyncio
from typing import List, Tuple, Any, Set, Union, Dict, Optional
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
from src.core.degradation import HealthService


logger = logging.getLogger(__name__)


class NewsClient:
    def __init__(
        self,
        session: Session,
        redis_client: RedisClient,
        health_service: Optional[HealthService] = None,
    ):
        # Core dependencies
        self.session = session
        self.redis = redis_client
        self.health_service = health_service

        # Connection and client setup
        self.connection_pool = ConnectionPool(
            pool_size=settings.POOL_SIZE,
            max_concurrent_requests=settings.MAX_CONCURRENT_REQUEST,
        )
        self.http_client = HTTPClient(
            self.connection_pool, health_service=health_service
        )

        # Concurrency control
        self._semaphore = asyncio.Semaphore(min(settings.MAX_CONCURRENT_REQUEST, 10))

        # Caches
        self._parser_cache = {}
        self._category_cache = {}

        # Set up circuit breakers if health service is provided
        self._circuit_breakers = {}
        if health_service:
            self._init_circuit_breakers()

    def _init_circuit_breakers(self) -> None:
        """Initialize circuit breakers for various operations"""
        circuit_configs = {
            "feed": {
                "name": "news_feed_fetcher",
                "failure_threshold": 3,
                "reset_timeout": 30.0,
                "backoff_multiplier": 2.0,
                "max_timeout": 300.0,
            },
            "redis": {
                "name": "news_redis_cache",
                "failure_threshold": 3,
                "reset_timeout": 10.0,
                "backoff_multiplier": 1.5,
                "max_timeout": 60.0,
            },
            "db": {
                "name": "news_db_operations",
                "failure_threshold": 2,
                "reset_timeout": 15.0,
                "backoff_multiplier": 2.0,
                "max_timeout": 120.0,
            },
        }

        for circuit_type, config in circuit_configs.items():
            self._circuit_breakers[circuit_type] = (
                self.health_service.get_circuit_breaker(**config)
            )

    def _get_circuit(self, circuit_type: str):
        """Get a circuit breaker by type"""
        return self._circuit_breakers.get(circuit_type)

    async def fetch_multiple_feeds(
        self, feeds: List[Tuple[int, int, str]]
    ) -> List[Tuple[int, Exception]]:
        """Fetch multiple feeds in parallel with concurrency control"""
        # Prefetch categories for efficiency
        await self._prefetch_categories([cat_id for _, cat_id, _ in feeds])

        async def fetch_with_semaphore(source_id, category_id, url):
            async with self._semaphore:
                try:
                    return await self.fetch_headlines(source_id, category_id, url)
                except Exception as e:
                    logger.error(f"Error fetching {url}: {str(e)}")
                    self._update_health(
                        f"feed_{source_id}_{category_id}", "degraded", error=str(e)
                    )
                    return 0, e

        # Fetch all feeds concurrently with controlled concurrency
        tasks = [
            fetch_with_semaphore(source_id, category_id, url)
            for source_id, category_id, url in feeds
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _prefetch_categories(self, category_ids: List[int]) -> None:
        """Prefetch and cache categories to reduce database queries"""
        if not category_ids:
            return

        unique_ids = list(set(category_ids))

        async def fetch_categories():
            categories = self.session.exec(
                select(Categories).where(Categories.id.in_(unique_ids))
            ).all()

            for category in categories:
                self._category_cache[category.id] = category

        # Use circuit breaker if available
        db_circuit = self._get_circuit("db")
        try:
            if db_circuit:
                await db_circuit.execute(
                    fetch_categories,
                    cache_key=f"categories_{'-'.join(map(str, unique_ids))}",
                )
            else:
                await fetch_categories()
        except Exception as e:
            logger.error(f"Failed to prefetch categories: {e}")

    async def fetch_headlines(
        self, source_id: int, category_id: int, url: str
    ) -> Tuple[int, None | BaseException]:
        """Fetch headlines from a feed URL with graceful degradation"""
        start_time = time.time()
        service_name = f"feed_{source_id}_{category_id}"

        try:
            # Determine timeout based on URL
            timeout = 1.0 if "longread" in url else settings.REQUEST_TIMEOUT

            # If we have a circuit breaker, use it
            feed_circuit = self._get_circuit("feed")
            if feed_circuit:
                raw_feed = await asyncio.wait_for(
                    feed_circuit.execute(self._fetch_feed, url=url), timeout=timeout
                )
            else:
                # Original implementation without circuit breaker
                raw_feed = await asyncio.wait_for(
                    self._fetch_feed(url), timeout=timeout
                )

            # Process and save the articles
            articles = await self._process_feed(raw_feed, source_id)
            stats = await self._save_articles(articles, category_id)

            # Update health status on success
            self._update_health(service_name, "operational")

            logger.debug(
                f"Feed fetch completed in {time.time() - start_time:.2f}s for {url}"
            )
            return stats, None

        except asyncio.TimeoutError as e:
            logger.error(f"Timeout fetching feed: {url}")
            self._update_health(
                service_name, "degraded", error=f"Timeout fetching feed: {url}"
            )
            await self._log_error(
                RSSFeedError("Timeout fetching feed"),
                start_time,
                source_id,
                category_id,
            )
            return 0, e
        except Exception as e:
            self._update_health(service_name, "degraded", error=str(e))
            await self._log_error(e, start_time, source_id, category_id)
            return 0, e

    def _update_health(
        self, service_name: str, state: str, error: str | None = None
    ) -> None:
        """Update health service with current status"""
        if not self.health_service:
            return

        health_info = {
            "state": state,
            "last_failure_time": time.time() if state != "operational" else None,
            "last_success_time": time.time() if state == "operational" else None,
        }

        if error and state != "operational":
            health_info["last_error"] = error
            health_info["failure_count"] = 1

        self.health_service.update_service_health(service_name, **health_info)

    async def _fetch_feed(self, url: str) -> Tuple[Any, bytes]:
        """Fetch feed contents with timeout protection"""
        try:
            return await asyncio.wait_for(
                self.http_client.request("GET", url), timeout=settings.REQUEST_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching feed: {url}")
            raise RSSFeedError(f"Timeout fetching feed: {url}")

    async def _process_feed(
        self, raw_feed: Tuple[Any, bytes], source_id: int
    ) -> List[Articles]:
        """Process feed content into article objects"""
        headers, body = raw_feed
        content_type = headers.headers.get("Content-Type", "").lower()

        try:
            # Handle gzip compression if present
            if "gzip" in headers.headers.get("Content-Encoding", "").lower():
                body = gzip.decompress(body)

            # Convert bytes to string
            content = (
                body.decode("utf-8", errors="replace")
                if isinstance(body, bytes)
                else body
            )

            # Parse content using appropriate parser
            parser = self._get_parser(content_type, source_id)
            return await parser.parse_content(content)
        except Exception as e:
            logger.error(f"Error processing feed content: {e}")
            self._update_health(f"feed_parser_{source_id}", "degraded", error=str(e))
            return []

    def _get_parser(self, content_type: str, source_id: int) -> FeedParser:
        """Get or create an appropriate feed parser based on content type"""
        cache_key = f"{content_type}_{source_id}"

        # Return cached parser if available
        if cache_key in self._parser_cache:
            return self._parser_cache[cache_key]

        # Create appropriate parser based on content type
        if "xml" in content_type.lower():
            parser = XMLFeedParser(source_id)
        elif "json" in content_type.lower():
            parser = JSONFeedParser(source_id)
        else:
            logger.warning(
                f"Unknown content type: {content_type}, defaulting to XML parser. Source: {source_id}"
            )
            parser = XMLFeedParser(source_id)

        # Cache the parser for future use
        self._parser_cache[cache_key] = parser
        return parser

    async def _save_articles(self, articles: List[Articles], category_id: int) -> int:
        """Save articles to database with circuit breaker protection"""
        if not articles:
            return 0

        successful_articles = 0

        # Get category
        category = self._get_category(category_id)
        if not category:
            logger.warning(f"Category not found: {category_id}")
            return 0

        # Extract content hashes
        content_hashes = {
            article.content_hash for article in articles if article.content_hash
        }

        if not content_hashes:
            return 0

        # Check Redis first for existing hashes
        redis_hash_results = await self._check_hashes_in_redis(content_hashes)

        # Check database for remaining hashes not found in Redis
        content_hashes_to_check = {
            h
            for h in content_hashes
            if h not in redis_hash_results or not redis_hash_results[h]
        }

        existing_db_hashes = await self._check_articles_exist_in_db(
            content_hashes_to_check
        )

        # Combine Redis and DB results
        existing_hashes = {
            h
            for h in content_hashes
            if (h in redis_hash_results and redis_hash_results[h])
            or h in existing_db_hashes
        }

        # Filter out existing articles
        new_articles = [
            article
            for article in articles
            if article.content_hash and article.content_hash not in existing_hashes
        ]

        # De-duplicate articles by content hash, keeping the earliest publication
        unique_articles = {}
        for article in new_articles:
            if article.content_hash not in unique_articles:
                unique_articles[article.content_hash] = article
            elif article.pub_date < unique_articles[article.content_hash].pub_date:
                unique_articles[article.content_hash] = article

        new_articles = list(unique_articles.values())

        if new_articles:
            # Save articles to database
            success = await self._persist_articles(new_articles, category)
            return success

        return 0

    async def _check_hashes_in_redis(self, content_hashes: Set[str]) -> Dict[str, bool]:
        """Check which content hashes exist in Redis"""
        if not content_hashes:
            return {}

        try:
            redis_circuit = self._get_circuit("redis")
            if redis_circuit:
                return await redis_circuit.execute(
                    self.redis.pipeline_check_hashes, list(content_hashes)
                )
            else:
                return await self.redis.pipeline_check_hashes(list(content_hashes))
        except Exception as e:
            logger.warning(f"Redis hash check failed, falling back to DB: {e}")
            return {}

    async def _persist_articles(
        self, articles: List[Articles], category: Categories
    ) -> int:
        """Persist articles to database with circuit breaker protection"""
        successful_articles = 0

        async def save_articles():
            nonlocal successful_articles
            new_hashes = []

            for article in articles:
                article.categories.append(category)
                self.session.add(article)
                new_hashes.append(article.content_hash)
                successful_articles += 1

            self.session.commit()
            logger.info(f"Saved {successful_articles} new articles to database")

            # Add hashes to Redis asynchronously
            asyncio.create_task(self._cache_article_hashes(new_hashes))
            return successful_articles

        # Use circuit breaker if available
        db_circuit = self._get_circuit("db")
        try:
            if db_circuit:
                return await db_circuit.execute(save_articles)
            else:
                return await save_articles()
        except Exception as e:
            logger.error(f"Error committing new articles: {e}")
            self.session.rollback()
            self._update_health("news_db_operations", "degraded", error=str(e))
            return 0

    async def _cache_article_hashes(self, hashes: List[str]) -> None:
        """Cache article hashes in Redis for future duplicate checks"""
        if not hashes or not self.redis:
            return

        try:
            redis_circuit = self._get_circuit("redis")
            if redis_circuit:
                await redis_circuit.execute(self.redis.pipeline_add_hashes, hashes)
            else:
                await self.redis.pipeline_add_hashes(hashes)
        except Exception as e:
            logger.error(f"Failed to add hashes to Redis: {e}")

    async def _check_articles_exist_in_db(self, content_hashes: Set[str]) -> Set[str]:
        """Check which content hashes already exist in database"""
        if not content_hashes:
            return set()

        db_circuit = self._get_circuit("db")
        try:

            async def check_hashes():
                results = self.session.exec(
                    select(Articles.content_hash).where(
                        Articles.content_hash.in_(content_hashes)
                    )
                ).all()
                return set(results)

            if db_circuit:
                return await db_circuit.execute(check_hashes)
            else:
                return await check_hashes()
        except Exception as e:
            logger.error(f"DB hash check failed: {e}")
            return set()

    def _get_category(self, category_id: int) -> Optional[Categories]:
        """Get category by ID, using cache if available"""
        if category_id in self._category_cache:
            return self._category_cache[category_id]

        # If not in cache, fetch from database
        category = self.session.get(Categories, category_id)
        if category:
            self._category_cache[category_id] = category

        return category

    async def _log_error(
        self, error: Exception, start_time: float, source_id: int, category_id: int
    ) -> None:
        """Log feed fetch error with metrics"""
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

        # Update health service on error
        self._update_health(
            f"feed_{source_id}_{category_id}", "degraded", error=str(error)
        )
