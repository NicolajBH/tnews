from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from src.models.db_models import Articles
from src.utils.text_utils import create_content_signature


class FeedParser(ABC):
    def __init__(self, source_id: int):
        self.source_id = source_id

    @abstractmethod
    async def parse_content(self, content: str) -> List[Articles]:
        pass

    def create_article_signature(self, title: str, pub_date: datetime) -> str:
        return create_content_signature(title, pub_date, self.source_id)

    def prepare_article(
        self,
        title: str,
        pub_date: datetime,
        url: str,
        pub_date_raw: Optional[str] = None,
    ) -> dict:
        article_data = {
            "title": title,
            "pub_date": pub_date,
            "pub_date_raw": pub_date_raw,
            "source_id": self.source_id,
            "original_url": url,
            "signature": self.create_article_signature(title, pub_date),
        }
        return article_data
