"""DynamoDB pagination helpers for Lambda handlers.

Provides synchronous query/scan wrappers that follow LastEvaluatedKey so callers
do not silently truncate results at DynamoDB's 1 MB page limit. All wrappers
retry ``ProvisionedThroughputExceededException`` with exponential backoff, and
generator variants are available to bound memory growth on large result sets.
"""

import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.service_resource import Table

try:  # pragma: no cover
    from botocore.exceptions import ClientError
except ModuleNotFoundError:  # pragma: no cover
    ClientError = Exception  # type: ignore[misc, assignment]

try:  # pragma: no cover
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.logging import get_logger

logger = get_logger(__name__)

_MAX_RETRIES: int = 3
_BASE_BACKOFF_SECONDS: float = 0.05
_THROUGHPUT_ERROR: str = "ProvisionedThroughputExceededException"


def _is_throughput_error(exc: BaseException) -> bool:
    """Return True if the exception is a DynamoDB throughput error."""
    if not isinstance(exc, ClientError):
        return False
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return bool(response.get("Error", {}).get("Code") == _THROUGHPUT_ERROR)


def _calculate_backoff(attempt: int) -> float:
    """Return deterministic exponential backoff for the given retry attempt."""
    return float(_BASE_BACKOFF_SECONDS * (2**attempt))


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
            if _is_throughput_error(exc) and attempt < _MAX_RETRIES:
                attempt += 1
                backoff = _calculate_backoff(attempt)
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


def _paginated_scan(
    table: "Table",
    scan_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield items from a DynamoDB scan, following pagination and retrying throughput errors."""
    yield from _paginated(table, "scan", scan_kwargs, max_items=max_items, log_label="scan")


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


def scan_all_items(
    table: "Table",
    scan_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Execute a DynamoDB scan and follow pagination to return all items.

    Args:
        table: DynamoDB table resource to scan.
        scan_kwargs: Keyword arguments passed to ``Table.scan``.
        max_items: Optional maximum number of items to return. If provided,
            pagination stops once this many items have been collected, which
            bounds memory growth for large result sets.

    Returns:
        All items matching the scan, aggregated across pages. Throughput
        errors are retried with exponential backoff.
    """
    return list(_paginated_scan(table, scan_kwargs, max_items=max_items))


def scan_all_items_iter(
    table: "Table",
    scan_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield items from a DynamoDB scan without loading all pages into memory.

    Args:
        table: DynamoDB table resource to scan.
        scan_kwargs: Keyword arguments passed to ``Table.scan``.
        max_items: Optional maximum number of items to yield.

    Returns:
        Iterable of items matching the scan. Throughput errors are retried
        with exponential backoff.
    """
    yield from _paginated_scan(table, scan_kwargs, max_items=max_items)
