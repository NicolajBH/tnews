from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime
from typing import List


class Sources(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    feed_symbol: str = Field(default=None)
    base_url: str
    active_status: bool = Field(default=True)
    fetch_interval: int  # num seconds
    last_fetch_time: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    categories: List["Categories"] = Relationship(back_populates="source")
    articles: List["Articles"] = Relationship(back_populates="source")


class Categories(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(index=True)
    source_id: int = Field(foreign_key="sources.id")
    feed_url: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    source: Sources = Relationship(back_populates="categories")
    articles: List["Articles"] = Relationship(back_populates="category")

    def __init__(self, **data):
        super().__init__(**data)
        if self.slug is None and self.name:
            self.slug = "-".join(self.name.lower().split())


class Articles(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    content_hash: str = Field(unique=True, index=True)
    pub_date: datetime = Field(index=True)
    pub_date_raw: str = Field(default=None)
    source_id: int = Field(foreign_key="sources.id")
    category_id: int = Field(foreign_key="categories.id")
    original_url: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    source: Sources = Relationship(back_populates="articles")
    category: Categories = Relationship(back_populates="articles")
    content: List["ArticleContent"] | None = Relationship(back_populates="article")

    @property
    def pub_date_iso(self) -> str:
        return self.pub_date.isoformat()


class ArticleContent(SQLModel, table=True):
    article_id: int = Field(foreign_key="articles.id", primary_key=True)
    content: str
    content_type: str
    last_updated: datetime = Field(default_factory=datetime.now)

    article: Articles = Relationship(back_populates="content")
