from src.core.logging import LogContext, PerformanceLogger
from .base import FeedParser
from typing import List, Dict, Optional, Any
from src.models.db_models import Articles
import json
from datetime import datetime, timezone
from src.constants import JSON_FIELD_MAPPINGS

logger = LogContext(__name__)


class JSONFeedParser(FeedParser):
    async def parse_content(self, content: str) -> List[Articles]:
        with PerformanceLogger(logger, f"json_parse_source_{self.source_name}"):
            json_content = json.loads(content)
            return await self._parse_json_response(json_content)

    async def _parse_json_response(
        self, content: List[Dict[str, Any]]
    ) -> List[Articles]:
        articles_to_return = []
        field_mappings = dict(JSON_FIELD_MAPPINGS[self.source_name])

        # Map "author" to "author_name" for consistency
        if "author" in field_mappings and "author_name" not in field_mappings:
            field_mappings["author_name"] = field_mappings.pop("author")

        # Extend field mappings with optional fields if not already there
        if "description" not in field_mappings:
            field_mappings["description"] = self._guess_field(
                content, ["description", "summary", "content", "abstract", "excerpt"]
            )
        if "author_name" not in field_mappings:
            field_mappings["author_name"] = self._guess_field(
                content, ["author", "byline", "creator", "writers", "contributor"]
            )

        for item in content:
            article = await self._create_article_from_json(item, field_mappings)
            if article:
                articles_to_return.append(article)

        logger.info(
            "JSON parsing complete",
            extra={
                "source_name": self.source_name,
                "total_items": len(content),
                "successful_items": len(articles_to_return),
            },
        )
        return articles_to_return

    def _guess_field(
        self, content: List[Dict[str, Any]], possible_names: List[str]
    ) -> Optional[str]:
        """Generic field guessing function"""
        if not content:
            return None

        # Check first item for possible field names
        first_item = content[0]
        for field in possible_names:
            if field in first_item:
                return field

        return None

    async def _create_article_from_json(
        self, item: Dict[str, Any], field_mappings: Dict[str, str]
    ) -> Optional[Articles]:
        try:
            # Extract required fields
            title = item[field_mappings["title"]]
            pub_date_raw = item[field_mappings["published_date"]]
            url = item[field_mappings["url"]]

            # Check for required fields
            missing = []
            if not title:
                missing.append("title")
            if not pub_date_raw:
                missing.append("published_date")

            if missing:
                logger.warning(
                    "Skipping article",
                    extra={
                        "source_name": self.source_name,
                        "missing": ", ".join(missing),
                        "available_fields": list(item.keys()),
                    },
                )
                return None

            # Parse date
            pub_date = self._parse_date(pub_date_raw)

            # Extract optional fields
            description = None
            if (
                "description" in field_mappings
                and field_mappings["description"] in item
            ):
                description = item[field_mappings["description"]]

            author_info = {"author_name": None}
            if (
                "author_name" in field_mappings
                and field_mappings["author_name"] in item
            ):
                author_text = item[field_mappings["author_name"]]
                if author_text:
                    author_info = self.parse_author(author_text)

            # Create article data
            article_data = self.prepare_article(
                title=title,
                pub_date=pub_date,
                url=url,
                pub_date_raw=pub_date_raw,
                description=description,
                author_name=author_info["author_name"],
            )

            return Articles(**article_data)
        except (KeyError, ValueError) as e:
            logger.error(
                "Error parsing JSON",
                extra={
                    "error": str(e),
                    "source_name": self.source_name,
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
