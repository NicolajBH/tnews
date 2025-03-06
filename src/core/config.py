from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "RSS News API"

    # Security settings
    SECRET_KEY: str = "acc39f5ae7a709199234a23b97cc1dc3310e074e2ec182eb141b92f0b523f507"
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30

    # Redis settings
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600
    REDIS_HASH_TTL: int = 86400

    # Celery settings
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_TIMEOUT: int = 180
    CELERY_RESULT_EXPIRES: int = 1800
    CELERY_BROKER_CONNECTION_TIMEOUT: int = 5
    CELERY_BROKER_CONNECTION_MAX_RETRIES: int = 3
    CELERY_TASK_MAX_RETRIES: int = 3
    CELERY_BEAT_SCHEDULE_INTERVAL: int = 300
    CELERY_WORKERS_MAX_TASKS_PER_CHILD: int = 1000

    # Task chunk size
    FEED_CHUNK_SIZE: int = 4

    # Connection pool settings
    POOL_SIZE: int = 10
    MAX_CONCURRENT_REQUEST: int = 16
    REQUEST_TIMEOUT: int = 30

    # Performance tuning
    WORKER_CONCURRENCY: int = 8
    PREFETCH_MULTIPLIER: int = 1

    # Logging settings
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "api_log.log"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # Database settings
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
