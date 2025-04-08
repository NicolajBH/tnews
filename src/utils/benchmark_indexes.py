import time
import statistics
from sqlmodel import Session, select
from datetime import datetime, timedelta

from src.db.database import engine
from src.models.db_models import (
    Articles,
    ArticleCategories,
    Categories,
    FeedPreferences,
    Users,
)


def benchmark_query(session, query_func, name, iterations=5):
    """Run a query multiple times and record execution time"""
    times = []
    for i in range(iterations):
        start = time.time()
        result = query_func(session)
        end = time.time()
        times.append(end - start)
        print(
            f"{name} - Run {i + 1}: {times[-1]:.6f} seconds - Result count: {len(result) if hasattr(result, '__len__') else 1}"
        )

    avg_time = statistics.mean(times)
    print(f"{name} - Average time: {avg_time:.6f} seconds\n")


def get_user_articles(session, user_id=1, limit=20):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    query = (
        select(Articles)
        .join(ArticleCategories, Articles.id == ArticleCategories.article_id)
        .join(Categories, ArticleCategories.category_id == Categories.id)
        .join(FeedPreferences, Categories.id == FeedPreferences.feed_id)
        .where(FeedPreferences.user_id == user_id)
        .where(FeedPreferences.is_active == True)
        .where(Articles.pub_date >= start_date)
        .where(Articles.pub_date <= end_date)
        .order_by(Articles.pub_date.desc(), Articles.id.desc())
        .limit(limit)
    )
    return session.exec(query).all()


def get_user_feeds(session, user_id=1):
    query = (
        select(FeedPreferences, Categories)
        .join(Categories, FeedPreferences.feed_id == Categories.id)
        .where(FeedPreferences.user_id == user_id)
        .where(FeedPreferences.is_active == True)
    )
    return session.exec(query).all()


def run_benchmarks():
    """
    Run all benchmarks
    """

    with Session(engine) as session:
        print("Running benchmark tests...")
        print("-" * 50)

        benchmark_query(session, lambda s: get_user_articles(s), "Get User Articles")

        benchmark_query(session, lambda s: get_user_feeds(s), "Get User Feeds")

        session.close()


if __name__ == "__main__":
    run_benchmarks()
