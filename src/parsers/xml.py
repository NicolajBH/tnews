from .base import FeedParser
import xml.etree.ElementTree as ET
from typing import List, no_type_check, Optional
from src.models.db_models import Articles
import html
import logging
from email.utils import parsedate_to_datetime
import hashlib
from datetime import timezone

logger = logging.getLogger(__name__)


class XMLFeedParser(FeedParser):
    async def parse_content(self, content: str) -> List[Articles]:
        tree = ET.fromstring(content)
        return await self._parse_xml_response(tree)

    async def _parse_xml_response(self, tree: ET.Element) -> List[Articles]:
        articles_to_return = []
        for item in tree.findall(".//item"):
            article = await self._create_article_from_xml_item(item)
            if article:
                articles_to_return.append(article)

        return articles_to_return

    @no_type_check
    async def _create_article_from_xml_item(
        self, item: ET.Element
    ) -> Optional[Articles]:
        try:
            title, pub_date, url = (
                item.find(tag).text for tag in ("title", "pubDate", "link")
            )
            return Articles(
                title=html.unescape(title),
                content_hash=hashlib.md5(title.encode()).hexdigest(),
                pub_date=parsedate_to_datetime(pub_date).astimezone(timezone.utc),
                pub_date_raw=pub_date,
                original_url=url,
                source_id=self.source_id,
            )
        except TypeError as e:
            logger.error(f"Incorrect type: {str(e)}")
            return None
