"""Lambda resolver to delete all orders when a profile is deleted (cascade delete)."""

from typing import TYPE_CHECKING, Any, Dict, List

import boto3

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
        Exception: If DynamoDB operations fail
    """
    # Extract inputs from AppSync event
    profile_id = event.get("arguments", {}).get("profileId")
    if not profile_id:
        raise ValueError("profileId is required")

    # Ensure profile_id has PROFILE# prefix for consistent DynamoDB key format
    db_profile_id = ensure_profile_id(profile_id)

    # Get campaigns to delete from stash (populated by previous pipeline step)
    campaigns_to_delete = event.get("stash", {}).get("campaignsToDelete", [])
    logger.info(f"Deleting orders for {len(campaigns_to_delete)} campaigns in profile {db_profile_id}")

    # Get DynamoDB resource for batch operations
    orders_table: "Table" = tables.orders

    # Collect all order keys to delete
    all_order_keys: List[Dict[str, str]] = []

    # For each campaign, query all orders and collect keys
    for campaign in campaigns_to_delete:
        campaign_id = campaign.get("campaignId")
        if not campaign_id:
            logger.warning("Campaign missing campaignId, skipping")
            continue

        # Query all orders for this campaign
        try:
            response = orders_table.query(
                KeyConditionExpression="campaignId = :campaignId",
                ExpressionAttributeValues={":campaignId": campaign_id},
                ProjectionExpression="campaignId, orderId",  # Only need keys for deletion
            )

            # Collect order keys for batch deletion
            for item in response.get("Items", []):
                all_order_keys.append(
                    {
                        "campaignId": str(item["campaignId"]),
                        "orderId": str(item["orderId"]),
                    }
                )
        except Exception as e:
            logger.error(f"Error querying orders for campaign {campaign_id}: {str(e)}")
            # Continue with next campaign rather than failing entirely
            continue

    logger.info(f"Found {len(all_order_keys)} orders to delete")

    # Batch delete orders (DynamoDB supports up to 25 items per batch_write_item call)
    orders_deleted = 0
    batch_size = 25

    for i in range(0, len(all_order_keys), batch_size):
        batch = all_order_keys[i : i + batch_size]

        try:
            # Use batch_write_item to delete multiple orders efficiently
            with orders_table.batch_writer(overwrite_by_pkeys=["campaignId", "orderId"]) as batch_writer:
                for order_key in batch:
                    # Delete item via batch writer
                    batch_writer.delete_item(Key=order_key)

            orders_deleted += len(batch)
            logger.info(f"Deleted batch of {len(batch)} orders (total: {orders_deleted})")

        except Exception as e:
            logger.error(f"Error deleting batch of orders: {str(e)}")
            # Continue with next batch rather than failing entirely
            continue

    logger.info(f"Successfully deleted {orders_deleted} orders for profile {db_profile_id}")

    return {"ordersDeleted": orders_deleted}
