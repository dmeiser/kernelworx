"""
Centralized DynamoDB table access utilities.

Provides singleton-pattern table accessors with lazy initialization
and test monkeypatch support, plus the shared chunked BatchGetItem helper.
"""

import os
import time
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

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
