"""Tests for logging utilities."""

import json
from typing import Any, Dict

from src.utils.logging import StructuredLogger, get_correlation_id


class TestStructuredLogger:
    """Tests for StructuredLogger class."""

    def test_logger_initialization(self) -> None:
        """Test logger initializes with correlation ID."""
        logger = StructuredLogger("test", "test-id-123")

        assert logger.correlation_id == "test-id-123"

    def test_logger_generates_correlation_id(self) -> None:
        """Test logger generates correlation ID if not provided."""
        logger = StructuredLogger("test")

        assert logger.correlation_id is not None
        assert len(logger.correlation_id) > 0

    def test_info_logs_json(self, capsys: Any) -> None:
        """Test info logging outputs JSON."""
        logger = StructuredLogger("test", "test-id")

        logger.info("Test message", key="value")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Test message"
        assert log_entry["correlationId"] == "test-id"
        assert log_entry["key"] == "value"
        assert "timestamp" in log_entry

    def test_warning_logs_json(self, capsys: Any) -> None:
        """Test warning logging outputs JSON."""
        logger = StructuredLogger("test", "test-id")

        logger.warning("Warning message", code=123)

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert log_entry["level"] == "WARNING"
        assert log_entry["message"] == "Warning message"
        assert log_entry["code"] == 123

    def test_error_logs_json(self, capsys: Any) -> None:
        """Test error logging outputs JSON."""
        logger = StructuredLogger("test", "test-id")

        logger.error("Error message", error="details")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert log_entry["level"] == "ERROR"
        assert log_entry["message"] == "Error message"
        assert log_entry["error"] == "details"

    def test_debug_logs_json(self, capsys: Any) -> None:
        """Test debug logging outputs JSON when level is DEBUG."""
        logger = StructuredLogger("test-debug", "test-id")
        logger.logger.setLevel("DEBUG")

        logger.debug("Debug message", data={"key": "value"})

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert log_entry["level"] == "DEBUG"
        assert log_entry["message"] == "Debug message"

    def test_none_values_filtered(self, capsys: Any) -> None:
        """Test that None values are filtered from logs."""
        logger = StructuredLogger("test", "test-id")

        logger.info("Test", value=None, other="present")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert "value" not in log_entry
        assert log_entry["other"] == "present"

    def test_disabled_level_does_not_output(self, capsys: Any) -> None:
        """Test that messages below the configured level are not emitted."""
        logger = StructuredLogger("disabled-test", "test-id")
        logger.logger.setLevel(40)  # ERROR

        logger.info("Should not appear")

        captured = capsys.readouterr()
        assert captured.out.strip() == ""

    def test_default_level_is_info(self, capsys: Any) -> None:
        """Test that the default log level is INFO."""
        logger = StructuredLogger("default-level-test", "test-id")

        logger.debug("Should not appear by default")
        logger.info("Should appear by default")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())
        assert log_entry["message"] == "Should appear by default"

    def test_extra_dict_merged(self, capsys: Any) -> None:
        """Test that the extra dict is merged into the log entry."""
        logger = StructuredLogger("extra-test", "test-id")

        logger.info("Test", extra={"service": "test-service"})

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert log_entry["service"] == "test-service"

    def test_exc_info_true_adds_traceback(self, capsys: Any) -> None:
        """Test that exc_info=True renders the active exception traceback."""
        logger = StructuredLogger("exc-true-test", "test-id")

        try:
            raise ValueError("boom")
        except ValueError:
            logger.error("Oops", exc_info=True)

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert log_entry["message"] == "Oops"
        assert "traceback" in log_entry
        assert "ValueError: boom" in log_entry["traceback"]

    def test_exc_info_exception_instance_adds_traceback(self, capsys: Any) -> None:
        """Test that passing an exception instance renders its traceback."""
        logger = StructuredLogger("exc-instance-test", "test-id")

        err = ValueError("instance boom")
        logger.error("Oops", exc_info=err)

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert "traceback" in log_entry
        assert "ValueError: instance boom" in log_entry["traceback"]

    def test_exc_info_tuple_none_does_not_add_traceback(self, capsys: Any) -> None:
        """Test that a (None, None, None) exc_info tuple adds no traceback."""
        logger = StructuredLogger("exc-none-test", "test-id")

        logger.error("Oops", exc_info=(None, None, None))

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert "traceback" not in log_entry
        assert log_entry["message"] == "Oops"

    def test_non_standard_level_falls_back_to_info(self, capsys: Any) -> None:
        """Test that unknown level names fall back to INFO and still emit."""
        logger = StructuredLogger("custom-level-test", "test-id")

        logger._log("CUSTOM", "Custom level message")

        captured = capsys.readouterr()
        log_entry = json.loads(captured.out.strip())

        assert log_entry["level"] == "CUSTOM"
        assert log_entry["message"] == "Custom level message"


class TestGetCorrelationId:
    """Tests for get_correlation_id function."""

    def test_extract_from_appsync_request_context(self) -> None:
        """Test extracting correlation ID from AppSync request context."""
        event = {"requestContext": {"requestId": "appsync-request-123"}}

        correlation_id = get_correlation_id(event)

        assert correlation_id == "appsync-request-123"

    def test_extract_from_custom_header(self) -> None:
        """Test extracting correlation ID from custom header."""
        event = {"request": {"headers": {"x-correlation-id": "custom-id-456"}}}

        correlation_id = get_correlation_id(event)

        assert correlation_id == "custom-id-456"

    def test_generate_new_id_if_not_found(self) -> None:
        """Test generating new ID if not found in event."""
        event: Dict[str, Any] = {}

        correlation_id = get_correlation_id(event)

        assert correlation_id is not None
        assert len(correlation_id) > 0

    def test_appsync_context_takes_precedence(self) -> None:
        """Test that AppSync request context takes precedence."""
        event = {
            "requestContext": {"requestId": "appsync-123"},
            "request": {"headers": {"x-correlation-id": "header-456"}},
        }

        correlation_id = get_correlation_id(event)

        assert correlation_id == "appsync-123"
