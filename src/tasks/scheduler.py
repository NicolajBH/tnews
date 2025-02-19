import asyncio
import logging
import time
from typing import Tuple
from sqlmodel import Session
from src.clients.news import NewsClient
from src.db.operations import fetch_feed_urls
from src.db.database import engine


logger = logging.getLogger(__name__)


async def periodic_fetch() -> None:
    while True:
        start_time = time.time()
        successful_fetches = 0
        failed_fetches = 0
        total_articles = 0

        try:
            with Session(engine) as session:
                news_client = NewsClient(session)
                results = fetch_feed_urls(session)
                article_tasks = []

                for category, source in results:
                    if category.source_id is None or category.id is None:
                        logger.error(f"Feed {category.feed_url} has None IDs")
                        failed_fetches += 1
                        continue
                    try:
                        url = source.base_url + category.feed_url
                        article_tasks.append(
                            news_client.fetch_headlines(
                                category.source_id, category.id, url
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to fetch feed {category.feed_url}: {e}")
                        failed_fetches += 1
                        continue
                if article_tasks:
                    results = await asyncio.gather(
                        *article_tasks, return_exceptions=True
                    )
                    for result in results:
                        if isinstance(result, Exception):
                            failed_fetches += 1
                        elif isinstance(result, Tuple):
                            successful_count, _ = result
                            total_articles += successful_count
                            successful_fetches += 1

                total_time = time.time() - start_time
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
            await asyncio.sleep(5 * 60)
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(
                f"Periodic fetch failed: {e}",
                extra={
                    "metrics": {
                        "total_articles": total_articles,
                        "successful_fetches": successful_fetches,
                        "failed_fetches": failed_fetches,
                        "fetch_time_seconds": round(total_time, 2),
                    }
                },
            )
            await asyncio.sleep(60)
