from celery import shared_task
from sqlmodel import Session
import asyncio
from src.db.database import engine
from src.clients.news import NewsClient
from src.clients.redis import RedisClient
from src.db.operations import fetch_feed_urls


@shared_task
def fetch_all_feeds():
    with Session(engine) as session:
        redis_client = RedisClient()
        news_client = NewsClient(session, redis_client)
        results = fetch_feed_urls(session)

        feeds = [
            (cat.source_id, cat.id, source.base_url + cat.feed_url)
            for cat, source in results
            if cat.source_id and cat.id
        ]

        return asyncio.run(news_client.fetch_multiple_feeds(feeds))
