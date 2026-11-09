"""
Centralized DynamoDB table access utilities.

Provides singleton-pattern table accessors with lazy initialization
and test monkeypatch support, plus the shared chunked BatchGetItem helper.
"""

import os
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast

import boto3
from botocore.exceptions import ClientError

from .errors import AppError, ErrorCode
from .logging import get_logger
from .pagination import BASE_BACKOFF_SECONDS, MAX_RETRY_ATTEMPTS

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table


# Constant partition key of the accounts table's ``emailSearchIndex`` GSI.
# Every account item that carries this value (plus its ``email``) is searchable
# by an email prefix with a Query; items without it are invisible to that index
# and are only reachable through a table scan. Written by the Cognito account
# bootstrap trigger and by the one-off backfill (scripts/backfill_email_search_key.py).
EMAIL_SEARCH_KEY = "EMAIL"

# Named with a leading underscore so `batch_get_chunked`'s `logger` parameter
# can fall back to it without shadowing the module global.
_logger = get_logger(__name__)

# DynamoDB caps BatchGetItem at 100 keys per request; the shared helper is the
# single place that enforces it so every call site inherits the cap (#557).
BATCH_GET_CHUNK_SIZE: int = 100

# DynamoDB throttling codes. A throttled read is retryable, so it surfaces as a
# retryable RESOURCE_BUSY rather than a non-retryable internal error (#557).
_THROTTLING_ERROR_CODES = frozenset(
    {
        "ProvisionedThroughputExceededException",
        "ThrottlingException",
        "TooManyRequestsException",
        "RequestLimitExceeded",
    }
)

# AWS conditions that mean the same call may well succeed a moment later. Every
# other condition (a failed ``ConditionExpression``, a missing table, a denied
# permission) is permanent: retrying it produces the identical failure, so it
# must not be reported to the caller as retryable (#549).
TRANSIENT_ERROR_CODES = frozenset(
    {"ProvisionedThroughputExceededException", "ThrottlingException", "TooManyRequestsException"}
)


def is_transient_client_error(error: ClientError) -> bool:
    """Return True when ``error`` is a retryable DynamoDB condition (throttling)."""
    return error.response.get("Error", {}).get("Code", "") in TRANSIENT_ERROR_CODES


# ----------------------------------------------------------------------------
# Show & Sell transaction + idempotency helpers (impact map 3.4).
#
# Convention (decision record: docs/investigations/show-sell-idempotency-convention.md,
# ported from the gate-proven clean-room build):
#   1. Validate input DETERMINISTICALLY before touching the marker; every
#      state check lives inside the transaction plan.
#   2. The idempotency marker and its effect write in ONE TransactWriteItems
#      call — a committed marker always means a committed effect.
#   3. A committed marker whose stored request fingerprint matches replays
#      the stored result (equality, never re-execution); a fingerprint
#      mismatch is a CONDITION failure (CONFLICT), not an overwrite.
#   4. Race retries are bounded: at most MAX_RACE_RETRIES attempts, backoff
#      only on transient throttling, and the FULL plan re-executes (plans are
#      rebuilt per attempt, never partially applied).
#   5. The 90-item preflight cap leaves headroom under DynamoDB's 100-item
#      service limit for ConditionCheck entries the planner adds.
# ----------------------------------------------------------------------------

# Preflight cap for TransactWriteItems plans (service limit is 100; the cap
# leaves headroom for planner-added ConditionCheck entries).
MAX_TRANSACT_ITEMS: int = 90

# Bounded race-retry ceiling (F1 ruling from the clean-room build: an
# unbounded retry turns throttling into a Lambda timeout; three attempts
# with exponential backoff resolve genuine races without masking a hot key).
MAX_RACE_RETRIES: int = 3

# Common idempotency-marker retention: seven days, numeric epoch seconds on
# the tables' shared expiresAtEpoch TTL attribute (impact map 4.1).
IDEM_TTL_SECONDS: int = 7 * 24 * 3600


class TransactionDuplicateKeyError(ValueError):
    """A transaction plan addresses one table key twice (client-side pin).

    DynamoDB would surface this only opaquely through cancellation reasons;
    the layer rejects it outright so planner bugs fail at build time.
    """


class TransactionCancelledError(Exception):
    """TransactWriteItems cancelled: carries the indexes of the failed items.

    ``failed_indexes`` lists the positions in the submitted plan whose
    ConditionCheck/Put/Update/Delete failed, so the handler can map the
    failure to a domain error without re-reading the world.
    """

    def __init__(self, failed_indexes: List[int]):
        self.failed_indexes = failed_indexes
        super().__init__(f"transaction cancelled at items {failed_indexes}")


class TransactionThrottledError(Exception):
    """Transient throttling persisted past the bounded race retries."""


def transaction_item_key(transact_item: Dict[str, Any]) -> tuple[str, tuple[tuple[str, Any], ...]]:
    """Extract the (table, key) identity of a TransactWriteItems entry.

    Every entry form (Put/Update/Delete/ConditionCheck) carries TableName and
    either Item (Put) or Key (the rest); the identity is what the duplicate-key
    pin compares.
    """
    body = transact_item[next(iter(transact_item))]
    table_name = body["TableName"]
    item = body.get("Item", body.get("Key", {}))
    return table_name, tuple(sorted(item.items()))


def _preflight_plan(transact_items: List[Dict[str, Any]]) -> None:
    """Reject oversized or duplicate-key plans before any AWS call."""
    if len(transact_items) > MAX_TRANSACT_ITEMS:
        raise ValueError(f"transaction plan has {len(transact_items)} items; cap is {MAX_TRANSACT_ITEMS}")
    seen: set[tuple[str, tuple[tuple[str, Any], ...]]] = set()
    for entry in transact_items:
        identity = transaction_item_key(entry)
        if identity in seen:
            raise TransactionDuplicateKeyError(f"duplicate key in transaction plan: {identity}")
        seen.add(identity)


def _cancelled_indexes(exc: ClientError, plan_length: int) -> List[int]:
    """Map a TransactionCanceledException to the failed plan indexes."""
    reasons = exc.response.get("CancellationReasons") or []
    failed = [
        index
        for index, reason in enumerate(reasons)
        if isinstance(reason, dict) and reason.get("Code") not in (None, "None")
    ]
    return failed or list(range(plan_length))


def execute_transaction(
    transact_items: List[Dict[str, Any]],
    *,
    client: Optional[Any] = None,
    max_retries: int = MAX_RACE_RETRIES,
) -> None:
    """Execute a TransactWriteItems plan with preflight checks and bounded retries.

    Args:
        transact_items: The plan entries (Put/Update/Delete/ConditionCheck).
        client: Optional DynamoDB client; defaults to the shared resource's
            client. Injectable for tests.
        max_retries: Retry ceiling for transient throttling (F1 bound).

    Raises:
        ValueError: Plan exceeds MAX_TRANSACT_ITEMS (planner bug).
        TransactionDuplicateKeyError: The plan addresses one key twice.
        TransactionCancelledError: A condition failed; failed item indexes
            are carried for domain-error mapping.
        TransactionThrottledError: Throttling persisted past ``max_retries``.
    """
    _preflight_plan(transact_items)
    if client is None:
        client = cast(Any, _get_dynamodb().meta.client)

    attempt = 0
    while True:
        try:
            client.transact_write_items(TransactItems=transact_items)
            return
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "TransactionCanceledException":
                raise TransactionCancelledError(_cancelled_indexes(exc, len(transact_items))) from None
            if code not in TRANSIENT_ERROR_CODES:
                raise
            if attempt >= max_retries:
                raise TransactionThrottledError(f"transaction throttled after {max_retries} retries") from exc
            time.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
            attempt += 1


def idem_item_key(scope: str, marker_key: str) -> str:
    """Item-key attribute for an idempotency-marker row in an aggregate table.

    Layout: IDEM#<scope>#<markerKey>, stored under the table's base hash key
    (e.g. unitId or unitCampaignId) with the marker TTL attribute.
    """
    return f"IDEM#{scope}#{marker_key}"


def idem_expiry_epoch(now_epoch: int) -> int:
    """Expiry epoch (seconds) for a marker committed at ``now_epoch``.

    Seven-day retention per the common marker convention (impact map 4.1);
    the numeric value lands on the tables' shared expiresAtEpoch TTL.
    """
    return now_epoch + IDEM_TTL_SECONDS


def new_marker_item(
    *,
    scope: str,
    marker_key: str,
    fingerprint: str,
    now_epoch: int,
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the idempotency-marker item written in the same transaction as its effect.

    The marker records the deterministic request fingerprint (committed-replay
    equality: a replay with the same fingerprint returns ``result`` without
    re-executing) and expires seven days after commit.
    """
    marker: Dict[str, Any] = {
        "itemKey": idem_item_key(scope, marker_key),
        "idemFingerprint": fingerprint,
        "idemCommittedAtEpoch": now_epoch,
        "expiresAtEpoch": idem_expiry_epoch(now_epoch),
    }
    if result is not None:
        marker["idemResult"] = result
    return marker


# Module-level cache for test overrides
_table_overrides: dict[str, Optional["Table"]] = {}

# Module-level cache for the DynamoDB service resource
_dynamodb_resource: Optional["DynamoDBServiceResource"] = None


def get_required_env(name: str, default: Optional[str] = None) -> str:
    """Get a required environment variable.

    In Lambda/production, the env var must be set. For tests, a default can be
    provided to allow the code to run in mocked environments.

    Args:
        name: Environment variable name
        default: Optional default for test environments (should not be dev resource)

    Returns:
        The environment variable value

    Raises:
        ValueError: If the env var is not set and no default is provided
    """
    value = os.getenv(name, default)
    if value is None:
        raise ValueError(f"Required environment variable '{name}' is not set")
    return value


def _get_dynamodb() -> "DynamoDBServiceResource":
    """Get DynamoDB resource with optional endpoint override for LocalStack."""
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))
    return _dynamodb_resource


def get_dynamodb_resource() -> "DynamoDBServiceResource":
    """Get DynamoDB resource for direct resource-level operations like batch_get_item.

    Use this for operations that require the resource directly rather than a table.
    For table-level operations, prefer using the `tables` singleton.
    """
    return _get_dynamodb()


def _unprocessed_keys(response: Any, table_name: str) -> list[dict[str, Any]]:
    """Extract the keys DynamoDB reports as unprocessed for a table in a BatchGetItem response."""
    unprocessed = response.get("UnprocessedKeys", {}).get(table_name, {}).get("Keys", [])
    return list(unprocessed)


def _batch_get_attempt(
    table_name: str,
    keys: list[dict[str, Any]],
    on_item: Callable[[dict[str, Any]], None],
    consistent_read: bool,
    log: Any,
) -> list[dict[str, Any]]:
    """Run one BatchGetItem attempt, hand items to on_item, and return unprocessed keys.

    Failures are translated here so every caller reports them identically: a
    throttling condition becomes a retryable RESOURCE_BUSY, anything else an
    INTERNAL_ERROR. Never returns unprocessed keys after raising.
    """
    key_spec: dict[str, Any] = {"Keys": keys}
    if consistent_read:
        key_spec["ConsistentRead"] = True

    try:
        response: Any = get_dynamodb_resource().batch_get_item(RequestItems=cast(Any, {table_name: key_spec}))
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in _THROTTLING_ERROR_CODES:
            log.warning("BatchGetItem throttled", error=str(exc), error_code=error_code, table_name=table_name)
            raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to load data. Please retry.") from exc
        log.error("BatchGetItem failed", error=str(exc), error_code=error_code, table_name=table_name)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to load data") from exc
    except Exception as exc:
        log.error("BatchGetItem failed unexpectedly", error=str(exc), table_name=table_name)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to load data") from exc

    for item in response.get("Responses", {}).get(table_name, []):
        on_item(item)
    return _unprocessed_keys(response, table_name)


def batch_get_chunked(
    table_name: str,
    keys: list[dict[str, Any]],
    on_item: Callable[[dict[str, Any]], None],
    *,
    consistent_read: bool = True,
    max_attempts: int = MAX_RETRY_ATTEMPTS,
    logger: Any = None,
) -> None:
    """Batch-get keys with UnprocessedKeys retry, chunked at DynamoDB's 100-key cap.

    The single owner of the BatchGetItem + UnprocessedKeys drain loop every
    handler used to reimplement (#557). Calls on_item for every returned item.
    An empty key list makes no API call at all.

    Args:
        table_name: Table to read from.
        keys: Keys to fetch; split into ``BATCH_GET_CHUNK_SIZE``-key requests.
        on_item: Called with each returned item.
        consistent_read: Issue a strongly consistent read (omitted from the
            request when False, preserving DynamoDB's eventual-consistency default).
        max_attempts: Attempts per chunk before giving up.
        logger: Structured logger to use; falls back to this module's logger.

    Raises:
        AppError: RESOURCE_BUSY, the retryable signal, in two cases: a throttling
            ClientError is translated and raised on the attempt that hit it
            immediately, and keys still unprocessed after a chunk's final
            attempt are also reported as RESOURCE_BUSY. Any other BatchGetItem
            failure is translated to INTERNAL_ERROR.
    """
    if not keys:
        return

    log = logger if logger is not None else _logger
    for start in range(0, len(keys), BATCH_GET_CHUNK_SIZE):
        pending: list[dict[str, Any]] = list(keys[start : start + BATCH_GET_CHUNK_SIZE])
        for attempt in range(max_attempts):
            if not pending:
                break
            pending = _batch_get_attempt(table_name, pending, on_item, consistent_read, log)
            if pending and attempt < max_attempts - 1:
                log.warning(
                    "Unprocessed keys, retrying",
                    table_name=table_name,
                    attempt=attempt + 1,
                    count=len(pending),
                )
                time.sleep(BASE_BACKOFF_SECONDS * (2**attempt))
        if pending:
            raise AppError(
                ErrorCode.RESOURCE_BUSY,
                f"DynamoDB BatchGetItem failed to return {len(pending)} keys after retries",
            )


class TableAccessor:
    """Centralized access to DynamoDB tables with environment-based naming."""

    _instance: Optional["TableAccessor"] = None
    _tables: dict[str, "Table"]

    def __new__(cls) -> "TableAccessor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tables = {}
        return cls._instance

    def _get_table(self, table_name_key: str) -> "Table":
        """Return a cached table, or create and cache it."""
        if override := _table_overrides.get(table_name_key):
            return override
        if table_name_key not in self._tables:
            table_name = get_required_env(f"{table_name_key.upper()}_TABLE_NAME")
            self._tables[table_name_key] = _get_dynamodb().Table(table_name)
        return self._tables[table_name_key]

    @property
    def accounts(self) -> "Table":
        """Get accounts table instance."""
        return self._get_table("accounts")

    @property
    def profiles(self) -> "Table":
        """Get profiles table instance (V2 multi-table design)."""
        return self._get_table("profiles")

    @property
    def campaigns(self) -> "Table":
        """Get campaigns table instance (V2 multi-table design)."""
        return self._get_table("campaigns")

    @property
    def orders(self) -> "Table":
        """Get orders table instance (V2 multi-table design)."""
        return self._get_table("orders")

    @property
    def shares(self) -> "Table":
        """Get shares table instance."""
        return self._get_table("shares")

    @property
    def catalogs(self) -> "Table":
        """Get catalogs table instance."""
        return self._get_table("catalogs")

    @property
    def invites(self) -> "Table":
        """Get invites table instance."""
        return self._get_table("invites")

    @property
    def shared_campaigns(self) -> "Table":
        """Get shared campaigns table instance."""
        return self._get_table("shared_campaigns")

    @property
    def units(self) -> "Table":
        """Get units table instance (Show & Sell)."""
        return self._get_table("units")

    @property
    def unit_campaigns(self) -> "Table":
        """Get unit campaigns table instance (Show & Sell)."""
        return self._get_table("unit_campaigns")

    @property
    def inventory(self) -> "Table":
        """Get inventory table instance (Show & Sell)."""
        return self._get_table("inventory")

    @property
    def show_and_sells(self) -> "Table":
        """Get show and sells table instance (Show & Sell events aggregate)."""
        return self._get_table("show_and_sells")

    @property
    def order_fulfillments(self) -> "Table":
        """Get order fulfillments table instance (Show & Sell)."""
        return self._get_table("order_fulfillments")


# Singleton instance for import
tables = TableAccessor()


# Test utilities
def override_table(table_name: str, table: Optional["Table"]) -> None:
    """Override a table for testing. Set to None to clear override."""
    _table_overrides[table_name] = table


def clear_all_overrides() -> None:
    """Clear all table overrides (call in test teardown)."""
    _table_overrides.clear()


def reset_singleton() -> None:
    """Reset the singleton instance (for testing isolation)."""
    if TableAccessor._instance is not None:
        TableAccessor._instance._tables = {}
    # Also clear the module-level singleton's cache so external imports that
    # hold a reference to the old instance do not reuse stale tables.
    tables._tables = {}
    TableAccessor._instance = None


def reset_dynamodb_resource() -> None:
    """Reset the cached DynamoDB resource (for testing isolation)."""
    global _dynamodb_resource
    _dynamodb_resource = None
