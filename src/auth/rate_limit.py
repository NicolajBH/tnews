import time
import logging
from fastapi import Request, HTTPException, status
from functools import wraps
from typing import Callable, Dict, Tuple, Any

from src.clients.redis import RedisClient
from src.core.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiting utility using redis as a backend"""

    def __init__(self, redis_client: RedisClient | None = None):
        self.redis = redis_client or RedisClient()

    async def initialize(self):
        """Initialize redis connection if not already initialized"""
        if self.redis.redis is None:
            await self.redis.initialize()

    async def is_rate_limited(
        self, key: str, max_attempts: int, window_seconds: int, lockout_time: int = 300
    ) -> Tuple[bool, int, int]:
        """
        Check if a key is rate limited

        Args:
            key: Unique identifier (typically IP + endpoint)
            max_attempts: Maximum number of attempts allowed in the window
            window_seconds: Time window in seconds
            lockout_time: Time in seconds to lock out after exceeding limits

        Returns:
            Tuple of (is_limited, attempts_remaining, retry_after)
        """
        await self.initialize()

        if self.redis.redis is None:
            logger.warning(f"Redis not available for rate limiting, allowing request")
            return False, max_attempts, 0

        # check if key is in a lockout state
        lockout_key = f"lockout:{key}"
        is_locked = await self.redis.get(lockout_key)

        if is_locked:
            # get ttl for the lockout key
            ttl = await self.redis.redis.ttl(lockout_key)
            return True, 0, ttl

        current_time = int(time.time())

        # key for rate limit counter
        rate_key = f"ratelimit:{key}"

        async with self.redis.redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(
                rate_key,
                0,
                current_time - window_seconds,
            )  # remove expired attempts
            pipe.zrange(rate_key, 0, -1)  # get all attempts in window
            pipe.zcard(rate_key)  # count attempts
            _, attempts_list, attempts_count = await pipe.execute()

        if attempts_count >= max_attempts:
            await self.redis.set(lockout_key, "1", expire=lockout_time)
            return True, 0, lockout_time

        # not rate limited
        return False, max_attempts - attempts_count, 0

    async def increment(
        self,
        key: str,
        window_seconds: int,
    ) -> None:
        """
        Increment the counter for a key

        Args:
            key: Unique identifier
            window_seconds: Time window in seconds
        """
        await self.initialize()

        if self.redis.redis is None:
            logger.warning(f"Redis not available for rate limiting, skipping increment")
            return

        current_time = int(time.time())
        rate_key = f"ratelimit:{key}"

        # add current timestamp to the sorted set with score = current_time
        await self.redis.redis.zadd(rate_key, {str(current_time): current_time})

        # set expiry on the key to auto cleanup
        await self.redis.redis.expire(rate_key, window_seconds * 2)


def rate_limit_dependency(
    endpoint_name: str,
    max_attempts: int = settings.AUTH_RATE_LIMIT_ATTEMPTS,
    window_seconds: int = settings.AUTH_RATE_LIMIT_WINDOW,
    lockout_time: int = settings.AUTH_RATE_LIMIT_TIMEOUT_TIME,
):
    """
    FastAPI dependency for rate limiting

    Args:
        endpoint_name: Name of the endpoint for key generation
        max_attempts: Maximum attempts allowed in a window
        window_seconds: Time window in seconds
        lockout_time: Time in seconds to lock out after exceeding limits

    Returns:
        Dependency function that performs rate limting
    """

    async def check_rate_limit(request: Request):
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return

        # get client ip
        client_ip = request.client.host

        # create unique key based on ip and endpoint
        key = f"{client_ip}:{endpoint_name}"

        limiter = RateLimiter()

        # check if rate limited
        is_limited, remaining, retry_after = await limiter.is_rate_limited(
            key, max_attempts, window_seconds, lockout_time
        )

        await limiter.increment(key, window_seconds)

        if is_limited:
            headers = {
                "X-RateLimit-Limit": str(max_attempts),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(retry_after),
                "Retry-After": str(retry_after),
            }
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers=headers,
            )

        headers = {
            "X-RateLimit-Limit": str(max_attempts),
            "X-RateLimit-Remaining": str(remaining - 1),
        }
        request.state.rate_limit_headers = headers

    return check_rate_limit


def apply_rate_limit_headers(response: Any, request: Request) -> Any:
    """
    Add rate limit headers to response
    """
    if hasattr(request.state, "rate_limit_headers"):
        for name, value in request.state.rate_limit_headers.items():
            response.headers[name] = value

    return response
