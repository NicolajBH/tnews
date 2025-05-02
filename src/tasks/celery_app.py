from celery import Celery
from src.core.config import settings
from src.core.logging import setup_logging, LogContext
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import task_prerun
from src.core.logging import add_correlation_id, reset_correlation_context

# Initialize logging
setup_logging()

# Get a logger for Celery's internal logs
celery_logger = LogContext("celery")


# Set up time-based rotation for Celery logs
def setup_celery_logging():
    # Create celery logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(settings.LOG_FILE), "celery_logs")
    os.makedirs(log_dir, exist_ok=True)

    celery_log_file = os.path.join(log_dir, "celery.log")

    # Get the custom formatter from the root logger
    root_logger = logging.getLogger()
    formatter = None
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            formatter = handler.formatter
            break

    if not formatter:
        # Create a basic formatter if we couldn't find the custom one
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    # Create a timed rotating file handler (daily rotation, keep 30 days of logs)
    handler = TimedRotatingFileHandler(
        celery_log_file,
        when="midnight",
        interval=1,  # Daily rotation
        backupCount=30,  # Keep 30 days of logs
    )
    handler.setFormatter(formatter)
    handler.setLevel(settings.LOG_LEVEL)
    handler.suffix = "%Y-%m-%d"  # Use date as suffix for rotated files

    # Add the handler to Celery loggers
    for logger_name in ["celery", "celery.task", "celery.worker", "celery.beat"]:
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)
        logger.propagate = False  # Prevent duplicate logs

    return celery_log_file


# Set up the rotating log file
celery_log_file = setup_celery_logging()

# Create Celery app
celery_app = Celery(
    "news_reader",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["src.tasks.feed_tasks"],
)

# Configure Celery
celery_app.conf.update(
    # Your existing configuration...
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
    # Add Celery logging settings
    worker_hijack_root_logger=False,  # Don't hijack root logger
    worker_log_color=False,  # Disable colors for file logging
    worker_redirect_stdouts=True,  # Redirect stdout/stderr to logger
    worker_redirect_stdouts_level="INFO",  # Level for stdout/stderr logs
)

# Log the config
celery_logger.info(
    "Celery logging configured",
    extra={"log_file": celery_log_file, "rotation": "daily", "backup_count": 30},
)


# Connect to Celery's logging system
@celery_setup_logging.connect
def on_celery_setup_logging(**kwargs):
    """Prevent Celery from setting up its own logging"""
    return True  # Returning True prevents Celery from setting up logging


# Add signal handlers for additional task context/correlation IDs
@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    """Set up correlation context for tasks"""
    reset_correlation_context()  # Reset to avoid leaking context between tasks
    add_correlation_id("task_id", task_id)
    add_correlation_id("task_name", task.name)
    add_correlation_id(
        "operation", task.name.split(".")[-1]
    )  # Extract operation name from task name

    # Add additional context information if available
    if (
        kwargs.get("request")
        and hasattr(kwargs["request"], "parent_id")
        and kwargs["request"].parent_id
    ):
        add_correlation_id("parent_task_id", kwargs["request"].parent_id)
