import gzip
import time
import asyncio
from typing import List, Tuple, Any, Set, Dict, Optional
from sqlmodel import Session, select
from src.clients.redis import RedisClient
from src.core.logging import LogContext, PerformanceLogger, add_correlation_id
from src.models.db_models import Articles, Categories
from src.clients.http import HTTPClient
from src.clients.connection import ConnectionPool
from src.core.exceptions import RSSFeedError
from src.parsers.xml import XMLFeedParser
from src.parsers.json import JSONFeedParser
from src.parsers.base import FeedParser
from src.core.config import settings
from src.core.degradation import HealthService


logger = LogContext(__name__)


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

        logger.info(
            "NewsClient initialized",
            extra={
                "pool_size": settings.POOL_SIZE,
                "max_concurrent_requests": settings.MAX_CONCURRENT_REQUEST,
                "has_health_service": health_service is not None,
            },
        )

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

        logger.info(
            "Circuit breakers initialized",
            extra={"circuit_types": list(circuit_configs.keys())},
        )

    def _get_circuit(self, circuit_type: str):
        """Get a circuit breaker by type"""
        return self._circuit_breakers.get(circuit_type)

    async def fetch_multiple_feeds(
        self, feeds: List[Tuple[int, int, str]]
    ) -> List[Tuple[int, Exception]]:
        """Fetch multiple feeds in parallel with concurrency control"""
        # Add operation information to correlation context
        add_correlation_id("operation", "fetch_multiple_feeds")
        add_correlation_id("feed_count", len(feeds))

        feed_start_time = time.time()
        logger.info(
            "Starting batch feed fetch",
            extra={
                "feed_count": len(feeds),
                "sources": [source_id for source_id, _, _ in feeds],
            },
        )

        # Prefetch categories for efficiency
        await self._prefetch_categories([cat_id for _, cat_id, _ in feeds])

        async def fetch_with_semaphore(source_id, category_id, url):
            async with self._semaphore:
                try:
                    # Add feed-specific context
                    add_correlation_id("source_id", source_id)
                    add_correlation_id("category_id", category_id)
                    add_correlation_id("feed_url", url)

                    with PerformanceLogger(
                        logger, f"fetch_feed_{source_id}_{category_id}"
                    ):
                        result = await self.fetch_headlines(source_id, category_id, url)
                        return result
                except Exception as e:
                    logger.error(
                        "Error fetching headlines",
                        extra={
                            "error": str(e),
                            "source_id": source_id,
                            "category_id": category_id,
                            "url": url,
                            "error_type": e.__class__.__name__,
                        },
                    )
                    self._update_health(
                        f"feed_{source_id}_{category_id}", "degraded", error=str(e)
                    )
                    return 0, e

        # Fetch all feeds concurrently with controlled concurrency
        tasks = [
            fetch_with_semaphore(source_id, category_id, url)
            for source_id, category_id, url in feeds
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Calculate batch metrics
        total_duration = time.time() - feed_start_time
        success_count = sum(1 for r in results if isinstance(r, tuple) and r[1] is None)
        total_articles = sum(
            r[0] if isinstance(r, tuple) and r[1] is None else 0 for r in results
        )

        logger.info(
            "Batch feed fetch complete",
            extra={
                "total_duration_s": round(total_duration, 2),
                "feed_count": len(feeds),
                "success_count": success_count,
                "failure_count": len(feeds) - success_count,
                "total_articles": total_articles,
                "articles_per_second": round(total_articles / total_duration, 2)
                if total_duration > 0
                else 0,
            },
        )

        return results

    async def _prefetch_categories(self, category_ids: List[int]) -> None:
        """Prefetch and cache categories to reduce database queries"""
        if not category_ids:
            return

        unique_ids = list(set(category_ids))

        logger.debug(
            "Prefetching categories", extra={"category_count": len(unique_ids)}
        )

        async def fetch_categories():
            categories = self.session.exec(
                select(Categories).where(Categories.id.in_(unique_ids))
            ).all()

            for category in categories:
                self._category_cache[category.id] = category

            logger.debug(
                "Categories prefetched",
                extra={
                    "requested": len(unique_ids),
                    "found": len(categories),
                    "missing": len(unique_ids) - len(categories),
                },
            )

        # Use circuit breaker if available
        db_circuit = self._get_circuit("db")
        try:
            with PerformanceLogger(logger, "prefetch_categories"):
                if db_circuit:
                    await db_circuit.execute(
                        fetch_categories,
                        cache_key=f"categories_{'-'.join(map(str, unique_ids))}",
                    )
                else:
                    await fetch_categories()
        except Exception as e:
            logger.error(
                "Failed to prefetch categories",
                extra={
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "category_ids": unique_ids,
                },
            )

    async def fetch_headlines(
        self, source_id: int, category_id: int, url: str
    ) -> Tuple[int, None | BaseException]:
        """Fetch headlines from a feed URL with graceful degradation"""
        start_time = time.time()
        service_name = f"feed_{source_id}_{category_id}"

        # Add feed-specific correlation IDs
        add_correlation_id("source_id", source_id)
        add_correlation_id("category_id", category_id)
        add_correlation_id("feed_url", url)

        logger.info(
            "Fetching feed headlines",
            extra={"source_id": source_id, "category_id": category_id, "url": url},
        )

        try:
            # Determine timeout based on URL
            timeout = 1.0 if "longread" in url else settings.REQUEST_TIMEOUT

            # If we have a circuit breaker, use it
            feed_circuit = self._get_circuit("feed")

            with PerformanceLogger(logger, f"fetch_raw_feed_{source_id}_{category_id}"):
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
            with PerformanceLogger(logger, f"process_feed_{source_id}_{category_id}"):
                articles = await self._process_feed(raw_feed, source_id)

            with PerformanceLogger(logger, f"save_articles_{source_id}_{category_id}"):
                stats = await self._save_articles(articles, category_id)

            # Update health status on success
            self._update_health(service_name, "operational")

            duration = time.time() - start_time
            logger.info(
                "Feed fetch completed",
                extra={
                    "duration_s": round(duration, 2),
                    "articles_found": len(articles),
                    "articles_saved": stats,
                    "source_id": source_id,
                    "category_id": category_id,
                    "url": url,
                },
            )
            return stats, None

        except asyncio.TimeoutError as e:
            logger.error(
                "Timeout fetching feed",
                extra={
                    "error": str(e),
                    "url": url,
                    "error_type": e.__class__.__name__,
                    "timeout": timeout,  # pyright: ignore[reportPossiblyUnboundVariable]
                },
            )
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
        logger.debug(f"Fetching feed from URL: {url}")

        try:
            response = await asyncio.wait_for(
                self.http_client.request("GET", url), timeout=settings.REQUEST_TIMEOUT
            )

            headers, body = response
            content_length = len(body) if body else 0

            logger.debug(
                "Feed fetched successfully",
                extra={
                    "url": url,
                    "status_code": headers.status_line,
                    "content_type": headers.headers.get("Content-Type", "unknown"),
                    "content_length": content_length,
                },
            )

            return response
        except asyncio.TimeoutError as e:
            logger.error(
                "Timeout fetching feed",
                extra={
                    "error": str(e),
                    "url": url,
                    "error_type": e.__class__.__name__,
                    "timeout": settings.REQUEST_TIMEOUT,
                },
            )
            raise RSSFeedError(f"Timeout fetching feed: {url}")

    async def _process_feed(
        self, raw_feed: Tuple[Any, bytes], source_id: int
    ) -> List[Articles]:
        """Process feed content into article objects"""
        headers, body = raw_feed
        content_type = headers.headers.get("Content-Type", "").lower()

        logger.debug(
            "Processing feed content",
            extra={
                "source_id": source_id,
                "content_type": content_type,
                "content_length": len(body) if body else 0,
            },
        )

        try:
            # Handle gzip compression if present
            if "gzip" in headers.headers.get("Content-Encoding", "").lower():
                body = gzip.decompress(body)
                logger.debug(
                    "Decompressed gzipped content", extra={"source_id": source_id}
                )

            # Convert bytes to string
            content = (
                body.decode("utf-8", errors="replace")
                if isinstance(body, bytes)
                else body
            )

            # Parse content using appropriate parser
            parser = self._get_parser(content_type, source_id)
            articles = await parser.parse_content(content)

            logger.debug(
                "Feed content processed",
                extra={"source_id": source_id, "article_count": len(articles)},
            )

            return articles
        except Exception as e:
            logger.error(
                "Error processing feed content",
                extra={
                    "error": str(e),
                    "source_id": source_id,
                    "content_type": content_type,
                    "error_type": e.__class__.__name__,
                },
            )
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
            parser_type = "xml"
        elif "json" in content_type.lower():
            parser = JSONFeedParser(source_id)
            parser_type = "json"
        else:
            logger.warning(
                "Unknown content type. Trying XML parser",
                extra={"content_type": content_type, "source_id": source_id},
            )
            parser = XMLFeedParser(source_id)
            parser_type = "xml_fallback"

        logger.debug(
            "Created feed parser",
            extra={
                "parser_type": parser_type,
                "content_type": content_type,
                "source_id": source_id,
            },
        )

        # Cache the parser for future use
        self._parser_cache[cache_key] = parser
        return parser

    async def _save_articles(self, articles: List[Articles], category_id: int) -> int:
        """Save articles to database with circuit breaker protection"""
        if not articles:
            logger.debug("No articles to save", extra={"category_id": category_id})
            return 0

        # Get category
        category = self._get_category(category_id)
        if not category:
            logger.warning("Category not found", extra={"category_id": category_id})
            return 0

        # Extract signature hashes
        hashes = {article.signature for article in articles if article.signature}

        if not hashes:
            logger.warning(
                "No hashes in articles",
                extra={"category_id": category_id, "article_count": len(articles)},
            )
            return 0

        logger.debug(
            "Checking for duplicate articles",
            extra={
                "category_id": category_id,
                "total_articles": len(articles),
                "unique_hashes": len(hashes),
            },
        )

        # Check Redis first for existing hashes
        redis_hash_results = await self._check_hashes_in_redis(hashes)

        # Check database for remaining hashes not found in Redis
        hashes_to_check = {
            h
            for h in hashes
            if h not in redis_hash_results or not redis_hash_results[h]
        }

        existing_db_hashes = await self._check_articles_exist_in_db(hashes_to_check)

        # Combine Redis and DB results
        existing_hashes = {
            h
            for h in hashes
            if (h in redis_hash_results and redis_hash_results[h])
            or h in existing_db_hashes
        }

        existing_articles = self.session.exec(
            select(Articles).where(Articles.signature.in_(existing_hashes))
        ).all()

        existing_by_hash = {article.signature: article for article in existing_articles}
        new_by_hash = {
            article.signature: article
            for article in articles
            if article.signature in existing_hashes
        }

        articles_updated = 0
        for hash, existing_article in existing_by_hash.items():
            if hash in new_by_hash:
                new_article = new_by_hash[hash]
                if existing_article.title != new_article.title:
                    existing_article.title = new_article.title
                    existing_article.updated_at = new_article.updated_at
                    existing_article.original_url = new_article.original_url
                    self.session.add(existing_article)
                    articles_updated += 1

        if articles_updated:
            self.session.commit()
            logger.info(
                "Updated article title",
                extra={"category_id": category.id, "updated_count": articles_updated},
            )

        # Filter out existing articles
        new_articles = [
            article
            for article in articles
            if article.signature and article.signature not in existing_hashes
        ]

        # De-duplicate articles by hash, keeping the earliest publication
        unique_articles = {}
        for article in new_articles:
            if article.signature not in unique_articles:
                unique_articles[article.signature] = article
            elif article.pub_date < unique_articles[article.signature].pub_date:
                unique_articles[article.signature] = article

        new_articles = list(unique_articles.values())

        logger.debug(
            "Filtered duplicate articles",
            extra={
                "category_id": category_id,
                "total_articles": len(articles),
                "existing_articles": len(existing_hashes),
                "new_articles": len(new_articles),
            },
        )

        if new_articles:
            # Save articles to database
            success = await self._persist_articles(new_articles, category)
            return success

        return 0

    async def _check_hashes_in_redis(self, hashes: Set[str]) -> Dict[str, bool]:
        """Check which content hashes exist in Redis"""
        if not hashes:
            return {}

        try:
            start_time = time.time()
            redis_circuit = self._get_circuit("redis")
            if redis_circuit:
                result = await redis_circuit.execute(
                    self.redis.pipeline_check_hashes, list(hashes)
                )
            else:
                result = await self.redis.pipeline_check_hashes(list(hashes))

            duration_ms = (time.time() - start_time) * 1000
            logger.debug(
                "Redis hash check completed",
                extra={
                    "duration_ms": round(duration_ms, 2),
                    "hash_count": len(hashes),
                    "found_count": sum(1 for v in result.values() if v),
                },
            )
            return result
        except Exception as e:
            logger.warning(
                "Redis hash check failed. Falling back to DB",
                extra={"error": str(e), "error_type": e.__class__.__name__},
            )
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
                new_hashes.append(article.signature)
                successful_articles += 1

            self.session.commit()
            logger.info(
                "Saved new articles to database",
                extra={
                    "article_count": successful_articles,
                    "category_id": category.id,
                    "category_name": category.name,
                },
            )

            # Add hashes to Redis asynchronously
            asyncio.create_task(self._cache_article_hashes(new_hashes))
            return successful_articles

        # Use circuit breaker if available
        db_circuit = self._get_circuit("db")
        try:
            with PerformanceLogger(logger, f"persist_articles_{category.id}"):
                if db_circuit:
                    return await db_circuit.execute(save_articles)
                else:
                    return await save_articles()
        except Exception as e:
            logger.error(
                "Error committing new articles",
                extra={
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "article_count": len(articles),
                    "category_id": category.id,
                },
            )
            self.session.rollback()
            self._update_health("news_db_operations", "degraded", error=str(e))
            return 0

    async def _cache_article_hashes(self, hashes: List[str]) -> None:
        """Cache article hashes in Redis for future duplicate checks"""
        if not hashes or not self.redis:
            return

        try:
            start_time = time.time()
            redis_circuit = self._get_circuit("redis")
            if redis_circuit:
                await redis_circuit.execute(self.redis.pipeline_add_hashes, hashes)
            else:
                await self.redis.pipeline_add_hashes(hashes)

            duration_ms = (time.time() - start_time) * 1000
            logger.debug(
                "Cached article hashes in Redis",
                extra={"hash_count": len(hashes), "duration_ms": round(duration_ms, 2)},
            )
        except Exception as e:
            logger.error(
                "Failed to add hashes to Redis",
                extra={"error": str(e), "error_type": e.__class__.__name__},
            )

    async def _check_articles_exist_in_db(self, hashes: Set[str]) -> Set[str]:
        """Check which content hashes already exist in database"""
        if not hashes:
            return set()

        db_circuit = self._get_circuit("db")
        try:
            start_time = time.time()

            async def check_hashes():
                results = self.session.exec(
                    select(Articles.signature).where(Articles.signature.in_(hashes))
                ).all()
                return set(results)

            if db_circuit:
                result = await db_circuit.execute(check_hashes)
            else:
                result = await check_hashes()

            duration_ms = (time.time() - start_time) * 1000
            logger.debug(
                "DB hash check completed",
                extra={
                    "duration_ms": round(duration_ms, 2),
                    "hash_count": len(hashes),
                    "found_count": len(result),
                },
            )

            return result
        except Exception as e:
            logger.error(
                "DB hash check failed",
                extra={
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "hash_count": len(hashes),
                },
            )
            return set()

    def _get_category(self, category_id: int) -> Optional[Categories]:
        """Get category by ID, using cache if available"""
        if category_id in self._category_cache:
            return self._category_cache[category_id]

        # If not in cache, fetch from database
        category = self.session.get(Categories, category_id)
        if category:
            self._category_cache[category_id] = category
            logger.debug(
                "Category fetched from database and cached",
                extra={"category_id": category_id, "category_name": category.name},
            )
        else:
            logger.warning(
                "Category not found in database", extra={"category_id": category_id}
            )

        return category

    async def _log_error(
        self, error: Exception, start_time: float, source_id: int, category_id: int
    ) -> None:
        """Log feed fetch error with metrics"""
        fetch_time = time.time() - start_time
        logger.error(
            "Error fetching feed",
            extra={
                "error": str(error),
                "error_type": error.__class__.__name__,
                "fetch_time_seconds": round(fetch_time, 2),
                "source_id": source_id,
                "category_id": category_id,
            },
        )

        # Update health service on error
        self._update_health(
            f"feed_{source_id}_{category_id}", "degraded", error=str(error)
        )
