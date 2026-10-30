"""
Admin profile-share & campaign shared-code handlers (extracted from admin_operations, #773).

Provides:
- adminGetProfileShares: Get all shares for a profile
- adminDeleteShare: Delete a specific share (revoke access)
- adminUpdateCampaignSharedCode: Update a campaign's sharedCampaignCode field

The handlers stay registered on the shared admin-operations Lambda:
``admin_operations`` imports them for its operation dispatcher map, so the
Lambda entry point (``handlers.admin_operations.lambda_handler``) and the
AppSync handler mapping are unchanged.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import require_admin_mfa
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id, ensure_campaign_id, ensure_profile_id
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import require_admin_mfa
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id, ensure_campaign_id, ensure_profile_id
    from ..utils.logging import get_logger

# query_all_items must be typed for mypy (warn_return_any): mypy reads only the
# TYPE_CHECKING branch; the runtime fallback tries the absolute import first so it
# resolves in the Lambda zip (package `utils`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.pagination import query_all_items
else:  # pragma: no cover
    try:
        from utils.pagination import query_all_items
    except ModuleNotFoundError:
        from ..utils.pagination import query_all_items

# The decorator stays typed for mypy via the relative import below; at runtime
# the absolute import resolves in the Lambda zip (package `utils`) and the
# relative fallback resolves in unit tests (package `src.handlers`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling


def _convert_permissions_to_lists(shares: list[Dict[str, Any]]) -> None:
    """Convert DynamoDB permission sets to lists for JSON serialization."""
    for share in shares:
        if "permissions" in share and isinstance(share["permissions"], set):
            share["permissions"] = list(share["permissions"])


def _query_profile_shares(db_profile_id: str) -> list[Dict[str, Any]]:
    """Query all shares for a profile."""
    return query_all_items(
        tables.shares,
        {
            "KeyConditionExpression": "profileId = :pid",
            "ExpressionAttributeValues": {":pid": db_profile_id},
        },
    )


def _require_admin_and_get_target_profile_id(event: Dict[str, Any]) -> tuple[str, str]:
    """Require admin + MFA, returning ``(db_profile_id, actor_sub)`` (#507).

    ``db_profile_id`` is the target profile named by the request; ``actor_sub``
    is the calling administrator, returned alongside so the audit line can
    attribute the operation.
    """
    from .admin_operations import _actor_sub

    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()

    if not profile_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID is required")

    # Add PROFILE# prefix if not present
    db_profile_id = ensure_profile_id(profile_id)
    return db_profile_id, actor_sub


@with_error_handling(error_message="Failed to get profile shares")
def admin_get_profile_shares(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shares for a specific profile.

    Admin-only operation. Returns all users who have access to this profile.
    """
    logger = get_logger(__name__)

    db_profile_id, actor_sub = _require_admin_and_get_target_profile_id(event)

    # Query shares and convert sets to lists
    shares = _query_profile_shares(db_profile_id)
    _convert_permissions_to_lists(shares)

    logger.info("Retrieved profile shares", profile_id=db_profile_id, count=len(shares), actor_sub=actor_sub)
    return shares


def _normalize_profile_and_account_ids(profile_id: str, target_account_id: str) -> tuple[str, str]:
    """Normalize profile ID and target account ID with prefixes."""
    db_profile_id = ensure_profile_id(profile_id)
    db_target_id = ensure_account_id(target_account_id)
    return db_profile_id, db_target_id


def _require_admin_and_get_share_ids(event: Dict[str, Any]) -> tuple[str, str, str]:
    """Require admin + MFA, returning ``(profile_id, target_account_id, actor_sub)`` (#507).

    The first two are the share the request names; the third is the calling
    administrator, carried so the revocation can be attributed.
    """
    from .admin_operations import _actor_sub

    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()
    target_account_id = arguments.get("targetAccountId", "").strip()

    if not profile_id or not target_account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID and target account ID are required")

    return profile_id, target_account_id, actor_sub


@with_error_handling(error_message="Failed to delete share")
def admin_delete_share(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete a specific share (revoke access).

    Admin-only operation. Allows admin to remove someone's access to a profile.
    """
    logger = get_logger(__name__)

    profile_id, target_account_id, actor_sub = _require_admin_and_get_share_ids(event)
    db_profile_id, db_target_id = _normalize_profile_and_account_ids(profile_id, target_account_id)

    tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_target_id})

    logger.info(
        "Deleted share",
        profile_id=profile_id,
        target_account_id=target_account_id,
        actor_sub=actor_sub,
    )
    return True


def _get_campaign_profile_id(db_campaign_id: str, campaign_id: str) -> str:
    """Get profile ID for a campaign via GSI lookup."""
    response = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": db_campaign_id},
    )

    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, f"Campaign not found: {campaign_id}")

    return str(items[0]["profileId"])


def _update_campaign_shared_code(
    profile_id: str, db_campaign_id: str, shared_campaign_code: Optional[str]
) -> Dict[str, Any]:
    """Update campaign's sharedCampaignCode field and return the stored item."""
    updated_at = datetime.now(timezone.utc).isoformat()

    if shared_campaign_code is None:
        update_expr = "REMOVE sharedCampaignCode SET updatedAt = :updated"
        expr_vals = {":updated": updated_at}
    else:
        update_expr = "SET sharedCampaignCode = :code, updatedAt = :updated"
        expr_vals = {":code": shared_campaign_code, ":updated": updated_at}

    response = tables.campaigns.update_item(
        Key={"profileId": profile_id, "campaignId": db_campaign_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_vals,
        ReturnValues="ALL_NEW",
    )

    return cast(Dict[str, Any], response.get("Attributes", {}))


def _require_admin_and_get_target_campaign_id(event: Dict[str, Any]) -> tuple[str, Optional[str], str]:
    """Require admin + MFA, returning ``(campaign_id, shared_campaign_code, actor_sub)`` (#507).

    ``campaign_id`` is the target campaign named by the request; ``actor_sub``
    is the calling administrator, carried so the update can be attributed.
    """
    from .admin_operations import _actor_sub

    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    campaign_id = arguments.get("campaignId", "").strip()
    shared_campaign_code = arguments.get("sharedCampaignCode")

    if not campaign_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Campaign ID is required")

    return campaign_id, shared_campaign_code, actor_sub


@with_error_handling(error_message="Failed to update campaign shared code")
def admin_update_campaign_shared_code(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update a campaign's sharedCampaignCode field and return the stored campaign item.

    Admin-only operation. Allows associating a campaign with a shared campaign.
    """
    logger = get_logger(__name__)

    campaign_id, shared_campaign_code, actor_sub = _require_admin_and_get_target_campaign_id(event)

    # Add CAMPAIGN# prefix if not present
    db_campaign_id = ensure_campaign_id(campaign_id)

    # Get campaign profile, update shared code, and return the stored item
    profile_id = _get_campaign_profile_id(db_campaign_id, campaign_id)
    updated_campaign = _update_campaign_shared_code(profile_id, db_campaign_id, shared_campaign_code)

    logger.info(
        "Updated campaign shared code",
        campaign_id=campaign_id,
        shared_campaign_code=shared_campaign_code,
        actor_sub=actor_sub,
    )
    return updated_campaign
