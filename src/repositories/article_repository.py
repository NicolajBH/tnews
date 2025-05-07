from datetime import datetime
from typing import List, Tuple, Dict
from sqlmodel import select, col, Session
from src.models.db_models import (
    Articles,
    ArticleFeeds,
    Feeds,
    FeedPreferences,
    Sources,
)


class ArticleRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_articles_for_user(
        self,
        user_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        pub_date_lt: datetime | None = None,
        id_lt: int | None = None,
        limit: int = 20,
    ) -> List[Articles]:
        """
        Get articles for a specific user with filters
        Args:
            user_id: The user's ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            pub_date_lt: Optional publication date less than filter (for cursor)
            id_lt: Optional ID less than filter (for cursor)
            limit: Maximum number of articles to return
        Returns:
            List of Articles objects
        """
        query = (
            select(Articles)
            .join(ArticleFeeds, Articles.id == ArticleFeeds.article_id)
            .join(
                Feeds,
                (ArticleFeeds.feed_source_name == Feeds.source_name)
                & (ArticleFeeds.feed_name == Feeds.name),
            )
            .join(
                FeedPreferences,
                (FeedPreferences.feed_source_name == Feeds.source_name)
                & (FeedPreferences.feed_name == Feeds.name),
            )
            .where(FeedPreferences.user_id == user_id)
            .where(FeedPreferences.is_active == True)
        )

        # apply date range filters
        if start_date:
            query = query.where(Articles.pub_date >= start_date)
        if end_date:
            query = query.where(Articles.pub_date <= end_date)

        # apply cursor pagination filters
        if pub_date_lt and id_lt:
            query = query.where((Articles.pub_date, Articles.id) < (pub_date_lt, id_lt))

        # apply sorting and limit
        query = query.order_by(col(Articles.pub_date).desc(), col(Articles.id).desc())
        query = query.limit(limit)

        return self.session.exec(query).all()

    def get_sources_by_name(self, source_names: List[str]) -> Dict[str, Sources]:
        """
        Get sources by their names

        Args:
            source_names: List of source names

        Returns:
            Dictionary mapping source name to source object
        """
        if not source_names:
            return {}

        sources = self.session.exec(
            select(Sources).where(Sources.name.in_(source_names))
        ).all()

        return {source.name: source for source in sources}

    def get_articles_by_id(self, article_id: int) -> Articles | None:
        """
        Get an article by its ID

        Args:
            article_id: The article's ID

        Returns:
            Article object or None if not found
        """
        return self.session.get(Articles, article_id)

    def get_feeds_for_user(
        self, user_id: int, active_only: bool = True
    ) -> List[Tuple[FeedPreferences, Feeds]]:
        """
        Gets feeds that a user has subscribed to

        Args:
            user_id: The user's ID
            active_only: Whether to only return active subscriptions

        Returns:
            List of (FeedPreferences, Feeds) tuples
        """
        query = (
            select(FeedPreferences, Feeds)
            .join(
                Feeds,
                (FeedPreferences.feed_source_name == Feeds.source_name)
                & (FeedPreferences.feed_name == Feeds.name),
            )
            .where(FeedPreferences.user_id == user_id)
        )

        if active_only:
            query = query.where(FeedPreferences.is_active == True)

        return self.session.exec(query).all()
