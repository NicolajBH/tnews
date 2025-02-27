import json
import logging
import asyncio
import redis.asyncio as aioredis
from typing import Dict, List, Any
from src.core.config import settings


logger = logging.getLogger(__name__)


class RedisClient:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs) -> "RedisClient":
        if cls._instance is None:
            cls._instance = super(RedisClient, cls).__new__(cls)
            cls._instance._initialized = False

        return cls._instance

    def __init__(self, redis_url: str = settings.REDIS_URL) -> None:
        if not hasattr(self, "_initialized") or not self._initialized:
            self.redis = None
            self.redis_url = redis_url
            self.connection_retries = 0
            self._initialized = True

    async def initialize(self) -> None:
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
                        return
                    except (aioredis.RedisError, ConnectionError, OSError) as e:
                        self.connection_retries += 1
                        logger.warning(
                            f"Redis connection attempt {attempt + 1}/{max_retries} failed: {e}"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (2**attempt))
                        else:
                            logger.error(
                                f"Failed to connect to redis after {max_retries} attempts"
                            )
                            return

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
                    return None

    async def get_article(self, content_hash: str) -> Dict[str, Any] | None:
        async def _operation():
            data = await self.redis.get(f"article:{content_hash}")
            return json.loads(data) if data else None

        return await self._execute_with_retry(_operation)

    async def set_article(
        self, content_hash: str, article_data: Dict[str, Any], expire: int = 3600
    ) -> None:
        async def _operation():
            serialized = json.dumps(article_data)
            await self.redis.set(f"article:{content_hash}", serialized, ex=expire)

        await self._execute_with_retry(_operation)

    async def add_hash(self, content_hash: str, expires: int = 86400) -> None:
        async def _operation():
            await self.redis.set(f"hash:{content_hash}", "1", ex=expires)

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

        await self._execute_with_retry(_operation)

    async def pipeline_check_hashes(self, content_hashes: List[str]) -> Dict[str, bool]:
        if not content_hashes:
            return {}

        try:
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
        except Exception as e:
            logger.error(f"Redis batch check failed: {e}")
            return {hash: False for hash in content_hashes}

    async def close(self) -> None:
        if self.redis is not None:
            try:
                await self.redis.aclose()
                logger.debug("Redis connection returned to pool")
            except Exception as e:
                logger.error(f"Error with Redis connection: {e}")
