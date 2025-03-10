from fastapi import HTTPException
from typing import Dict, Any


class BaseAPIException(HTTPException):
    """Base exception class for API errors"""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str,
        additional_info: Dict[str, Any] | None = None,
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code
        self.additional_info = additional_info or {}


class RSSFeedError(BaseAPIException):
    """Raised when there\'s an error fetching or parsing RSS feeds"""

    def __init__(
        self, detail: str, source: str | None = None, category: str | None = None
    ):
        additional_info = {"source": source, "category": category} if source else {}
        super().__init__(
            status_code=500,
            detail=detail,
            error_code="RSS_FEED_ERROR",
            additional_info=additional_info,
        )


class DateParsingError(BaseAPIException):
    """Raised when there\'s an error parsing article dates"""

    def __init__(self, detail: str, date_string: str):
        super().__init__(
            status_code=500,
            detail=detail,
            error_code="DATE_PARSING_ERROR",
            additional_info={"invalid_date": date_string},
        )


class InvalidSourceError(BaseAPIException):
    """Raised when an invalid source is requested"""

    def __init__(self, source: str):
        super().__init__(
            status_code=404,
            detail=f"Invalid source: {source}",
            error_code="INVALID_SOURCE",
            additional_info={"source": source},
        )


class InvalidCategoryError(BaseAPIException):
    """Raised when an invalid category is requested"""

    def __init__(self, source: str, category: str):
        super().__init__(
            status_code=404,
            detail=f"Invalid category '{category}' for source '{source}'",
            error_code="INVALID_CATEGORY",
            additional_info={"source": source, "category": category},
        )


class HTTPClientError(BaseAPIException):
    """Raised when there\'s an error in the HTTP client"""

    def __init__(
        self,
        detail: str,
        status_code: int = 500,
        host: str | None = None,
    ):
        additional_info = {"host": host} if host else {}
        super().__init__(
            status_code=status_code,
            detail=detail,
            error_code="HTTP_CLIENT_ERROR",
            additional_info=additional_info,
        )


class PasswordTooWeakError(BaseAPIException):
    """Raised when password doesn\'t meet requirements"""

    def __init__(self, detail: str, requirements_failed: list[str] | None = None):
        additional_info = (
            {"requirements_failed": requirements_failed} if requirements_failed else {}
        )
        super().__init__(
            status_code=400,
            detail=detail,
            error_code="PASSWORD_TOO_WEAK",
            additional_info=additional_info,
        )
