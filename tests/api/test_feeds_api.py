from datetime import datetime, timezone
import pytest
from fastapi import status
import json
from unittest.mock import patch, MagicMock, PropertyMock

from src.api.dependencies import get_date_filters
from src.core.config import settings
from src.models.article import ArticleQueryParameters
from src.models.db_models import ArticleCategories, Articles, FeedPreferences
from tests.factories import (
    UserFactory,
    SourceFactory,
    CategoryFactory,
    ArticleFactory,
    FeedPreferencesFactory,
    set_factory_session,
)

PREFIX = settings.API_V1_STR


@pytest.fixture(autouse=True)
def setup_factories(db_session):
    set_factory_session(db_session)


class TestLatestArticlesEndpoint:
    def test_latest_articles_unauthorized(self, client):
        response = client.get(f"{PREFIX}/articles/latest")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_latest_articles_empty(self, auth_client, test_user):
        response = auth_client.get(f"{PREFIX}/articles/latest")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_latest_articles_with_subscriptions(
        self, db_session, auth_client, test_user
    ):
        source = SourceFactory()
        category = CategoryFactory(source_id=source.id)

        pref = FeedPreferencesFactory(user=test_user, feed_id=category.id)
        articles = [
            ArticleFactory(source_id=source.id, categories=[category]) for _ in range(3)
        ]
        db_session.commit()

        response = auth_client.get(f"{PREFIX}/articles/latest")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data) == 3

    def test_latest_articles_with_date_filters(
        self, db_session, auth_client, test_user
    ):
        source = SourceFactory()
        category = CategoryFactory(source_id=source.id)
        pref = FeedPreferencesFactory(user=test_user, feed_id=category.id)

        date1 = datetime(2025, 3, 1, tzinfo=timezone.utc)
        date2 = datetime(2025, 3, 15, tzinfo=timezone.utc)
        date3 = datetime(2025, 3, 30, tzinfo=timezone.utc)

        article1 = ArticleFactory(
            source_id=source.id, categories=[category], pub_date=date1
        )
        article2 = ArticleFactory(
            source_id=source.id, categories=[category], pub_date=date2
        )
        article3 = ArticleFactory(
            source_id=source.id, categories=[category], pub_date=date3
        )
        db_session.commit()

        # test start date filter
        response = auth_client.get(f"{PREFIX}/articles/latest?start_date=2025-03-02")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2

        # test end date filter
        response = auth_client.get(f"{PREFIX}/articles/latest?end_date=2025-03-29")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2

        # test start and end date filter
        response = auth_client.get(
            f"{PREFIX}/articles/latest?start_date=2025-03-02&end_date=2025-03-29"
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1

        # test invalid date range
        try:
            response = auth_client.get(
                f"{PREFIX}/articles/latest?start_date=2025-03-01&end_date=2025-02-01"
            )
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
            data = response.json()
            assert "end_date must be greater than or equal to start_date" in str(data)
        except ValueError as e:
            assert "end_date must be greater than or equal to start_date" in str(e)


class TestCategoriesEndpoint:
    @patch("src.api.routes.feeds.RSS_FEEDS")
    def test_get_categories(self, mock_rss_feeds, auth_client):
        mock_rss_feeds.__getitem__.side_effect = lambda key: {
            "source1": {"feeds": {"cat1": "url1", "cat2": "url2"}},
            "source2": {"feeds": {"cat3": "url3"}},
        }.__getitem__(key)
        mock_rss_feeds.items.return_value = [
            ("source1", {"feeds": {"cat1": "url1", "cat2": "url2"}}),
            ("source2", {"feeds": {"cat3": "url3"}}),
        ]
        mock_rss_feeds.keys.return_value = ["source1", "source2"]

        response = auth_client.get(f"{PREFIX}/categories")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == {"source1": ["cat1", "cat2"], "source2": ["cat3"]}

    def test_get_categories_error_handling(self, auth_client, mock_logger):
        with patch("src.api.routes.feeds.RSS_FEEDS") as mock_rss:
            mock_rss.items.side_effect = Exception("Test exception")
            with patch("src.api.routes.feeds.logger", mock_logger):
                response = auth_client.get(f"{PREFIX}/categories")
                assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
                assert response.json()["detail"] == "Error fetching categories"
                mock_logger.error.assert_called_once_with(
                    "Error fetching categories: Test exception", exc_info=True
                )


class TestSourcesEndpoint:
    @patch("src.api.routes.feeds.RSS_FEEDS")
    def test_get_sources(self, mock_rss_feeds, auth_client):
        mock_rss_feeds.keys.return_value = ["source1", "source2"]

        response = auth_client.get(f"{PREFIX}/sources")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data == {"sources": ["source1", "source2"]}

    def test_get_sources_error_handling(self, auth_client, mock_logger):
        with patch("src.api.routes.feeds.RSS_FEEDS") as mock_rss:
            mock_rss.keys.side_effect = Exception("Test exception")
            with patch("src.api.routes.feeds.logger", mock_logger):
                response = auth_client.get(f"{PREFIX}/sources")
                assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
                assert response.json()["detail"] == "Error fetching sources"

                mock_logger.error.assert_called_once_with(
                    "Error fetching sources: Test exception", exc_info=True
                )


class TestSubscriptionEndpoints:
    def test_subscribe_to_feed(self, db_session, auth_client, test_user):
        category = CategoryFactory()

        response = auth_client.post(f"{PREFIX}/subscribe/{category.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "status": "subscribed",
            "category_id": category.id,
        }

        preference = (
            db_session.query(FeedPreferencesFactory._meta.model)
            .filter_by(
                user_id=test_user.id,
                feed_id=category.id,
            )
            .first()
        )

        assert preference is not None
        assert preference.is_active is True

    def test_subscribe_to_nonexistent_feed(self, auth_client):
        response = auth_client.post(f"{PREFIX}/subscribe/999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Category not found"

    def test_subscribe_to_already_subscribed_feed(
        self, db_session, auth_client, test_user
    ):
        category = CategoryFactory()
        FeedPreferencesFactory(user=test_user, feed_id=category.id, is_active=True)
        db_session.commit()

        response = auth_client.post(f"{PREFIX}/subscribe/{category.id}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Already subscribed to this feed"

    def test_resubscribe_to_inactive_feed(self, db_session, auth_client, test_user):
        category = CategoryFactory()
        FeedPreferencesFactory(user=test_user, feed_id=category.id, is_active=False)

        response = auth_client.post(f"{PREFIX}/subscribe/{category.id}")
        assert response.status_code == status.HTTP_200_OK

        preference = (
            db_session.query(FeedPreferencesFactory._meta.model)
            .filter_by(
                user_id=test_user.id,
                feed_id=category.id,
            )
            .first()
        )

        assert preference is not None
        assert preference.is_active is True

    def test_unsubscribe_from_feed(self, db_session, auth_client, test_user):
        category = CategoryFactory()
        FeedPreferencesFactory(user=test_user, feed_id=category.id, is_active=True)
        db_session.commit()

        response = auth_client.post(f"{PREFIX}/unsubscribe/{category.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "status": "unsubscribed",
            "category_id": category.id,
        }

        preference = (
            db_session.query(FeedPreferencesFactory._meta.model)
            .filter_by(
                user_id=test_user.id,
                feed_id=category.id,
            )
            .first()
        )

        assert preference is not None
        assert preference.is_active is False

    def test_unsubscribe_from_nonexistent_feed(self, auth_client):
        response = auth_client.post(f"{PREFIX}/unsubscribe/999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Not subscribed to this feed"


class TestMyFeedEndpoint:
    def test_get_my_feeds_empty(self, auth_client):
        response = auth_client.get(f"{PREFIX}/my")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_get_my_feeds(self, db_session, auth_client, test_user):
        categories = [CategoryFactory() for _ in range(3)]

        for i in range(2):
            FeedPreferencesFactory(
                user=test_user, feed_id=categories[i].id, is_active=True
            )

        FeedPreferencesFactory(
            user=test_user, feed_id=categories[2].id, is_active=False
        )

        db_session.commit()
        response = auth_client.get(f"{PREFIX}/my")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data) == 2

        for item in data:
            assert "category_id" in item
            assert "name" in item
            assert "feed_url" in item
            assert "subscribed_at" in item
