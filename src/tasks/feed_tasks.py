from celery import shared_task, group, chord
from sqlmodel import Session
import asyncio
import logging
import time
import random
from collections import defaultdict
from src.clients.connection import ConnectionPool
from src.db.database import engine
from src.clients.news import NewsClient
from src.clients.redis import RedisClient
from src.db.operations import fetch_feed_urls
from src.core.config import settings

logger = logging.getLogger(__name__)


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
    start_time = time.time()

    try:
        with Session(engine) as session:
            results = fetch_feed_urls(session)
            feeds = [
                (cat.source_id, cat.id, source.base_url + cat.feed_url)
                for cat, source in results
                if cat.source_id and cat.id
            ]
        total_feeds = len(feeds)
        logger.info(f"Starting fetch of {total_feeds} feeds")

        if not feeds:
            logger.warning("No feeds to process")
            return {
                "total_articles": 0,
                "successful_fetches": 0,
                "failed_fetches": 0,
                "fetch_time_seconds": 0,
                "feeds_processed": 0,
            }

        chunk_size = getattr(settings, "FEED_CHUNK_SIZE", 5)
        feed_chunks = [
            feeds[i : i + chunk_size] for i in range(0, len(feeds), chunk_size)
        ]
        random.shuffle(feed_chunks)

        tasks_group = group(fetch_feed_chunk.s(chunk) for chunk in feed_chunks)
        chord_result = chord(tasks_group)(collect_feed_results.s(start_time))

        return {
            "task_id": chord_result.id,
            "feeds_dispatched": len(feeds),
            "chunks_created": len(feed_chunks),
        }
    except Exception as e:
        logger.error(f"Feed fetch coordinator task failed: {e}")
        self.retry(exc=e, countdown=30)


@shared_task
def collect_feed_results(task_results, start_time):
    total_time = time.time() - start_time

    total_articles = sum(res.get("total_articles", 0) for res in task_results if res)
    successful_fetches = sum(
        res.get("successful_fetches", 0) for res in task_results if res
    )
    failed_fetches = sum(res.get("failed_fetches", 0) for res in task_results if res)

    logger.info(
        "Article fetch completed",
        extra={
            "metrics": {
                "total_articles": total_articles,
                "successful_fetches": successful_fetches,
                "failed_fetches": failed_fetches,
                "fetch_time_seconds": round(total_time, 2),
            }
        },
    )
    return {
        "total_articles": total_articles,
        "successful_fetches": successful_fetches,
        "failed_fetches": failed_fetches,
        "fetch_time_seconds": round(total_time, 2),
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
    logger.info(f"Starting chunk processing at {time.time()}")
    start_time = time.time()
    successful_fetches = 0
    failed_fetches = 0
    total_articles = 0

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        connection_pool = ConnectionPool()
        connection_pool.reset_pools()
        connection_pool.pools = defaultdict(
            lambda: asyncio.Queue(maxsize=connection_pool.pool_size)
        )

        with Session(engine) as session:
            redis_client = RedisClient()
            news_client = NewsClient(session, redis_client)

            fetch_results = loop.run_until_complete(
                news_client.fetch_multiple_feeds(feeds_chunk)
            )
            loop.run_until_complete(redis_client.close())

            for result in fetch_results:
                if isinstance(result, Exception):
                    logger.error(f"Feed fetch error: {result}")
                    failed_fetches += 1
                else:
                    article_count, _ = result
                    total_articles += article_count
                    successful_fetches += 1
                    logger.debug(f"Feed processed with {article_count} article")

            chunk_time = time.time() - start_time
            logger.info(
                f"Chunk processing complete - {len(feeds_chunk)} feeds",
                extra={
                    "metrics": {
                        "chunk_size": len(feeds_chunk),
                        "total_articles": total_articles,
                        "successful_fetches": successful_fetches,
                        "failed_fetches": failed_fetches,
                        "fetch_time_seconds": round(chunk_time, 2),
                    }
                },
            )

            return {
                "total_articles": total_articles,
                "successful_fetches": successful_fetches,
                "failed_fetches": failed_fetches,
                "fetch_time_seconds": round(chunk_time, 2),
                "chunk_size": len(feeds_chunk),
            }

    except Exception as e:
        logger.error(f"Feed chunk processing failed: {e}")
        raise

    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception as e:
            logger.warning(f"Error while cancelling pending tasks: {e}")

        loop.close()
