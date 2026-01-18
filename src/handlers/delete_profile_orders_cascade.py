"""Lambda resolver to delete all orders when a profile is deleted (cascade delete)."""

from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.service_resource import Table

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.ids import ensure_profile_id
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.ids import ensure_profile_id
    from ..utils.logging import get_logger

logger = get_logger(__name__)


def _query_campaign_orders(orders_table: "Table", campaign_id: str) -> List[Dict[str, str]]:
    """Query all order keys for a single campaign.

    Args:
        orders_table: DynamoDB table resource
        campaign_id: Campaign ID to query orders for

    Returns:
        List of order key dictionaries with campaignId and orderId
    """
    order_keys: List[Dict[str, str]] = []
    last_evaluated_key: Dict[str, Any] | None = None

    while True:
        query_kwargs: Dict[str, Any] = {
            "KeyConditionExpression": "campaignId = :campaignId",
            "ExpressionAttributeValues": {":campaignId": campaign_id},
            "ProjectionExpression": "campaignId, orderId",
        }

        if last_evaluated_key is not None:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        response = orders_table.query(**query_kwargs)

        for item in response.get("Items", []):
            order_keys.append({
                "campaignId": str(item["campaignId"]),
                "orderId": str(item["orderId"]),
            })

        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break

    return order_keys


def _collect_all_order_keys(
    orders_table: "Table", campaigns_to_delete: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """Collect all order keys from all campaigns.

    Args:
        orders_table: DynamoDB table resource
        campaigns_to_delete: List of campaign dictionaries

    Returns:
        List of all order key dictionaries
    """
    all_order_keys: List[Dict[str, str]] = []

    for campaign in campaigns_to_delete:
        campaign_id = campaign.get("campaignId")
        if not campaign_id:
            logger.warning("Campaign missing campaignId, skipping")
            continue

        try:
            order_keys = _query_campaign_orders(orders_table, campaign_id)
            all_order_keys.extend(order_keys)
        except Exception as e:
            logger.error(f"Error querying orders for campaign {campaign_id}: {str(e)}")
            continue

    return all_order_keys


def _batch_delete_orders(orders_table: "Table", all_order_keys: List[Dict[str, str]]) -> int:
    """Delete orders in batches.

    Args:
        orders_table: DynamoDB table resource
        all_order_keys: List of order key dictionaries to delete

    Returns:
        Number of orders deleted
    """
    orders_deleted = 0
    batch_size = 25

    for i in range(0, len(all_order_keys), batch_size):
        batch = all_order_keys[i : i + batch_size]

        try:
            with orders_table.batch_writer(overwrite_by_pkeys=["campaignId", "orderId"]) as batch_writer:
                for order_key in batch:
                    batch_writer.delete_item(Key=order_key)

            orders_deleted += len(batch)
            logger.info(f"Deleted batch of {len(batch)} orders (total: {orders_deleted})")
        except Exception as e:
            logger.error(f"Error deleting batch of orders: {str(e)}")
            continue

    return orders_deleted


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete all orders for all campaigns in a profile.

    Args:
        event: Lambda event from AppSync. Contains:
            - arguments: { profileId: str }
            - stash: { campaignsToDelete: List[Dict] }
        context: Lambda context

    Returns:
        { ordersDeleted: int }

    Raises:
        ValueError: If profileId is missing
    """
    profile_id = event.get("arguments", {}).get("profileId")
    if not profile_id:
        raise ValueError("profileId is required")

    db_profile_id = ensure_profile_id(profile_id)
    campaigns_to_delete = event.get("stash", {}).get("campaignsToDelete", [])
    logger.info(f"Deleting orders for {len(campaigns_to_delete)} campaigns in profile {db_profile_id}")

    orders_table: "Table" = tables.orders
    all_order_keys = _collect_all_order_keys(orders_table, campaigns_to_delete)
    logger.info(f"Found {len(all_order_keys)} orders to delete")

    orders_deleted = _batch_delete_orders(orders_table, all_order_keys)
    logger.info(f"Successfully deleted {orders_deleted} orders for profile {db_profile_id}")

    return {"ordersDeleted": orders_deleted}
