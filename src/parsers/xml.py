from src.core.logging import LogContext, PerformanceLogger
from .base import FeedParser
import xml.etree.ElementTree as ET
from typing import List, no_type_check, Optional
from src.models.db_models import Articles
import html
from email.utils import parsedate_to_datetime
from datetime import timezone, datetime

logger = LogContext(__name__)


class XMLFeedParser(FeedParser):
    async def parse_content(self, content: str) -> List[Articles]:
        with PerformanceLogger(logger, f"xml_parse_source_id_{self.source_id}"):
            tree = ET.fromstring(content)
            return await self._parse_xml_response(tree)

    async def _parse_xml_response(self, tree: ET.Element) -> List[Articles]:
        articles_to_return = []
        for item in tree.findall(".//item"):
            article = await self._create_article_from_xml_item(item)
            if article:
                articles_to_return.append(article)

        logger.info(
            "XML parsing complete",
            extra={
                "source_id": self.source_id,
                "total_items": len(tree.findall(".//item")),
                "successful_items": len(articles_to_return),
            },
        )
        return articles_to_return

    @no_type_check
    async def _create_article_from_xml_item(
        self, item: ET.Element
    ) -> Optional[Articles]:
        try:
            title_elem = item.find("title")
            pub_date_raw = self._find_date_element(item)
            link_elem = item.find("link")

            if title_elem is None or title_elem.text is None or pub_date_raw is None:
                missing = []
                if title_elem is None or title_elem.text is None:
                    missing.append("title")
                if pub_date_raw is None:
                    missing.append("pubDate")
                logger.warning(
                    "Skipping article",
                    extra={
                        "source_id": self.source_id,
                        "missing": ", ".join(missing),
                        "available_fields": [child.tag for child in item],
                    },
                )
                return None

            title = html.unescape(title_elem.text)
            pub_date = self._parse_date(pub_date_raw)
            url = (
                link_elem.text
                if link_elem is not None and link_elem.text is not None
                else ""
            )
            article_data = self.prepare_article(title, pub_date, url, pub_date_raw)

            return Articles(**article_data)
        except (TypeError, AttributeError) as e:
            logger.error(
                "Error parsing XML item",
                extra={
                    "error": str(e),
                    "source_id": self.source_id,
                    "error_type": e.__class__.__name__,
                    "title": getattr(title_elem, "text", None) if title_elem else None,
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error parsing XML item",
                extra={
                    "error": str(e),
                    "source_id": self.source_id,
                    "error_type": e.__class__.__name__,
                },
            )

    def _parse_date(self, date_str: str) -> datetime:
        date_formats = [
            lambda s: parsedate_to_datetime(s).astimezone(timezone.utc),
            lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            ),
            lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            ),
        ]
        for format_parser in date_formats:
            try:
                return format_parser(date_str)
            except (ValueError, TypeError):
                continue

        return datetime.now(timezone.utc)

    def _find_date_element(self, item: ET.Element) -> Optional[str]:
        # Standard RSS
        date_elem = item.find("pubDate")
        if date_elem is not None and date_elem.text is not None:
            return date_elem.text

        # Look for any tag ending with 'date' (handles namespaces)
        for elem in item.iter():
            if elem.tag.endswith("}date") or elem.tag == "dc:date":
                return elem.text

        return None
