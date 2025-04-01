from fastapi import Depends
from typing import Annotated

from sqlmodel import Session

from src.clients.redis import RedisClient
from src.db.database import get_session
from src.api.dependencies import get_redis_client
from src.repositories.article_repository import ArticleRepository
from src.services.article_service import ArticleService
from src.services.cache_service import CacheService

SessionDep = Annotated[Session, Depends(get_session)]
RedisDep = Annotated[RedisClient, Depends(get_redis_client)]


def get_article_repository(session: Session) -> ArticleRepository:
    return ArticleRepository(session)


ArticleRepositoryDep = Annotated[ArticleRepository, Depends(get_article_repository)]


def get_cache_service(redis: RedisDep) -> CacheService:
    return CacheService(redis)


def get_article_service(
    repo: ArticleRepositoryDep,
    cache: CacheService = Depends(get_cache_service),
) -> ArticleService:
    return ArticleService(repo, cache)


CacheServiceDep = Annotated[CacheService, Depends(get_cache_service)]
ArticleServiceDep = Annotated[ArticleService, Depends(get_article_service)]
