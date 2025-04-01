import logging
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict
from sqlmodel import Session, select, col
from datetime import datetime
import json

# Dependencies
from src.api.dependencies import get_date_filters, get_redis_client
from src.clients.redis import RedisClient
from src.db.database import get_session
from src.auth.dependencies import get_current_user

# Models
from src.models.db_models import (
    ArticleCategories,
    Articles,
    Sources,
    Categories,
    Users,
    FeedPreferences,
)
from src.models.article import Article, ArticleQueryParameters
from src.models.pagination import PaginatedResponse, PaginationInfo

# Constants and exceptions
from src.constants import RSS_FEEDS
from src.core.exceptions import RSSFeedError

# Services and repositories
from src.repositories.article_repository import ArticleRepository
from src.services.article_service import ArticleService
from src.services.cache_service import CacheService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"], dependencies=[Depends(get_current_user)])


@router.get("/articles/latest", response_model=PaginatedResponse[Article])
async def get_latest_articles(
    session: Session = Depends(get_session),
    current_user: Users = Depends(get_current_user),
    params: ArticleQueryParameters = Depends(get_date_filters),
    redis: RedisClient = Depends(get_redis_client),
) -> PaginatedResponse[Article]:
    try:
        # initialize services
        cache_service = CacheService(redis)
        article_repository = ArticleRepository(session)
        article_service = ArticleService(article_repository, cache_service)

        articles, pagination_info = await article_service.get_paginated_articles(
            user_id=current_user.id,
            cursor=params.cursor,
            limit=params.limit,
            start_date=params.start_date,
            end_date=params.end_date,
        )

        return PaginatedResponse(
            data=articles,
            pagination=pagination_info,
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching articles: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occured while fetching articles",
        )


@router.get("/categories")
async def get_categories(
    redis: RedisClient = Depends(get_redis_client),
) -> Dict[str, List[str]]:
    try:
        cached = await redis.get("categories")
        if cached:
            return json.loads(cached)

        categories = {
            source: list(cats["feeds"].keys()) for source, cats in RSS_FEEDS.items()
        }

        await redis.set("categories", json.dumps(categories), expire=3600)

        return categories
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching categories",
        )


@router.get("/sources")
async def get_sources(
    redis: RedisClient = Depends(get_redis_client),
) -> Dict[str, List[str]]:
    try:
        cached = await redis.get("sources")
        if cached:
            return json.loads(cached)

        sources = {"sources": list(RSS_FEEDS.keys())}
        await redis.set("sources", json.dumps(sources), expire=3600)
        return sources
    except Exception as e:
        logger.error(f"Error fetching sources: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching sources",
        )


@router.post("/subscribe/{category_id}")
async def subscribe_to_feed(
    category_id: int,
    session: Session = Depends(get_session),
    current_user: Users = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis_client),
):
    """
    Subscribe to a feed category
    """
    try:
        # initialize services
        cache_service = CacheService(redis)
        article_repository = ArticleRepository(session)
        article_service = ArticleService(article_repository, cache_service)

        # check if category exists
        category = session.get(Categories, category_id)
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
            )

        existing = session.exec(
            select(FeedPreferences)
            .where(FeedPreferences.user_id == current_user.id)
            .where(FeedPreferences.feed_id == category_id)
        ).first()

        if existing:
            if existing.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Already subscribed to this feed",
                )
            existing.is_active = True
            session.add(existing)
        else:
            new_preference = FeedPreferences(
                user_id=current_user.id,
                feed_id=category_id,
            )
            session.add(new_preference)

        session.commit()

        await cache_service.invalidate_user_feeds(current_user.id)
        await article_service.invalidate_user_articles_cache(current_user.id)

        return {
            "status": "subscribed",
            "category_id": category_id,
            "category_name": category.name,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error subscribing to feed: {str(e)}", exc_info=True)
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occured while subscribing to the feed",
        )


@router.post("/unsubscribe/{category_id}")
async def unsubscribe_from_feed(
    category_id: int,
    session: Session = Depends(get_session),
    current_user: Users = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis_client),
):
    """
    Unsubscribe from a feed category
    """
    try:
        # initialize services
        cache_service = CacheService(redis)
        article_repository = ArticleRepository(session)
        article_service = ArticleService(article_repository, cache_service)

        # find subscription
        preference = session.exec(
            select(FeedPreferences)
            .where(FeedPreferences.user_id == current_user.id)
            .where(FeedPreferences.feed_id == category_id)
            .where(FeedPreferences.is_active == True)
        ).first()

        if not preference:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not subscribed to this feed",
            )

        # update sub status
        preference.is_active = False
        session.add(preference)
        session.commit()

        # get category name for response
        category = session.get(Categories, category_id)
        category_name = category.name if category else "Unknown"

        # invalidate caches
        await cache_service.invalidate_user_feeds(current_user.id)
        await article_service.invalidate_user_articles_cache(current_user.id)

        return {
            "status": "unsubscribed",
            "category_id": category_id,
            "category_name": category_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsubscribing from feed: {str(e)}", exc_info=True)
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occured while unsubscribing from the feed",
        )


@router.get("/my")
async def get_my_feeds(
    session: Session = Depends(get_session),
    current_user: Users = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis_client),
):
    cache_key = f"user:{current_user.id}:feeds"

    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    results = session.exec(
        select(FeedPreferences, Categories)
        .join(Categories, FeedPreferences.feed_id == Categories.id)
        .where(FeedPreferences.user_id == current_user.id)
        .where(FeedPreferences.is_active == True)
    ).all()

    feeds = [
        {
            "category_id": cat.id,
            "name": cat.name,
            "feed_url": cat.feed_url,
            "subscribed_at": pref.created_at.isoformat()
            if hasattr(pref.created_at, "isoformat")
            else pref.created_at,
        }
        for pref, cat in results
    ]

    await redis.set(cache_key, json.dumps(feeds), expire=300)

    return feeds
