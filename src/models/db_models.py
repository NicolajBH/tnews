from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime
from typing import List
from urllib.parse import urlparse, unquote


class ArticleCategories(SQLModel, table=True):
    article_id: int = Field(foreign_key="articles.id", primary_key=True)
    category_id: int = Field(foreign_key="categories.id", primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now)


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
    source_id: int = Field(foreign_key="sources.id")
    feed_url: str = Field(unique=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    source: Sources = Relationship(back_populates="categories")
    articles: List["Articles"] = Relationship(
        back_populates="categories", link_model=ArticleCategories
    )
    user_preferences: List["FeedPreferences"] = Relationship(back_populates="category")


class Articles(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    content_hash: str = Field(unique=True, index=True)
    pub_date: datetime = Field(index=True)
    pub_date_raw: str = Field(default=None)
    source_id: int = Field(foreign_key="sources.id")
    original_url: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(
        default_factory=datetime.now, sa_column_kwargs={"onupdate": None}
    )

    source: Sources = Relationship(back_populates="articles")
    categories: List[Categories] = Relationship(
        back_populates="articles", link_model=ArticleCategories
    )

    @property
    def pub_date_iso(self) -> str:
        return self.pub_date.isoformat()

    @property
    def slug(self) -> str:
        path = urlparse(self.original_url).path.rstrip("/")
        return unquote(path.rsplit("/", 1)[1]).lower()


class Users(SQLModel, table=True):
    id: int | None = Field(index=True, default=None, primary_key=True)
    username: str = Field(unique=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.now)
    last_login: datetime = Field(default_factory=datetime.now)
    password_hash: str = Field(index=True, nullable=False)
    is_active: bool = Field(default=True)

    # refresh tokens
    refresh_token: str | None = Field(default=None)
    refresh_token_expires: datetime | None = Field(default=None)

    feed_preferences: List["FeedPreferences"] = Relationship(back_populates="user")


class FeedPreferences(SQLModel, table=True):
    id: int | None = Field(index=True, default=None, primary_key=True)
    user_id: int | None = Field(foreign_key="users.id", default=None)
    feed_id: int = Field(foreign_key="categories.id")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.now)
    last_fetched: datetime = Field(default_factory=datetime.now)

    user: Users = Relationship(back_populates="feed_preferences")
    category: Categories = Relationship(back_populates="user_preferences")
