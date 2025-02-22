from abc import ABC, abstractmethod
from typing import List
from src.models.db_models import Articles


class FeedParser(ABC):
    def __init__(self, source_id: int):
        self.source_id = source_id

    @abstractmethod
    async def parse_content(self, content: str) -> List[Articles]:
        pass
