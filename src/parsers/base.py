from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Dict
import re
import html
from src.models.db_models import Articles
from src.utils.text_utils import create_content_signature

# Pre-compile regex patterns
CDATA_PATTERN = re.compile(r"<!\[CDATA\[(.*?)\]\]>")
EMAIL_PATTERN = re.compile(r"([\w\.-]+@[\w\.-]+\.\w+)\s*\(([^)]+)\)")


class FeedParser(ABC):
    def __init__(self, source_name: str):
        self.source_name = source_name

    @abstractmethod
    async def parse_content(self, content: str) -> List[Articles]:
        pass

    def create_article_signature(
        self, title: str, pub_date: datetime, description: Optional[str]
    ) -> str:
        return create_content_signature(title, pub_date, self.source_name, description)

    def get_base_url(self) -> str:
        """Get base URL directly from RSS_FEEDS"""
        from src.constants import RSS_FEEDS

        if self.source_name not in RSS_FEEDS:
            return "example.com"

        return RSS_FEEDS[self.source_name]["base_url"]

    def normalize_url(self, url: str) -> str:
        """
        Ensure URL includes domain name and protocol
        """
        # Return if already has protocol
        if url.startswith("http://") or url.startswith("https://"):
            return url

        # Get base URL directly
        base_url = self.get_base_url()

        # Handle various URL formats
        if url.startswith("//"):
            return f"https:{url}"
        elif url.startswith("/"):
            return f"https://{base_url}{url}"
        else:
            return f"https://{base_url}/{url}"

    def _sanitize_text(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None

        cleaned_text = html.unescape(text)
        cleaned_text = cleaned_text.replace("\u00ad", "")  # soft hyphen
        cleaned_text = cleaned_text.replace("\u00a0", " ")  # non breaking spaces
        cleaned_text = cleaned_text.replace("\u200b", "")  # zero width spaces
        cleaned_text = " ".join(cleaned_text.split())

        return cleaned_text if cleaned_text else None

    def prepare_article(
        self,
        title: str,
        pub_date: datetime,
        url: str,
        pub_date_raw: Optional[str] = None,
        description: Optional[str] = None,
        author_name: Optional[str] = None,
    ) -> dict:
        """
        Prepare article data dictionary with all fields.
        """

        sanitized_title = self._sanitize_text(title)
        sanitized_title = sanitized_title if sanitized_title is not None else ""

        sanitized_description = self._sanitize_text(description)
        sanitized_author = self._sanitize_text(author_name)

        article_data = {
            "title": sanitized_title,
            "pub_date": pub_date,
            "pub_date_raw": pub_date_raw,
            "source_name": self.source_name,
            "original_url": self.normalize_url(url),
            "signature": self.create_article_signature(
                sanitized_title, pub_date, description
            ),
            "description": sanitized_description,
            "author_name": sanitized_author,
        }
        return article_data

    def parse_author(self, author_text: Optional[str]) -> Dict[str, Optional[str]]:
        """Parse author field into name component"""
        if not author_text:
            return {"author_name": None}

        # Clean CDATA if present
        if "![CDATA[" in author_text:
            author_text = CDATA_PATTERN.sub(r"\1", author_text)

        # Check for email format: email@domain.com (Name)
        email_match = EMAIL_PATTERN.search(author_text)
        if email_match:
            return {"author_name": email_match.group(2)}

        # Assume it's just a name or comma-separated names
        return {"author_name": author_text}
