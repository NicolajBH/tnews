import time
from prometheus_client import Counter, Histogram, Gauge, Summary, Info

# app info
app_info = Info("app_info", "Application information")
app_info.info({"app": "news_feed_api", "version": "1.0.0"})

# http request metrics
http_requests_total = Counter(
    "app_http_requests_total",
    "Total HTTP requests count",
    ["method", "endpoint", "status_code"],
)

http_request_duration = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

active_requests = Gauge("app_active_requests", "Number of active HTTP reqeusts")

# db metrics
db_query_duration = Histogram(
    "app_db_query_duration_seconds",
    "Database query duration in seconds",
    ["operation", "table"],
)

db_connection_pool_size = Gauge(
    "app_db_connection_pool_size", "Database connection pool size"
)

# redis metrics
redis_operation_duration = Histogram(
    "app_redis_operation_duration_seconds",
    "Redis operation duration in seconds",
    ["operation"],
)

redis_client_state = Gauge(
    "app_redis_client_state",
    "Redis client state (0=disconnected, 1=connected, 2=degraded)",
)

# cache metrics
cache_hits = Counter("app_cache_hits_total", "Cache hits", ["cache_type"])

cache_misses = Counter("app_cache_misses_total", "Cache misses", ["cache_type"])

# auth metrics
auth_attempts = Counter(
    "app_auth_attempts_total", "Authentication attempts", ["auth_type", "status"]
)

# rate limiting metrics
rate_limited_requests = Counter(
    "app_rate_limited_requests_total", "Total rate limited requests", ["endpoint"]
)

# feed metrics
feed_fetch_operations = Counter(
    "app_feed_fetch_operations_total", "Feed fetch operations", ["source", "status"]
)

feed_processing_duration = Histogram(
    "app_feed_processing_seconds", "Feed processing duration in seconds", ["operation"]
)

articles_processed = Counter(
    "app_articles_processed_total", "Articles processed", ["source", "status"]
)

# circuit breaker metrics
circuit_breaker_state = Gauge(
    "app_circuit_breaker_state",
    "Circuit breaker state (0=open, 1=half_open, 2=closed)",
    ["service"],
)

circuit_breaker_failures = Counter(
    "app_circuit_breaker_failures_total", "Circuit breaker failures", ["service"]
)

# health metrics
service_health_state = Gauge(
    "app_service_health_state",
    "Service health state (0=unavailable, 1=degraded, 2=operational)",
    ["service"],
)

# user metrics
feed_subscriptions = Counter(
    "app_feed_subscriptions_total", "Feed subscription operations", ["operation"]
)

active_users = Gauge("app_active_users", "Number of active users in the last 24 hours")

# performance metrics from PerformanceLogger
performance_timings = Histogram(
    "app_performance_duration_seconds",
    "Duration of performance-logged operations",
    ["operation"],
)
