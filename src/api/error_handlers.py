from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from typing import Any
from src.core.exceptions import BaseAPIException


async def api_exception_handler(
    request: Request,
    exc: Any,
) -> JSONResponse:
    """Handler for API exceptions"""
    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": exc.status_code,
        "error_code": exc.error_code,
        "message": exc.detail,
        "path": request.url.path,
    }

    if exc.additional_info:
        error_response["additional_info"] = exc.additional_info

    return JSONResponse(status_code=exc.status_code, content=error_response)


async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handler for unexpected exceptions"""
    error_response = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": 500,
        "error_code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected error occurred",
        "path": request.url.path,
        "type": exc.__class__.__name__,
    }

    return JSONResponse(status_code=500, content=error_response)


def setup_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BaseAPIException, api_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
