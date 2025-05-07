import gzip
import time
import asyncio
from typing import List, Tuple, Any, Set, Dict, Optional
from sqlmodel import Session, select
from src.clients.redis import RedisClient
from src.core.logging import LogContext, PerformanceLogger, add_correlation_id
from src.models.db_models import Articles, Feeds
from src.clients.http import HTTPClient
from src.clients.connection import ConnectionPool
from src.core.exceptions import RSSFeedError
from src.parsers.xml import XMLFeedParser
from src.parsers.json import JSONFeedParser
from src.parsers.base import FeedParser
from src.core.config import settings
from src.core.degradation import HealthService
from src.utils.text_utils import calculate_title_similarity


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
        self._feed_cache = {}

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
        self,
        feeds: List[
            Tuple[str, str, str]
        ],  # Changed from (int, int, str) to (str, str, str)
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
                "sources": [source_name for source_name, _, _ in feeds],
            },
        )

        # Prefetch feeds for efficiency
        await self._prefetch_feeds([(source, feed) for source, feed, _ in feeds])

        async def fetch_with_semaphore(source_name, feed_name, url):
            async with self._semaphore:
                try:
                    # Add feed-specific context
                    add_correlation_id("source_name", source_name)
                    add_correlation_id("feed_name", feed_name)
                    add_correlation_id("feed_url", url)

                    with PerformanceLogger(
                        logger, f"fetch_feed_{source_name}_{feed_name}"
                    ):
                        result = await self.fetch_headlines(source_name, feed_name, url)
                        return result
                except Exception as e:
                    logger.error(
                        "Error fetching headlines",
                        extra={
                            "error": str(e),
                            "source_name": source_name,
                            "feed_name": feed_name,
                            "url": url,
                            "error_type": e.__class__.__name__,
                        },
                    )
                    self._update_health(
                        f"feed_{source_name}_{feed_name}", "degraded", error=str(e)
                    )
                    return 0, e

        # Fetch all feeds concurrently with controlled concurrency
        tasks = [
            fetch_with_semaphore(source_name, feed_name, url)
            for source_name, feed_name, url in feeds
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

    async def _prefetch_feeds(self, feed_keys: List[Tuple[str, str]]) -> None:
        """Prefetch and cache feeds to reduce database queries"""
        if not feed_keys:
            return

        unique_keys = list(set(feed_keys))

        logger.debug("Prefetching feeds", extra={"feed_count": len(unique_keys)})

        async def fetch_feeds():
            feeds = []
            for source_name, feed_name in unique_keys:
                feed = self.session.exec(
                    select(Feeds).where(
                        (Feeds.source_name == source_name) & (Feeds.name == feed_name)
                    )
                ).first()
                if feed:
                    feeds.append(feed)

            for feed in feeds:
                self._feed_cache[(feed.source_name, feed.name)] = feed

            logger.debug(
                "Feeds prefetched",
                extra={
                    "requested": len(unique_keys),
                    "found": len(feeds),
                    "missing": len(unique_keys) - len(feeds),
                },
            )

        # Use circuit breaker if available
        db_circuit = self._get_circuit("db")
        try:
            with PerformanceLogger(logger, "prefetch_feeds"):
                if db_circuit:
                    await db_circuit.execute(
                        fetch_feeds,
                        cache_key=f"feeds_{'-'.join([f'{s}_{f}' for s, f in unique_keys])}",
                    )
                else:
                    await fetch_feeds()
        except Exception as e:
            logger.error(
                "Failed to prefetch feeds",
                extra={
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "feed_keys": unique_keys,
                },
            )

    async def fetch_headlines(
        self, source_name: str, feed_name: str, url: str
    ) -> Tuple[int, None | BaseException]:
        """Fetch headlines from a feed URL with graceful degradation"""
        start_time = time.time()
        service_name = f"feed_{source_name}_{feed_name}"

        # Add feed-specific correlation IDs
        add_correlation_id("source_name", source_name)
        add_correlation_id("feed_name", feed_name)
        add_correlation_id("feed_url", url)

        logger.info(
            "Fetching feed headlines",
            extra={"source_name": source_name, "feed_name": feed_name, "url": url},
        )

        try:
            # Determine timeout based on URL
            timeout = 1.0 if "longread" in url else settings.REQUEST_TIMEOUT

            # If we have a circuit breaker, use it
            feed_circuit = self._get_circuit("feed")

            with PerformanceLogger(logger, f"fetch_raw_feed_{source_name}_{feed_name}"):
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
            with PerformanceLogger(logger, f"process_feed_{source_name}_{feed_name}"):
                articles = await self._process_feed(raw_feed, source_name)

            with PerformanceLogger(logger, f"save_articles_{source_name}_{feed_name}"):
                stats = await self._save_articles(articles, source_name, feed_name)

            # Update health status on success
            self._update_health(service_name, "operational")

            duration = time.time() - start_time
            logger.info(
                "Feed fetch completed",
                extra={
                    "duration_s": round(duration, 2),
                    "articles_found": len(articles),
                    "articles_saved": stats,
                    "source_name": source_name,
                    "feed_name": feed_name,
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
                source_name,
                feed_name,
            )
            return 0, e
        except Exception as e:
            self._update_health(service_name, "degraded", error=str(e))
            await self._log_error(e, start_time, source_name, feed_name)
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
        self, raw_feed: Tuple[Any, bytes], source_name: str
    ) -> List[Articles]:
        """Process feed content into article objects"""
        headers, body = raw_feed
        content_type = headers.headers.get("Content-Type", "").lower()

        logger.debug(
            "Processing feed content",
            extra={
                "source_name": source_name,
                "content_type": content_type,
                "content_length": len(body) if body else 0,
            },
        )

        try:
            # Handle gzip compression if present
            if "gzip" in headers.headers.get("Content-Encoding", "").lower():
                body = gzip.decompress(body)
                logger.debug(
                    "Decompressed gzipped content", extra={"source_name": source_name}
                )

            # Convert bytes to string
            content = (
                body.decode("utf-8", errors="replace")
                if isinstance(body, bytes)
                else body
            )

            # Parse content using appropriate parser
            parser = self._get_parser(content_type, source_name)
            articles = await parser.parse_content(content)

            logger.debug(
                "Feed content processed",
                extra={"source_name": source_name, "article_count": len(articles)},
            )

            return articles
        except Exception as e:
            logger.error(
                "Error processing feed content",
                extra={
                    "error": str(e),
                    "source_name": source_name,
                    "content_type": content_type,
                    "error_type": e.__class__.__name__,
                },
            )
            self._update_health(f"feed_parser_{source_name}", "degraded", error=str(e))
            return []

    def _get_parser(self, content_type: str, source_name: str) -> FeedParser:
        """Get or create an appropriate feed parser based on content type"""
        cache_key = f"{content_type}_{source_name}"

        # Return cached parser if available
        if cache_key in self._parser_cache:
            return self._parser_cache[cache_key]

        # Create appropriate parser based on content type
        if "xml" in content_type.lower():
            parser = XMLFeedParser(source_name)
            parser_type = "xml"
        elif "json" in content_type.lower():
            parser = JSONFeedParser(source_name)
            parser_type = "json"
        else:
            logger.warning(
                "Unknown content type. Trying XML parser",
                extra={"content_type": content_type, "source_name": source_name},
            )
            parser = XMLFeedParser(source_name)
            parser_type = "xml_fallback"

        logger.debug(
            "Created feed parser",
            extra={
                "parser_type": parser_type,
                "content_type": content_type,
                "source_name": source_name,
            },
        )

        # Cache the parser for future use
        self._parser_cache[cache_key] = parser
        return parser

    async def _save_articles(
        self, articles: List[Articles], source_name: str, feed_name: str
    ) -> int:
        """Save articles to database with deduplication"""
        if not articles:
            logger.debug(
                "No articles to save",
                extra={"source_name": source_name, "feed_name": feed_name},
            )
            return 0

        # Get feed
        feed = self._get_feed(source_name, feed_name)
        if not feed:
            logger.warning(
                "Feed not found",
                extra={"source_name": source_name, "feed_name": feed_name},
            )
            return 0

        # Check which articles already exist by signature
        new_articles, existing_hashes = await self._filter_existing_articles(
            articles, source_name, feed_name
        )

        # Update any existing articles if needed
        await self._update_existing_articles(articles, existing_hashes)

        # De-duplicate new articles by signature
        new_articles = self._deduplicate_by_signature(new_articles)

        # Check for similar titles
        if new_articles:
            new_articles = self._filter_by_title_similarity(
                new_articles, existing_hashes, source_name, feed_name
            )

        # Save the remaining articles
        if new_articles:
            return await self._persist_articles(new_articles, feed)

        return 0

    async def _filter_existing_articles(
        self, articles: List[Articles], source_name: str, feed_name: str
    ) -> Tuple[List[Articles], Set[str]]:
        """Check which articles already exist by signature hash"""
        # Extract signature hashes
        hashes = {article.signature for article in articles if article.signature}

        if not hashes:
            logger.warning(
                "No hashes in articles",
                extra={
                    "source_name": source_name,
                    "feed_name": feed_name,
                    "article_count": len(articles),
                },
            )
            return [], set()

        logger.debug(
            "Checking for duplicate articles",
            extra={
                "source_name": source_name,
                "feed_name": feed_name,
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

        # Filter out existing articles
        new_articles = [
            article
            for article in articles
            if article.signature and article.signature not in existing_hashes
        ]

        return new_articles, existing_hashes

    async def _update_existing_articles(
        self, articles: List[Articles], existing_hashes: Set[str]
    ) -> int:
        """Update any existing articles that have changed"""
        # Get existing articles that match our hashes
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
                "Updated articles",
                extra={
                    "articles_updated": articles_updated,
                    "source_name": new_article.source_name,
                },
            )

        return articles_updated

    def _deduplicate_by_signature(self, articles: List[Articles]) -> List[Articles]:
        """Deduplicate articles by signature, keeping earliest pub_date"""
        unique_articles = {}
        for article in articles:
            if article.signature not in unique_articles:
                unique_articles[article.signature] = article
            elif article.pub_date < unique_articles[article.signature].pub_date:
                unique_articles[article.signature] = article

        return list(unique_articles.values())

    def _filter_by_title_similarity(
        self,
        articles: List[Articles],
        existing_hashes: Set[str],
        source_name: str,
        feed_name: str,
    ) -> List[Articles]:
        """Filter out articles with similar titles or identical URLs"""
        duplicates = []

        for article in articles[:]:
            # Skip if already identified as a duplicate
            if article.signature in existing_hashes:
                continue

            # Find candidates with the exact same pub_date and source
            candidates = self.session.exec(
                select(Articles)
                .where(Articles.source_name == article.source_name)
                .where(Articles.pub_date == article.pub_date)
                .limit(30)  # Increased limit to catch more potential duplicates
            ).all()

            for candidate in candidates:
                # Check URL first - identical URLs are almost certainly duplicates
                if article.original_url == candidate.original_url:
                    logger.info(
                        "Found duplicate by identical URL",
                        extra={
                            "new_title": article.title,
                            "existing_title": candidate.title,
                            "url": article.original_url,
                            "source_name": article.source_name,
                        },
                    )
                    duplicates.append(article)
                    existing_hashes.add(article.signature)
                    break

                # Check author name if available
                if (
                    article.author_name
                    and candidate.author_name
                    and article.author_name == candidate.author_name
                ):
                    # Same author, same date - likely duplicate, use lower similarity threshold
                    similarity = calculate_title_similarity(
                        article.title, candidate.title
                    )
                    if similarity > 0.6:  # Lower threshold when author matches
                        logger.info(
                            "Found duplicate by author match and moderate title similarity",
                            extra={
                                "new_title": article.title,
                                "existing_title": candidate.title,
                                "similarity": round(similarity, 3),
                                "author": article.author_name,
                                "source_name": article.source_name,
                            },
                        )
                        duplicates.append(article)
                        existing_hashes.add(article.signature)
                        break

                # High title similarity check as before
                similarity = calculate_title_similarity(article.title, candidate.title)
                if similarity > 0.85:
                    logger.info(
                        "Found duplicate by high title similarity",
                        extra={
                            "new_title": article.title,
                            "existing_title": candidate.title,
                            "similarity": round(similarity, 3),
                            "source_name": article.source_name,
                        },
                    )
                    duplicates.append(article)
                    existing_hashes.add(article.signature)
                    break

        # Filter out duplicates found
        if duplicates:
            logger.info(
                "Filtered out duplicates",
                extra={
                    "duplicates_found": len(duplicates),
                    "source_name": source_name,
                    "feed_name": feed_name,
                },
            )
            return [a for a in articles if a not in duplicates]

        return articles

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

    async def _persist_articles(self, articles: List[Articles], feed: Feeds) -> int:
        """Persist articles to database with circuit breaker protection"""
        successful_articles = 0

        async def save_articles():
            nonlocal successful_articles
            new_hashes = []

            for article in articles:
                article.feeds.append(feed)
                self.session.add(article)
                new_hashes.append(article.signature)
                successful_articles += 1

            self.session.commit()
            logger.info(
                "Saved new articles to database",
                extra={
                    "article_count": successful_articles,
                    "source_name": feed.source_name,
                    "feed_name": feed.name,
                },
            )

            # Add hashes to Redis asynchronously
            asyncio.create_task(self._cache_article_hashes(new_hashes))
            return successful_articles

        # Use circuit breaker if available
        db_circuit = self._get_circuit("db")
        try:
            with PerformanceLogger(
                logger, f"persist_articles_{feed.source_name}_{feed.name}"
            ):
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
                    "source_name": feed.source_name,
                    "feed_name": feed.name,
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

    def _get_feed(self, source_name: str, feed_name: str) -> Optional[Feeds]:
        """Get feed by composite key, using cache if available"""
        cache_key = (source_name, feed_name)
        if cache_key in self._feed_cache:
            return self._feed_cache[cache_key]

        # If not in cache, fetch from database
        feed = self.session.exec(
            select(Feeds).where(
                (Feeds.source_name == source_name) & (Feeds.name == feed_name)
            )
        ).first()

        if feed:
            self._feed_cache[cache_key] = feed
            logger.debug(
                "Feed fetched from database and cached",
                extra={
                    "source_name": source_name,
                    "feed_name": feed_name,
                    "display_name": feed.display_name,
                },
            )
        else:
            logger.warning(
                "Feed not found in database",
                extra={"source_name": source_name, "feed_name": feed_name},
            )

        return feed

    async def _log_error(
        self, error: Exception, start_time: float, source_name: str, feed_name: str
    ) -> None:
        """Log feed fetch error with metrics"""
        fetch_time = time.time() - start_time
        logger.error(
            "Error fetching feed",
            extra={
                "error": str(error),
                "error_type": error.__class__.__name__,
                "fetch_time_seconds": round(fetch_time, 2),
                "source_name": source_name,
                "feed_name": feed_name,
            },
        )

        # Update health service on error
        self._update_health(
            f"feed_{source_name}_{feed_name}", "degraded", error=str(error)
        )
