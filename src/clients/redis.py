import json
import logging
import asyncio
import redis.asyncio as aioredis
from typing import Dict, List, Any
from src.core.config import settings
from src.core.degradation import HealthService


logger = logging.getLogger(__name__)


class RedisClient:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs) -> "RedisClient":
        if cls._instance is None:
            cls._instance = super(RedisClient, cls).__new__(cls)
            cls._instance._initialized = False

        return cls._instance

    def __init__(
        self,
        redis_url: str = settings.REDIS_URL,
        health_service: HealthService | None = None,
    ) -> None:
        if not hasattr(self, "_initialized") or not self._initialized:
            self.redis = None
            self.redis_url = redis_url
            self.connection_retries = 0
            self.health_service = health_service

            if health_service:
                self._circuit_breaker = health_service.get_circuit_breaker(
                    name="redis_client",
                    failure_threshold=3,
                    reset_timeout=5.0,
                    backoff_multiplier=2.0,
                    max_timeout=60.0,
                )

            self._initialized = True

    async def initialize(self) -> "RedisClient":
        async with self._lock:
            if self.redis is None:
                max_retries = 2
                retry_delay = 0.5

                for attempt in range(max_retries):
                    try:
                        self.redis = aioredis.from_url(
                            self.redis_url,
                            decode_responses=True,
                            max_connections=settings.POOL_SIZE,
                            health_check_interval=60,
                            socket_connect_timeout=3.0,
                            socket_keepalive=True,
                            retry_on_timeout=True,
                        )

                        await self.redis.ping()
                        logger.debug("Redis connection established successfully")
                        self.connection_retries = 0

                        if self.health_service:
                            self.health_service.update_service_health(
                                "redis_client",
                                state="operational",
                                last_success_time=asyncio.get_event_loop().time(),
                            )
                        return self
                    except (aioredis.RedisError, ConnectionError, OSError) as e:
                        self.connection_retries += 1
                        logger.warning(
                            f"Redis connection attempt {attempt + 1}/{max_retries} failed: {e}"
                        )

                        if self.health_service:
                            self.health_service.update_service_health(
                                "redis_client",
                                state="degraded"
                                if attempt < max_retries - 1
                                else "unavailable",
                                failure_count=self.connection_retries,
                                last_failure_time=asyncio.get_event_loop().time(),
                                last_error=str(e),
                            )

                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (2**attempt))
                        else:
                            logger.error(
                                f"Failed to connect to redis after {max_retries} attempts"
                            )
                            return self

    async def get(self, key: str) -> str | None:
        """get value from redis by key with retry logic"""

        async def _operation():
            return await self.redis.get(key)

        if self._circuit_breaker:

            async def _fallback(*args, **kwargs):
                logger.info(f"Redis fallback used for GET operation on key: {key}")
                return None

            return await self._circuit_breaker.execute(
                self._execute_with_retry,
                cache_key=f"get_{key}",
                fallback=_fallback,
                operation=_operation,
            )
        else:
            return await self._execute_with_retry(_operation)

    async def set(self, key: str, value: str, expire: int = 3600) -> None:
        """set a key-value pair in redis with retry logic"""

        async def _operation():
            await self.redis.set(key, value, ex=expire)

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(f"Redis SET opeation failed for key {key}: {e}")
        else:
            await self._execute_with_retry(_operation)

    async def set_with_expiry(self, key: str, value: Any, expiry: int = 3600) -> None:
        """Set a value with expiration, serializing if necessary"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            await self.set(key, value, expiry)
        except Exception as e:
            logger.error(f"Error setting value with expiry: {e}")

    async def delete(self, key: str) -> None:
        """delete a key from redis with retry logic"""

        async def _operation():
            await self.redis.delete(key)

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(f"Redis DELETE operation failed for key {key}: {e}")

        else:
            await self._execute_with_retry(_operation)

    async def _execute_with_retry(self, operation, *args, **kwargs):
        max_retries = 1
        retry_delay = 0.1

        if self.redis is None:
            await self.initialize()

        if self.redis is None:
            logger.warning("Redis not available, skipping operation")
            return None

        for attempt in range(max_retries + 1):
            try:
                return await operation(*args, **kwargs)
            except (aioredis.RedisError, ConnectionError) as e:
                if attempt < max_retries:
                    logger.warning(
                        f"Redis operation failed, retrying ({attempt + 1}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(retry_delay * (2**attempt))
                else:
                    logger.error(
                        f"Redis operation failed after {max_retries} retries: {e}"
                    )
                    if self.health_service:
                        self.health_service.update_service_health(
                            "redis_client",
                            state="degraded",
                            failure_count=1,
                            last_failure_time=asyncio.get_event_loop().time(),
                            last_error=str(e),
                        )
                    return None

    async def get_article(self, content_hash: str) -> Dict[str, Any] | None:
        async def _operation():
            data = await self.redis.get(f"article:{content_hash}")
            return json.loads(data) if data else None

        if self._circuit_breaker:

            async def _fallback(*args, **kwargs):
                logger.info(f"Redis fallback used for articles: {content_hash}")
                return None

            return await self._circuit_breaker.execute(
                self._execute_with_retry,
                cache_key=f"article_{content_hash}",
                fallback=_fallback,
                operation=_operation,
            )
        else:
            return await self._execute_with_retry(_operation)

    async def set_article(
        self, content_hash: str, article_data: Dict[str, Any], expire: int = 3600
    ) -> None:
        async def _operation():
            serialized = json.dumps(article_data)
            await self.redis.set(f"article:{content_hash}", serialized, ex=expire)

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(f"Redis set_article failed for {content_hash}: {e}")

        else:
            await self._execute_with_retry(_operation)

    async def add_hash(self, content_hash: str, expires: int = 86400) -> None:
        async def _operation():
            await self.redis.set(f"hash:{content_hash}", "1", ex=expires)

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(f"Redis add_hash failed for {content_hash}: {e}")
        else:
            await self._execute_with_retry(_operation)

    async def pipeline_add_hashes(
        self, content_hashes: List[str], expires: int = 86400
    ) -> None:
        if not content_hashes:
            return

        async def _operation():
            async with self.redis.pipeline(transaction=False) as pipe:
                for content_hash in content_hashes:
                    pipe.set(f"hash:{content_hash}", "1", ex=expires)
                await pipe.execute()

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(f"Redis pipeline_add_hashes failed: {e}")
        else:
            await self._execute_with_retry(_operation)

    async def pipeline_check_hashes(self, content_hashes: List[str]) -> Dict[str, bool]:
        if not content_hashes:
            return {}

        async def _operation():
            if self.redis is None:
                await self.initialize()

            if self.redis is None:
                return {hash: False for hash in content_hashes}

            result = {}
            async with self.redis.pipeline(transaction=False) as pipe:
                for content_hash in content_hashes:
                    pipe.exists(f"hash:{content_hash}")
                responses = await pipe.execute()
                for i, content_hash in enumerate(content_hashes):
                    result[content_hash] = bool(responses[i])
            return result

        async def _fallback(*args, **kwargs):
            logger.info("Redis fallback used for pipeline_check_hashes")
            return {hash: False for hash in content_hashes}

        if self._circuit_breaker:
            try:
                return await self._circuit_breaker.execute(
                    lambda: _operation(), fallback=_fallback
                )
            except Exception as e:
                logger.error(f"Redis batch check failed: {e}")
                return {hash: False for hash in content_hashes}
        else:
            try:
                return await _operation()
            except Exception as e:
                logger.error(f"Redis batch check failed: {e}")
                return {hash: False for hash in content_hashes}

    async def keys(self, pattern: str) -> List[str]:
        """
        Get all keys matching a pattern

        Not recommended for production use with large databases as it may block the server

        Args:
            pattern: Pattern to match keys (e.g., "user:*:feeds")

        Returns:
            List of matching keys
        """

        async def _operation():
            return await self.redis.keys(pattern)

        async def _fallback(*args, **kwargs):
            logger.info(f"Redis fallback used for keys pattern: {pattern}")
            return []

        if self._circuit_breaker:
            result = await self._circuit_breaker.execute(
                self._execute_with_retry,
                cache_key=f"keys_pattern",
                fallback=_fallback,
                operation=_operation,
            )
            return result or []
        else:
            result = await self._execute_with_retry(_operation)
            return result or []

    async def scan(self, match: str | None = None, count: int = 100) -> List[str]:
        """
        Incrementally iterate over keys using SCAN

        Safer alternative to keys for production

        Args:
            match: Optional pattern to match
            count: Hint for how many keys to scan per iteration

        Returns
            List of all matching keys
        """

        async def _scan_operation():
            all_keys = []
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor, match=match, count=count)
                all_keys.extend(keys)
                if cursor == 0:
                    break
            return all_keys

        async def _fallback(*args, **kwargs):
            logger.info(f"Redis fallback used for scan pattern: {match}")
            return []

        if self._circuit_breaker:
            result = await self._circuit_breaker.execute(
                self._execute_with_retry,
                cache_key=f"scan_{match}_{count}",
                fallback=_fallback,
                operation=_scan_operation,
            )
            return result or []
        else:
            result = await self._execute_with_retry(_scan_operation)
            return result or []

    async def delete_keys_by_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args
            pattern: Pattern to match keys

        Returns
            Number of keys deleted
        """
        try:
            keys_to_delete = await self.scan(match=pattern)
            if not keys_to_delete:
                return 0

            async def _operation():
                return await self.redis.delete(*keys_to_delete)

            if self._circuit_breaker:
                try:
                    result = await self._circuit_breaker.execute(
                        self._execute_with_retry, operation=_operation
                    )
                except Exception as e:
                    logger.error(f"Error deleting keys by pattern: {str(e)}")
                    return 0
            else:
                result = await self._execute_with_retry(_operation)
                return result or 0
        except Exception as e:
            logger.error(f"Error deleting keys by pattern: {str(e)}")
            return 0

    async def close(self) -> None:
        if self.redis is not None:
            try:
                await self.redis.aclose()
                logger.debug("Redis connection returned to pool")
            except Exception as e:
                logger.error(f"Error with Redis connection: {e}")

    async def invalidate_by_prefix(self, prefix: str) -> bool:
        """
        Invalidate all cache entries with a given prefix

        Args:
            prefix: Key prefix to invalidate

        Returns:
            True if successful, False otherwise
        """
        try:
            count = await self.delete_keys_by_pattern(f"{prefix}*")
            logger.info(f"Invalidated {count} cache entries with prefix {prefix}")
            return True
        except Exception as e:
            logger.error(f"Failed to invalidate cache with prefix {prefix}: {e}")
            return False

    async def publish(self, channel: str, message: str) -> int:
        """
        Publish a message to a Redis channel with circuit breaker protection

        Args:
            channel: Channel name
            message: Message to publish

        Returns:
            Number of clients that received the message
        """

        async def _operation():
            return await self.redis.publish(channel, message)

        if self._circuit_breaker:
            try:
                return (
                    await self._circuit_breaker.execute(
                        self._execute_with_retry, operation=_operation
                    )
                    or 0
                )
            except Exception as e:
                logger.warning(f"Redis publish failed for channel {channel}: {e}")
        else:
            result = await self._execute_with_retry(_operation)
            return result or 0

    async def subscribe(self, channel: str) -> None:
        """
        Subscribe to a Redis channel

        Args:
            channel: Channel name to subscribe to
        """
        if self.redis is None:
            await self.initialize()

        if self.redis is None:
            logger.warning(f"Redis not available, cannot subscribe")
            return

        try:
            await self.redis.subscribe(channel)
            logger.debug(f"Subscribed to Redis channel: {channel}")
        except Exception as e:
            logger.error(f"Failed to subscribe to Redis channel {channel}: {e}")

            if self.health_service:
                self.health_service.update_service_health(
                    "redis_client",
                    state="degraded",
                    failure_count=1,
                    last_failure_time=asyncio.get_event_loop().time(),
                    last_error=str(e),
                )

    async def get_message(self, timeout: float = 0.01) -> Dict | None:
        """
        Get a message from subscribed channels with timeout

        Args:
            timeout: Time to wait for message in seconds

        Returns:
            Message dict or None if no message
        """
        if self.redis is None:
            logger.warning("Redis not available, cannot get message")
            return None

        try:
            return await self.redis.get_message(timeout=timeout)
        except Exception as e:
            logger.error(f"Failed to get message from Redis: {e}")
            return None
