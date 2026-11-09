"""DynamoDB pagination helpers for Lambda handlers.

Provides a synchronous query wrapper that follows LastEvaluatedKey so callers
do not silently truncate results at DynamoDB's 1 MB page limit. It retries
``ProvisionedThroughputExceededException`` with exponential backoff, and a
generator variant is available to bound memory growth on large result sets.
"""

import base64
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional

from botocore.exceptions import ClientError

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.service_resource import Table

from .logging import get_logger

logger = get_logger(__name__)

# Shared retry constants: the query wrapper below and the BatchGetItem helper
# in ``utils.dynamodb`` back off identically so a fix to one cannot drift from
# the others (#557).
MAX_RETRY_ATTEMPTS: int = 3
BASE_BACKOFF_SECONDS: float = 0.05


def _is_throughput_error(exc: BaseException) -> bool:
    """Return True if the exception is a retryable DynamoDB throttling error."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    # Import lazily to avoid a circular import (dynamodb.py imports retry
    # constants from this module). Reuse the shared, authoritative classifier
    # so the retry set here cannot drift from the rest of the codebase.
    from .dynamodb import is_transient_client_error

    return is_transient_client_error(exc)  # type: ignore[arg-type]


def _calculate_backoff(attempt: int) -> float:
    """Return deterministic exponential backoff for the given retry attempt."""
    return float(BASE_BACKOFF_SECONDS * (2**attempt))


def _call_with_retry(
    method: Callable[..., Dict[str, Any]],
    kwargs: Dict[str, Any],
    log_label: str,
) -> Dict[str, Any]:
    """Call a DynamoDB operation, retrying throughput errors with exponential backoff."""
    attempt = 0
    while True:
        try:
            return method(**kwargs)
        except ClientError as exc:
            if _is_throughput_error(exc) and attempt < MAX_RETRY_ATTEMPTS:
                backoff = _calculate_backoff(attempt)
                attempt += 1
                logger.warning(
                    f"DynamoDB {log_label} throttled, retrying",
                    attempt=attempt,
                    backoff=backoff,
                )
                time.sleep(backoff)
                continue
            raise


def _reached_limit(yielded: int, max_items: Optional[int]) -> bool:
    """Return True if the requested item limit has been reached."""
    return max_items is not None and yielded >= max_items


def _paginated(
    table: "Table",
    method_name: str,
    kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
    log_label: str = "query",
) -> Iterable[Dict[str, Any]]:
    """Yield items from a DynamoDB operation, following pagination and retrying throughput errors."""
    method = getattr(table, method_name)
    query_kwargs = dict(kwargs)
    yielded = 0

    while True:
        response = _call_with_retry(method, query_kwargs, log_label)

        for item in response.get("Items", []):
            if _reached_limit(yielded, max_items):
                return
            yield item
            yielded += 1

        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break
        query_kwargs["ExclusiveStartKey"] = last_evaluated_key


def _paginated_query(
    table: "Table",
    query_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield items from a DynamoDB query, following pagination and retrying throughput errors."""
    yield from _paginated(table, "query", query_kwargs, max_items=max_items, log_label="query")


def query_all_items(
    table: "Table",
    query_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Execute a DynamoDB query and follow pagination to return all items.

    Args:
        table: DynamoDB table resource to query.
        query_kwargs: Keyword arguments passed to ``Table.query``. Must include
            ``KeyConditionExpression`` and any ``ExpressionAttributeValues``.
        max_items: Optional maximum number of items to return. If provided,
            pagination stops once this many items have been collected, which
            bounds memory growth for large result sets.

    Returns:
        All items matching the query, aggregated across pages. Throughput
        errors are retried with exponential backoff.
    """
    return list(_paginated_query(table, query_kwargs, max_items=max_items))


def query_all_items_iter(
    table: "Table",
    query_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield items from a DynamoDB query without loading all pages into memory.

    Args:
        table: DynamoDB table resource to query.
        query_kwargs: Keyword arguments passed to ``Table.query``.
        max_items: Optional maximum number of items to yield.

    Returns:
        Iterable of items matching the query. Throughput errors are retried
        with exponential backoff.
    """
    yield from _paginated_query(table, query_kwargs, max_items=max_items)


# ----------------------------------------------------------------------------
# Opaque, scope-bound cursor pagination (Show & Sell, spec API section 3.1).
#
# Default page size 50, maximum 100. Cursors are base64url JSON binding the
# query scope to the last evaluated key; a cursor minted for one tenant or
# query cannot enter another (PAGE-01 cursor isolation), and a tampered or
# stale cursor is INVALID_INPUT, never a silent wrong page.
# ----------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT: int = 50
MAX_PAGE_LIMIT: int = 100


def validate_page_limit(limit: Optional[int]) -> int:
    """Resolve a caller page limit to the default when absent, else validate bounds.

    Args:
        limit: Caller-requested page size, or None for the default.

    Returns:
        The page size to request (1..MAX_PAGE_LIMIT, default DEFAULT_PAGE_LIMIT).

    Raises:
        AppError: INVALID_INPUT when the limit is not an int in 1..100. Bools
            are rejected: JSON ``true`` must not become page size 1.
    """
    from .errors import AppError, ErrorCode

    if limit is None:
        return DEFAULT_PAGE_LIMIT
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE_LIMIT:
        raise AppError(ErrorCode.INVALID_INPUT, f"Page limit must be between 1 and {MAX_PAGE_LIMIT}")
    return limit


def encode_cursor(scope: str, last_evaluated_key: Dict[str, Any]) -> str:
    """Encode a query's last evaluated key into an opaque, scope-bound cursor."""
    payload = json.dumps({"v": 1, "s": scope, "lek": last_evaluated_key}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str, expected_scope: str) -> Dict[str, Any]:
    """Decode and validate a cursor, returning the exclusive-start key.

    Args:
        cursor: The opaque cursor string from the previous page.
        expected_scope: The scope of the query now running; must match the
            scope the cursor was minted for.

    Returns:
        The DynamoDB ``LastEvaluatedKey`` dict to pass as ``ExclusiveStartKey``.

    Raises:
        AppError: INVALID_INPUT when the cursor is malformed, minted for a
            different scope, or carries a version this code cannot read.
    """
    from .errors import AppError, ErrorCode

    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        version, scope, last_evaluated_key = payload["v"], payload["s"], payload["lek"]
    except ValueError, KeyError, TypeError, UnicodeDecodeError:
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid page cursor") from None
    if version != 1 or not isinstance(scope, str) or not isinstance(last_evaluated_key, dict):
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid page cursor") from None
    if scope != expected_scope:
        # A cursor from another tenant/query must not open that result set.
        raise AppError(ErrorCode.INVALID_INPUT, "Page cursor does not belong to this query")
    return last_evaluated_key
