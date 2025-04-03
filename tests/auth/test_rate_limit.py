import pytest
from unittest.mock import patch
import time
import redis.asyncio as aioredis
import asyncio

from src.main import app
from src.auth.rate_limit import RateLimiter, rate_limit_dependency
from src.core.config import settings
from fastapi.testclient import TestClient


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_rate_limiter_with_real_redis():
    # try to connect to redis, skip if not available
    try:
        redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
        )
        await redis.ping()
    except (aioredis.RedisError, ConnectionError, asyncio.TimeoutError):
        pytest.skip("Redis not available - skipping integration test")
        return

    limiter = RateLimiter()
    await limiter.initialize()

    test_key = f"test:rate_limit:{time.time()}"
    await redis.delete(f"ratelimit:{test_key}")
    await redis.delete(f"lockout:{test_key}")

    is_limited, remaining, retry_after = await limiter.is_rate_limited(
        test_key, 3, 60, 5
    )
    print(f"remaining is now {remaining}")
    assert not is_limited
    assert remaining == 3

    # add some attempts
    await limiter.increment(test_key, 60)
    is_limited, remaining, retry_after = await limiter.is_rate_limited(
        test_key, 3, 60, 5
    )
    print(f"remaining is now {remaining}")
    assert not is_limited
    assert remaining == 2

    # add some attempts
    await limiter.increment(test_key, 60)
    is_limited, remaining, retry_after = await limiter.is_rate_limited(
        test_key, 3, 60, 5
    )
    print(f"remaining is now {remaining}")
    assert not is_limited
    assert remaining == 1

    # clean up
    await redis.delete(f"ratelimit:{test_key}")
    await redis.delete(f"lockout:{test_key}")
    await redis.aclose()


def test_rate_limit_key_generation():
    """
    Test the key generation logic
    """
    client_ip = "127.0.0.1"
    endpoint = "login"

    key = f"{client_ip}:{endpoint}"
    assert key == "127.0.0.1:login"

    assert key != "192.168.1.1:login"
    assert key != "127.0.0.1:register"


def test_login_endpoints():
    # cringe test man
    pass
