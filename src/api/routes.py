import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict
from sqlmodel import select, col
from email.utils import parsedate_to_datetime
from src.api.dependencies import get_date_filters
from src.constants import RSS_FEEDS
from src.core.exceptions import RSSFeedError
from src.models.db_models import Articles, Sources, Categories
from src.db.database import SessionDep
from src.models.article import Article, ArticleQueryParameters, CategoryParams

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/articles/latest", response_model=List[Article])
async def get_latest_articles(
    session: SessionDep, params: ArticleQueryParameters = Depends(get_date_filters)
) -> List[Article]:
    query = select(Articles).order_by(col(Articles.pub_date).desc())

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
                formatted_time=parsedate_to_datetime(result.pub_date_raw).strftime(
                    "%H:%M"
                ),
            )
        )
    return articles_to_return


@router.get("/sources/{source}/categories/{category}", response_model=List[Article])
async def get_category_articles(
    session: SessionDep, params: CategoryParams = Depends()
) -> List[Article]:
    try:
        if params.source not in RSS_FEEDS:
            raise HTTPException(status_code=404, detail="Source not found")
        if params.category not in RSS_FEEDS[params.source]["feeds"]:
            raise HTTPException(status_code=404, detail="Feed not found")
        statement = (
            select(Articles, Sources, Categories)
            .select_from(Articles)
            .join(Sources, Articles.source_id == Sources.id)
            .join(Categories, Articles.category_id == Categories.id)
            .where(Sources.name == params.source)
            .where(Categories.name == params.category)
        )
        statement = statement.limit(20)

        results = session.exec(statement).all()
        articles_to_return = []
        for article, sources, _ in results:
            articles_to_return.append(
                Article(
                    title=article.title,
                    pubDate=article.pub_date_raw,
                    source=sources.feed_symbol,
                    formatted_time=parsedate_to_datetime(article.pub_date_raw).strftime(
                        "%H:%M"
                    ),
                )
            )
        return articles_to_return

    except Exception as e:
        logger.error(
            f"Error fetching articles for {params.source}/{params.category}: {str(e)}",
            exc_info=True,
        )
        raise RSSFeedError(
            detail="Failed to fetch articles",
            source=params.source,
            category=params.category,
        )


@router.get("/categories")
async def get_categories() -> Dict[str, List[str]]:
    try:
        return {
            source: list(cats["feeds"].keys()) for source, cats in RSS_FEEDS.items()
        }
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching categories")


@router.get("/sources")
async def get_sources() -> Dict[str, List[str]]:
    try:
        return {"sources": list(RSS_FEEDS.keys())}
    except Exception as e:
        logger.error(f"Error fetching sources: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching sources")
