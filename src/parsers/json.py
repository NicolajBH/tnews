from src.core.logging import LogContext, PerformanceLogger
from .base import FeedParser
from typing import List, Dict, Optional
from src.models.db_models import Articles
import json
from datetime import datetime, timezone
from src.constants import JSON_FIELD_MAPPINGS

logger = LogContext(__name__)


class JSONFeedParser(FeedParser):
    async def parse_content(self, content: str) -> List[Articles]:
        with PerformanceLogger(logger, f"json_parse_source_{self.source_id}"):
            json_content = json.loads(content)
            return await self._parse_json_response(json_content)

    async def _parse_json_response(
        self, content: List[Dict[str, str]]
    ) -> List[Articles]:
        articles_to_return = []
        source_name = self._get_source_name()
        field_mappings = JSON_FIELD_MAPPINGS[source_name]
        for item in content:
            article = await self._create_article_from_json(item, field_mappings)
            if article:
                articles_to_return.append(article)

        logger.info(
            "JSON parsing complete",
            extra={
                "source_id": self.source_id,
                "total_items": len(content),
                "successful_items": len(articles_to_return),
            },
        )
        return articles_to_return

    async def _create_article_from_json(
        self, item: Dict[str, str], field_mappings: Dict[str, str]
    ):
        try:
            title = item[field_mappings["title"]]
            pub_date_raw = item[field_mappings["published_date"]]
            url = item[field_mappings["url"]]

            missing = []
            if not title:
                missing.append("title")
            if not pub_date_raw:
                missing.append("published_date")

            if missing:
                logger.warning(
                    "Skipping article",
                    extra={
                        "source_id": self.source_id,
                        "missing": ", ".join(missing),
                        "available_fields": list(item.keys()),
                    },
                )
                return None

            pub_date = self._parse_date(pub_date_raw)
            article_data = self.prepare_article(title, pub_date, url, pub_date_raw)
            return Articles(**article_data)
        except (KeyError, ValueError) as e:
            logger.error(
                "Error parsing JSON",
                extra={
                    "error": str(e),
                    "source_id": self.source_id,
                    "item": item,
                    "error_type": e.__class__.__name__,
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error parsing JSON",
                extra={
                    "error": str(e),
                    "item": item,
                    "error_type": e.__class__.__name__,
                },
            )
            return None

    def _get_source_name(self):
        source_id_to_name = {2: "bloomberg", 8: "tradingeconomics"}
        return source_id_to_name[self.source_id]

    def _parse_date(self, date_str: str) -> datetime:
        date_formats = [
            # Standard ISO format
            lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
            # Format with milliseconds: 2025-05-02T06:27:28.003
            lambda s: datetime.strptime(s.split(".")[0], "%Y-%m-%dT%H:%M:%S"),
            # Standard datetime format
            lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
        ]

        for format_parser in date_formats:
            try:
                return format_parser(date_str)
            except (ValueError, TypeError):
                continue

        return datetime.now(timezone.utc)
