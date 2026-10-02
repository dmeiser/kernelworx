"""
Error handling utilities for Lambda functions.

`AppError` carries the `ErrorCode` vocabulary that `utils.handlers` serializes
into the GraphQL `extensions` block; the resolver layer, not this module, owns
the response shape.
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
    # Admin performed an action that requires MFA; the frontend keys the MFA
    # setup UI off this code (#451), not the human-readable message.
    MFA_REQUIRED = "MFA_REQUIRED"

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
    # The resource is in a state the operation does not accept (e.g. a purge
    # run while the per-entity cascade that must precede it is incomplete).
    CONFLICT = "CONFLICT"

    # System errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    # Transient resource contention (e.g. DynamoDB/Cognito throttling); the client may retry
    RESOURCE_BUSY = "RESOURCE_BUSY"
