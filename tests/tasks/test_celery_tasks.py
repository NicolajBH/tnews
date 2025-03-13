import pytest
from unittest.mock import patch, MagicMock, call, ANY
import time
import random
from celery import chord, group

from src.tasks.feed_tasks import fetch_all_feeds, fetch_feed_chunk, collect_feed_results
from src.core.config import settings
from tests.factories import SourceFactory, CategoryFactory, set_factory_session


@pytest.fixture
def mock_fetch_feed_urls():
    with patch("src.tasks.feed_tasks.fetch_feed_urls") as mock:
        yield mock


@pytest.fixture
def mock_session():
    with patch("src.tasks.feed_tasks.Session") as mock:
        mock_session_instance = MagicMock()
        mock.return_value.__enter__.return_value = mock_session_instance
        yield mock_session_instance


@pytest.fixture
def mock_time():
    with patch("src.tasks.feed_tasks.time") as mock_time:
        mock_time.time.return_value = 1000.0
        yield mock_time


@pytest.fixture
def mock_chord():
    with patch("src.tasks.feed_tasks.chord") as mock:
        yield mock


@pytest.fixture
def mock_group():
    with patch("src.tasks.feed_tasks.group") as mock:
        yield mock


@pytest.fixture
def mock_random():
    with patch("src.tasks.feed_tasks.random") as mock:
        yield mock


class TestFetchAllFeeds:
    def test_empty_feeds(self, mock_session, mock_fetch_feed_urls, mock_time):
        mock_fetch_feed_urls.return_value = []
        result = fetch_all_feeds()

        assert result == {
            "total_articles": 0,
            "successful_fetches": 0,
            "failed_fetches": 0,
            "fetch_time_seconds": 0,
            "feeds_processed": 0,
        }
        mock_fetch_feed_urls.assert_called_once_with(mock_session)

    def test_creates_chunks_and_dispatches_tasks(
        self, mock_session, mock_fetch_feed_urls, mock_group, mock_chord, mock_random
    ):
        cat1 = MagicMock(source_id=1, id=100)
        source1 = MagicMock(base_url="https://example1.com")

        cat2 = MagicMock(source_id=2, id=102)
        source2 = MagicMock(base_url="https://example2.com")

        mock_fetch_feed_urls.return_value = [
            (cat1, source1),
            (cat2, source2),
        ]

        mock_chord.return_value.return_value = MagicMock(id="task-id-123")

        with patch.object(settings, "FEED_CHUNK_SIZE", 1):
            result = fetch_all_feeds()
            mock_random.shuffle.assert_called_once()
            mock_group.assert_called_once()
            group_args = list(mock_group.call_args[0][0])
            assert len(group_args) == 2

            mock_chord.assert_called_once_with(mock_group.return_value)

            assert mock_chord.return_value.call_count == 1
            callback_arg = mock_chord.return_value.call_args[0][0]
            assert callback_arg.name == "src.tasks.feed_tasks.collect_feed_results"

            assert result == {
                "task_id": "task-id-123",
                "feeds_dispatched": 2,
                "chunks_created": 2,
            }

    def test_retry_on_exception(self, mock_session, mock_fetch_feed_urls):
        mock_fetch_feed_urls.side_effect = Exception("Test exception")
        with patch.object(fetch_all_feeds, "retry") as mock_retry:
            fetch_all_feeds()
            mock_retry.assert_called_once()
            args, kwargs = mock_retry.call_args
            assert isinstance(kwargs["exc"], Exception)
            assert str(kwargs["exc"]) == "Test exception"
            assert kwargs["countdown"] == 30

    def test_custom_chunk_size(
        self, mock_session, mock_fetch_feed_urls, mock_group, mock_chord, mock_random
    ):
        mock_feeds = []
        for i in range(1, 6):
            source = MagicMock(id=i, base_url="https://example{i}.com/")
            category = MagicMock(id=100 + i, source_id=source.id)
            mock_feeds.append((category, source))

        mock_fetch_feed_urls.return_value = mock_feeds

        mock_chord.return_value.return_value = MagicMock(id="task-id-123")

        with patch.object(settings, "FEED_CHUNK_SIZE", 2):
            result = fetch_all_feeds()
            assert result["feeds_dispatched"] == 5
            assert result["chunks_created"] == 3

            group_args = list(mock_group.call_args[0][0])
            assert len(group_args) == 3
