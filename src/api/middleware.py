from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from src.auth.rate_limit import apply_rate_limit_headers


class RateLimitHeaderMiddleware(BaseHTTPMiddleware):
    """Middleware to apply rate limit headers to response"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        return apply_rate_limit_headers(response, request)
