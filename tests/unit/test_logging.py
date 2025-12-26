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
        """Test debug logging outputs JSON."""
        logger = StructuredLogger("test", "test-id")

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
