import logging
import json
from typing import Dict, Any
from src.core.config import settings


class CustomFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }

        metrics = getattr(record, "metrics", None)
        if metrics is not None:
            log_entry["metrics"] = metrics

        if record.exc_info and isinstance(record.exc_info, tuple):
            exc_type, exc_value, _ = record.exc_info
            if exc_type and exc_value:
                log_entry["error"] = {
                    "type": exc_type.__name__,
                    "message": str(exc_value),
                }

        return json.dumps(log_entry)


def setup_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)
    root_logger.handlers = []

    formatter = CustomFormatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt=settings.LOG_DATE_FORMAT,
    )

    file_handler = logging.FileHandler(settings.LOG_FILE)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
    root_logger.addHandler(console_handler)
