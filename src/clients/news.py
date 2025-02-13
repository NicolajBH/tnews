import logging
import gzip
import html
import xml.etree.ElementTree as ET
from typing import List
from src.models.article import ArticleContent
from src.clients.http import HTTPClient
from src.clients.connection import ConnectionPool
from src.core.exceptions import RSSFeedError

logger = logging.getLogger(__name__)


class NewsClient:
    def __init__(self):
        self.connection_pool = ConnectionPool(pool_size=3)
        self.http_client = HTTPClient(self.connection_pool)

    async def fetch_headlines(self, rss_feed: str) -> List[ArticleContent]:
        """Fetches headlines from RSS feeds"""
        try:
            headers, body = await self.http_client.request("GET", rss_feed)

            xml_string = gzip.decompress(body).decode("utf-8", errors="replace")
            tree = ET.fromstring(xml_string)

            return [
                ArticleContent(
                    title=html.unescape(title_elem.text),
                    pubDate=pubdate_elem.text,
                    source=rss_feed.split(".")[0],
                )
                for item in tree.findall(".//item")
                if (title_elem := item.find("title")) is not None
                and title_elem.text is not None
                and (pubdate_elem := item.find("pubDate")) is not None
                and pubdate_elem.text is not None
            ]
        except Exception as e:
            logger.error(f"Error fetching RSS feed {rss_feed}: {str(e)}")
            raise RSSFeedError(detail=f"Failed to fetch RSS feed: {str(e)}")
