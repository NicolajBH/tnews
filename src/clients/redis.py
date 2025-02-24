import json
import aioredis


class RedisClient:
    def __init__(self, redis_url: str = "redis://localhost") -> None:
        self.redis = aioredis.from_url(redis_url, decode_responses=True)

    async def get_article(self, content_hash: str) -> dict | None:
        data = await self.redis.get(f"article:{content_hash}")
        return json.loads(data) if data else None

    async def set_article(
        self, content_hash: str, article_data: dict, expire: int = 3600
    ):
        await self.redis.set(
            f"article:{content_hash}", json.dumps(article_data), ex=expire
        )

    async def exists_hash(self, content_hash: str) -> bool:
        return await self.redis.exists(f"article:{content_hash}")

    async def add_hash(self, content_hash: str):
        await self.redis.set(f"hash:{content_hash}", "1", ex=86400)
