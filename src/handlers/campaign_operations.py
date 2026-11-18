"""Lambda resolver for campaign order operations and deletion verification helpers."""

import time
from typing import TYPE_CHECKING, Any, Dict, List, NoReturn, Optional, Tuple

import botocore.exceptions

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.auth import require_profile_access
    from utils.dynamodb import batch_get_chunked, get_required_env, tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_campaign_id
    from utils.logging import get_logger
    from utils.pagination import query_all_items
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.auth import require_profile_access
    from ..utils.dynamodb import batch_get_chunked, get_required_env, tables
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


def _raise_delete_error(table_name: str, exc: Exception, log: Any = None) -> NoReturn:
    """Translate a failed batch deletion into a typed AppError via the shared classifier.

    Reuses `admin_operations._raise_batch_lookup_error` (the single
    classify-and-raise helper) instead of re-implementing the transient/permanent
    split. The import is function-level: a top-level import would be circular
    (`admin_operations` -> `deletion_cascade` -> `campaign_operations`).
    """
    from .admin_operations import _raise_batch_lookup_error

    target_log = log if log is not None else _default_logger
    _raise_batch_lookup_error(
        f"delete batch from {table_name}",
        target_log,
        exc,
        busy_message="Temporarily unable to delete data. Please retry.",
    )


def _drop_duplicate_delete_keys(keys: List[Dict[str, Any]], primary_keys: Optional[List[str]]) -> List[Dict[str, Any]]:
    """Drop duplicate deletes by primary key, keeping the last occurrence.

    Replaces boto3's ``overwrite_by_pkeys`` buffer dedup, which only ever saw
    the current flush chunk and so could not collapse a duplicate that straddled
    two chunks. For identical DeleteRequests the retained copy is equivalent;
    doing it up front also keeps the delete count honest.
    """
    if not primary_keys:
        return list(keys)

    positions: Dict[Any, int] = {}
    unique: List[Dict[str, Any]] = []
    for key in keys:
        identity = tuple(str(key.get(name)) for name in primary_keys)
        existing = positions.get(identity)
        if existing is None:
            positions[identity] = len(unique)
            unique.append(key)
        else:
            unique[existing] = key
    return unique


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
    unique = _drop_duplicate_delete_keys(keys, primary_keys)
    deleted_count = 0

    for i in range(0, len(unique), BATCH_SIZE):
        batch = unique[i : i + BATCH_SIZE]
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


# The Order row's fulfillment version attribute. Its owner is
# `src/utils/order_fulfillment_models.py`; the name is repeated here for the same
# reason the fulfillment partition Query below is spelled locally -- see
# `_fulfillment_version_delete_condition`.
ORDER_FULFILLMENT_VERSION_ATTRIBUTE = "fulfillmentVersion"


def _fulfillment_version_delete_condition(expected_version: int) -> Dict[str, Any]:
    """The guard that makes deleting an Order safe against a concurrent fulfillment.

    The condition is the one `order_fulfillment_models.fulfillment_version_condition`
    owns, spelled locally because this module must not import that one: it drags
    `inventory` and `units` into the import closure of Lambdas that never read them, and
    the closure gate (`tests/unit/test_lambda_table_env_closure.py`) would then demand
    env vars those functions have no use for. The only difference is encoding: the owner
    feeds the low-level client and returns `wire_value` form, while this delete goes
    through the resource client, which marshals a Python number itself.
    `tests/unit/test_order_fulfillment_operations.py` fails if the two expressions
    disagree, so the duplication is checked rather than trusted.

    Why a DELETE needs a version guard at all: a fulfillment or a reversal is one
    transaction that moves the Order row's `fulfillmentVersion` and writes its
    `OrderFulfillment` row together, and that UpdateItem requires
    `attribute_exists(#orderId)`. So an Order whose version still equals what this
    cascade read cannot have gained a fulfillment row since that read, and deleting it
    cannot orphan anything; an Order whose version moved fails this condition and STAYS
    in the table, where the next cascade run still sees it. That is what makes a
    deletion retryable instead of terminal: the parent row, not the cascade's memory,
    records which partition still needs cleanup.
    """
    placeholder = f"#{ORDER_FULFILLMENT_VERSION_ATTRIBUTE}"
    equality = f"{placeholder} = :expectedFulfillmentVersion"
    version_test = f"(attribute_not_exists({placeholder}) OR {equality})" if expected_version == 0 else equality
    return {
        "ConditionExpression": f"{version_test} AND attribute_exists(#orderId)",
        "ExpressionAttributeNames": {
            placeholder: ORDER_FULFILLMENT_VERSION_ATTRIBUTE,
            "#orderId": "orderId",
        },
        "ExpressionAttributeValues": {":expectedFulfillmentVersion": expected_version},
    }


def _order_fulfillment_version(order: Dict[str, Any]) -> int:
    """The version to pin a delete to: the stored value, or 0 for a pre-Wave-3 row."""
    raw = order.get(ORDER_FULFILLMENT_VERSION_ATTRIBUTE)
    return 0 if raw is None else int(raw)


def _read_order_for_delete(campaign_id: str, order_id: str) -> Optional[Dict[str, Any]]:
    """One strongly consistent read of the Order this cascade is about to delete.

    Consistent, and BEFORE the history sweep, on purpose. The version this read returns
    is the pin the delete carries; a version read after the sweep would already include
    a fulfillment that landed during the sweep -- a row the sweep never saw, and that the
    delete would then orphan.
    """
    response = tables.orders.get_item(
        Key={"campaignId": campaign_id, "orderId": order_id},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return item if isinstance(item, dict) else None


def _delete_order_pinned(campaign_id: str, order_id: str, observed_version: int, log: Any) -> None:
    """Delete one Order, or leave it and its history in place for the next run.

    A failed condition is the retryable case, not a lost delete: something fulfilled
    this Order after this cascade read it, so nothing was removed, and re-reading the
    Order and sweeping it again is the whole remedy.
    """
    try:
        tables.orders.delete_item(
            Key={"campaignId": campaign_id, "orderId": order_id},
            **_fulfillment_version_delete_condition(observed_version),
        )
    except botocore.exceptions.ClientError as error:
        if error.response.get("Error", {}).get("Code", "") == "ConditionalCheckFailedException":
            log.warning(
                "Order changed while its delete was in flight; the order and its history stay for the retry",
                campaign_id=campaign_id,
                order_id=order_id,
                observed_version=observed_version,
            )
            raise AppError(
                ErrorCode.CONFLICT,
                f"Order {order_id} was fulfilled while its delete was in flight; "
                "nothing was deleted for it, re-read and retry",
            ) from error
        _raise_delete_error(_table_name(tables.orders, "ORDERS_TABLE_NAME"), error, log)


def delete_order_and_fulfillments(campaign_id: str, order_id: str, *, logger: Any = None) -> Tuple[bool, int]:
    """Delete one Order together with its fulfillment history.

    Returns `(order_deleted, fulfillment_records_deleted)`.

    Three steps, and their order is the whole design:

    1. Read the Order strongly and take its `fulfillmentVersion`.
    2. Sweep every fulfillment and reversal row it owns (consistently, paged, batched)
       and refuse to continue while any swept record survives the batch.
    3. Delete the Order conditioned on the version read in step 1.

    That ordering is what closes the gap the reviewer found in the batch form. Deleting
    all Orders first and sweeping their history afterwards leaves a window in which a
    fulfillment can commit; if the cleanup after that window fails, the Orders are
    already gone and the next run has no record of which partitions still need sweeping,
    so the surviving rows are orphaned forever. Here an Order can only disappear through
    a write that proves nothing fulfilled it after step 1, so "the Orders are gone" is
    evidence that its history is gone too -- and any failure instead leaves the Order
    readable, which is what a retry needs.

    An Order that is already absent is not an error: whoever removed it was itself
    pinned, so it took this Order's history with it.
    """
    log = logger if logger is not None else _default_logger
    order = _read_order_for_delete(campaign_id, order_id)
    if order is None:
        return False, 0

    fulfillment_records = delete_fulfillments_for_orders([order_id], logger=log)
    _delete_order_pinned(campaign_id, order_id, _order_fulfillment_version(order), log)
    return True, fulfillment_records


# The fulfillment partition's key grammar and item shape live in
# `src/utils/order_fulfillment_models.py`; this module reads only the KEY PAIRS of the
# optional `campaignId-createdAt-index` (data model §6.5) for a delete sweep. The query is
# spelled here rather than imported from that module on purpose: the closure gate
# (`tests/unit/test_lambda_table_env_closure.py`) names an env var for every table a
# deployed function's import graph can reach, and importing the fulfillment model would
# put `inventory` and `units` in the closure of five Lambdas that never read them. A
# delete sweep should cost the tables it touches.
def fulfillment_keys_for_orders(order_ids: List[str]) -> List[Dict[str, str]]:
    """Every fulfillment and reversal row keyed by these Orders.

    Read from the base table, one strongly consistent partition Query per Order, and
    deliberately NOT through the optional `campaignId-createdAt-index`: a global secondary
    index cannot be read consistently (DynamoDB rejects the request outright), so an index
    sweep can silently miss a fulfillment committed moments before the delete and leave
    behind exactly the orphan this sweep exists to remove. The per-Order cost matches the
    posture this module already takes for the Orders themselves, which are verified gone by
    a strongly consistent read each.
    """
    keys: List[Dict[str, str]] = []
    for order_id in order_ids:
        items = query_all_items(
            tables.order_fulfillments,
            {
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": str(order_id)},
                "ConsistentRead": True,
            },
        )
        keys.extend(
            {"pk": str(item["pk"]), "sk": str(item["sk"])}
            for item in items
            if isinstance(item, dict) and item.get("pk") is not None and item.get("sk") is not None
        )
    return keys


def delete_fulfillments_for_orders(order_ids: List[str], *, logger: Any = None) -> int:
    """Remove these Orders' fulfillment history.

    ARCH-1 (impact assessment, children-first deletion). `OrderFulfillment` rows are keyed
    by the Order and append-only, and the reversal and audit surfaces both re-load the
    Order to authorize themselves, so a campaign or profile cascade that deletes only the
    Order rows strands records nobody can reverse or read — beside inventory movements
    that already moved stock.

    Callers reach this per Order, from `delete_order_and_fulfillments`, immediately before
    that Order's version-pinned delete: the sweep empties the partition, and the pin then
    proves nothing landed in it afterwards.

    What the verification guarantees is precise. A batch write that silently left a record
    behind raises here (`_verify_fulfillment_keys_deleted`) BEFORE the Order can be
    deleted, so an Order never goes under surviving history. A failure partway through a
    sweep can still leave an Order that lost some records and kept the rest; what makes
    that survivable is that the Order row is still there, so the next run reads the
    partition again and takes what remains.

    There is no size window here, unlike the AppSync `deleteOrder` path: a Lambda can loop,
    so `query_all_items` pages a history of any length and `batch_delete_keys` drains the
    keys in batches. An Order with 5,000 fulfillment rows is swept by this path in one run.

    Returns the number of fulfillment records deleted.
    """
    log = logger if logger is not None else _default_logger
    keys = fulfillment_keys_for_orders(order_ids)
    if not keys:
        return 0

    deleted = batch_delete_keys(tables.order_fulfillments, keys, ["pk", "sk"], logger=log)
    _verify_fulfillment_keys_deleted(order_ids)
    log.info("Deleted fulfillment history for orders", order_ids=len(order_ids), count=deleted)
    return deleted


def _verify_fulfillment_keys_deleted(order_ids: List[str]) -> None:
    """Refuse to report success while any swept Order still has fulfillment rows."""
    remaining = fulfillment_keys_for_orders(order_ids)
    if remaining:
        raise AppError(
            ErrorCode.CONFLICT,
            f"{len(remaining)} fulfillment record(s) are still present; no further deletion was attempted",
        )


def _table_name(table: Any, env_var: str) -> str:
    """Return the table name from the table resource or environment variable."""
    name = getattr(table, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(get_required_env(env_var))


def _verify_order_keys_deleted(order_keys: List[Dict[str, Any]]) -> None:
    """Verify deleted orders are absent from the base table.

    Uses strongly consistent batch reads on the exact keys that were deleted,
    which deterministically reflects the completed deletes. The orderId-index
    GSI cannot be used here: it is eventually consistent and can keep showing
    deleted rows for an unbounded time. Raises AppError if any key persists.
    """
    if not order_keys:
        return

    unique_keys = _drop_duplicate_delete_keys(
        [{"campaignId": str(key["campaignId"]), "orderId": str(key["orderId"])} for key in order_keys],
        ["campaignId", "orderId"],
    )

    def _on_persisting_order(item: Dict[str, Any]) -> None:
        logger.error(
            "Order still present after delete verification",
            campaign_id=item.get("campaignId"),
            order_id=item.get("orderId"),
        )
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete order")

    table_name = _table_name(tables.orders, "ORDERS_TABLE_NAME")
    batch_get_chunked(
        table_name,
        unique_keys,
        _on_persisting_order,
        consistent_read=True,
        logger=logger,
    )


def _verify_campaign_deleted(profile_id: str, campaign_id: str) -> None:
    """Verify a deleted campaign is absent from the base table.

    Uses a strongly consistent batch read on the exact key that was deleted,
    which deterministically reflects the completed delete. The campaignId-index
    GSI cannot be used here: it is eventually consistent and can keep showing a
    deleted row for an unbounded time. Raises AppError if the key persists.
    """
    keys = [{"profileId": profile_id, "campaignId": campaign_id}]

    def _on_persisting_campaign(item: Dict[str, Any]) -> None:
        persisting_profile_id = item.get("profileId", profile_id)
        persisting_campaign_id = item.get("campaignId", campaign_id)
        logger.error(
            "Campaign still present after delete verification",
            profile_id=persisting_profile_id,
            campaign_id=persisting_campaign_id,
        )
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete campaign")

    table_name = _table_name(tables.campaigns, "CAMPAIGNS_TABLE_NAME")
    batch_get_chunked(
        table_name,
        keys,
        _on_persisting_campaign,
        consistent_read=True,
        logger=logger,
    )


def delete_orders_for_campaign(campaign_id: str, *, logger: Any = None) -> int:
    """Delete all orders for a campaign and verify they are gone.

    Every Order goes through `delete_order_and_fulfillments`: its whole fulfillment
    partition is swept first, then the Order itself is deleted conditioned on the
    ``fulfillmentVersion`` this cascade read. A fulfillment that lands in between fails
    that condition, so the Order and its new record both stay in the table and the next
    run finds the work still marked by the Order row.

    Args:
        campaign_id: The campaign ID (with CAMPAIGN# prefix).
        logger: Optional logger instance.

    Returns:
        Number of orders deleted.

    Raises:
        AppError: CONFLICT if a fulfillment moved an Order while its delete was in
            flight (nothing was deleted for it) or if swept fulfillment records remain;
            INTERNAL_ERROR if a deleted order is still present afterwards.
    """
    orders = _query_order_keys_for_campaign(campaign_id)
    if not orders:
        # An honest answer, not a hopeful one. An Order row leaves this table only
        # through a write pinned to its fulfillmentVersion -- this cascade, the profile
        # cascade, and the AppSync deleteOrder step all pin -- and every pinned delete
        # takes the Order's whole fulfillment partition with it. So "no Orders" really
        # does mean "no partitions left to sweep", which is what the batch form of this
        # function could not claim after it deleted the Orders before the history.
        return 0

    log = logger if logger is not None else _default_logger
    deleted_count = 0
    for order in orders:
        order_deleted, _ = delete_order_and_fulfillments(str(order["campaignId"]), str(order["orderId"]), logger=log)
        if order_deleted:
            deleted_count += 1

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

    caller_account_id = get_caller_id(event)
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
