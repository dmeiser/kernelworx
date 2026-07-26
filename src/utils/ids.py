"""
ID normalization utilities for DynamoDB prefixed IDs.

Provides consistent handling of entity ID prefixes (PROFILE#, CAMPAIGN#, etc.)
across all Lambda handlers and utilities.
"""

import uuid
from typing import Optional


def generate_id(prefix: str = "") -> str:
    """Generate a unique ID, optionally prefixed (e.g. PROFILE#uuid)."""
    raw_id = str(uuid.uuid4())
    if prefix:
        p = prefix.rstrip("#")
        return f"{p}#{raw_id}"
    return raw_id


def ensure_prefix(prefix: str, id_value: Optional[str]) -> Optional[str]:
    """
    Ensure an ID has the specified prefix.

    Args:
        prefix: Prefix without '#' (e.g., 'PROFILE', 'CAMPAIGN')
        id_value: ID to normalize, may be None

    Returns:
        ID with prefix, or None if input was None

    Examples:
        >>> ensure_prefix('PROFILE', 'abc-123')
        'PROFILE#abc-123'
        >>> ensure_prefix('PROFILE', 'PROFILE#abc-123')
        'PROFILE#abc-123'
        >>> ensure_prefix('CAMPAIGN', None)
        None
    """
    if not id_value:
        return None
    wanted = f"{prefix}#"
    return id_value if id_value.startswith(wanted) else f"{wanted}{id_value}"


def strip_prefix(id_value: Optional[str]) -> str:
    """
    Remove prefix from an ID to get raw UUID.

    Args:
        id_value: Prefixed ID (e.g., 'PROFILE#abc-123')

    Returns:
        UUID without prefix, or empty string if input was None

    Examples:
        >>> strip_prefix('PROFILE#abc-123')
        'abc-123'
        >>> strip_prefix('abc-123')
        'abc-123'
        >>> strip_prefix(None)
        ''
    """
    if not id_value:
        return ""
    hash_index = id_value.find("#")
    return id_value[hash_index + 1 :] if hash_index >= 0 else id_value


# Entity-specific helpers
def ensure_profile_id(id_value: Optional[str]) -> Optional[str]:
    """Normalize profile ID with PROFILE# prefix."""
    return ensure_prefix("PROFILE", id_value)


def ensure_campaign_id(id_value: Optional[str]) -> Optional[str]:
    """Normalize campaign ID with CAMPAIGN# prefix."""
    return ensure_prefix("CAMPAIGN", id_value)


def ensure_catalog_id(id_value: Optional[str]) -> Optional[str]:
    """Normalize catalog ID with CATALOG# prefix."""
    return ensure_prefix("CATALOG", id_value)


def ensure_order_id(id_value: Optional[str]) -> Optional[str]:
    """Normalize order ID with ORDER# prefix."""
    return ensure_prefix("ORDER", id_value)


def ensure_account_id(id_value: Optional[str]) -> Optional[str]:
    """Normalize account ID with ACCOUNT# prefix."""
    return ensure_prefix("ACCOUNT", id_value)


def ensure_product_id(id_value: Optional[str]) -> Optional[str]:
    """Normalize product ID with PRODUCT# prefix."""
    return ensure_prefix("PRODUCT", id_value)
