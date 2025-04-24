from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE, HTTP_207_MULTI_STATUS

from src.core.exceptions import ServiceUnavailableError, DegradedServiceError
from src.core.degradation import HealthService, ServiceState
from src.core.logging import LogContext

logger = LogContext(__name__)


class ServiceDegradationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for managing service degradation responses.

    This middleware:
    1. Handles service unavailable errors with proper headers
    2. Adds degraded service warning headers when applicable
    3. Provides circuit breaker state in response headers for debugging
    """

    def __init__(self, app, health_service: HealthService):
        super().__init__(app)
        self.health_service = health_service

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add degradation information to response"""
        # Check if any services are in degraded state before processing
        system_health = self.health_service.get_system_health()
        status = system_health.get("status", ServiceState.OPERATIONAL)
        unhealthy_services = system_health.get("unhealthy_services", [])

        # Store in request state for access in route handlers
        request.state.system_health = system_health
        request.state.service_status = status
        request.state.unhealthy_services = unhealthy_services

        # Process request
        try:
            response = await call_next(request)

            # Add health headers to response if there are unhealthy services
            if unhealthy_services:
                response.headers["X-Service-Health"] = status
                response.headers["X-Degraded-Services"] = ",".join(unhealthy_services)

            return response

        except ServiceUnavailableError as e:
            # Let the regular exception handler deal with this
            # but add our service status in the request for better error reporting
            request.state.service_error = e
            request.state.health_info = self.health_service.get_service_health(
                e.additional_info.get("service", "unknown")
            )

            # Add retry-after header if provided
            if e.additional_info.get("retry_after"):
                e.headers["Retry-After"] = str(e.additional_info["retry_after"])

            raise

        except DegradedServiceError as e:
            # Similar to above
            request.state.service_error = e
            request.state.health_info = self.health_service.get_service_health(
                e.additional_info.get("service", "unknown")
            )
            raise
