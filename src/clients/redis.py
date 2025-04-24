import json
import asyncio
import time
import redis.asyncio as aioredis
from typing import Dict, List, Any
from src.core.config import settings
from src.core.degradation import HealthService
from src.core.logging import LogContext, PerformanceLogger, add_correlation_id

logger = LogContext(__name__)


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
            else:
                self._circuit_breaker = None

            logger.info(
                "Redis client initialized",
                extra={
                    "redis_url": redis_url.split("@")[-1],  # Hide credentials
                    "has_health_service": health_service is not None,
                },
            )
            self._initialized = True

    async def initialize(self) -> "RedisClient":
        async with self._lock:
            if self.redis is None:
                max_retries = 2
                retry_delay = 0.5

                init_start_time = time.time()

                for attempt in range(max_retries):
                    try:
                        connection_start = time.time()
                        self.redis = aioredis.from_url(
                            self.redis_url,
                            decode_responses=True,
                            max_connections=settings.POOL_SIZE,
                            health_check_interval=60,
                            socket_connect_timeout=3.0,
                            socket_keepalive=True,
                            retry_on_timeout=True,
                        )

                        ping_start = time.time()
                        await self.redis.ping()
                        ping_time = time.time() - ping_start

                        connection_time = ping_start - connection_start
                        logger.info(
                            "Redis connection established successfully",
                            extra={
                                "connection_time_ms": round(connection_time * 1000, 2),
                                "ping_time_ms": round(ping_time * 1000, 2),
                                "pool_size": settings.POOL_SIZE,
                                "attempts": attempt + 1,
                            },
                        )
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
                            "Redis connection attempt failed",
                            extra={
                                "error": str(e),
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                                "error_type": e.__class__.__name__,
                                "retry_delay_ms": round(
                                    retry_delay * (2**attempt) * 1000, 2
                                ),
                            },
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
                            total_init_time = time.time() - init_start_time
                            logger.error(
                                "Failed to connect to Redis after all attempts",
                                extra={
                                    "attempts": max_retries,
                                    "total_init_time_ms": round(
                                        total_init_time * 1000, 2
                                    ),
                                    "error_type": e.__class__.__name__,
                                },
                            )
                            return self

    async def get(self, key: str) -> str | None:
        """get value from redis by key with retry logic"""
        # Create a safe key name for logging (truncate if too long)
        log_key = key[:15] + "..." if len(key) > 15 else key

        async def _operation():
            with PerformanceLogger(logger, f"redis_get_{log_key}"):
                result = await self.redis.get(key)
                # Log cache hit/miss statistics
                logger.debug(
                    "Redis GET operation",
                    extra={
                        "key": log_key,
                        "hit": result is not None,
                        "operation": "GET",
                    },
                )
                return result

        if self._circuit_breaker:

            async def _fallback(*args, **kwargs):
                logger.info(
                    "Redis fallback used for GET operation", extra={"key": log_key}
                )
                return None

            return await self._circuit_breaker.execute(
                self._execute_with_retry,
                cache_key=f"get_{log_key}",
                fallback=_fallback,
                operation=_operation,
            )
        else:
            return await self._execute_with_retry(_operation)

    async def set(self, key: str, value: str, expire: int = 3600) -> None:
        """set a key-value pair in redis with retry logic"""
        log_key = key[:15] + "..." if len(key) > 15 else key

        async def _operation():
            with PerformanceLogger(logger, f"redis_set_{log_key}"):
                await self.redis.set(key, value, ex=expire)
                logger.debug(
                    "Redis SET operation",
                    extra={"key": log_key, "expire_s": expire, "operation": "SET"},
                )

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(
                    "Redis SET operation failed",
                    extra={
                        "error": str(e),
                        "key": log_key,
                        "error_type": e.__class__.__name__,
                    },
                )
        else:
            await self._execute_with_retry(_operation)

    async def set_with_expiry(self, key: str, value: Any, expiry: int = 3600) -> None:
        """Set a value with expiration, serializing if necessary"""
        log_key = key[:15] + "..." if len(key) > 15 else key

        try:
            with PerformanceLogger(logger, f"redis_set_with_expiry_{log_key}"):
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                await self.set(key, value, expiry)
        except Exception as e:
            logger.error(
                "Error setting value with expiry",
                extra={
                    "error": str(e),
                    "key": log_key,
                    "error_type": e.__class__.__name__,
                    "value_type": type(value).__name__,
                },
            )

    async def delete(self, key: str) -> None:
        """delete a key from redis with retry logic"""
        log_key = key[:15] + "..." if len(key) > 15 else key

        async def _operation():
            with PerformanceLogger(logger, f"redis_delete_{log_key}"):
                result = await self.redis.delete(key)
                logger.debug(
                    "Redis DELETE operation",
                    extra={
                        "key": log_key,
                        "deleted": result > 0,
                        "operation": "DELETE",
                    },
                )

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(
                    "Redis DELETE operation failed",
                    extra={
                        "error": str(e),
                        "key": log_key,
                        "error_type": e.__class__.__name__,
                    },
                )
        else:
            await self._execute_with_retry(_operation)

    async def _execute_with_retry(self, operation, *args, **kwargs):
        """Execute Redis operation with retry logic"""
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
                        "Redis operation failed. Retrying...",
                        extra={
                            "error": str(e),
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "error_type": e.__class__.__name__,
                        },
                    )
                    await asyncio.sleep(retry_delay * (2**attempt))
                else:
                    logger.error(
                        "Redis operation failed after retries",
                        extra={
                            "error": str(e),
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "error_type": e.__class__.__name__,
                        },
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
        """Get article data by content hash"""
        log_hash = content_hash[:10] + "..." if len(content_hash) > 10 else content_hash
        add_correlation_id("content_hash", log_hash)

        async def _operation():
            with PerformanceLogger(logger, f"redis_get_article_{log_hash}"):
                data = await self.redis.get(f"article:{content_hash}")
                hit = data is not None
                logger.debug(
                    "Redis article lookup", extra={"content_hash": log_hash, "hit": hit}
                )
                return json.loads(data) if data else None

        if self._circuit_breaker:

            async def _fallback(*args, **kwargs):
                logger.info(
                    "Redis fallback used for article lookup",
                    extra={"content_hash": log_hash},
                )
                return None

            return await self._circuit_breaker.execute(
                self._execute_with_retry,
                cache_key=f"article_{log_hash}",
                fallback=_fallback,
                operation=_operation,
            )
        else:
            return await self._execute_with_retry(_operation)

    async def set_article(
        self, content_hash: str, article_data: Dict[str, Any], expire: int = 3600
    ) -> None:
        """Cache article data by content hash"""
        log_hash = content_hash[:10] + "..." if len(content_hash) > 10 else content_hash

        async def _operation():
            with PerformanceLogger(logger, f"redis_set_article_{log_hash}"):
                serialized = json.dumps(article_data)
                await self.redis.set(f"article:{content_hash}", serialized, ex=expire)
                logger.debug(
                    "Redis article cached",
                    extra={
                        "content_hash": log_hash,
                        "expire_s": expire,
                        "data_size_bytes": len(serialized),
                    },
                )

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(
                    "Redis set_article failed",
                    extra={
                        "error": str(e),
                        "content_hash": log_hash,
                        "error_type": e.__class__.__name__,
                    },
                )
        else:
            await self._execute_with_retry(_operation)

    async def add_hash(self, content_hash: str, expires: int = 86400) -> None:
        """Add a content hash marker to Redis"""
        log_hash = content_hash[:10] + "..." if len(content_hash) > 10 else content_hash

        async def _operation():
            with PerformanceLogger(logger, f"redis_add_hash_{log_hash}"):
                await self.redis.set(f"hash:{content_hash}", "1", ex=expires)
                logger.debug(
                    "Redis hash added",
                    extra={"content_hash": log_hash, "expire_s": expires},
                )

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(
                    "Redis add_hash failed",
                    extra={
                        "error": str(e),
                        "content_hash": log_hash,
                        "error_type": e.__class__.__name__,
                    },
                )
        else:
            await self._execute_with_retry(_operation)

    async def pipeline_add_hashes(
        self, content_hashes: List[str], expires: int = 86400
    ) -> None:
        """Add multiple content hashes in a single pipeline operation"""
        if not content_hashes:
            return

        # Create a shortened representation for logging
        hash_count = len(content_hashes)
        sample_hash = (
            content_hashes[0][:10] + "..."
            if len(content_hashes[0]) > 10
            else content_hashes[0]
        )

        add_correlation_id("hash_count", hash_count)

        async def _operation():
            with PerformanceLogger(logger, f"redis_pipeline_add_hashes_{hash_count}"):
                async with self.redis.pipeline(transaction=False) as pipe:
                    for content_hash in content_hashes:
                        pipe.set(f"hash:{content_hash}", "1", ex=expires)
                    await pipe.execute()

                logger.debug(
                    "Redis hash batch added",
                    extra={
                        "hash_count": hash_count,
                        "sample_hash": sample_hash,
                        "expire_s": expires,
                    },
                )

        if self._circuit_breaker:
            try:
                await self._circuit_breaker.execute(
                    self._execute_with_retry, operation=_operation
                )
            except Exception as e:
                logger.warning(
                    "Redis pipeline_add_hashes failed",
                    extra={
                        "error": str(e),
                        "hash_count": hash_count,
                        "error_type": e.__class__.__name__,
                    },
                )
        else:
            await self._execute_with_retry(_operation)

    async def pipeline_check_hashes(self, content_hashes: List[str]) -> Dict[str, bool]:
        """Check if multiple content hashes exist in Redis"""
        if not content_hashes:
            return {}

        hash_count = len(content_hashes)
        sample_hash = (
            content_hashes[0][:10] + "..."
            if len(content_hashes[0]) > 10
            else content_hashes[0]
        )

        add_correlation_id("hash_check_count", hash_count)

        async def _operation():
            if self.redis is None:
                await self.initialize()

            if self.redis is None:
                return {hash: False for hash in content_hashes}

            with PerformanceLogger(logger, f"redis_pipeline_check_hashes_{hash_count}"):
                result = {}
                async with self.redis.pipeline(transaction=False) as pipe:
                    for content_hash in content_hashes:
                        pipe.exists(f"hash:{content_hash}")
                    responses = await pipe.execute()
                    for i, content_hash in enumerate(content_hashes):
                        result[content_hash] = bool(responses[i])

                # Calculate hit rate for metrics
                hits = sum(1 for v in result.values() if v)
                hit_rate = hits / hash_count if hash_count > 0 else 0

                logger.debug(
                    "Redis hash batch check completed",
                    extra={
                        "hash_count": hash_count,
                        "sample_hash": sample_hash,
                        "hit_count": hits,
                        "hit_rate": round(hit_rate, 2),
                    },
                )

                return result

        async def _fallback(*args, **kwargs):
            logger.info(
                "Redis fallback used for pipeline_check_hashes",
                extra={"hash_count": hash_count},
            )
            return {hash: False for hash in content_hashes}

        if self._circuit_breaker:
            try:
                return await self._circuit_breaker.execute(
                    lambda: _operation(), fallback=_fallback
                )
            except Exception as e:
                logger.error(
                    "Redis batch check failed",
                    extra={
                        "error": str(e),
                        "hash_count": hash_count,
                        "error_type": e.__class__.__name__,
                    },
                )
                return {hash: False for hash in content_hashes}
        else:
            try:
                return await _operation()
            except Exception as e:
                logger.error(
                    "Redis batch check failed",
                    extra={
                        "error": str(e),
                        "hash_count": hash_count,
                        "error_type": e.__class__.__name__,
                    },
                )
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
            with PerformanceLogger(logger, f"redis_keys_{pattern}"):
                keys = await self.redis.keys(pattern)
                logger.debug(
                    "Redis keys operation",
                    extra={"pattern": pattern, "key_count": len(keys)},
                )
                return keys

        async def _fallback(*args, **kwargs):
            logger.info(
                "Redis fallback used for keys pattern", extra={"pattern": pattern}
            )
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
            with PerformanceLogger(logger, f"redis_scan_{match}"):
                all_keys = []
                cursor = 0
                iteration_count = 0

                while True:
                    iteration_count += 1
                    cursor, keys = await self.redis.scan(
                        cursor, match=match, count=count
                    )
                    all_keys.extend(keys)
                    if cursor == 0:
                        break

                logger.debug(
                    "Redis scan completed",
                    extra={
                        "pattern": match,
                        "iterations": iteration_count,
                        "key_count": len(all_keys),
                    },
                )
                return all_keys

        async def _fallback(*args, **kwargs):
            logger.info(
                "Redis fallback used for scan pattern", extra={"pattern": match}
            )
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
            with PerformanceLogger(logger, f"redis_delete_pattern_{pattern}"):
                keys_to_delete = await self.scan(match=pattern)
                if not keys_to_delete:
                    logger.debug(
                        "No keys found for deletion pattern", extra={"pattern": pattern}
                    )
                    return 0

                async def _operation():
                    deleted = await self.redis.delete(*keys_to_delete)
                    logger.debug(
                        "Redis keys deleted by pattern",
                        extra={
                            "pattern": pattern,
                            "deleted_count": deleted,
                            "requested_count": len(keys_to_delete),
                        },
                    )
                    return deleted

                if self._circuit_breaker:
                    try:
                        result = await self._circuit_breaker.execute(
                            self._execute_with_retry, operation=_operation
                        )
                    except Exception as e:
                        logger.error(
                            "Error deleting keys by pattern",
                            extra={
                                "error": str(e),
                                "pattern": pattern,
                                "error_type": e.__class__.__name__,
                                "key_count": len(keys_to_delete),
                            },
                        )
                        return 0
                else:
                    result = await self._execute_with_retry(_operation)
                    return result or 0
        except Exception as e:
            logger.error(
                "Error deleting keys by pattern",
                extra={
                    "error": str(e),
                    "pattern": pattern,
                    "error_type": e.__class__.__name__,
                },
            )
            return 0

    async def close(self) -> None:
        """Close Redis connection"""
        if self.redis is not None:
            try:
                with PerformanceLogger(logger, "redis_close"):
                    await self.redis.aclose()
                    logger.info("Redis connection closed")
            except Exception as e:
                logger.error(
                    "Error closing Redis connection",
                    extra={"error": str(e), "error_type": e.__class__.__name__},
                )

    async def invalidate_by_prefix(self, prefix: str) -> bool:
        """
        Invalidate all cache entries with a given prefix

        Args:
            prefix: Key prefix to invalidate

        Returns:
            True if successful, False otherwise
        """
        try:
            with PerformanceLogger(logger, f"redis_invalidate_prefix_{prefix}"):
                count = await self.delete_keys_by_pattern(f"{prefix}*")
                logger.info(
                    "Invalidated cache entries by prefix",
                    extra={"count": count, "prefix": prefix},
                )
                return True
        except Exception as e:
            logger.error(
                "Failed to invalidate cache with prefix",
                extra={
                    "error": str(e),
                    "prefix": prefix,
                    "error_type": e.__class__.__name__,
                },
            )
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
            with PerformanceLogger(logger, f"redis_publish_{channel}"):
                receivers = await self.redis.publish(channel, message)
                logger.debug(
                    "Redis message published",
                    extra={
                        "channel": channel,
                        "receivers": receivers,
                        "message_size": len(message),
                    },
                )
                return receivers

        if self._circuit_breaker:
            try:
                return (
                    await self._circuit_breaker.execute(
                        self._execute_with_retry, operation=_operation
                    )
                    or 0
                )
            except Exception as e:
                logger.warning(
                    "Redis publish failed",
                    extra={
                        "error": str(e),
                        "channel": channel,
                        "message_size": len(message),
                        "error_type": e.__class__.__name__,
                    },
                )
                return 0
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
            logger.warning(
                "Redis not available, cannot subscribe", extra={"channel": channel}
            )
            return

        try:
            with PerformanceLogger(logger, f"redis_subscribe_{channel}"):
                await self.redis.subscribe(channel)
                logger.info("Subscribed to Redis channel", extra={"channel": channel})
        except Exception as e:
            logger.error(
                "Failed to subscribe to Redis channel",
                extra={
                    "error": str(e),
                    "channel": channel,
                    "error_type": e.__class__.__name__,
                },
            )

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
            start_time = time.time()
            result = await self.redis.get_message(timeout=timeout)

            if result:
                duration_ms = (time.time() - start_time) * 1000
                logger.debug(
                    "Redis message received",
                    extra={
                        "channel": result.get("channel", "unknown"),
                        "duration_ms": round(duration_ms, 2),
                    },
                )

            return result
        except Exception as e:
            logger.error(
                "Failed to get message from Redis",
                extra={"error": str(e), "error_type": e.__class__.__name__},
            )
            return None
