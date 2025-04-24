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


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to generate and track request IDs and establish correlation context

    This middleware:
    1. Checks if incoming request has an X-Request-ID header
    2. If not, generates a new unique request ID
    3. Sets up correlation context for the request
    4. Stores the request ID in request.state and logging context
    5. Adds the request ID to response headers
    6. Logs request and response info with timing information
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from src.utils.request_id import (
            generate_request_id,
            get_request_id_from_headers,
        )
        from src.core.logging import (
            set_request_id,
            add_correlation_id,
            reset_correlation_context,
            LogContext,
        )
        import time

        logger = LogContext("src.api.middleware")

        reset_correlation_context()

        request_id = (
            get_request_id_from_headers(request.headers) or generate_request_id()
        )

        request.state.request_id = request_id

        set_request_id(request_id)

        add_correlation_id("method", request.method)
        add_correlation_id("path", request.url.path)
        add_correlation_id(
            "client_ip", request.client.host if request.client else "unknown"
        )

        user_agent = request.headers.get("user-agent")
        if user_agent:
            add_correlation_id("user_agent", user_agent)

        start_time = time.time()

        logger.info(f"Request received: {request.method} {request.url.path}")

        try:
            response = await call_next(request)

            duration_ms = (time.time() - start_time) * 1000

            add_correlation_id("status_code", response.status_code)
            add_correlation_id("duration_ms", round(duration_ms, 2))

            response.headers["X-Request-ID"] = request_id

            logger.info(
                f"Request completed: {request.method} {request.url.path} - {response.status_code} in {duration_ms:.2f}ms"
            )
            return response
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            add_correlation_id("duration_ms", round(duration_ms, 2))
            add_correlation_id("error", str(e))

            logger.exception(f"Unhandled exception in request processing: {str(e)}")
            raise
