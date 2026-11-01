"""
Token comparison utilities.

Provides constant-time comparison for capability tokens to prevent
timing attacks on secret values.
"""

import hmac
from typing import Any


def constant_time_token_match(stored: Any, submitted: Any) -> bool:
    """Compare two tokens in constant time using hmac.compare_digest.

    Both values must be non-empty strings. Any non-string, empty, or
    missing value returns False without revealing which condition failed.

    Args:
        stored: The stored token value
        submitted: The submitted token value

    Returns:
        True if both are non-empty strings and equal, False otherwise
    """
    if not isinstance(stored, str) or not stored or not isinstance(submitted, str) or not submitted:
        return False
    return hmac.compare_digest(submitted.encode("utf-8"), stored.encode("utf-8"))
