"""
Error handling utilities for Lambda functions.

Provides standardized error responses with error codes.
"""

from typing import Any, Dict, Optional


class AppError(Exception):
    """
    Application error with error code and message.

    Used to return structured errors to GraphQL clients.
    """

    def __init__(self, error_code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for GraphQL response."""
        return {
            "errorCode": self.error_code,
            "message": self.message,
            **self.details,
        }


# Common error codes
class ErrorCode:
    """Standard error codes for the application."""

    # Authorization errors
    FORBIDDEN = "FORBIDDEN"
    UNAUTHORIZED = "UNAUTHORIZED"

    # Resource errors
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"

    # Validation errors
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_PHONE = "INVALID_PHONE"
    INVALID_ADDRESS = "INVALID_ADDRESS"

    # Business logic errors
    INVITE_EXPIRED = "INVITE_EXPIRED"
    INVITE_ALREADY_USED = "INVITE_ALREADY_USED"
    CAMPAIGN_READ_ONLY = "CAMPAIGN_READ_ONLY"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"

    # System errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"


def handle_error(error: Exception) -> Dict[str, Any]:
    """
    Convert exception to standardized error response.

    Args:
        error: Exception to handle

    Returns:
        Error dictionary for GraphQL response
    """
    if isinstance(error, AppError):
        return error.to_dict()

    # Unexpected error - log and return generic message
    return {
        "errorCode": ErrorCode.INTERNAL_ERROR,
        "message": "An unexpected error occurred. Please try again.",
    }


def create_error_response(error_code: str, message: str) -> Dict[str, Any]:
    """
    Create standardized error response dictionary.

    Args:
        error_code: Error code (use ErrorCode constants)
        message: Human-readable error message

    Returns:
        Error dictionary for GraphQL response
    """
    return {
        "errorCode": error_code,
        "message": message,
    }


class ValidationError(AppError):
    """Error raised when input validation fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.INVALID_INPUT, message, details)


class AuthorizationError(AppError):
    """Error raised when user is not authorized to perform an action."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.FORBIDDEN, message, details)
