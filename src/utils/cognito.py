"""Cognito client helpers for Lambda handlers.

Provides a retry wrapper for Cognito User Pool operations so callers do not
duplicate transient-fault backoff loops.
"""

import time
from typing import Any, Callable

from botocore.exceptions import ClientError

_RETRYABLE_CODES: frozenset[str] = frozenset(
    {"TooManyRequestsException", "InternalErrorException", "ProvisionedThroughputExceededException"}
)
_RETRY_MAX_ATTEMPTS: int = 3
_RETRY_BASE_BACKOFF_SECONDS: float = 0.1


def retry_on_transient_errors(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke a Cognito client method, retrying transient throttling faults with exponential backoff.

    The callable is invoked up to ``_RETRY_MAX_ATTEMPTS`` times. A ``ClientError`` whose
    ``response["Error"]["Code"]`` is one of the transient codes (``TooManyRequestsException``,
    ``InternalErrorException``, ``ProvisionedThroughputExceededException``) on any attempt before
    the final one is absorbed: the call sleeps for ``_RETRY_BASE_BACKOFF_SECONDS * (2 ** attempt)``
    seconds (after attempts 0 and 1) and retries. Any other ``ClientError``, or a transient error
    on the final attempt, propagates unchanged, so callers keep their own handling of terminal
    codes such as ``UserNotFoundException``.

    Args:
        method: Bound Cognito client method to invoke.
        *args: Positional arguments forwarded to ``method``.
        **kwargs: Keyword arguments forwarded to ``method``.

    Returns:
        Whatever ``method`` returns on a successful attempt.

    Raises:
        ClientError: The original error, unmodified, when it is not retryable or retries are
            exhausted. No other exception type is ever translated by this helper.
    """
    attempt = 0
    while True:
        try:
            return method(*args, **kwargs)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if attempt < _RETRY_MAX_ATTEMPTS - 1 and error_code in _RETRYABLE_CODES:
                time.sleep(_RETRY_BASE_BACKOFF_SECONDS * (2**attempt))
                attempt += 1
                continue
            raise
