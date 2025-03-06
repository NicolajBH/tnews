import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.core.exceptions import (
    BaseAPIException,
    RSSFeedError,
    DateParsingError,
    InvalidSourceError,
    InvalidCategoryError,
    HTTPClientError,
)


class TestBaseAPIException:
    def test_base_api_exception(self):
        exception = BaseAPIException(
            status_code=400,
            detail="Test error",
            error_code="TEST_ERROR",
            additional_info={"test": "info"},
        )

        assert exception.status_code == 400
        assert exception.detail == "Test error"
        assert exception.error_code == "TEST_ERROR"
        assert exception.additional_info == {"test": "info"}

    def test_base_api_exception_with_default_additional_info(self):
        exception = BaseAPIException(
            status_code=400,
            detail="Test error",
            error_code="TEST_ERROR",
        )

        assert exception.additional_info == {}


class TestSpecificExceptions:
    def test_rss_feed_error(self):
        exception = RSSFeedError(detail="Failed to fetch RSS Feed")
        assert exception.status_code == 500
        assert exception.detail == "Failed to fetch RSS Feed"
        assert exception.error_code == "RSS_FEED_ERROR"
        assert exception.additional_info == {}

        exception = RSSFeedError(
            detail="Failed to fetch RSS Feed",
            source="test_source",
            category="test_category",
        )
        assert exception.additional_info == {
            "source": "test_source",
            "category": "test_category",
        }

    def test_date_parsing_error(self):
        exception = DateParsingError(
            detail="Invalid date format",
            date_string="invalid-date",
        )

        assert exception.status_code == 500
        assert exception.detail == "Invalid date format"
        assert exception.error_code == "DATE_PARSING_ERROR"
        assert exception.additional_info == {"invalid_date": "invalid-date"}

    def test_invalid_source_error(self):
        exception = InvalidSourceError(source="unknown_source")
        assert exception.status_code == 404
        assert exception.detail == "Invalid source: unknown_source"
        assert exception.error_code == "INVALID_SOURCE"
        assert exception.additional_info == {"source": "unknown_source"}

    def test_invalid_category_error(self):
        exception = InvalidCategoryError(
            source="test_source",
            category="unknown_category",
        )
        assert exception.status_code == 404
        assert (
            exception.detail
            == "Invalid category 'unknown_category' for source 'test_source'"
        )
        assert exception.error_code == "INVALID_CATEGORY"
        assert exception.additional_info == {
            "source": "test_source",
            "category": "unknown_category",
        }

    def test_http_client_error(self):
        exception = HTTPClientError(detail="Failed to connect")
        assert exception.status_code == 500
        assert exception.detail == "Failed to connect"
        assert exception.error_code == "HTTP_CLIENT_ERROR"
        assert exception.additional_info == {}

        exception = HTTPClientError(
            detail="Failed to connect", status_code=503, host="example.com"
        )
        assert exception.status_code == 503
        assert exception.additional_info == {"host": "example.com"}
