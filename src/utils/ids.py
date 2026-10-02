"""
ID normalization utilities for DynamoDB prefixed IDs.

Provides consistent handling of entity ID prefixes (PROFILE#, CAMPAIGN#, etc.)
across all Lambda handlers and utilities.
"""

from typing import Optional, Union


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


def ensure_account_id(id_value: Optional[str]) -> Optional[str]:
    """Normalize account ID with ACCOUNT# prefix."""
    return ensure_prefix("ACCOUNT", id_value)


def build_unit_campaign_key(
    unit_type: str, unit_number: int, city: str, state: str, campaign_name: str, campaign_year: Union[int, str]
) -> str:
    """Build the unitCampaignKey for unit+campaign queries.

    This format is the partition-key contract for the unitCampaignKey-index
    GSI. Unit reporting, unit catalog listing, and campaign creation all read
    or write the same index with this exact key layout, so it must have a
    single definition: the format must not change without a data migration,
    and new code must call this helper rather than rebuild the key.

    ``campaign_year`` is an int on every query path; the campaign write path
    passes an empty string when no year is set yet, which is the same key
    layout with an empty trailing component.
    """
    return f"{unit_type}#{unit_number}#{city}#{state}#{campaign_name}#{campaign_year}"
