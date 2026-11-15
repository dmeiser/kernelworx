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
    # A campaign's lifetime public-order cap is spent; the buyer must not retry.
    PUBLIC_ORDER_LIMIT_EXCEEDED = "PUBLIC_ORDER_LIMIT_EXCEEDED"
    INVITE_EXPIRED = "INVITE_EXPIRED"
    INVITE_ALREADY_USED = "INVITE_ALREADY_USED"
    CAMPAIGN_READ_ONLY = "CAMPAIGN_READ_ONLY"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    # The resource is in a state the operation does not accept (e.g. a purge
    # run while the per-entity cascade that must precede it is incomplete).
    CONFLICT = "CONFLICT"
    # A mutation's complete write plan exceeds the 90-action budget, or the
    # resulting event could no longer finalize within it. Emitted as a CONFLICT
    # (data model §8.10: `CONFLICT`/`OPERATION_TOO_LARGE`); the code is carried
    # in the error `details` so the client can identify the required reduction
    # without re-reading the spec, and only authorized subcodes are forwarded
    # across the GraphQL boundary (impact map §3.1).
    OPERATION_TOO_LARGE = "OPERATION_TOO_LARGE"

    # Abuse limits (data model §6.6: Unit-invite redemption attempt 11 in one
    # UTC hour). Distinct from RESOURCE_BUSY: retrying the same attempt within
    # the window cannot succeed.
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # System errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    # Transient resource contention (e.g. DynamoDB/Cognito throttling); the client may retry
    RESOURCE_BUSY = "RESOURCE_BUSY"
