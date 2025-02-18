import logging
from fastapi import APIRouter, Depends
from typing import List
from sqlmodel import select, col
from email.utils import parsedate_to_datetime
from src.api.dependencies import get_date_filters
from src.models.db_models import Articles, Sources
from src.db.database import SessionDep
from src.models.article import Article, ArticleQueryParameters

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
async def get_category_articles() -> None:
    pass


@router.get("/categories")
async def get_categories() -> None:
    pass


@router.get("/sources")
async def get_sources() -> None:
    pass
