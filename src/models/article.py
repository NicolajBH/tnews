from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime
from src.constants import RSS_FEEDS


class Article(BaseModel):
    title: str
    pubDate: str
    source: str
    formatted_time: str


class ArticleContent(BaseModel):
    title: str
    pubDate: str
    source: str

    @property
    def formatted_date(self) -> str:
        dt = datetime.strptime(self.pubDate, "%a, %d %b %Y %H:%M:%S %z")
        return datetime.strftime(dt, "%H:%M")


class ArticleQueryParameters(BaseModel):
    start_date: date | None = Field(
        default=None,
        description="Start date for filtering articles(inclusive)",
        examples=["2024-02-10"],
    )
    end_date: date | None = Field(
        default=None,
        description="End date for filtering articles (inclusive)",
        examples=["2025-02,13"],
    )

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, end_date: date | None, info) -> date | None:
        start_date = info.data.get("start_date")
        if start_date and end_date and end_date < start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        return end_date


class CategoryParams(BaseModel):
    source: str = Field(
        description="News source identifier", examples=["borsen"], min_length=1
    )
    category: str = Field(
        description="Category identifier for the specified source",
        examples=["tech", "finans"],
        min_length=1,
    )

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in RSS_FEEDS:
            raise ValueError(
                f"Invalid source. Must be one of: {', '.join(RSS_FEEDS.keys())}"
            )
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str, info) -> str:
        source = info.data.get("source")
        if source not in RSS_FEEDS[source]:
            raise ValueError(f"Invalid category for source {source}")
        return v
