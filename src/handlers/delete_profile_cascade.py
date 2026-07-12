"""Lambda resolver to cascade-delete a profile and all related data."""

from typing import TYPE_CHECKING, Any, Dict, List

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

logger = get_logger(__name__)

BATCH_SIZE = 25


def _query_all_items(
    table: "Table",
    key_condition: str,
    expression_values: Dict[str, Any],
    index_name: str | None = None,
    projection: str | None = None,
) -> List[Dict[str, Any]]:
    """Query all items for a given key condition, handling pagination."""
    items: List[Dict[str, Any]] = []
    last_evaluated_key: Dict[str, Any] | None = None

    while True:
        query_kwargs: Dict[str, Any] = {
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeValues": expression_values,
        }
        if index_name is not None:
            query_kwargs["IndexName"] = index_name
        if projection is not None:
            query_kwargs["ProjectionExpression"] = projection
        if last_evaluated_key is not None:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break

    return items


def _batch_delete_keys(table: "Table", keys: List[Dict[str, Any]], primary_keys: List[str]) -> int:
    """Delete a list of keys in batches of 25, returning the number deleted."""
    if not keys:
        return 0

    deleted_count = 0
    for i in range(0, len(keys), BATCH_SIZE):
        batch = keys[i : i + BATCH_SIZE]
        try:
            with table.batch_writer(overwrite_by_pkeys=primary_keys) as batch_writer:
                for key in batch:
                    batch_writer.delete_item(Key=key)
            deleted_count += len(batch)
            logger.info(f"Deleted batch of {len(batch)} items from {table.name}")
        except Exception as e:
            logger.error(f"Error deleting batch from {table.name}: {str(e)}")

    return deleted_count


def _get_profile_owner_id(profile_id: str) -> str:
    """Look up the owner account ID for a profile via its GSI."""
    response = tables.profiles.query(
        IndexName="profileId-index",
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": profile_id},
        Limit=1,
    )
    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")
    return str(items[0]["ownerAccountId"])


def _collect_order_keys(campaigns: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Collect all order keys for all campaigns."""
    order_keys: List[Dict[str, str]] = []
    for campaign in campaigns:
        campaign_id = campaign.get("campaignId")
        if not campaign_id:
            logger.warning("Campaign missing campaignId, skipping order query")
            continue
        orders = _query_all_items(
            tables.orders,
            "campaignId = :cid",
            {":cid": campaign_id},
            projection="campaignId, orderId",
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

    shares = _query_all_items(
        tables.shares,
        "profileId = :pid",
        {":pid": db_profile_id},
    )
    invites = _query_all_items(
        tables.invites,
        "profileId = :pid",
        {":pid": db_profile_id},
        index_name="profileId-index",
    )
    campaigns = _query_all_items(
        tables.campaigns,
        "profileId = :pid",
        {":pid": db_profile_id},
    )

    order_keys = _collect_order_keys(campaigns)

    orders_deleted = _delete_orders(order_keys)
    campaigns_deleted = _delete_campaigns(db_profile_id, campaigns)
    shares_deleted = _delete_shares(db_profile_id, shares)
    invites_deleted = _delete_invites(invites)

    _delete_profile(owner_account_id, db_profile_id)

    logger.info(
        f"Cascade delete complete for profile {db_profile_id}: "
        f"orders={orders_deleted}, campaigns={campaigns_deleted}, "
        f"shares={shares_deleted}, invites={invites_deleted}"
    )
    return True
