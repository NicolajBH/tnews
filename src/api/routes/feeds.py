import meilisearch

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from typing import Any, List, Dict
from sqlmodel import Session, select

# Dependencies
from src.api.dependencies import get_date_filters, get_redis_client
from src.clients.redis import RedisClient
from src.db.database import get_session
from src.auth.dependencies import get_current_user

# Models
from src.models.db_models import (
    ArticleFeeds,
    Articles,
    Sources,
    Feeds,
    Users,
    FeedPreferences,
)
from src.models.article import Article, ArticleQueryParameters
from src.models.pagination import PaginatedResponse, PaginationInfo

# Constants and exceptions
from src.constants import RSS_FEEDS
from src.core.logging import LogContext

# Services and repositories
from src.repositories.article_repository import ArticleRepository
from src.services.article_service import ArticleService
from src.services.cache_service import CacheService
from src.utils.etag import generate_etag

logger = LogContext(__name__)

router = APIRouter(tags=["auth"], dependencies=[Depends(get_current_user)])


@router.get("/articles/latest", response_model=PaginatedResponse[Article])
async def get_latest_articles(
    request: Request,
    response: Response,
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

        # create unique resource key for this request
        cursor_part = params.cursor or "first"
        date_range = "all"
        if params.start_date or params.end_date:
            start_str = params.start_date.isoformat() if params.start_date else "start"
            end_str = params.end_date.isoformat() if params.end_date else "end"
            date_range = f"{start_str}_to_{end_str}"

        resource_key = f"articles:user:{current_user.id}:page:{cursor_part}:limit:{params.limit}:range:{date_range}"

        # check for etag
        etag = await cache_service.get_etag(resource_key)

        is_conditional = (
            hasattr(request.state, "is_conditional") and request.state.is_conditional
        )
        client_etag = getattr(request.state, "client_etag", None)

        # get articles and pagination info
        articles, pagination_info = await article_service.get_paginated_articles(
            user_id=current_user.id,
            cursor=params.cursor,
            limit=params.limit,
            start_date=params.start_date,
            end_date=params.end_date,
        )

        # create response data
        response_data = PaginatedResponse(items=articles, pagination=pagination_info)

        # generate etag if we don't have one yet
        if not etag:
            etag = generate_etag(
                {
                    "articles": [article.model_dump() for article in articles],
                    "pagination": pagination_info.model_dump(),
                }
            )
            await cache_service.set_etag(resource_key, etag)

        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "private, max-age=60"

        return response_data

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(
            "Error fetching articles",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching articles",
        )


@router.get("/feeds")
async def get_feeds(
    request: Request,
    response: Response,
    redis: RedisClient = Depends(get_redis_client),
) -> Dict[str, Dict[str, Any]]:
    try:
        cache_service = CacheService(redis)
        resource_key = "categories"

        etag, cached_data = await cache_service.get_etag_with_data(resource_key)

        if cached_data:
            if etag:
                response.headers["ETag"] = etag
            response.headers["Cache-Control"] = "public, max-age=3600"
            return cached_data

        available_feeds = {"sources": {}}
        for source_name, config in RSS_FEEDS.items():
            available_feeds["sources"][source_name] = {
                "display_name": config["display_name"],
                "feeds": [
                    {
                        "id": f"{source_name}:{feed_name}",
                        "feed_name": feed_name,
                        "display_name": feed_details["display_name"],
                    }
                    for feed_name, feed_details in config["feeds"].items()
                ],
            }

        new_etag, _ = await cache_service.set_etag_with_data(
            resource_key, available_feeds, expire=3600
        )
        response.headers["ETag"] = new_etag
        response.headers["Cache-Control"] = "public, max-age=3600"

        return available_feeds

    except Exception as e:
        logger.error(
            "Error fetching feeds",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching feeds",
        )


@router.get("/sources")
async def get_sources(
    request: Request,
    response: Response,
    redis: RedisClient = Depends(get_redis_client),
) -> Dict[str, List[str]]:
    try:
        cache_service = CacheService(redis)
        resource_key = "sources"

        etag, cached_data = await cache_service.get_etag_with_data(resource_key)
        if cached_data:
            if etag:
                response.headers["ETag"] = etag
            response.headers["Cache-Control"] = "public, max-age=3600"
            return cached_data

        sources = {"sources": list(RSS_FEEDS.keys())}
        new_etag, _ = await cache_service.set_etag_with_data(
            resource_key, sources, expire=3600
        )
        response.headers["ETag"] = new_etag
        response.headers["Cache-Control"] = "public, max-age=3600"

        return sources
    except Exception as e:
        logger.error(
            "Error fetching sources",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching sources",
        )


@router.post("/subscribe/{source_name}/{feed_name}")
async def subscribe_to_feed(
    source_name: str,
    feed_name: str,
    session: Session = Depends(get_session),
    current_user: Users = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis_client),
):
    """
    Subscribe to a feed
    """
    try:
        # initialize services
        cache_service = CacheService(redis)
        article_repository = ArticleRepository(session)
        article_service = ArticleService(article_repository, cache_service)

        # check if feed exists
        feed = session.exec(
            select(Feeds).where(
                (Feeds.source_name == source_name) & (Feeds.name == feed_name)
            )
        ).first()

        if not feed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
            )

        existing = session.exec(
            select(FeedPreferences)
            .where(FeedPreferences.user_id == current_user.id)
            .where(FeedPreferences.feed_source_name == source_name)
            .where(FeedPreferences.feed_name == feed_name)
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
                feed_source_name=source_name,
                feed_name=feed_name,
            )
            session.add(new_preference)

        session.commit()

        resource_key = f"user:{current_user.id}:feeds"
        await cache_service.invalidate(resource_key)
        await cache_service.invalidate_etag(resource_key)

        await cache_service.invalidate_by_prefix(f"articles:user:{current_user.id}")
        await cache_service.invalidate_by_prefix(
            f"etag:articles:user:{current_user.id}"
        )

        return {
            "status": "subscribed",
            "source_name": source_name,
            "feed_name": feed_name,
            "display_name": feed.display_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error subscribing to feed",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while subscribing to the feed",
        )


@router.post("/unsubscribe/{source_name}/{feed_name}")
async def unsubscribe_from_feed(
    source_name: str,
    feed_name: str,
    session: Session = Depends(get_session),
    current_user: Users = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis_client),
):
    """
    Unsubscribe from a feed
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
            .where(FeedPreferences.feed_source_name == source_name)
            .where(FeedPreferences.feed_name == feed_name)
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

        # get feed name for response
        feed = session.exec(
            select(Feeds).where(
                (Feeds.source_name == source_name) & (Feeds.name == feed_name)
            )
        ).first()
        display_name = feed.display_name if feed else "Unknown"

        # invalidate caches
        resource_key = f"user:{current_user.id}:feeds"
        await cache_service.invalidate(resource_key)
        await cache_service.invalidate_etag(resource_key)

        await cache_service.invalidate_by_prefix(f"articles:user:{current_user.id}")
        await cache_service.invalidate_by_prefix(
            f"etag:articles:user:{current_user.id}"
        )

        return {
            "status": "unsubscribed",
            "source_name": source_name,
            "feed_name": feed_name,
            "display_name": display_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error unsubscribing from feed",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while unsubscribing from the feed",
        )


@router.get("/my")
async def get_my_feeds(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    current_user: Users = Depends(get_current_user),
    redis: RedisClient = Depends(get_redis_client),
):
    try:
        cache_service = CacheService(redis)
        resource_key = f"user:{current_user.id}:feeds"

        etag, cached_data = await cache_service.get_etag_with_data(resource_key)

        if cached_data:
            if etag:
                response.headers["ETag"] = etag
            response.headers["Cache-Control"] = "private, max-age=300"
            return cached_data

        results = session.exec(
            select(FeedPreferences, Feeds)
            .join(
                Feeds,
                (FeedPreferences.feed_source_name == Feeds.source_name)
                & (FeedPreferences.feed_name == Feeds.name),
            )
            .where(FeedPreferences.user_id == current_user.id)
            .where(FeedPreferences.is_active == True)
        ).all()

        feeds = {
            f"{feed.source_name}:{feed.name}": {
                "source_name": feed.source_name,
                "feed_name": feed.name,
                "display_name": feed.display_name,
                "feed_url": feed.feed_url,
                "subscribed_at": pref.created_at.isoformat()
                if hasattr(pref.created_at, "isoformat")
                else pref.created_at,
            }
            for pref, feed in results
        }

        new_etag, _ = await cache_service.set_etag_with_data(
            resource_key, feeds, expire=300
        )

        response.headers["ETag"] = new_etag
        response.headers["Cache-Control"] = "private, max-age=300"

        return feeds
    except Exception as e:
        logger.error(
            "Error fetching feeds",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching feeds",
        )


@router.get("/articles/search", response_model=PaginatedResponse[Article])
async def search_articles(
    q: str,
    date_from: str | None = None,
    date_to: str | None = None,
    source: str | None = None,
    feed: str | None = None,
    limit: int = 20,
    offset: int = 0,
    current_user: Users = Depends(get_current_user),
) -> PaginatedResponse[Article]:
    try:
        client = meilisearch.Client("http://localhost:7700")
        index = client.index("articles")
        search_params = {
            "limit": limit,
            "offset": offset,
        }

        # Add filters if provided
        filters = []
        if date_from:
            filters.append(f"pub_date >= '{date_from}'")
        if date_to:
            filters.append(f"pub_date <= '{date_to}'")
        if source:
            filters.append(f"source_name = '{source}'")
        if feed:
            filters.append(f"feed_symbol = '{feed}'")

        if filters:
            search_params["filter"] = " AND ".join(filters)

        # Perform search
        results = index.search(q, search_params)

        # Convert Meilisearch results to your Article model
        articles = [Article(**hit) for hit in results["hits"]]

        # Create pagination info
        pagination_info = PaginationInfo(
            has_more=offset + limit < results["estimatedTotalHits"],
            next_cursor=str(offset + limit)
            if offset + limit < results["estimatedTotalHits"]
            else None,
        )

        return PaginatedResponse(items=articles, pagination=pagination_info)

    except Exception as e:
        logger.error(
            "Error searching articles",
            extra={"error": str(e), "error_type": e.__class__.__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while searching articles",
        )
