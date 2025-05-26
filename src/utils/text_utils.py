import re
import nltk
import hashlib
import unicodedata

from typing import Optional
from datetime import datetime
from nltk.corpus import stopwords
from difflib import SequenceMatcher

from core.logging import LogContext

logger = LogContext(__name__)


class StopwordManager:
    """Manages stopwords for multiple languages with caching"""

    _instance = None
    _stopwords = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StopwordManager, cls).__new__(cls)
            cls._instance._load_stopwords()
        return cls._instance

    def _load_stopwords(self):
        try:
            stopwords.words("english")
        except (LookupError, ImportError):
            nltk.download("stopwords", quiet=True)

        languages = ["danish", "english"]
        self._stopwords = set()
        for lang in languages:
            try:
                self._stopwords.update(stopwords.words(lang))
            except Exception as e:
                logger.warning(
                    "Could not download words",
                    extra={
                        "error": str(e),
                        "language": lang,
                        "error_type": e.__class__.__name__,
                    },
                )

    def is_stopword(self, word):
        return word in self._stopwords

    def get_all_stopwords(self):
        return self._stopwords


stopword_manager = StopwordManager()


def normalize_headlines(title: str) -> str:
    if not title:
        return ""

    text = title.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join([c for c in text if not unicodedata.combining(c)])
    text = re.sub(r"[^\w\s]", "", text)
    text = text.replace("-", "")

    words = text.split()
    words = [
        word
        for word in words
        if not stopword_manager.is_stopword(word) and len(word) > 2
    ]
    words.sort()

    text = " ".join(words)
    text = re.sub(r"\s", " ", text).strip()

    return text


def create_content_signature(
    title: str, pub_date: datetime, source_name: str, description: Optional[str] = None
) -> str:
    """Create a more robust unique signature for an article"""
    title_norm = re.sub(r"[^\w\s]", "", title.lower().strip())
    title_norm = re.sub(r"\s+", " ", title_norm)

    title_core = remove_common_affixes(title_norm)

    date_str = pub_date.strftime("%Y-%m-%d")

    desc_part = ""
    if description and description.strip():
        desc_norm = re.sub(r"[^\w\s]", "", description.lower().strip())[:100]
        desc_part = re.sub(r"\s+", " ", desc_norm)

    sig_input = f"{title_core}|{date_str}|{source_name}|{desc_part}"
    return hashlib.sha256(sig_input.encode()).hexdigest()


def remove_common_affixes(title):
    """Remove common prefixes/suffixes that might vary between sources"""
    # Remove source names that might be appended
    patterns = [
        r"\s*[-|]\s*[\w\s]+$",  # "Title - Source Name"
        r"^\w+\s*:\s*",  # "Breaking: Title"
        r"\s*\[\w+\]$",  # "Title [video]"
    ]

    result = title
    for pattern in patterns:
        result = re.sub(pattern, "", result)

    return result.strip()


def clean_html_for_textual(html_content):
    """
    Clean HTML content from RSS feeds for proper display in Textual UI.
    Handles CDATA sections, HTML tags, and special characters.

    Args:
        html_content (str): HTML content from an RSS feed

    Returns:
        str: Clean text formatted for Textual display
    """
    if not html_content:
        return ""

    # Remove description tags and CDATA sections
    cleaned = re.sub(r"<description>\s*<!\[CDATA\[\s*", "", html_content)
    cleaned = re.sub(r"\]\]>\s*</description>", "", cleaned)
    cleaned = re.sub(r"<description>", "", cleaned)
    cleaned = re.sub(r"</description>", "", cleaned)

    # Replace problematic ellipsis representation
    cleaned = cleaned.replace("[…]", "...")
    cleaned = cleaned.replace("[&#8230;]", "...")

    # Convert HTML entities
    cleaned = cleaned.replace("&amp;", "&")
    cleaned = cleaned.replace("&lt;", "<")
    cleaned = cleaned.replace("&gt;", ">")

    # Replace problematic Unicode characters that cause Textual markup issues
    cleaned = cleaned.replace("—", "-")  # em dash
    cleaned = cleaned.replace("–", "-")  # en dash
    cleaned = cleaned.replace("…", "...")  # ellipsis
    cleaned = cleaned.replace('"', '"')  # smart quotes
    cleaned = cleaned.replace('"', '"')  # smart quotes
    cleaned = cleaned.replace(
        """, "'")  # smart apostrophe
    cleaned = cleaned.replace(""",
        "'",
    )  # smart apostrophe

    # Handle paragraphs
    cleaned = re.sub(r"<p>", "\n\n", cleaned)
    cleaned = re.sub(r"</p>", "", cleaned)

    # Handle lists
    cleaned = re.sub(r"<ul>", "\n", cleaned)
    cleaned = re.sub(r"</ul>", "\n", cleaned)
    cleaned = re.sub(r"<li><p>", "\n• ", cleaned)
    cleaned = re.sub(r"</p></li>", "", cleaned)
    cleaned = re.sub(r"<li>", "\n• ", cleaned)
    cleaned = re.sub(r"</li>", "", cleaned)

    # Handle links
    cleaned = re.sub(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', r"\2 (\1)", cleaned)

    # Remove any remaining HTML tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned)

    # Fix whitespace and multiple line breaks
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    return cleaned


def calculate_title_similarity(title1: str, title2: str) -> float:
    """
    Calculate similarity between two titles

    Args:
        title1: First title
        title2: Second title

    Returns:
        Similarity score (0-1 float)
    """
    if not title1 or not title2:
        return 0.0

    # Normalize titles
    t1 = re.sub(r"[^\w\s]", "", title1.lower().strip())
    t2 = re.sub(r"[^\w\s]", "", title2.lower().strip())

    return SequenceMatcher(None, t1, t2).ratio()
