from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from datetime import datetime, timezone
from typing import Any
from src.core.exceptions import BaseAPIException


async def api_exception_handler(
    request: Request,
    exc: Any,
) -> JSONResponse:
    """Handler for API exceptions"""
    # get request id from request state
    request_id = getattr(request.state, "request_id", None)

    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": exc.status_code,
        "error_code": exc.error_code,
        "message": exc.detail,
        "path": request.url.path,
        "request_id": request_id,
    }

    if exc.additional_info:
        error_response["additional_info"] = exc.additional_info

    response = JSONResponse(status_code=exc.status_code, content=error_response)

    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """
    Handler for FastAPI HTTP Exceptions
    """
    request_id = getattr(request.state, "request_id", None)

    # map status codes to error codes
    status_code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        408: "REQUEST_TIMEOUT",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        501: "NOT_IMPLEMENTED",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }
    error_code = status_code_map.get(exc.status_code, f"HTTP_ERROR_{exc.status_code}")

    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": exc.status_code,
        "error_code": error_code,
        "message": exc.detail,
        "path": request.url.path,
        "request_id": request_id,
    }

    response = JSONResponse(status_code=exc.status_code, content=error_response)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    Handler for request validation errors
    """
    # get request id from request state
    request_id = getattr(request.state, "request_id", None)

    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": 422,
        "error_code": "VALIDATION_ERROR",
        "message": "Request validation error",
        "path": request.url.path,
        "request_id": request_id,
        "errors": exc.errors(),
    }

    response = JSONResponse(status_code=422, content=error_response)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handler for unexpected exceptions"""
    # get request id from request state
    request_id = getattr(request.state, "request_id", None)

    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": 500,
        "error_code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected error occurred",
        "path": request.url.path,
        "type": exc.__class__.__name__,
        "request_id": request_id,
    }

    response = JSONResponse(status_code=500, content=error_response)

    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


def setup_error_handlers(app: FastAPI) -> None:
    # custom api exceptions
    app.add_exception_handler(BaseAPIException, api_exception_handler)

    # fastapi and starlette http exceptions
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # validation errors
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # catch all for unexpected exceptions
    app.add_exception_handler(Exception, generic_exception_handler)
