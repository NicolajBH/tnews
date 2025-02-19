import logging
import gzip
import html
import hashlib
import time
import xml.etree.ElementTree as ET
from typing import Tuple
from sqlmodel import Session, select
from datetime import timezone
from email.utils import parsedate_to_datetime
from src.models.db_models import Articles
from src.clients.http import HTTPClient
from src.clients.connection import ConnectionPool
from src.core.exceptions import RSSFeedError

logger = logging.getLogger(__name__)


class NewsClient:
    def __init__(self, session: Session):
        self.connection_pool = ConnectionPool(pool_size=3)
        self.http_client = HTTPClient(self.connection_pool)
        self.session = session

    async def fetch_headlines(
        self, source_id: int, category_id: int, url: str
    ) -> Tuple[int, int]:
        """Fetches headlines from RSS feeds"""
        start_time = time.time()
        successful_articles = 0

        try:
            headers, body = await self.http_client.request("GET", url)

            xml_string = gzip.decompress(body).decode("utf-8", errors="replace")
            tree = ET.fromstring(xml_string)
            for item in tree.findall(".//item"):
                if (title_elem := item.find("title")) is not None and title_elem.text:
                    content_hash = hashlib.md5(title_elem.text.encode()).hexdigest()
                    existing = self.session.exec(
                        select(Articles).where(Articles.content_hash == content_hash)
                    ).all()
                    if (
                        pub_date_elem := item.find("pubDate")
                    ) is not None and pub_date_elem.text:
                        raw_date = pub_date_elem.text
                        parsed_date = parsedate_to_datetime(raw_date)
                        utc_date = parsed_date.astimezone(timezone.utc)

                        if not existing:
                            article = Articles(
                                title=html.unescape(title_elem.text),
                                pub_date=utc_date,
                                pub_date_raw=raw_date,
                                content_hash=content_hash,
                                source_id=source_id,
                                category_id=category_id,
                                original_url=url,
                            )
                            self.session.add(article)
                            successful_articles += 1

            self.session.commit()
            fetch_time = time.time() - start_time
            return successful_articles, 0

        except Exception as e:
            fetch_time = time.time() - start_time
            logger.error(
                f"Error fetching RSS feed: {str(e)}",
                extra={
                    "metrics": {
                        "fetch_time_seconds": round(fetch_time, 2),
                        "source_id": source_id,
                        "category_id": category_id,
                    }
                },
            )
            raise RSSFeedError(detail="Failed to fetch RSS feed: {str(e)}")
