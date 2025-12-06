"""
Logging utilities for Lambda functions.

Provides structured JSON logging with correlation IDs for tracing requests.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class StructuredLogger:
    """
    JSON logger for Lambda functions with correlation ID support.

    Example:
        logger = StructuredLogger(__name__)
        logger.info("Processing order", order_id="ORDER#123", profile_id="PROFILE#456")
    """

    def __init__(self, name: str, correlation_id: Optional[str] = None) -> None:
        self.logger = logging.getLogger(name)
        self.logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
        self.correlation_id = correlation_id or str(uuid.uuid4())

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        """Internal method to emit structured JSON logs."""
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "correlationId": self.correlation_id,
            **kwargs,
        }

        # Remove None values
        log_entry = {k: v for k, v in log_entry.items() if v is not None}

        print(json.dumps(log_entry))

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info level message."""
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning level message."""
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error level message."""
        self._log("ERROR", message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug level message."""
        self._log("DEBUG", message, **kwargs)


def get_correlation_id(event: Dict[str, Any]) -> str:
    """
    Extract or generate correlation ID from Lambda event.

    Checks for correlation ID in:
    1. event['requestContext']['requestId'] (AppSync)
    2. event['request']['headers']['x-correlation-id']
    3. Generates new UUID if not found
    """
    # Try AppSync request context
    if "requestContext" in event and "requestId" in event.get("requestContext", {}):
        return str(event["requestContext"]["requestId"])

    # Try custom header
    headers = event.get("request", {}).get("headers", {})
    if "x-correlation-id" in headers:
        return str(headers["x-correlation-id"])

    # Generate new ID
    return str(uuid.uuid4())


def get_logger(name: str, correlation_id: Optional[str] = None) -> StructuredLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)
        correlation_id: Optional correlation ID for tracing

    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name, correlation_id)
