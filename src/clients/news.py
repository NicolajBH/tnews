import logging
import gzip
import time
from typing import List, Tuple, Any, Optional
from sqlmodel import Session, select
from src.models.db_models import Articles, Categories
from src.clients.http import HTTPClient
from src.clients.connection import ConnectionPool
from src.core.exceptions import RSSFeedError
from src.parsers.json import JSONFeedParser
from src.parsers.xml import XMLFeedParser
from src.parsers.base import FeedParser

logger = logging.getLogger(__name__)


class NewsClient:
    def __init__(self, session: Session):
        self.connection_pool = ConnectionPool(pool_size=3)
        self.http_client = HTTPClient(self.connection_pool)
        self.session = session

    async def fetch_headlines(
        self, source_id: int, category_id: int, url: str
    ) -> Tuple[int, int]:
        """Fetch and process feeds"""
        start_time = time.time()
        try:
            raw_feed = await self._fetch_feed(url)
            articles = await self._process_feed(raw_feed, source_id)
            stats = await self._save_articles(articles, category_id)
            return stats
        except Exception as e:
            await self._log_error(e, start_time, source_id, category_id)
            raise RSSFeedError(f"Failed to fetch feed: {str(e)}")

    async def _fetch_feed(self, url: str) -> Tuple[Any, bytes]:
        return await self.http_client.request("GET", url)

    def _get_parser(self, content_type: str, source_id: int) -> FeedParser:
        if "xml" in content_type.lower():
            return XMLFeedParser(source_id)
        elif "json" in content_type.lower():
            return JSONFeedParser(source_id)
        else:
            raise RSSFeedError(f"Unsupported content type: {content_type}")

    async def _process_feed(
        self, raw_feed: Tuple[Any, bytes], source_id: int
    ) -> List[Articles]:
        headers, body = raw_feed
        content_type = headers.headers.get("Content-Type", "")
        decompressed_body = gzip.decompress(body).decode("utf-8", errors="replace")
        parser = self._get_parser(content_type, source_id)
        return await parser.parse_content(decompressed_body)

    async def _save_articles(
        self, articles: List[Articles], category_id: int
    ) -> Tuple[int, int]:
        successful_articles = 0
        new_category_associations = 0

        category = self._get_category(category_id)
        if not category:
            return 0, 0

        for article in articles:
            if await self._save_article(article, category):
                successful_articles += 1

        self.session.commit()
        return successful_articles, new_category_associations

    async def _save_article(self, article: Articles, category: Categories) -> bool:
        """Save article if new"""
        if self._article_exists(article.content_hash):
            return False

        article.categories.append(category)
        self.session.add(article)
        return True

    def _article_exists(self, content_hash: str) -> bool:
        return bool(
            self.session.exec(
                select(Articles).where(Articles.content_hash == content_hash)
            ).first()
        )

    def _get_category(self, category_id: int) -> Optional[Categories]:
        return self.session.get(Categories, category_id)

    async def _log_error(
        self, error: Exception, start_time: float, source_id: int, category_id: int
    ) -> None:
        fetch_time = time.time() - start_time
        logger.error(
            f"Error fetching feed: {str(error)}",
            extra={
                "metrics": {
                    "fetch_time_seconds": fetch_time,
                    "source_id": source_id,
                    "category_id": category_id,
                }
            },
        )
