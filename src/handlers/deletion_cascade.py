"""Shared account-deletion cascade internals.

The whole-user deletion cascade used to be split between
``account_operations``, which orchestrated it, and ``admin_operations``,
which held the per-domain sub-cascades. That split was a circular import:
``admin_operations`` imported the orchestrator at module scope, so the
orchestrator had to import the sub-cascades back inside function bodies.
A consequence was that every sub-cascade re-paginated the whole profiles
table on its own, so one account deletion paid six full profiles sweeps
(#554).

The internals now live here, below both handlers in the graph:
``delete_all_user_data`` sweeps the profiles table once and passes the list
into each sub-cascade, which only ever iterates it. Only self-service
``deleteMyAccount`` runs the whole cascade today: admin deletion is
client-side (#521) and reuses these per-entity sub-cascades directly, then
calls ``adminPurgeUserAccount`` — see the #521 entry in AGENTS.md.
"""

from typing import TYPE_CHECKING, Any, Dict

from botocore.exceptions import ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .campaign_operations import (
    _verify_campaign_deleted,
    batch_delete_keys,
    delete_orders_for_campaign,
)
from .delete_profile_cascade import _delete_s3_reports

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.logging import get_logger
    from utils.payment_methods import delete_all_user_qr_codes
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.logging import get_logger
    from ..utils.payment_methods import delete_all_user_qr_codes

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.pagination import query_all_items
else:  # pragma: no cover
    try:
        from utils.pagination import query_all_items
    except ModuleNotFoundError:
        from ..utils.pagination import query_all_items

logger = get_logger(__name__)


def normalize_account_id(account_id: str) -> str:
    """Add ACCOUNT# prefix if not present."""
    return account_id if account_id.startswith("ACCOUNT#") else f"ACCOUNT#{account_id}"


def get_user_profiles(db_account_id: str) -> list[Dict[str, Any]]:
    """Get all profiles owned by an account."""
    return query_all_items(
        tables.profiles,
        {
            "KeyConditionExpression": "ownerAccountId = :owner",
            "ExpressionAttributeValues": {":owner": db_account_id},
        },
    )


def delete_user_orders(profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all orders for all campaigns of the given profiles.

    Verifies with strongly consistent reads that each deleted order is gone
    from the orders table before returning. Raises AppError if a deleted order
    is still present.

    Returns:
        Count of orders deleted.
    """
    deleted_count = 0

    for profile in profiles:
        profile_id = profile["profileId"]
        campaigns = query_all_items(
            tables.campaigns,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
            },
        )
        for campaign in campaigns:
            deleted_count += delete_orders_for_campaign(campaign["campaignId"], logger=logger)

    logger.info("Deleted user orders", count=deleted_count)
    return deleted_count


def delete_user_campaigns(profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all campaigns for the given profiles.

    Verifies with strongly consistent reads that each deleted campaign is gone
    from the campaigns table before returning. Raises AppError if a deleted
    campaign is still present.

    Returns:
        Count of campaigns deleted.
    """
    deleted_count = 0

    for profile in profiles:
        profile_id = profile["profileId"]
        campaigns = query_all_items(
            tables.campaigns,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
            },
        )
        campaign_keys = [
            {"profileId": profile_id, "campaignId": campaign["campaignId"]}
            for campaign in campaigns
            if campaign.get("campaignId")
        ]
        if campaign_keys:
            deleted_count += batch_delete_keys(
                tables.campaigns, campaign_keys, ["profileId", "campaignId"], logger=logger
            )
            for campaign in campaigns:
                _verify_campaign_deleted(profile_id, campaign["campaignId"])

    logger.info("Deleted user campaigns", count=deleted_count)
    return deleted_count


def delete_user_shares(profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all outbound shares for the given profiles. Returns count deleted."""
    deleted_count = 0

    for profile in profiles:
        profile_id = profile["profileId"]
        shares = query_all_items(
            tables.shares,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
            },
        )
        share_keys = [
            {"profileId": profile_id, "targetAccountId": share["targetAccountId"]}
            for share in shares
            if share.get("targetAccountId")
        ]
        if share_keys:
            deleted_count += batch_delete_keys(
                tables.shares, share_keys, ["profileId", "targetAccountId"], logger=logger
            )

    logger.info("Deleted user shares", count=deleted_count)
    return deleted_count


def delete_user_profiles(account_id: str, profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete the given profiles. Returns count deleted."""
    db_account_id = normalize_account_id(account_id)

    profile_keys = [
        {"ownerAccountId": db_account_id, "profileId": profile["profileId"]}
        for profile in profiles
        if profile.get("profileId")
    ]
    deleted_count = (
        batch_delete_keys(tables.profiles, profile_keys, ["ownerAccountId", "profileId"], logger=logger)
        if profile_keys
        else 0
    )

    logger.info("Deleted user profiles", account_id=account_id, count=deleted_count)
    return deleted_count


def delete_invites_for_owned_profiles(profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all invites for the given profiles."""
    deleted_count = 0

    for profile in profiles:
        profile_id = profile["profileId"]
        invites = query_all_items(
            tables.invites,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
                "IndexName": "profileId-index",
            },
        )
        invite_keys = [{"inviteCode": invite["inviteCode"]} for invite in invites if invite.get("inviteCode")]
        if invite_keys:
            deleted_count += batch_delete_keys(tables.invites, invite_keys, ["inviteCode"], logger=logger)

    logger.info("Deleted invites for owned profiles", count=deleted_count)
    return deleted_count


def delete_inbound_shares(account_id: str, logger: Any) -> int:
    """Delete all inbound shares where the account is the target."""
    db_account_id = normalize_account_id(account_id)

    shares = query_all_items(
        tables.shares,
        {
            "KeyConditionExpression": "targetAccountId = :tid",
            "ExpressionAttributeValues": {":tid": db_account_id},
            "IndexName": "targetAccountId-index",
        },
    )
    share_keys = [
        {"profileId": share["profileId"], "targetAccountId": share["targetAccountId"]}
        for share in shares
        if share.get("profileId") and share.get("targetAccountId")
    ]
    deleted_count = (
        batch_delete_keys(tables.shares, share_keys, ["profileId", "targetAccountId"], logger=logger)
        if share_keys
        else 0
    )

    logger.info("Deleted inbound shares", account_id=account_id, count=deleted_count)
    return deleted_count


def delete_user_s3_reports(profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all S3 report objects and versions for the given profiles.

    Returns the count of deleted S3 report versions.
    """
    total_deleted = 0
    for profile in profiles:
        profile_id = profile.get("profileId")
        if profile_id:
            total_deleted += _delete_s3_reports(str(profile_id))

    logger.info("Deleted user S3 reports", count=total_deleted)
    return total_deleted


def delete_all_user_data(account_id: str, logger: Any = None) -> None:
    """Delete all user data from DynamoDB and S3 using shared deletion internals.

    The profiles table is swept once and the resulting list is handed to every
    sub-cascade, which only iterates it (#554).
    """
    log = logger or get_logger(__name__)

    profiles = get_user_profiles(normalize_account_id(account_id))

    delete_user_orders(profiles, log)
    delete_user_campaigns(profiles, log)
    delete_user_shares(profiles, log)
    delete_invites_for_owned_profiles(profiles, log)
    delete_inbound_shares(account_id, log)
    delete_user_s3_reports(profiles, log)
    delete_user_profiles(account_id, profiles, log)
    # Catalogs are preserved per product design and should never be deleted.
    # Delete payment method QR codes from S3 per captain decision
    delete_all_user_qr_codes(account_id, log)

    account_id_key = normalize_account_id(account_id)
    try:
        tables.accounts.delete_item(Key={"accountId": account_id_key})
        log.info("Deleted account from DynamoDB", account_id=account_id_key)
    except ClientError as e:
        log.error("Failed to delete account from DynamoDB", error=str(e), account_id=account_id_key)
        raise
    log.info("Deleted all user data from DynamoDB")
