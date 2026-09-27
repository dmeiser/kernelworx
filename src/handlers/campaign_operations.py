"""Lambda resolver for campaign order operations and deletion verification helpers."""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from botocore.exceptions import ClientError

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
_default_logger = logger

BATCH_SIZE = 25

# DynamoDB signals BatchWriteItem throttling primarily as UnprocessedItems in an
# HTTP 200 response, not as an exception, so the retry has to be bounded here.
# boto3's BatchWriter.__exit__ is `while self._items_buffer: self._flush()` and
# _flush re-appends UnprocessedItems with no cap and no sleep, which turns a
# throttled delete into a Lambda timeout instead of a retryable error.
MAX_BATCH_WRITE_ATTEMPTS = 5
BATCH_WRITE_BACKOFF_SECONDS = 0.05

_THROTTLING_ERROR_CODES = frozenset(
    {"ProvisionedThroughputExceededException", "ThrottlingException", "TooManyRequestsException"}
)


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


def _raise_delete_error(table_name: str, exc: Exception, log: Any = None) -> None:
    """Log and re-raise a batch deletion failure as an AppError."""
    target_log = log if log is not None else _default_logger
    if isinstance(exc, ClientError):
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in _THROTTLING_ERROR_CODES:
            target_log.warning(f"Batch delete from {table_name} throttled", error=str(exc), error_code=error_code)
            raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to delete data. Please retry.") from exc
        target_log.error(f"Error deleting batch from {table_name}: {str(exc)}", error_code=error_code)
    else:
        target_log.error(f"Unexpected error deleting batch from {table_name}: {str(exc)}")
    raise AppError(
        ErrorCode.INTERNAL_ERROR,
        f"Failed to delete batch from {table_name}",
    ) from exc


def _dedupe_delete_keys(keys: List[Dict[str, Any]], primary_keys: Optional[List[str]]) -> List[Dict[str, Any]]:
    """Drop duplicate deletes by primary key, keeping the last occurrence.

    Replaces boto3's ``overwrite_by_pkeys`` buffer dedup, which only ever saw
    the current flush chunk and so could not collapse a duplicate that straddled
    two chunks. For identical DeleteRequests the retained copy is equivalent;
    doing it up front also keeps the delete count honest.
    """
    if not primary_keys:
        return list(keys)

    positions: Dict[Any, int] = {}
    deduped: List[Dict[str, Any]] = []
    for key in keys:
        identity = tuple(str(key.get(name)) for name in primary_keys)
        existing = positions.get(identity)
        if existing is None:
            positions[identity] = len(deduped)
            deduped.append(key)
        else:
            deduped[existing] = key
    return deduped


def _flush_delete_requests(client: Any, table_name: str, requests: List[Dict[str, Any]], log: Any) -> None:
    """Send DeleteRequests, retrying unprocessed items with bounded backoff.

    Raises:
        AppError: RESOURCE_BUSY when items are still unprocessed after
            MAX_BATCH_WRITE_ATTEMPTS attempts, so a throttled delete surfaces as
            a retryable error rather than spinning until the Lambda times out.
    """
    pending = requests
    for attempt in range(1, MAX_BATCH_WRITE_ATTEMPTS + 1):
        response = client.batch_write_item(RequestItems={table_name: pending})
        pending = (response.get("UnprocessedItems") or {}).get(table_name) or []
        if not pending:
            return
        if attempt < MAX_BATCH_WRITE_ATTEMPTS:
            time.sleep(BATCH_WRITE_BACKOFF_SECONDS * attempt)

    log.warning(
        f"Batch delete from {table_name} left items unprocessed",
        pending_count=len(pending),
        attempts=MAX_BATCH_WRITE_ATTEMPTS,
    )
    raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to delete data. Please retry.")


def batch_delete_keys(
    table: Any,
    keys: List[Dict[str, Any]],
    primary_keys: Optional[List[str]] = None,
    *,
    logger: Any = None,
) -> int:
    """Delete a list of keys in batches of 25, returning the count deleted.

    Args:
        table: DynamoDB Table resource.
        keys: List of key dicts to delete.
        primary_keys: Optional list of primary key attribute names for deduplication.
        logger: Optional logger instance.

    Returns:
        Number of items deleted.

    Raises:
        AppError: RESOURCE_BUSY on throttling (as an exception or as
            UnprocessedItems that survive the retry cap), INTERNAL_ERROR on
            other failures.
    """
    if not keys:
        return 0

    log = logger if logger is not None else _default_logger
    table_name = getattr(table, "name", str(table))
    deduped = _dedupe_delete_keys(keys, primary_keys)
    deleted_count = 0

    for i in range(0, len(deduped), BATCH_SIZE):
        batch = deduped[i : i + BATCH_SIZE]
        requests = [{"DeleteRequest": {"Key": key}} for key in batch]
        try:
            _flush_delete_requests(table.meta.client, table_name, requests, log)
        except AppError:
            raise
        except Exception as e:
            _raise_delete_error(table_name, e, log)
        deleted_count += len(batch)
        log.info(f"Deleted batch of {len(batch)} items from {table_name}")

    return deleted_count


def delete_order_keys(orders: List[Dict[str, Any]], *, logger: Any = None) -> int:
    """Delete the given order items by primary key, returning the count deleted.

    The single shared path for deleting orders by key: every caller builds keys
    through this so the key shape (and its string coercion) lives in one place.
    """
    order_keys = [{"campaignId": str(order["campaignId"]), "orderId": str(order["orderId"])} for order in orders]
    return batch_delete_keys(
        tables.orders,
        order_keys,
        primary_keys=["campaignId", "orderId"],
        logger=logger,
    )


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


def delete_orders_for_campaign(campaign_id: str, *, logger: Any = None) -> int:
    """Delete all orders for a campaign and verify they are gone.

    Args:
        campaign_id: The campaign ID (with CAMPAIGN# prefix).
        logger: Optional logger instance.

    Returns:
        Number of orders deleted.

    Raises:
        AppError: If a deleted order is still present afterwards or deletion fails.
    """
    orders = _query_order_keys_for_campaign(campaign_id)
    if not orders:
        return 0

    log = logger if logger is not None else _default_logger
    deleted_count = delete_order_keys(orders, logger=log)
    _verify_order_keys_deleted(orders)

    log.info("Deleted orders for campaign", campaign_id=campaign_id, count=deleted_count)
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

    deleted_count = delete_orders_for_campaign(db_campaign_id)
    return {"deletedCount": deleted_count}
