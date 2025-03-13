import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, call
import time

from src.tasks.feed_tasks import fetch_feed_chunk


@pytest.fixture
def mock_session():
    with patch("src.tasks.feed_tasks.Session") as mock:
        mock_session_instance = MagicMock()
        mock.return_value.__enter__.return_value = mock_session_instance
        yield mock_session_instance


@pytest.fixture
def mock_asyncio():
    with patch("src.tasks.feed_tasks.asyncio") as mock:
        mock_loop = MagicMock()
        mock.new_event_loop.return_value = mock_loop
        mock_task1 = MagicMock()
        mock_task2 = MagicMock()
        mock.all_tasks.return_value = [mock_task1, mock_task2]
        yield mock


@pytest.fixture
def mock_connection_pool():
    with patch("src.tasks.feed_tasks.ConnectionPool") as mock:
        mock_pool_instance = MagicMock()
        mock.return_value = mock_pool_instance
        yield mock_pool_instance


@pytest.fixture
def mock_redis_client():
    with patch("src.tasks.feed_tasks.RedisClient") as mock:
        mock_redis_instance = MagicMock()
        mock_redis_instance.close = AsyncMock()
        mock.return_value = mock_redis_instance
        yield mock_redis_instance


@pytest.fixture
def mock_news_client():
    with patch("src.tasks.feed_tasks.NewsClient") as mock:
        mock_client_instance = MagicMock()
        mock_client_instance.fetch_multiple_feeds = AsyncMock()
        mock.return_value = mock_client_instance
        yield mock_client_instance


@pytest.fixture
def mock_time():
    with patch("src.tasks.feed_tasks.time") as mock_time:
        mock_time.time.return_value = 1000.0
        yield mock_time


class TestFetchFeedChunk:
    def test_successful_processing(
        self,
        mock_session,
        mock_asyncio,
        mock_connection_pool,
        mock_redis_client,
        mock_news_client,
    ):
        # Setup
        feeds_chunk = [
            (1, 101, "https://example1.com/feed.xml"),
            (2, 102, "https://example2.com/feed.xml"),
        ]

        # Set up mock return values
        mock_asyncio.new_event_loop.return_value.run_until_complete.side_effect = [
            [(3, 1), (2, 0)],  # Result from fetch_multiple_feeds
            None,  # Result from redis_client.close()
        ]

        result = fetch_feed_chunk(feeds_chunk)

        # Assert the result, excluding the fetch_time_seconds field
        assert result["total_articles"] == 5
        assert result["successful_fetches"] == 2
        assert result["failed_fetches"] == 0
        assert result["chunk_size"] == 2
        # Don't check fetch_time_seconds since it depends on actual execution time

    def test_handling_feed_errors(
        self,
        mock_session,
        mock_asyncio,
        mock_connection_pool,
        mock_redis_client,
        mock_news_client,
        mock_time,
    ):
        # Setup
        feeds_chunk = [
            (1, 101, "https://example1.com/feed.xml"),
            (2, 102, "https://example2.com/feed.xml"),
            (3, 103, "https://example3.com/feed.xml"),
        ]

        # Set up asyncio to return error results
        error_result = [
            (2, 0),  # 2 articles, 0 new category associations
            Exception("Feed fetch error"),  # Error for second feed
            (3, 1),  # 3 articles, 1 new category association
        ]
        mock_asyncio.new_event_loop.return_value.run_until_complete.side_effect = [
            error_result,  # Result from fetch_multiple_feeds
            None,  # Result from redis_client.close()
        ]

        # Set a constant time to avoid StopIteration
        mock_time.time.return_value = 1000.0

        # Execute
        result = fetch_feed_chunk(feeds_chunk)

        # Assert everything except fetch_time_seconds
        assert result["total_articles"] == 5
        assert result["successful_fetches"] == 2
        assert result["failed_fetches"] == 1
        assert result["chunk_size"] == 3
        # Don't check fetch_time_seconds as it depends on execution timing

    def test_task_exception_handling(
        self,
        mock_session,
        mock_asyncio,
        mock_connection_pool,
        mock_redis_client,
        mock_news_client,
        mock_time,
    ):
        # Setup - Force an exception during processing
        feeds_chunk = [(1, 101, "https://example.com/feed.xml")]
        mock_asyncio.new_event_loop.return_value.run_until_complete.side_effect = (
            Exception("Test exception")
        )

        # Set a constant time to avoid StopIteration
        mock_time.time.return_value = 1000.0

        # Execute - Should raise the exception
        with pytest.raises(Exception, match="Test exception"):
            fetch_feed_chunk(feeds_chunk)

        # Assert - Verify cleanup still happens
        mock_asyncio.new_event_loop.return_value.close.assert_called_once()

        # Verify tasks were canceled during cleanup
        assert mock_asyncio.all_tasks.called
        for task in mock_asyncio.all_tasks.return_value:
            task.cancel.assert_called_once()

    def test_empty_feed_chunk(
        self,
        mock_session,
        mock_asyncio,
        mock_connection_pool,
        mock_redis_client,
        mock_news_client,
        mock_time,
    ):
        # Setup
        feeds_chunk = []

        # Set up asyncio to return empty result
        mock_asyncio.new_event_loop.return_value.run_until_complete.side_effect = [
            [],  # Empty result from fetch_multiple_feeds
            None,  # Result from redis_client.close()
        ]

        # Set a constant time to avoid StopIteration
        mock_time.time.return_value = 1000.0

        # Execute
        result = fetch_feed_chunk(feeds_chunk)

        # Assert everything except fetch_time_seconds
        assert result["total_articles"] == 0
        assert result["successful_fetches"] == 0
        assert result["failed_fetches"] == 0
        assert result["chunk_size"] == 0
        # Don't check fetch_time_seconds as it depends on execution timing
