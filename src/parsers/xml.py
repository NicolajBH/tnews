from src.core.logging import LogContext, PerformanceLogger
from .base import FeedParser
import xml.etree.ElementTree as ET
from typing import List, no_type_check, Optional, Dict
from src.models.db_models import Articles
import html
from email.utils import parsedate_to_datetime
from datetime import timezone, datetime
import re

logger = LogContext(__name__)

CDATA_PATTERN = re.compile(r"<!\[CDATA\[(.*?)\]\]>")
NAMESPACES = {
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",  # Required for DW feeds
    "dwsyn": "http://rss.dw.com/syndication/dwsyn/",  # DW-specific namespace
}


class XMLFeedParser(FeedParser):
    async def parse_content(self, content: str) -> List[Articles]:
        with PerformanceLogger(logger, f"xml_parse_source_name_{self.source_name}"):
            # Register common NAMESPACES to make parsing easier

            # Register NAMESPACES with ElementTree
            for prefix, uri in NAMESPACES.items():
                ET.register_namespace(prefix, uri)

            try:
                tree = ET.fromstring(content)
                return await self._parse_xml_response(tree)
            except ET.ParseError as e:
                logger.error(
                    "XML parsing error",
                    extra={
                        "error": str(e),
                        "source_name": self.source_name,
                    },
                )
                return []

    async def _parse_xml_response(self, tree: ET.Element) -> List[Articles]:
        articles_to_return = []

        # Look for items in various RSS/Atom formats
        for item in tree.findall(".//item"):
            article = await self._create_article_from_xml_item(item)
            if article:
                articles_to_return.append(article)

        # If no items found via //item, try looking for entries (Atom format)
        if not articles_to_return:
            for entry in tree.findall(".//entry"):
                article = await self._create_article_from_xml_item(entry)
                if article:
                    articles_to_return.append(article)

        logger.info(
            "XML parsing complete",
            extra={
                "source_name": self.source_name,
                "total_items": len(tree.findall(".//item"))
                + len(tree.findall(".//entry")),
                "successful_items": len(articles_to_return),
            },
        )
        return articles_to_return

    def extract_xml_text_content(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None

        # Use the pre-compiled pattern
        if "![CDATA[" in text:
            text = CDATA_PATTERN.sub(r"\1", text)
        return text

    def _find_author(self, item: ET.Element) -> Dict[str, Optional[str]]:
        """Extract author information from various possible elements"""
        # Standard RSS author
        author_elem = item.find("author")
        if author_elem is not None and author_elem.text is not None:
            return self.parse_author(author_elem.text)

        # Dublin Core creator
        dc_creator = item.find(
            ".//dc:creator", {"dc": "http://purl.org/dc/elements/1.1/"}
        )
        if dc_creator is not None and dc_creator.text is not None:
            return self.parse_author(dc_creator.text)

        # Atom author name
        atom_author = item.find(".//author/name")
        if atom_author is not None and atom_author.text is not None:
            return {"author_name": atom_author.text}

        return {"author_name": None}

    def _find_description(self, item: ET.Element) -> Optional[str]:
        """Extract description from various possible elements"""
        # Standard RSS description
        desc_elem = item.find("description")
        if desc_elem is not None and desc_elem.text is not None:
            return self.extract_xml_text_content(desc_elem.text)

        # Atom summary
        summary_elem = item.find("summary")
        if summary_elem is not None and summary_elem.text is not None:
            return self.extract_xml_text_content(summary_elem.text)

        # Content:encoded (often used for full content)
        content_elem = item.find(
            ".//content:encoded",
            {"content": "http://purl.org/rss/1.0/modules/content/"},
        )
        if content_elem is not None and content_elem.text is not None:
            return self.extract_xml_text_content(content_elem.text)

        return None

    @no_type_check
    async def _create_article_from_xml_item(
        self, item: ET.Element
    ) -> Optional[Articles]:
        try:
            # Extract base fields
            title_elem = item.find("title")
            pub_date_raw = self._find_date_element(item)
            link_elem = item.find("link")

            # Skip if required fields are missing
            if title_elem is None or title_elem.text is None or pub_date_raw is None:
                missing = []
                if title_elem is None or title_elem.text is None:
                    missing.append("title")
                if pub_date_raw is None:
                    missing.append("pubDate")
                logger.warning(
                    "Skipping article",
                    extra={
                        "source_name": self.source_name,
                        "missing": ", ".join(missing),
                        "available_fields": [child.tag for child in item],
                    },
                )
                return None

            # Clean and parse the base fields
            title = self.extract_xml_text_content(title_elem.text)
            pub_date = self._parse_date(pub_date_raw)
            url = (
                link_elem.text
                if link_elem is not None and link_elem.text is not None
                else ""
            )

            # Extract new fields
            description = self._find_description(item)
            author_info = self._find_author(item)

            # Prepare the article data with all fields
            article_data = self.prepare_article(
                title=title,
                pub_date=pub_date,
                url=url,
                pub_date_raw=pub_date_raw,
                description=description,
                author_name=author_info["author_name"],
            )

            return Articles(**article_data)
        except (TypeError, AttributeError) as e:
            logger.error(
                "Error parsing XML item",
                extra={
                    "error": str(e),
                    "source_name": self.source_name,
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
                    "source_name": self.source_name,
                    "error_type": e.__class__.__name__,
                },
            )
            return None

    def _parse_date(self, date_str: str) -> datetime:
        # Define date formats as a tuple for cleaner code
        date_formats = (
            # RFC 2822 (standard email date format)
            lambda s: parsedate_to_datetime(s).astimezone(timezone.utc),
            # ISO 8601 format with Z for UTC
            lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
            # Common date-time formats
            lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            ),
            lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc
            ),
        )

        # Try each format, return current time as fallback
        for parse_func in date_formats:
            try:
                return parse_func(date_str)
            except (ValueError, TypeError):
                continue

        return datetime.now(timezone.utc)

    def _find_date_element(self, item: ET.Element) -> Optional[str]:
        # Standard RSS
        date_elem = item.find("pubDate")
        if date_elem is not None and date_elem.text is not None:
            return date_elem.text

        # Dublin Core date (used by Deutsche Welle)
        dc_date = item.find("dc:date")
        if dc_date is not None and dc_date.text is not None:
            return dc_date.text

        # Try with full namespace path
        dc_date_ns = item.find(".//{http://purl.org/dc/elements/1.1/}date")
        if dc_date_ns is not None and dc_date_ns.text is not None:
            return dc_date_ns.text

        # Look for any tag ending with 'date' (handles NAMESPACES)
        for elem in item.iter():
            if elem.tag.endswith("}date") or elem.tag == "date":
                return elem.text

        # Atom published or updated
        published = item.find("published")
        if published is not None and published.text is not None:
            return published.text

        updated = item.find("updated")
        if updated is not None and updated.text is not None:
            return updated.text

        return None
