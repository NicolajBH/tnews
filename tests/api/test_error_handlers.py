from fastapi.testclient import TestClient
from starlette.middleware.exceptions import ExceptionMiddleware
import pytest
import json
import logging
from unittest.mock import MagicMock, patch
from fastapi import status, Request, Response

from src.core.config import settings
from src.core.exceptions import BaseAPIException, RSSFeedError, InvalidSourceError
from src.api.error_handlers import (
    api_exception_handler,
    generic_exception_handler,
    setup_error_handlers,
)

PREFIX = settings.API_V1_STR


class MockRequest:
    def __init__(self, path="/test-path"):
        self.url = MagicMock()
        self.url.path = path
        self.headers = {}


@pytest.fixture
def app_with_error_handlers():
    from fastapi import FastAPI

    app = FastAPI()
    setup_error_handlers(app)

    @app.get(f"{PREFIX}/test-rss-error")
    async def test_rss_error():
        raise RSSFeedError("Test RSS feed error")

    @app.get(f"{PREFIX}/test-source-error")
    async def test_source_error():
        raise InvalidSourceError("Unknown source")

    @app.get(f"{PREFIX}/test-generic-error")
    async def test_generic_error():
        raise ValueError("Unexpected error")

    return app


@pytest.fixture
def error_client(app_with_error_handlers):
    client = TestClient(app_with_error_handlers, raise_server_exceptions=False)
    return client


class TestAPIExceptionHandler:
    @pytest.mark.asyncio
    async def test_api_exception_handler(self):
        request = MockRequest(path=f"{PREFIX}/test-path")
        exception = RSSFeedError(detail="Test error", source="test_source")

        response = await api_exception_handler(request, exception)

        assert response.status_code == 500

        content = json.loads(response.body)
        assert content["message"] == "Test error"
        assert content["error_code"] == "RSS_FEED_ERROR"
        assert content["additional_info"]["source"] == "test_source"
        assert "timestamp" in content
        assert content["path"] == f"{PREFIX}/test-path"

    def test_api_exception_response_format(self, error_client):
        response = error_client.get(f"{PREFIX}/test-source-error")
        assert response.status_code == 404

        data = response.json()

        logging.info(data)
        assert "timestamp" in data
        assert data["status"] == 404
        assert data["error_code"] == "INVALID_SOURCE"
        assert data["message"] == "Invalid source: Unknown source"
        assert data["path"] == f"{PREFIX}/test-source-error"
        assert "additional_info" in data
        assert data["additional_info"]["source"] == "Unknown source"


class TestGenericExceptionHandler:
    @pytest.mark.asyncio
    async def test_generic_exception_handler(self):
        request = MockRequest(path="/test-generic")
        exception = ValueError("Something went wrong")

        response = await generic_exception_handler(request, exception)

        assert response.status_code == 500

        content = json.loads(response.body)
        assert content["message"] == "An unexpected error occurred"
        assert content["error_code"] == "INTERNAL_SERVER_ERROR"
        assert content["type"] == "ValueError"
        assert "timestamp" in content
        assert content["path"] == "/test-generic"

    def test_generic_exception_response(self, error_client):
        response = error_client.get(f"{PREFIX}/test-generic-error")
        assert response.status_code == 500

        data = response.json()
        print(f"Response JSON: {data}")
        assert "timestamp" in data
        assert data["status"] == 500
        assert data["error_code"] == "INTERNAL_SERVER_ERROR"
        assert data["message"] == "An unexpected error occurred"
        assert data["path"] == f"{PREFIX}/test-generic-error"
        assert data["type"] == "ValueError"


class TestErrorHandlerRegistration:
    def test_setup_error_handlers(self):
        app = MagicMock()

        setup_error_handlers(app)

        assert app.add_exception_handler.call_count == 2

        app.add_exception_handler.assert_any_call(
            BaseAPIException, api_exception_handler
        )

        app.add_exception_handler.assert_any_call(Exception, generic_exception_handler)
