import pytest
import json
import logging
import tempfile
import os
from unittest.mock import patch, MagicMock

from src.core.logging import CustomFormatter, setup_logging

DEBUG_LEVEL = logging.DEBUG
INFO_LEVEL = logging.INFO
WARNING_LEVEL = logging.WARNING


@pytest.fixture
def sample_log_record():
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test_file.py",
        lineno=42,
        msg="Test log message",
        args=(),
        exc_info=None,
    )
    record.module = "test_module"
    return record


class TestCustomFormatter:
    def test_basic_formatting(self, sample_log_record):
        formatter = CustomFormatter()
        result = formatter.format(sample_log_record)

        log_entry = json.loads(result)

        assert "timestamp" in log_entry
        assert log_entry["level"] == "INFO"
        assert log_entry["module"] == "test_module"
        assert log_entry["message"] == "Test log message"
        assert "metrics" not in log_entry
        assert "error" not in log_entry

    def test_formatting_with_metrics(self, sample_log_record):
        sample_log_record.metrics = {"duration_ms": 150, "status_code": 200}

        formatter = CustomFormatter()
        result = formatter.format(sample_log_record)

        log_entry = json.loads(result)

        assert "metrics" in log_entry
        assert log_entry["metrics"]["duration_ms"] == 150
        assert log_entry["metrics"]["status_code"] == 200

    def test_formatting_with_exception(self, sample_log_record):
        try:
            raise ValueError("Test exception")
        except ValueError as e:
            sample_log_record.exc_info = (type(e), e, e.__traceback__)

        formatter = CustomFormatter()
        result = formatter.format(sample_log_record)

        log_entry = json.loads(result)

        assert "error" in log_entry
        assert log_entry["error"]["type"] == "ValueError"
        assert log_entry["error"]["message"] == "Test exception"


class TestSetupLogging:
    @patch("src.core.logging.logging")
    @patch("src.core.logging.settings")
    def test_setup_logging_configuration(self, mock_settings, mock_logging):
        mock_settings.LOG_LEVEL = INFO_LEVEL
        mock_settings.LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
        mock_settings.LOG_FILE = "test.log"

        mock_logging.DEBUG = DEBUG_LEVEL
        mock_logging.INFO = INFO_LEVEL
        mock_logging.WARNING = WARNING_LEVEL

        mock_root_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_root_logger

        mock_file_handler = MagicMock()
        mock_logging.FileHandler.return_value = mock_file_handler

        mock_console_handler = MagicMock()
        mock_logging.StreamHandler.return_value = mock_console_handler

        setup_logging()

        mock_logging.getLogger.assert_called_once_with()
        mock_root_logger.setLevel.assert_called_once_with(mock_settings.LOG_LEVEL)

        mock_logging.FileHandler.assert_called_once_with(mock_settings.LOG_FILE)
        mock_file_handler.setFormatter.assert_called_once()
        mock_file_handler.setLevel.assert_called_once_with(DEBUG_LEVEL)
        mock_root_logger.addHandler.assert_any_call(mock_file_handler)

        mock_logging.StreamHandler.assert_called_once()
        mock_console_handler.setFormatter.assert_called_once()
        mock_console_handler.setLevel.assert_called_once_with(WARNING_LEVEL)
        mock_root_logger.addHandler.assert_any_call(mock_console_handler)

    def test_setup_logging_integration(self):
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_log_file = temp_file.name

        try:
            with patch("src.core.logging.settings") as mock_settings:
                mock_settings.LOG_LEVEL = logging.DEBUG
                mock_settings.LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
                mock_settings.LOG_FILE = temp_log_file

                setup_logging()

                logger = logging.getLogger()
                logger.debug("Debug message")
                logger.info("Info message")
                logger.warning("Warning message")
                logger.error("Error message")

                test_logger = logging.getLogger("test")
                test_logger.info(
                    "Message with metrics", extra={"metrics": {"value": 42}}
                )

                try:
                    raise ValueError("Test exception")
                except ValueError:
                    test_logger.exception("Exception occurred")

                with open(temp_log_file, "r") as log_file:
                    log_lines = log_file.readlines()

                    assert len(log_lines) >= 6

                    for line in log_lines:
                        log_entry = json.loads(line)
                        assert isinstance(log_entry, dict)
                        assert "timestamp" in log_entry
                        assert "level" in log_entry
                        assert "message" in log_entry

                logging.getLogger().handlers = []

        finally:
            if os.path.exists(temp_log_file):
                os.unlink(temp_log_file)
