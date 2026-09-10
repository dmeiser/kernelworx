"""Lambda resolver for campaign order operations and deletion verification helpers."""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import require_profile_access
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_campaign_id
    from utils.logging import get_logger
    from utils.pagination import query_all_items
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import require_profile_access
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_campaign_id
    from ..utils.logging import get_logger
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


logger = get_logger(__name__)

BATCH_DELETE_SIZE = 25


def _get_campaign_by_id(campaign_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a campaign by its campaignId via the campaignId-index GSI.

    Args:
        campaign_id: The campaign ID (with CAMPAIGN# prefix).

    Returns:
        The campaign item or None if not found.
    """
    response = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :campaignId",
        ExpressionAttributeValues={":campaignId": campaign_id},
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else None


def _query_order_keys_for_campaign(campaign_id: str) -> List[Dict[str, Any]]:
    """Return the order keys (campaignId, orderId) for a campaign."""
    orders: List[Dict[str, Any]] = query_all_items(
        tables.orders,
        {
            "KeyConditionExpression": "campaignId = :cid",
            "ExpressionAttributeValues": {":cid": campaign_id},
            "ProjectionExpression": "campaignId, orderId",
        },
    )
    return orders


def _delete_order_keys(orders: List[Dict[str, Any]]) -> int:
    """Delete a list of order keys in batches, returning the count deleted."""
    deleted_count = 0
    for i in range(0, len(orders), BATCH_DELETE_SIZE):
        batch = orders[i : i + BATCH_DELETE_SIZE]
        with tables.orders.batch_writer(overwrite_by_pkeys=["campaignId", "orderId"]) as writer:
            for order in batch:
                writer.delete_item(
                    Key={
                        "campaignId": str(order["campaignId"]),
                        "orderId": str(order["orderId"]),
                    }
                )
        deleted_count += len(batch)
    return deleted_count


def _verify_order_keys_deleted(order_keys: List[Dict[str, Any]]) -> None:
    """Verify deleted orders are absent from the base table.

    Uses a strongly consistent read on each exact key that was deleted, which
    deterministically reflects the completed deletes. The orderId-index GSI
    cannot be used here: it is eventually consistent and can keep showing
    deleted rows for an unbounded time. Raises AppError if any key persists.
    """
    for key in order_keys:
        response = tables.orders.get_item(
            Key={"campaignId": str(key["campaignId"]), "orderId": str(key["orderId"])},
            ConsistentRead=True,
        )
        if response.get("Item"):
            logger.error(
                "Order still present after delete verification",
                campaign_id=key["campaignId"],
                order_id=key["orderId"],
            )
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete order")


def _verify_campaign_deleted(profile_id: str, campaign_id: str) -> None:
    """Verify a deleted campaign is absent from the base table.

    Uses a strongly consistent read on the exact key that was deleted, which
    deterministically reflects the completed delete. The campaignId-index GSI
    cannot be used here: it is eventually consistent and can keep showing a
    deleted row for an unbounded time. Raises AppError if the key persists.
    """
    response = tables.campaigns.get_item(
        Key={"profileId": profile_id, "campaignId": campaign_id},
        ConsistentRead=True,
    )
    if response.get("Item"):
        logger.error(
            "Campaign still present after delete verification",
            profile_id=profile_id,
            campaign_id=campaign_id,
        )
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete campaign")


def _delete_orders_for_campaign(campaign_id: str) -> int:
    """Delete all orders for a campaign and verify they are gone.

    Args:
        campaign_id: The campaign ID (with CAMPAIGN# prefix).

    Returns:
        Number of orders deleted.

    Raises:
        AppError: If a deleted order is still present afterwards.
    """
    orders = _query_order_keys_for_campaign(campaign_id)
    if not orders:
        return 0

    deleted_count = _delete_order_keys(orders)
    _verify_order_keys_deleted(orders)

    logger.info("Deleted orders for campaign", campaign_id=campaign_id, count=deleted_count)
    return deleted_count


@with_error_handling(error_message="Failed to delete campaign orders")
def delete_campaign_orders(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete all orders for a campaign (AppSync Lambda resolver).

    Expects event.arguments.campaignId. Returns { deletedCount: int }.

    Verifies with strongly consistent reads that each deleted order is gone
    from the orders table before returning success. Raises AppError if a
    deleted order is still present.

    Authorization: the caller must have WRITE access to the profile that owns the
    campaign. This is enforced here in the handler so a resolver rewire or a
    second datasource cannot bypass it.
    """
    campaign_id_arg = event.get("arguments", {}).get("campaignId", "")
    if not campaign_id_arg:
        raise AppError(ErrorCode.INVALID_INPUT, "campaignId is required")

    caller_account_id = event.get("identity", {}).get("sub")
    if not caller_account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Caller identity is required")

    db_campaign_id = ensure_campaign_id(campaign_id_arg)
    assert db_campaign_id is not None

    campaign = _get_campaign_by_id(db_campaign_id)
    if not campaign:
        raise AppError(ErrorCode.NOT_FOUND, f"Campaign {campaign_id_arg} not found")

    profile_id = campaign.get("profileId")
    if not profile_id:
        raise AppError(ErrorCode.NOT_FOUND, f"Campaign {campaign_id_arg} has no profile")

    require_profile_access(caller_account_id, profile_id, "WRITE")

    deleted_count = _delete_orders_for_campaign(db_campaign_id)
    return {"deletedCount": deleted_count}
