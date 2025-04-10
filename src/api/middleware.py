from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_304_NOT_MODIFIED
from src.utils.etag import extract_etag_header, is_etag_match
from src.auth.rate_limit import apply_rate_limit_headers


class RateLimitHeaderMiddleware(BaseHTTPMiddleware):
    """Middleware to apply rate limit headers to response"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        return apply_rate_limit_headers(response, request)


class ETagMiddleware(BaseHTTPMiddleware):
    """
    Middleware for handling conditional requests with ETags

    This middleware processes ETag-related headers (If-None-Match, If-Match)
    and responds appropriately for conditional requests
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method != "GET":
            return await call_next(request)

        client_etag = None
        if "if-none-match" in request.headers:
            client_etag = extract_etag_header(request.headers, "if-none-match")

        request.state.client_etag = client_etag
        request.state.is_conditional = client_etag is not None

        response = await call_next(request)

        if "etag" in response.headers and client_etag is not None:
            server_etag = response.headers["etag"]

            if is_etag_match(server_etag, client_etag):
                new_response = Response(status_code=HTTP_304_NOT_MODIFIED)
                preserved_headers = [
                    "cache-control",
                    "content-location",
                    "date",
                    "etag",
                    "expires",
                    "vary",
                ]

                for header in preserved_headers:
                    if header in response.headers:
                        new_response.headers[header] = response.headers[header]

                return new_response

        return response
