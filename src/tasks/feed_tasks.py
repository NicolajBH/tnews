from celery import shared_task, group, chord
from sqlmodel import Session
import asyncio
import time
import random
from collections import defaultdict

from src.clients.connection import ConnectionPool
from src.core.container import get_health_service
from src.core.logging import LogContext, PerformanceLogger, add_correlation_id
from src.db.database import engine
from src.clients.news import NewsClient
from src.clients.redis import RedisClient
from src.db.operations import fetch_feed_urls
from src.core.config import settings

logger = LogContext(__name__)


@shared_task(
    bind=True,
    max_retries=2,
    soft_time_limit=290,
    time_limit=300,
    acks_late=True,
    priority=9,
    expires=300,
)
def fetch_all_feeds(self):
    """
    Coordinator task that fetches all feeds in parallel chunks
    """
    start_time = time.time()
    task_id = self.request.id

    add_correlation_id("task_id", task_id)
    add_correlation_id("operation", "fetch_all_feeds")

    logger.info(
        "Starting feed fetch coordinator tasks",
        extra={"task_id": task_id, "priority": 9, "max_retries": 2},
    )

    try:
        with PerformanceLogger(logger, "fetch_feed_urls"):
            from src.db.database import get_engine

            task_engine = get_engine()

            with Session(task_engine) as session:
                results = fetch_feed_urls(session)
                feeds = [
                    (cat.source_id, cat.id, source.base_url + cat.feed_url)
                    for cat, source in results
                    if cat.source_id and cat.id
                ]

        total_feeds = len(feeds)
        sources = {source_id for source_id, _, _ in feeds}

        logger.info(
            "Feeds retrieved from database",
            extra={
                "total_feeds": total_feeds,
                "unique_sources": len(sources),
                "task_id": task_id,
            },
        )

        if not feeds:
            logger.warning("No feeds to process", extra={"task_id": task_id})
            return {
                "total_articles": 0,
                "successful_fetches": 0,
                "failed_fetches": 0,
                "fetch_time_seconds": 0,
                "feeds_processed": 0,
            }

        # calculate chunk size and create chunks
        chunk_size = getattr(settings, "FEED_CHUNK_SIZE", 5)
        feed_chunks = [
            feeds[i : i + chunk_size] for i in range(0, len(feeds), chunk_size)
        ]
        # shuffle to distribute load
        random.shuffle(feed_chunks)

        logger.info(
            "Feed chunks created",
            extra={
                "chunk_size": chunk_size,
                "total_chunks": len(feed_chunks),
                "total_feeds": total_feeds,
                "task_id": task_id,
            },
        )

        # create a chord of tasks: each chunk processed in parallel, then results collected
        tasks_group = group(fetch_feed_chunk.s(chunk) for chunk in feed_chunks)
        chord_result = chord(tasks_group)(collect_feed_results.s(start_time))

        setup_time = time.time() - start_time
        logger.info(
            "feed fetch tasks dispatched",
            extra={
                "task_id": task_id,
                "chord_id": chord_result.id,
                "feeds_dispatched": total_feeds,
                "chunks_created": len(feed_chunks),
                "setup_time_seconds": round(setup_time, 2),
            },
        )
    except Exception as e:
        logger.error(
            "Feed fetch coordinator task failed",
            extra={
                "error": str(e),
                "error_type": e.__class__.__name__,
                "task_id": task_id,
                "elapsed_seconds": round(time.time() - start_time, 2),
            },
        )
        self.retry(exc=e, countdown=30)


@shared_task
def collect_feed_results(task_results, start_time):
    """
    Collect and aggregate results from all feed fetch chunks
    """
    task_id = collect_feed_results.request.id
    total_time = time.time() - start_time

    add_correlation_id("task_id", task_id)
    add_correlation_id("operation", "collect_feed_results")

    # filter out failed tasks
    valid_results = [res for res in task_results if res]
    failed_tasks = len(task_results) - len(valid_results)

    if failed_tasks > 0:
        logger.warning(
            "Some chunk tasks failed completely",
            extra={
                "task_id": task_id,
                "failed_tasks": failed_tasks,
                "total_tasks": len(task_results),
            },
        )

    # aggregate metrics
    total_articles = sum(res.get("total_articles", 0) for res in valid_results)
    successful_fetches = sum(res.get("successful_fetches", 0) for res in valid_results)
    failed_fetches = sum(res.get("failed_fetches", 0) for res in valid_results)
    total_feeds = successful_fetches + failed_fetches

    # throughput rates
    articles_per_second = total_articles / total_time if total_time > 0 else 0
    feeds_per_second = total_feeds / total_time if total_time > 0 else 0

    logger.info(
        "Feed fetch operation completed",
        extra={
            "task_id": task_id,
            "total_articles": total_articles,
            "successful_fetches": successful_fetches,
            "failed_fetches": failed_fetches,
            "total_feeds": total_feeds,
            "fetch_time_seconds": round(total_time, 2),
            "success_rate": round(successful_fetches / total_feeds * 100, 2)
            if total_feeds > 0
            else 0,
            "articles_per_second": round(articles_per_second, 2),
            "feeds_per_second": round(feeds_per_second, 2),
            "chunk_tasks": len(task_results),
            "failed_chunk_tasks": failed_tasks,
        },
    )

    return {
        "total_articles": total_articles,
        "successful_fetches": successful_fetches,
        "failed_fetches": failed_fetches,
        "fetch_time_seconds": round(total_time, 2),
        "success_rate": round(successful_fetches / total_feeds * 100, 2)
        if total_feeds > 0
        else 0,
        "articles_per_second": round(articles_per_second, 2),
        "feeds_per_second": round(feeds_per_second, 2),
    }


@shared_task(
    bind=True,
    max_retries=3,
    soft_time_limit=60,
    time_limit=70,
    acks_late=True,
    priority=5,
    rate_limit="15/m",
)
def fetch_feed_chunk(self, feeds_chunk):
    """
    Process a chunk of feeds, fetching articles from each feed
    """
    task_id = self.request.id
    start_time = time.time()

    add_correlation_id("task_id", task_id)
    add_correlation_id("operation", "fetch_feed_chunk")
    add_correlation_id("chunk_size", len(feeds_chunk))

    # source ids for logging
    source_ids = list(set(source_id for source_id, _, _ in feeds_chunk))

    logger.info(
        "Starting feed chunk processing",
        extra={
            "task_id": task_id,
            "chunk_size": len(feeds_chunk),
            "source_ids": source_ids,
        },
    )

    successful_fetches = 0
    failed_fetches = 0
    total_articles = 0
    source_stats = defaultdict(lambda: {"success": 0, "failure": 0, "articles": 0})

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # initialize services
        with PerformanceLogger(logger, "chunk_init"):
            connection_pool = ConnectionPool()
            connection_pool.reset_pools()
            connection_pool.pools = defaultdict(
                lambda: asyncio.Queue(maxsize=connection_pool.pool_size)
            )

            with Session(engine) as session:
                health_service = get_health_service()
                redis_client = RedisClient(health_service=health_service)
                news_client = NewsClient(session, redis_client)

        # fetch chunk feeds
        with PerformanceLogger(logger, f"fetch_feed_chunk_{task_id}"):
            fetch_results = loop.run_until_complete(
                news_client.fetch_multiple_feeds(feeds_chunk)
            )
            loop.run_until_complete(redis_client.close())

        # process results
        for i, result in enumerate(fetch_results):
            source_id, category_id, url = feeds_chunk[i]

            if isinstance(result[1], Exception):
                failed_fetches += 1
                source_stats[source_id]["failure"] += 1
                logger.warning(
                    "Feed fetch failed",
                    extra={
                        "task_id": task_id,
                        "source_id": source_id,
                        "category_id": category_id,
                        "url": url,
                        "error": str(result[1]),
                        "error_type": result[1].__class__.__name__,
                    },
                )
            else:
                article_count, _ = result
                total_articles += article_count
                successful_fetches += 1
                source_stats[source_id]["success"] += 1
                source_stats[source_id]["articles"] += article_count

                logger.debug(
                    "Feed processsed successfully",
                    extra={
                        "task_id": task_id,
                        "source_id": source_id,
                        "category_id": category_id,
                        "article_count": article_count,
                    },
                )

            # metrics
            chunk_time = time.time() - start_time
            feeds_per_second = len(feeds_chunk) / chunk_time if chunk_time > 0 else 0
            articles_per_second = total_articles / chunk_time if chunk_time > 0 else 0
            success_rate = successful_fetches / len(feeds_chunk) if feeds_chunk else 0

            source_summary = {
                str(source_id): {
                    "success": stats["success"],
                    "failure": stats["failure"],
                    "articles": stats["articles"],
                }
                for source_id, stats in source_stats.items()
            }

            logger.info(
                "Feed chunk processing complete",
                extra={
                    "task_id": task_id,
                    "chunk_size": len(feeds_chunk),
                    "total_articles": total_articles,
                    "successful_fetches": successful_fetches,
                    "failed_fetches": failed_fetches,
                    "fetch_time_seconds": round(chunk_time, 2),
                    "feeds_per_second": round(feeds_per_second, 2),
                    "articles_per_second": round(articles_per_second, 2),
                    "sucess_rate": round(success_rate * 100, 2),
                    "source_stats": source_summary,
                },
            )

            return {
                "total_articles": total_articles,
                "successful_fetches": successful_fetches,
                "failed_fetches": failed_fetches,
                "fetch_time_seconds": round(chunk_time, 2),
                "chunk_size": len(feeds_chunk),
                "source_stats": source_summary,
            }
    except Exception as e:
        chunk_time = time.time() - start_time
        logger.error(
            "Feed chunk processing failed",
            extra={
                "error": str(e),
                "error_type": e.__class__.__name__,
                "task_id": task_id,
                "chunk_size": len(feeds_chunk),
                "elapsed_seconds": round(chunk_time, 2),
            },
        )
        raise
    finally:
        try:
            with PerformanceLogger(logger, "cleanup_event_loop"):
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()

                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
        except Exception as e:
            logger.warning(
                "Error during event loop cleanup",
                extra={
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "task_id": task_id,
                    "pending_tasks": len(pending)
                    if "pending" in locals()
                    else "unknown",
                },
            )
        loop.close()
