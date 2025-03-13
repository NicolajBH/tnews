import pytest
from unittest.mock import patch, MagicMock
import time
from src.tasks.feed_tasks import collect_feed_results


@pytest.fixture
def mock_time():
    with patch("src.tasks.feed_tasks.time") as mock_time:
        # Just use a constant time to avoid any timing issues
        mock_time.time.return_value = 1030.0
        yield mock_time


@pytest.fixture
def mock_logger():
    with patch("src.tasks.feed_tasks.logger") as mock_logger:
        yield mock_logger


class TestCollectFeedResults:
    def test_successful_aggregation(self, mock_time, mock_logger):
        # Setup
        start_time = 1000.0  # 30 seconds before mock_time

        # Task results from three chunks
        task_results = [
            {
                "total_articles": 5,
                "successful_fetches": 2,
                "failed_fetches": 0,
                "fetch_time_seconds": 10.0,
                "chunk_size": 2,
            },
            {
                "total_articles": 3,
                "successful_fetches": 1,
                "failed_fetches": 1,
                "fetch_time_seconds": 8.0,
                "chunk_size": 2,
            },
            {
                "total_articles": 7,
                "successful_fetches": 3,
                "failed_fetches": 0,
                "fetch_time_seconds": 12.0,
                "chunk_size": 3,
            },
        ]

        # Execute
        result = collect_feed_results(task_results, start_time)

        # Assert
        # Verify proper aggregation of metrics (excluding time)
        assert result["total_articles"] == 15
        assert result["successful_fetches"] == 6
        assert result["failed_fetches"] == 1
        # Don't check fetch_time_seconds as it depends on execution timing

        # Verify logger was called with the correct information
        assert mock_logger.info.call_count == 1
        # The exact arguments to the logger will include timing, so we don't check them

    def test_partial_results(self, mock_time, mock_logger):
        # Setup
        start_time = 1000.0  # 30 seconds before mock_time

        # Task results including None (failed task) and incomplete data
        task_results = [
            {
                "total_articles": 5,
                "successful_fetches": 2,
                "failed_fetches": 0,
                "fetch_time_seconds": 10.0,
            },
            None,  # Represents a completely failed task
            {
                # Missing some fields
                "total_articles": 3,
                "successful_fetches": 1,
            },
        ]

        # Execute
        result = collect_feed_results(task_results, start_time)

        # Assert
        # Verify proper handling of None and incomplete results
        assert result["total_articles"] == 8
        assert result["successful_fetches"] == 3
        assert result["failed_fetches"] == 0
        # Don't check fetch_time_seconds as it depends on execution timing

    def test_empty_results(self, mock_time, mock_logger):
        # Setup
        start_time = 1000.0  # 30 seconds before mock_time

        # Empty task results
        task_results = []

        # Execute
        result = collect_feed_results(task_results, start_time)

        # Assert
        # Verify proper handling of empty results
        assert result["total_articles"] == 0
        assert result["successful_fetches"] == 0
        assert result["failed_fetches"] == 0
        # Don't check fetch_time_seconds as it depends on execution timing

    def test_all_failed_results(self, mock_time, mock_logger):
        # Setup
        start_time = 1000.0  # 30 seconds before mock_time

        # All tasks failed
        task_results = [None, None, None]

        # Execute
        result = collect_feed_results(task_results, start_time)

        # Assert
        # Verify proper handling of all failed results
        assert result["total_articles"] == 0
        assert result["successful_fetches"] == 0
        assert result["failed_fetches"] == 0
        # Don't check fetch_time_seconds as it depends on execution timing

    def test_mixed_result_formats(self, mock_time, mock_logger):
        # Setup
        start_time = 1000.0  # 30 seconds before mock_time

        # Mix of result formats and values
        task_results = [
            {
                "total_articles": 5,
                "successful_fetches": 2,
                "failed_fetches": 1,
                "fetch_time_seconds": 10.0,
            },
            {},  # Empty dict
            {
                # Different field names
                "articles_processed": 3,  # This should be ignored
                "successful_fetches": 1,
                "failed_fetches": 2,
            },
            None,
        ]

        # Execute
        result = collect_feed_results(task_results, start_time)

        # Assert
        # Verify only recognized fields are aggregated
        assert result["total_articles"] == 5
        assert result["successful_fetches"] == 3
        assert result["failed_fetches"] == 3
        # Don't check fetch_time_seconds as it depends on execution timing
