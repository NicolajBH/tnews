from inspect import CO_ITERABLE_COROUTINE
from celery import Celery
from src.core.config import settings

celery_app = Celery(
    "news_reader",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.beat_schedule = {
    "fetch-news-every-5-minutes": {
        "task": "src.tasks.feed_tasks.fetch_all_feeds",
        "schedule": 300.0,
    }
}
