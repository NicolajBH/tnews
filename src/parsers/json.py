from .base import FeedParser
from typing import List, Dict
from src.models.db_models import Articles
import logging
import json
from email.utils import parsedate_to_datetime
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)


class JSONFeedParser(FeedParser):
    async def parse_content(self, content: str) -> List[Articles]:
        json_content = json.loads(content)
        return await self._parse_json_response(json_content)

    async def _parse_json_response(
        self, content: List[Dict[str, str]]
    ) -> List[Articles]:
        articles_to_return = []
        for item in content:
            article = await self._create_article_from_json(item)
            if article:
                articles_to_return.append(article)
        return articles_to_return

    async def _create_article_from_json(self, item: Dict[str, str]):
        try:
            missing = []
            if "headline" not in item or not item["headline"]:
                missing.append("headline")
            if "publishedAt" not in item or not item["publishedAt"]:
                missing.append("publishedAt")

            if missing:
                logger.warning(
                    f"Skipping article: Missing critical fields: {', '.join(missing)}"
                )
                return None

            url = item.get("url", "")
            return Articles(
                title=item["headline"],
                content_hash=hashlib.md5(item["headline"].encode()).hexdigest(),
                pub_date=datetime.fromisoformat(
                    item["publishedAt"].replace("Z", "+00:00")
                ),
                pub_date_raw=item["publishedAt"],
                original_url=url,
                source_id=self.source_id,
            )
        except (KeyError, ValueError) as e:
            logger.error(f"Error parsing JSON item: {str(e)}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing JSON item: {str(e)}", exc_info=True)
            return None
