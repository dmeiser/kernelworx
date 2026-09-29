"""
Account-deletion cascade internals.

This module owns the per-account deletion cascade shared by ``deleteMyAccount``
(:mod:`src.handlers.account_operations`) and ``adminDeleteUser``
(:mod:`src.handlers.admin_operations`). Both of those handlers used to reach into
each other's private helpers, and the resulting import cycle forced every
sub-cascade to paginate the caller's profile list independently — six redundant
``Query`` sweeps of the same data for a single account deletion (#554).

The cascade lives here so the dependency runs one way: this module imports only
``utils`` and the lower-level campaign/profile-cascade helpers, and both handler
modules import it at module scope. ``delete_all_user_data`` reads the profile
list once and hands it to each sub-cascade, so the profile sweep is a genuine
single read regardless of how many sub-cascades run.
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

# Handle both Lambda (absolute) and unit test (relative) imports.  mypy sees the
# relative path it can resolve; the runtime fallback tries absolute first for Lambda.
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.ids import normalize_account_id
    from ..utils.logging import get_logger
    from ..utils.pagination import query_all_items
    from ..utils.payment_methods import delete_all_user_qr_codes
else:  # pragma: no cover
    try:
        from utils.dynamodb import tables
        from utils.ids import normalize_account_id
        from utils.logging import get_logger
        from utils.pagination import query_all_items
        from utils.payment_methods import delete_all_user_qr_codes
    except ModuleNotFoundError:
        from ..utils.dynamodb import tables
        from ..utils.ids import normalize_account_id
        from ..utils.logging import get_logger
        from ..utils.pagination import query_all_items
        from ..utils.payment_methods import delete_all_user_qr_codes


logger = get_logger(__name__)


def get_user_profiles(db_account_id: str) -> list[Dict[str, Any]]:
    """Get all profiles owned by an account, paginating the whole partition.

    This is the single profile read for a deletion cascade; callers that need
    several sub-cascades must read once and pass the result down.
    """
    return query_all_items(
        tables.profiles,
        {
            "KeyConditionExpression": "ownerAccountId = :owner",
            "ExpressionAttributeValues": {":owner": db_account_id},
        },
    )


def delete_user_orders(account_id: str, profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all orders for all campaigns of the supplied profiles.

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

    logger.info("Deleted user orders", account_id=account_id, count=deleted_count)
    return deleted_count


def delete_user_campaigns(account_id: str, profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all campaigns for the supplied profiles.

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

    logger.info("Deleted user campaigns", account_id=account_id, count=deleted_count)
    return deleted_count


def delete_user_shares(account_id: str, profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all shares for the supplied profiles. Returns count deleted."""
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

    logger.info("Deleted user shares", account_id=account_id, count=deleted_count)
    return deleted_count


def delete_user_profiles(account_id: str, profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete the supplied profiles. Returns count deleted."""
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


def delete_invites_for_owned_profiles(account_id: str, profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all invites for the supplied profiles."""
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

    logger.info("Deleted invites for owned profiles", account_id=account_id, count=deleted_count)
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


def delete_user_s3_reports(account_id: str, profiles: list[Dict[str, Any]], logger: Any) -> int:
    """Delete all S3 report objects and versions for the supplied profiles.

    Returns the count of deleted S3 report versions.
    """
    total_deleted = 0
    for profile in profiles:
        profile_id = profile.get("profileId")
        if profile_id:
            total_deleted += _delete_s3_reports(str(profile_id))

    logger.info("Deleted user S3 reports", account_id=account_id, count=total_deleted)
    return total_deleted


def delete_all_user_data(account_id: str, logger: Any = None) -> None:
    """Delete all user data from DynamoDB and S3 using shared deletion internals.

    The caller's profile list is read once here and handed to every sub-cascade
    that needs it, so a deletion costs one profile ``Query`` rather than one per
    sub-cascade (#554).
    """
    log = logger or get_logger(__name__)

    profiles = get_user_profiles(normalize_account_id(account_id))

    delete_user_orders(account_id, profiles, log)
    delete_user_campaigns(account_id, profiles, log)
    delete_user_shares(account_id, profiles, log)
    delete_invites_for_owned_profiles(account_id, profiles, log)
    delete_inbound_shares(account_id, log)
    delete_user_s3_reports(account_id, profiles, log)
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
