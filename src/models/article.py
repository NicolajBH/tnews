from pydantic import BaseModel, Field
from datetime import datetime


class Article(BaseModel):
    id: int
    title: str
    pubDate: str
    feed_symbol: str
    display_name: str
    description: str
    author: str
    url: str


class ArticleQueryParameters(BaseModel):
    start_date: datetime | None = None
    end_date: datetime | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
