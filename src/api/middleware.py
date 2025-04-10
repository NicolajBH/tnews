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
    Middleware to genereate and track request IDs

    This middleware:
    1. Checks if incoming request has an X-Request-ID header
    2. If not, generates a new unique request ID
    3. Stores the request ID in request.state and logging logging context
    4. Adds the request ID to resposne headers
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from src.utils.request_id import (
            generate_request_id,
            get_request_id_from_headers,
        )
        from src.core.logging import set_request_id
        import logging

        logger = logging.getLogger("src.api.middleware")

        # check if request already has an id or genereate a new one
        request_id = (
            get_request_id_from_headers(request.headers) or generate_request_id()
        )

        # store in request state for access in route handlers and error handlers
        request.state.request_id = request_id

        # set request id in logging context
        set_request_id(request_id)

        extra = {"request_id": request_id}
        logger.info(
            f"Processing request: {request.method} {request.url.path}", extra=extra
        )

        # process request
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as e:
            logger.exception(
                f"Unhandled exception in request processing: {str(e)}", extra=extra
            )
            raise
        finally:
            logger.info(
                f"Completed request: {request.method} {request.url.path}", extra=extra
            )
