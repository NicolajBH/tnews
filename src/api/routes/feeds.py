import logging
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict
from sqlmodel import select, col
from datetime import datetime

from src.api.dependencies import get_date_filters
from src.constants import RSS_FEEDS
from src.core.exceptions import RSSFeedError
from src.models.db_models import (
    ArticleCategories,
    Articles,
    Sources,
    Categories,
    Users,
    FeedPreferences,
)
from src.db.database import SessionDep
from src.models.article import Article, ArticleQueryParameters, CategoryParams
from src.auth.dependencies import get_current_user


logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"], dependencies=[Depends(get_current_user)])


@router.get("/articles/latest", response_model=List[Article])
async def get_latest_articles(
    session: SessionDep,
    current_user: Users = Depends(get_current_user),
    params: ArticleQueryParameters = Depends(get_date_filters),
) -> List[Article]:
    query = (
        select(Articles)
        .join(ArticleCategories, Articles.id == ArticleCategories.article_id)
        .join(Categories, ArticleCategories.category_id == Categories.id)
        .join(FeedPreferences, Categories.id == FeedPreferences.feed_id)
        .where(FeedPreferences.user_id == current_user.id)
        .where(FeedPreferences.is_active == True)
        .order_by(col(Articles.pub_date).desc())
    )
    if params.start_date:
        query = query.where(Articles.pub_date >= params.start_date)
    if params.end_date:
        query = query.where(Articles.pub_date <= params.end_date)

    query = query.limit(20)
    results = session.exec(query).all()
    articles_to_return = []
    for result in results:
        # get source and feed_symbol from source id
        source = session.exec(
            select(Sources).where(Sources.id == result.source_id)
        ).first()
        if source is None:
            logger.error(f"No sources with ID {result.source_id}")
            continue
        articles_to_return.append(
            Article(
                title=result.title,
                pubDate=result.pub_date_raw,
                source=source.feed_symbol,
                formatted_time=datetime.strftime(result.pub_date, "%H:%M"),
            ),
        )
    return articles_to_return


@router.get("/categories")
async def get_categories() -> Dict[str, List[str]]:
    try:
        return {
            source: list(cats["feeds"].keys()) for source, cats in RSS_FEEDS.items()
        }
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching categories",
        )


@router.get("/sources")
async def get_sources() -> Dict[str, List[str]]:
    try:
        return {"sources": list(RSS_FEEDS.keys())}
    except Exception as e:
        logger.error(f"Error fetching sources: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching sources",
        )


@router.post("/subscribe/{category_id}")
async def subscribe_to_feed(
    category_id: int,
    session: SessionDep,
    current_user: Users = Depends(get_current_user),
):
    category = session.get(Categories, category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
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
    return {"status": "subscribed", "category_id": category_id}


@router.post("/unsubscribe/{category_id}")
async def unsubscribe_from_feed(
    category_id: int,
    session: SessionDep,
    current_user: Users = Depends(get_current_user),
):
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

    preference.is_active = False
    session.add(preference)
    session.commit()
    return {"status": "unsubscribed", "category_id": category_id}


@router.get("/my")
async def get_my_feeds(
    session: SessionDep, current_user: Users = Depends(get_current_user)
):
    results = session.exec(
        select(FeedPreferences, Categories)
        .join(Categories, FeedPreferences.feed_id == Categories.id)
        .where(FeedPreferences.user_id == current_user.id)
        .where(FeedPreferences.is_active == True)
    ).all()

    return [
        {
            "category_id": cat.id,
            "name": cat.name,
            "feed_url": cat.feed_url,
            "subscribed_at": pref.created_at,
        }
        for pref, cat in results
    ]
