import os
import time
from typing import TYPE_CHECKING, Any, Dict, List

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.service_resource import Table

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id, ensure_profile_id
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id, ensure_profile_id
    from ..utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.pagination import query_all_items
else:  # pragma: no cover
    try:
        from utils.pagination import query_all_items
    except ModuleNotFoundError:
        from ..utils.pagination import query_all_items

logger = get_logger(__name__)

BATCH_SIZE = 25
_PROFILE_LOOKUP_RETRIES = 3
_PROFILE_LOOKUP_DELAY_SECONDS = 0.1

s3_client: Any = None


def _get_s3_client() -> Any:
    """Return S3 client, supporting module-level mock for testing."""
    global s3_client
    if s3_client is not None:
        return s3_client
    return boto3.client("s3")


def _raise_delete_error(table_name: str, exc: Exception) -> None:
    """Log and re-raise a batch deletion failure as an AppError."""
    label = "Error" if isinstance(exc, ClientError) else "Unexpected error"
    logger.error(f"{label} deleting batch from {table_name}: {str(exc)}")
    raise AppError(
        ErrorCode.INTERNAL_ERROR,
        f"Failed to delete batch from {table_name}",
    ) from exc


def _batch_delete_keys(table: "Table", keys: List[Dict[str, Any]], primary_keys: List[str]) -> int:
    """Delete a list of keys in batches of 25, returning the number deleted.

    Raises:
        AppError: If any batch cannot be deleted.
    """
    if not keys:
        return 0

    table_name = table.name
    deleted_count = 0

    for i in range(0, len(keys), BATCH_SIZE):
        batch = keys[i : i + BATCH_SIZE]
        try:
            with table.batch_writer(overwrite_by_pkeys=primary_keys) as batch_writer:
                for key in batch:
                    batch_writer.delete_item(Key=key)
            deleted_count += len(batch)
            logger.info(f"Deleted batch of {len(batch)} items from {table_name}")
        except Exception as e:
            _raise_delete_error(table_name, e)

    return deleted_count


def _get_profile_owner_id(profile_id: str) -> str:
    """Look up the owner account ID for a profile via its GSI.

    GSIs are eventually consistent, so the lookup retries briefly when the
    profile is not yet visible after creation.
    """
    for attempt in range(1, _PROFILE_LOOKUP_RETRIES + 1):
        response = tables.profiles.query(
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
            Limit=1,
        )
        items = response.get("Items", [])
        if items:
            return str(items[0]["ownerAccountId"])
        if attempt < _PROFILE_LOOKUP_RETRIES:
            time.sleep(_PROFILE_LOOKUP_DELAY_SECONDS)

    raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")


def _collect_order_keys(campaigns: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Collect all order keys for all campaigns."""
    order_keys: List[Dict[str, str]] = []
    for campaign in campaigns:
        campaign_id = campaign.get("campaignId")
        if not campaign_id:
            logger.warning("Campaign missing campaignId, skipping order query")
            continue
        orders = query_all_items(
            tables.orders,
            {
                "KeyConditionExpression": "campaignId = :cid",
                "ExpressionAttributeValues": {":cid": campaign_id},
                "ProjectionExpression": "campaignId, orderId",
            },
        )
        for order in orders:
            order_keys.append(
                {
                    "campaignId": str(order["campaignId"]),
                    "orderId": str(order["orderId"]),
                }
            )
    return order_keys


def _delete_orders(order_keys: List[Dict[str, str]]) -> int:
    """Delete all orders for a profile."""
    return _batch_delete_keys(tables.orders, order_keys, ["campaignId", "orderId"])


def _delete_campaigns(profile_id: str, campaigns: List[Dict[str, Any]]) -> int:
    """Delete all campaigns for a profile."""
    keys = [
        {"profileId": profile_id, "campaignId": str(campaign["campaignId"])}
        for campaign in campaigns
        if campaign.get("campaignId")
    ]
    return _batch_delete_keys(tables.campaigns, keys, ["profileId", "campaignId"])


def _delete_shares(profile_id: str, shares: List[Dict[str, Any]]) -> int:
    """Delete all shares for a profile."""
    keys = [
        {"profileId": profile_id, "targetAccountId": str(share["targetAccountId"])}
        for share in shares
        if share.get("targetAccountId")
    ]
    return _batch_delete_keys(tables.shares, keys, ["profileId", "targetAccountId"])


def _delete_invites(invites: List[Dict[str, Any]]) -> int:
    """Delete all invites for a profile."""
    keys = [{"inviteCode": str(invite["inviteCode"])} for invite in invites if invite.get("inviteCode")]
    return _batch_delete_keys(tables.invites, keys, ["inviteCode"])


def _delete_shared_campaigns(campaigns: List[Dict[str, Any]], owner_account_id: str) -> int:
    """Delete shared campaigns created by the profile owner."""
    deleted_count = 0
    seen_codes: set[str] = set()
    normalized_owner = ensure_account_id(owner_account_id)
    for campaign in campaigns:
        code = campaign.get("sharedCampaignCode")
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        try:
            items = query_all_items(
                tables.shared_campaigns,
                {
                    "KeyConditionExpression": "sharedCampaignCode = :code",
                    "ExpressionAttributeValues": {":code": code},
                },
            )
            for item in items:
                created_by = item.get("createdBy", "")
                if created_by in (owner_account_id, normalized_owner):
                    key: Dict[str, Any] = {"sharedCampaignCode": code}
                    if "SK" in item:
                        key["SK"] = item["SK"]
                    tables.shared_campaigns.delete_item(Key=key)
                    deleted_count += 1
                    logger.info(f"Deleted shared campaign {code}")
        except Exception as e:
            logger.warning(f"Failed to delete shared campaign {code}: {str(e)}")
    return deleted_count


def _delete_s3_reports(profile_id: str) -> int:
    """Delete all S3 report objects for this profile."""
    bucket_name = os.environ.get("EXPORTS_BUCKET")
    if not bucket_name:
        return 0

    s3 = _get_s3_client()
    deleted_count = 0
    prefixes = [f"reports/{profile_id}/"]
    clean_id = profile_id.replace("PROFILE#", "")
    if clean_id != profile_id:
        prefixes.append(f"reports/{clean_id}/")

    for prefix in set(prefixes):
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
                objects = [{"Key": obj["Key"]} for obj in page.get("Contents", []) if "Key" in obj]
                if objects:
                    s3.delete_objects(Bucket=bucket_name, Delete={"Objects": objects})
                    deleted_count += len(objects)
                    logger.info(f"Deleted {len(objects)} report objects from S3 under {prefix}")
        except Exception as e:
            logger.warning(f"Error cleaning up S3 reports under {prefix}: {str(e)}")

    return deleted_count


def _delete_profile(owner_account_id: str, profile_id: str) -> None:
    """Delete the profile metadata record."""
    try:
        tables.profiles.delete_item(Key={"ownerAccountId": owner_account_id, "profileId": profile_id})
    except Exception as e:
        logger.error(f"Error deleting profile metadata: {str(e)}")
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete profile metadata")


def lambda_handler(event: Dict[str, Any], context: Any) -> bool:
    """Cascade-delete a profile and all related data.

    Args:
        event: Lambda event from AppSync. Contains:
            - arguments: { profileId: str }
        context: Lambda context

    Returns:
        True on success

    Raises:
        ValueError: If profileId is missing
        AppError: If authorization fails or deletion fails
    """
    profile_id = event.get("arguments", {}).get("profileId")
    if not profile_id:
        raise ValueError("profileId is required")

    db_profile_id = ensure_profile_id(profile_id)
    # ensure_profile_id only returns None for falsy input, which is guarded above
    assert db_profile_id is not None

    caller_account_id = event.get("identity", {}).get("sub")
    if not caller_account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

    owner_account_id = _get_profile_owner_id(db_profile_id)
    db_caller_id = ensure_account_id(caller_account_id)
    if owner_account_id != db_caller_id:
        raise AppError(ErrorCode.FORBIDDEN, "Only profile owner can delete a profile")

    logger.info(f"Starting cascade delete for profile {db_profile_id}")

    shares = query_all_items(
        tables.shares,
        {
            "KeyConditionExpression": "profileId = :pid",
            "ExpressionAttributeValues": {":pid": db_profile_id},
        },
    )
    invites = query_all_items(
        tables.invites,
        {
            "IndexName": "profileId-index",
            "KeyConditionExpression": "profileId = :pid",
            "ExpressionAttributeValues": {":pid": db_profile_id},
        },
    )
    campaigns = query_all_items(
        tables.campaigns,
        {
            "KeyConditionExpression": "profileId = :pid",
            "ExpressionAttributeValues": {":pid": db_profile_id},
        },
    )

    order_keys = _collect_order_keys(campaigns)

    orders_deleted = _delete_orders(order_keys)
    reports_deleted = _delete_s3_reports(db_profile_id)
    shared_campaigns_deleted = _delete_shared_campaigns(campaigns, owner_account_id)
    campaigns_deleted = _delete_campaigns(db_profile_id, campaigns)
    shares_deleted = _delete_shares(db_profile_id, shares)
    invites_deleted = _delete_invites(invites)

    _delete_profile(owner_account_id, db_profile_id)

    logger.info(
        f"Cascade delete complete for profile {db_profile_id}: "
        f"orders={orders_deleted}, campaigns={campaigns_deleted}, "
        f"shares={shares_deleted}, invites={invites_deleted}, "
        f"shared_campaigns={shared_campaigns_deleted}, reports={reports_deleted}"
    )
    return True
