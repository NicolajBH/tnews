import time
import logging
import asyncio
from enum import Enum
from typing import Dict, Any, Callable, Awaitable, TypeVar, Generic, List, Tuple

from src.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar("T")
F = TypeVar("F")


class ServiceState(str, Enum):
    """Service health states"""

    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ServiceHealth:
    """
    Tracks health information for a service
    """

    def __init__(
        self,
        name: str,
        state: ServiceState = ServiceState.OPERATIONAL,
        last_failure_time: float = 0,
        failure_count: int = 0,
        last_success_time: float = 0,
        last_error: str = "",
        retry_at: float = 0,
    ):
        self.name = name
        self.state = state
        self.last_failure_time = last_failure_time
        self.failure_count = failure_count
        self.last_success_time = last_success_time
        self.last_error = last_error
        self.retry_at = retry_at
        self.circuit_breaker = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert health info to dictionary
        """
        result = {
            "name": self.name,
            "state": self.state,
            "last_failure_time": self.last_failure_time,
            "failure_count": self.failure_count,
            "last_success_time": self.last_success_time,
            "last_error": self.last_error,
            "retry_at": self.retry_at,
        }
        if self.circuit_breaker:
            result["circuit"] = self.circuit_breaker.get_state()

        return result


class CircuitState(str, Enum):
    """Circuit states for breaker pattern"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker implementation for protecting against repeated failures

    Implements the circuit breaker pattern where:
    - Circuit starts CLOSED (service is used normally)
    - On failure count threshold exceeded, circuit becomes OPEN (no traffic)
    - After timeout, circuit becomes HALF_OPEN (test traffic allowed)
    - Success in HALF_OPEN returns to CLOSED, failure returns to OPEN
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
        backoff_multiplier: float = 2.0,
        max_timeout: float = 3600.0,
        health_service: "HealthService" = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.backoff_multiplier = backoff_multiplier
        self.max_timeout = max_timeout

        # state tracking
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.current_timeout = reset_timeout
        self.cache = {}

        # reference to health service for reporting
        self.health_service = health_service

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        cache_key: str | None = None,
        fallback: Callable[..., Awaitable[F]] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute function with circuit breaker pattern

        Args:
            func: Async function to execute
            cache_key: Optional key for caching results
            fallback: Optional fallback function to call if circuit is open
            *args, **kwargs: Arguments to pass to the function

        Returns:
            Result of the function call or fallback

        Raises:
            ServiceUnavailableError: If circuit is open and no fallback is provided
        """
        use_cache = cache_key is not None

        # check if circuit is open
        if self.state == CircuitState.OPEN:
            time_since_failure = time.time() - self.last_failure_time

            # if we havent waited long enough
            if time_since_failure < self.current_timeout:
                if use_cache and cache_key in self.cache:
                    logger.info(
                        f"Circuit {self.name} OPEN - using cached data for {cache_key}"
                    )
                    return self.cache[cache_key]

                if fallback:
                    logger.info(f"Circuit {self.name} OPEN - using fallback")
                    return await fallback(*args, **kwargs)

                logger.warning(f"Circuit {self.name} is OPEN and no fallback available")
                raise ServiceUnavailableError(
                    service=self.name,
                    detail=f"Service {self.name} is temporarily unavailable",
                    retry_after=int(self.current_timeout - time_since_failure),
                )

            logger.info(f"Circuit {self.name} switching to HALF_OPEN for testing")
            self.state = CircuitState.HALF_OPEN
            self._update_health()

        try:
            result = await func(*args, **kwargs)

            if self.state == CircuitState.HALF_OPEN:
                logger.info(f"Circuit {self.name} recovery successful - CLOSED")
                self._reset()

            self.failure_count = 0

            if use_cache:
                self.cache[cache_key] = result

            self._update_health()
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if (
                self.state == CircuitState.CLOSED
                and self.failure_count >= self.failure_threshold
            ):
                logger.warning(
                    f"Circuit {self.name} OPEN - threshold reached ({self.failure_count} failures)"
                )
                self.state = CircuitState.OPEN
            elif self.state == CircuitState.HALF_OPEN:
                logger.warning(f"Circuit {self.name} OPEN - test failed")
                self.state = CircuitState.OPEN
                self.current_timeout = min(
                    self.current_timeout * self.backoff_multiplier, self.max_timeout
                )

            self._update_health(str(e))

            if use_cache and cache_key in self.cache:
                logger.info(f"Circuit {self.name} - using cached data after failure")
                return self.cache[cache_key]
            if fallback:
                logger.info(f"Circuit {self.name} - using fallback after failure")
                try:
                    return await fallback(*args, **kwargs)
                except Exception as fallback_error:
                    logger.error(
                        f"Fallback for {self.name} also failed: {fallback_error}"
                    )

            raise

    def _reset(self):
        """Reset circuit to closed state"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.current_timeout = self.reset_timeout
        self._update_health()

    def _update_health(self, error: str = ""):
        """
        Update health service with current circuit state
        """
        if not self.health_service:
            return

        state = ServiceState.OPERATIONAL
        if self.state == CircuitState.OPEN:
            state = ServiceState.UNAVAILABLE
        elif self.state == CircuitState.HALF_OPEN:
            state = ServiceState.DEGRADED

        self.health_service.update_service_health(
            self.name,
            state=state,
            failure_count=self.failure_count,
            last_failure_time=self.last_failure_time,
            last_error=error,
            retry_at=self.last_failure_time + self.current_timeout
            if self.state == CircuitState.OPEN
            else 0,
        )

    def get_state(self) -> Dict[str, Any]:
        """
        Get current circuit state info
        """
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "current_timeout": self.current_timeout,
        }


class HealthService:
    """
    Central service for tracking and reporting service health

    This service:
    1. Maintains health state for all services
    2. Provides circuit breakers for services
    3. Exposes health check endpoint data
    """

    def __init__(self):
        self._services: Dict[str, ServiceHealth] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    def get_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
        backoff_multiplier: float = 2.0,
        max_timeout: float = 3600.0,
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker for a service

        Args:
            name: Service name
            failure_threshold: Number of failures before opening circuit
            reset_timeout: Initial timeout in seconds before testing service again
            backoff_multiplier: Factor to increase timeout by on repeated failures
            max_timeout: Maximum timeout in seconds

        Returns:
            CircuitBreaker instance
        """
        if name not in self._circuit_breakers:
            circuit = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                reset_timeout=reset_timeout,
                backoff_multiplier=backoff_multiplier,
                max_timeout=max_timeout,
                health_service=self,
            )
            self._circuit_breakers[name] = circuit

            if name not in self._services:
                self._services[name] = ServiceHealth(name=name)

            self._services[name].circuit_breaker = circuit

        return self._circuit_breakers[name]

    def update_service_health(
        self,
        service_name: str,
        state: ServiceState = None,
        failure_count: int = None,
        last_failure_time: float = None,
        last_success_time: float = None,
        last_error: str = None,
        retry_at: float = None,
    ) -> None:
        """
        Update health information for a service

        Args:
            service_name: Name of the service to update
            state: New service state
            failure_count: Number of consecutive failures
            last_failure_time: Timestamp of last failure
            last_success_time: Timestamp of last successful operation
            last_error: Last error message
            retry_at: Time when service will be retried
        """
        if service_name not in self._services:
            self._services[service_name] = ServiceHealth(name=service_name)

        service = self._services[service_name]

        if state is not None:
            service.state = state

        if failure_count is not None:
            service.failure_count = failure_count

        if last_failure_time is not None:
            service.last_failure_time = last_failure_time

        if last_success_time is not None:
            service.last_success_time = last_success_time

        if last_error is not None:
            service.last_error = last_error

        if retry_at is not None:
            service.retry_at = retry_at

    def get_service_health(self, service_name: str) -> ServiceHealth | None:
        """
        Get health information for a specific service
        """
        return self._services.get(service_name)

    def get_all_service_health(self) -> Dict[str, Dict[str, Any]]:
        """
        Get health information for all services
        """
        return {name: service.to_dict() for name, service in self._services.items()}

    def get_system_health(self) -> Dict[str, Any]:
        """
        Get overall system health status

        Returns a dictionary with:
        - overall_status: OPERATIONAL, DEGRADED, UNAVAILABLE
        - services: Dict of service health states
        - unhealthy_services: List of services that aren't operational
        """
        services = self.get_all_service_health()

        unhealthy = [
            name
            for name, info in services.items()
            if info.get("state") != ServiceState.OPERATIONAL
        ]

        overall_status = ServiceState.OPERATIONAL
        if any(
            services.get(name, {}).get("state") == ServiceState.DEGRADED
            for name in services
        ):
            overall_status = ServiceState.DEGRADED

        if any(
            services.get(name, {}).get("state") == ServiceState.UNAVAILABLE
            for name in services
        ):
            overall_status = ServiceState.UNAVAILABLE

        return {
            "status": overall_status,
            "services": services,
            "unhealthy_services": unhealthy,
        }
