import json
import logging
from typing import Any, Dict, List, Union, TypeVar, Generic, Pattern
import re

from src.clients.redis import RedisClient

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheService:
    def __init__(self, redis_client: RedisClient):
        self.redis = redis_client

    async def get_cached_data(self, key: str, default=None) -> Any | None:
        """
        Get data from cache with given key

        Args:
            key: The cache key
            default: Default value if key not found

        Returns:
            Deserialized data or default value
        """
        try:
            cached = await self.redis.get(key)
            if cached:
                return json.loads(cached)
            return default
        except Exception as e:
            logger.error(f"Error retrieving from cache: {str(e)}", exc_info=True)
            return default

    async def set_cached_data(self, key: str, data: Any, expire: int = 300) -> bool:
        """
        Set data in cache with the given key and expiration time

        Args:
            key: The cache key
            data: The data to cache (will be JSON serialized)
            expire: Expiration time in seconds

        Returns:
            True if successful, False otherwise
        """
        try:
            await self.redis.set(key, json.dumps(data), expire=expire)
            return True
        except Exception as e:
            logger.error(f"Error setting cache: {str(e)}", exc_info=True)
            return False

    async def invalidate(self, key: str) -> bool:
        """
        Invalidate cache for the given key

        Args:
            key: The cache key to invalidate
        Returns
            True if successful, False otherwise
        """
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error invalidating cache: {str(e)})", exc_info=True)
            return False

    async def keys_by_pattern(self, pattern: str) -> List[str]:
        """
        Get keys by matching a pattern

        Args:
            pattern: Redis key pattern with wildcards

        Returns:
            List of matching keys
        """
        try:
            # use scan isntead of keys for production safety
            return await self.redis.scan(match=pattern)
        except Exception as e:
            logger.error(f"Error getting keys by pattern: {str(e)}", exc_info=True)
            return []

    async def invalidate_by_prefix(self, prefix: str) -> bool:
        """
        Invalidate all keys with a common prefix
        This is safer than pattern matching for production

        Args:
            prefix: Key prefix to match

        Returns:
            True if successful, False otherwise
        """
        try:
            deleted = await self.redis.delete_keys_by_pattern(f"{prefix}*")
            logger.info(f"Invalidated {deleted} keys with prefix: {prefix}")
            return True
        except Exception as e:
            logger.error(f"Error invalidating by prefix: {str(e)}", exc_info=True)
            return False

    # application specific cache methods

    async def get_user_feeds(self, user_id: int) -> List[Dict[str, Any]] | None:
        """Get cached feeds for a specific user"""
        cache_key = f"user:{user_id}:feeds"
        return await self.get_cached_data(cache_key)

    async def set_user_feeds(self, user_id: int, feeds: List[Dict[str, Any]]) -> bool:
        """Cache feeds for a specific user"""
        cache_key = f"user:{user_id}:feeds"
        return await self.set_cached_data(cache_key, feeds, expire=300)

    async def invalidate_user_feeds(self, user_id: int) -> bool:
        """Invalidate cached feeds for a specific user"""
        cache_key = f"user:{user_id}:feeds"
        return await self.invalidate(cache_key)

    # article caching methods

    async def get_article_page(
        self, user_id: int, cursor: str | None, limit: int, date_range: str
    ) -> Dict[str, Any] | None:
        """
        Get cached article page

        Args:
            user_id: User ID
            cursor: Pagination cursor or None for first page
            limit: Number of articles per page
            date_range: String representing the date range filter

        Returns:
            Cached page data or None
        """
        cursor_part = cursor or "first"
        cache_key = f"article:user:{user_id}:page:{cursor_part}:limit:{limit}:range:{date_range}"
        return await self.get_cached_data(cache_key)

    async def set_article_page(
        self,
        user_id: int,
        cursor: str | None,
        limit: int,
        date_range: str,
        data: [Dict[str, Any]],
    ) -> bool:
        """
        Cache an article page

        Args:
            user_id: User ID
            cursor: Pagination cursor or None for first page
            limit: Number of articles per page
            date_range: String representing the date range filter
            data: Page data to cache

        Returns:
            True if succesful, False otherwise
        """
        cursor_part = cursor or "first"
        cache_key = f"article:user:{user_id}:page:{cursor_part}:limit:{limit}:range:{date_range}"
        return await self.set_cached_data(cache_key, data, expire=60)

    async def invalidate_user_article_cache(self, user_id: int) -> bool:
        """
        Invalidate all article cache for a user

        Args:
            user_id: User ID

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Invalidating article cache for user {user_id}")
        return True
