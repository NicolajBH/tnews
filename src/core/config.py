import os
import secrets
from typing import List, Literal
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Environment
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = False

    # API
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "RSS News API"
    VERSION: str = "1.0.0"

    # Database
    DATABASE_URL: str = "sqlite:///database.db"
    TEST_DATABASE_URL: str = "sqlite:///./test.db"

    # Database pool settings
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # Security - Generate secure defaults for development
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600
    REDIS_HASH_TTL: int = 86400

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    AUTH_RATE_LIMIT_ATTEMPTS: int = 5
    AUTH_RATE_LIMIT_WINDOW: int = 60
    AUTH_RATE_LIMIT_TIMEOUT_TIME: int = 300

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_TIMEOUT: int = 180
    CELERY_RESULT_EXPIRES: int = 1800
    CELERY_BROKER_CONNECTION_TIMEOUT: int = 5
    CELERY_BROKER_CONNECTION_MAX_RETRIES: int = 3
    CELERY_TASK_MAX_RETRIES: int = 3
    CELERY_BEAT_SCHEDULE_INTERVAL: int = 900
    CELERY_BEAT_MAX_LOOP_INTERVAL: int = 1000
    CELERY_WORKERS_MAX_TASKS_PER_CHILD: int = 1000

    # Task settings
    FEED_CHUNK_SIZE: int = 4
    POOL_SIZE: int = 10
    MAX_CONCURRENT_REQUEST: int = 16
    REQUEST_TIMEOUT: int = 30

    # Performance
    WORKER_CONCURRENCY: int = 8
    PREFETCH_MULTIPLIER: int = 1

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/api_log.log"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
    CORS_ALLOW_HEADERS: List[str] = ["Content-Type", "Authorization", "Accept"]

    # MeiliSearch
    MEILISEARCH_URL: str = "http://localhost:7700"
    MEILISEARCH_MASTER_KEY: str = ""
    MEILISEARCH_INDEX_NAME: str = "articles"

    # External APIs (for future use)
    EXTERNAL_API_TIMEOUT: int = 30
    EXTERNAL_API_RETRIES: int = 3

    class Config:
        env_file = ".env"
        case_sensitive = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Environment-specific configurations
        if self.ENVIRONMENT == "development":
            self.DEBUG = True
            self.LOG_LEVEL = "DEBUG"
            # Keep generated SECRET_KEY for development consistency

        elif self.ENVIRONMENT == "testing":
            self.DEBUG = True
            self.LOG_LEVEL = "ERROR"  # Reduce test noise
            self.DATABASE_URL = self.TEST_DATABASE_URL
            self.REDIS_URL = "redis://localhost:6379/1"  # Different Redis DB
            self.RATE_LIMIT_ENABLED = False  # Disable for tests

        elif self.ENVIRONMENT == "production":
            self.DEBUG = False
            self.LOG_LEVEL = "WARNING"
            # Require SECRET_KEY to be explicitly set in production
            if self.SECRET_KEY == secrets.token_urlsafe(32):
                raise ValueError(
                    "SECRET_KEY must be explicitly set in production environment"
                )

    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL for SQLModel"""
        return self.DATABASE_URL

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "testing"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()
