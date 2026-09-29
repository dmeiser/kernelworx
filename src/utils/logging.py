"""
Logging utilities for Lambda functions.

Provides structured JSON logging with correlation IDs for tracing requests.
"""

import json
import logging
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TextIO

#: Extra key names whose values are never emitted in the clear. Keys are
#: matched case-insensitively against these lowercase names, so ``customerPhone``
#: and ``qrCodeUrl`` are caught alongside ``email``. This is the structural
#: backstop for redaction: individual call sites still mask explicitly with
#: :func:`mask_email`, but a new call site that forgets cannot leak PII.
_SENSITIVE_KEYS = frozenset({"email", "username", "phone", "customerphone", "address", "qrcodeurl", "password"})
#: Sensitive keys whose value is an address and can therefore be masked
#: partially instead of dropped entirely.
_MASKABLE_KEYS = frozenset({"email", "username"})


def _redact_sensitive(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``entry`` with sensitive top-level values masked.

    Keys already named as masked (e.g. ``maskedEmail``) are left untouched, and
    masking an already-masked address is idempotent, so explicit
    :func:`mask_email` call sites keep working unchanged.
    """
    for key, value in entry.items():
        normalized = key.lower()
        if normalized not in _SENSITIVE_KEYS or "mask" in normalized:
            continue
        entry[key] = mask_email(value) if normalized in _MASKABLE_KEYS else "***"
    return entry


class _StdoutHandler(logging.StreamHandler[TextIO]):
    """Stream handler that writes to the current ``sys.stdout`` at emit time.

    Resolving ``sys.stdout`` when a record is emitted rather than binding it
    once at construction keeps the JSON line visible to harnesses that swap
    ``sys.stdout`` after import, such as pytest's ``capsys`` fixture.
    """

    @property
    def stream(self) -> TextIO:
        return sys.stdout

    @stream.setter
    def stream(self, value: TextIO) -> None:
        pass


_handler = _StdoutHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))


class StructuredLogger:
    """
    JSON logger for Lambda functions with correlation ID support.

    Honors the ``LOG_LEVEL`` environment variable and renders exception
    tracebacks when ``exc_info=True`` is passed.

    Example:
        logger = StructuredLogger(__name__)
        logger.info("Processing order", order_id="ORDER#123", profile_id="PROFILE#456")
    """

    def __init__(self, name: str, correlation_id: Optional[str] = None) -> None:
        self.logger = logging.getLogger(name)
        self.logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
        if _handler not in self.logger.handlers:
            self.logger.addHandler(_handler)
        self.correlation_id = correlation_id or str(uuid.uuid4())

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        """Internal method to emit structured JSON logs."""
        level_num = logging.getLevelName(level)
        if not isinstance(level_num, int):
            level_num = logging.INFO
        if not self.logger.isEnabledFor(level_num):
            return

        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "correlationId": self.correlation_id,
        }

        exc_info = kwargs.pop("exc_info", None)
        extra = kwargs.pop("extra", None)
        if isinstance(extra, dict):
            log_entry.update(extra)
        log_entry.update(kwargs)
        log_entry = _redact_sensitive(log_entry)

        if exc_info:
            if exc_info is True:
                exc_info = sys.exc_info()
            elif isinstance(exc_info, BaseException):
                exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
            if exc_info and exc_info[0] is not None:
                log_entry["traceback"] = "".join(traceback.format_exception(*exc_info))

        # Remove None values
        log_entry = {k: v for k, v in log_entry.items() if v is not None}

        self.logger.log(level_num, json.dumps(log_entry, default=str))

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


def mask_email(email: Optional[str]) -> str:
    """Mask an email address so the local part is not logged in full.

    Examples:
        "user@example.com" -> "u***@example.com"
        "ab@example.com"   -> "a***@example.com"
        "a@example.com"    -> "***@example.com"
        None or invalid    -> "***"
    """
    if not isinstance(email, str) or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) == 1:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"
