from celery import Celery
from src.core.config import settings

celery_app = Celery(
    "news_reader",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["src.tasks.feed_tasks"],
)

celery_app.conf.update(
    # task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # worker settings
    worker_prefetch_multiplier=settings.PREFETCH_MULTIPLIER,
    worker_max_tasks_per_child=settings.CELERY_WORKERS_MAX_TASKS_PER_CHILD,
    worker_concurrency=settings.WORKER_CONCURRENCY,
    task_time_limit=settings.CELERY_TASK_TIMEOUT,
    beat_max_loop_interval=settings.CELERY_BEAT_MAX_LOOP_INTERVAL,
    # result backend settings
    result_expires=settings.CELERY_RESULT_EXPIRES,
    # rate limiting
    task_annotations={"src.tasks.feed_tasks.fetch_feed_chunk": {"rate_limit": "50/m"}},
    # beat schedule
    beat_schedule={
        "fetch-news-every-15-minutes": {
            "task": "src.tasks.feed_tasks.fetch_all_feeds",
            "schedule": settings.CELERY_BEAT_SCHEDULE_INTERVAL,
        }
    },
    # broker settings
    broker_connection_timeout=settings.CELERY_BROKER_CONNECTION_TIMEOUT,
    broker_connection_retry=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=settings.CELERY_BROKER_CONNECTION_MAX_RETRIES,
    broker_heartbeat=10,
    # task excecution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_eager_propagates=True,
    task_create_missing_queues=True,
    task_default_priority=9,
    task_default_queue="feeds",
    task_queues={"feeds": {"exchange": "feeds", "routing_key": "feeds"}},
    # optimization settings
    task_compression=None,
    worker_lost_wait=30,
    result_compression=None,
    # disable
    task_track_started=False,
    task_send_sent_event=False,
    worker_direct=False,
    worker_disable_rate_limits=True,
    # redis settings
    redis_compression=True,
)
