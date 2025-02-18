import asyncio
import logging
from sqlmodel import Session
from src.clients.news import NewsClient
from src.db.operations import fetch_feed_urls
from src.db.database import engine


logger = logging.getLogger(__name__)


async def periodic_fetch() -> None:
    while True:
        try:
            with Session(engine) as session:
                news_client = NewsClient(session)
                results = fetch_feed_urls(session)
                article_tasks = []
                for category, source in results:
                    if category.source_id is None or category.id is None:
                        logger.error(f"Feed {category.feed_url} has None IDs")
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
                        continue
                if article_tasks:
                    await asyncio.gather(*article_tasks)
            await asyncio.sleep(5 * 60)
        except Exception as e:
            logger.error(f"Periodic fetch failed: {e}")
            await asyncio.sleep(60)
