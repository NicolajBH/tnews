from sqlmodel import Field, SQLModel, Relationship, Column, Text, ForeignKeyConstraint
from sqlalchemy import PrimaryKeyConstraint, Index
from datetime import datetime
from typing import List, Optional


class ArticleFeeds(SQLModel, table=True):
    article_id: int = Field(foreign_key="articles.id", primary_key=True)
    feed_source_name: str = Field(primary_key=True)
    feed_name: str = Field(primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["feed_source_name", "feed_name"], ["feeds.source_name", "feeds.name"]
        ),
    )

    created_at: datetime = Field(default_factory=datetime.now)


class Sources(SQLModel, table=True):
    name: str = Field(primary_key=True)
    display_name: str
    feed_symbol: str
    base_url: str
    active_status: bool = Field(default=True)
    fetch_interval: int  # num seconds
    last_fetch_time: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    feeds: List["Feeds"] = Relationship(back_populates="source")
    articles: List["Articles"] = Relationship(back_populates="source")


class Feeds(SQLModel, table=True):
    source_name: str = Field(foreign_key="sources.name", primary_key=True)
    name: str = Field(primary_key=True)

    feed_url: str
    display_name: str = Field(default=None)
    active_status: bool = Field(default=True)
    last_fetch_time: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    source: Sources = Relationship(back_populates="feeds")
    articles: List["Articles"] = Relationship(
        back_populates="feeds", link_model=ArticleFeeds
    )
    user_preferences: List["FeedPreferences"] = Relationship(back_populates="feed")


class Articles(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    signature: str = Field(index=True, nullable=False, unique=True)
    pub_date: datetime = Field(index=True)
    pub_date_raw: str = Field(default=None)
    source_name: str = Field(foreign_key="sources.name")
    original_url: str = Field(index=True)
    description: Optional[str] = Field(sa_column=Column(Text), default=None)
    author_name: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(
        default_factory=datetime.now, sa_column_kwargs={"onupdate": None}
    )

    source: Sources = Relationship(back_populates="articles")
    feeds: List[Feeds] = Relationship(
        back_populates="articles", link_model=ArticleFeeds
    )
    __table_args__ = (Index("ix_articles_source_pubdate", "source_name", "pub_date"),)


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
    feed_source_name: str = Field(index=True)
    feed_name: str = Field(index=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["feed_source_name", "feed_name"], ["feeds.source_name", "feeds.name"]
        ),
    )

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.now)
    last_fetched: datetime = Field(default_factory=datetime.now)

    user: Users = Relationship(back_populates="feed_preferences")
    feed: Feeds = Relationship(back_populates="user_preferences")
