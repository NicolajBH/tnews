import logging
import json
import time
from typing import Dict, Any, Optional, List
from contextvars import ContextVar
from src.core.config import settings

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
correlation_context_var: ContextVar[Dict[str, Any]] = ContextVar(
    "correlation_context", default={}
)


def set_request_id(request_id: str) -> None:
    """
    Set the request ID in the current context
    """
    request_id_var.set(request_id)
    ctx = correlation_context_var.get()
    ctx["request_id"] = request_id
    correlation_context_var.set(ctx)


def get_request_id() -> str | None:
    """
    Get the request ID from the current context
    """
    return request_id_var.get()


def add_correlation_id(key: str, value: Any) -> None:
    """
    Add a key-value pair to the correlation context
    """
    ctx = correlation_context_var.get()
    ctx[key] = value
    correlation_context_var.set(ctx)


def get_correlation_context() -> Dict[str, Any]:
    """
    Get the current correlation context
    """
    return correlation_context_var.get()


def reset_correlation_context() -> None:
    """
    Reset the correlation context
    """
    correlation_context_var.set({})


class LogContext:
    """
    Helper class to manage logging context and create structured logs
    """

    def __init__(self, logger_name: str | None = None):
        self.logger = (
            logging.getLogger(logger_name) if logger_name else logging.getLogger()
        )

    def info(self, message: str, extra: Dict[str, Any] | None = None) -> None:
        """
        Log an info message with correlation context
        """
        self._log(logging.INFO, message, extra)

    def warning(self, message: str, extra: Dict[str, Any] | None = None) -> None:
        """
        Log a warning message with correlation context
        """
        self._log(logging.WARNING, message, extra)

    def error(
        self, message: str, extra: Dict[str, Any] | None = None, exc_info: bool = False
    ) -> None:
        """
        Log an error message with correlation context
        """
        self._log(logging.ERROR, message, extra, exc_info)

    def debug(self, message: str, extra: Dict[str, Any] | None = None) -> None:
        """
        Log a debug message with correlation context
        """
        self._log(logging.DEBUG, message, extra)

    def exception(self, message: str, extra: Dict[str, Any] | None = None) -> None:
        """
        Log an exception message with correlation context and stack trace
        """
        self._log(logging.ERROR, message, extra, exc_info=True)

    def _log(
        self,
        level: int,
        message: str,
        extra: Dict[str, Any] | None = None,
        exc_info: bool = False,
    ) -> None:
        """
        Internal method to combine correlation context with extra data and log
        """
        if extra is None:
            extra = {}

        log_extra = {**get_correlation_context(), **extra}

        self.logger.log(level, message, extra=log_extra, exc_info=exc_info)


class CustomFormatter(logging.Formatter):
    """
    Custom formatter for structured logging that outputs JSON
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "path": f"{record.pathname}:{record.lineno}",
        }

        request_id = getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = request_id

        if hasattr(settings, "PROJECT_NAME"):
            log_entry["service"] = settings.PROJECT_NAME

        metrics = getattr(record, "metrics", None)
        if metrics is not None:
            log_entry["metrics"] = metrics

        duration_ms = getattr(record, "duration_ms", None)
        if duration_ms is not None:
            log_entry["duration_ms"] = duration_ms

        for key, value in record.__dict__.items():
            if (
                key not in ["request_id", "metrics", "duration_ms"]
                and not key.startswith("_")
                and not hasattr(logging.LogRecord("", 0, "", 0, "", (), None), key)
            ):
                log_entry[key] = value

        if record.exc_info and isinstance(record.exc_info, tuple):
            exc_type, exc_value, *_ = record.exc_info
            if exc_type and exc_value:
                log_entry["error"] = {
                    "type": exc_type.__name__,
                    "message": str(exc_value),
                }

        return json.dumps(log_entry)


class PerformanceLogger:
    """
    Utility class for timing operations and logging performance metrics
    """

    def __init__(self, logger: LogContext, operation_name: str):
        self.logger = logger
        self.operation_name = operation_name
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        extra = {"duration_ms": duration_ms}

        if exc_type:
            self.logger.error(
                f"Operation {self.operation_name} failed after {duration_ms:.2f}ms",
                extra=extra,
                exc_info=True,
            )
        else:
            self.logger.info(
                f"Operation {self.operation_name} completed in {duration_ms:.2f}ms",
                extra=extra,
            )


def setup_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)
    root_logger.handlers = []

    formatter = CustomFormatter()

    file_handler = logging.FileHandler(settings.LOG_FILE)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
    root_logger.addHandler(console_handler)

    reset_correlation_context()
