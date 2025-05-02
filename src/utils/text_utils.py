import re
import hashlib
import unicodedata
from typing import Optional
from datetime import datetime

import nltk
from nltk.corpus import stopwords

from src.core.logging import LogContext

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
    title: str, pub_date: Optional[datetime] = None, source_id: Optional[int] = None
) -> str:
    normalized_title = normalize_headlines(title)
    signature_parts = [normalized_title]

    if pub_date:
        date_str = pub_date.strftime("%Y-%m-%d")
        signature_parts.append(date_str)

    if source_id:
        signature_parts.append(str(source_id))

    signature = "|".join(signature_parts)
    return hashlib.md5(signature.encode()).hexdigest()
