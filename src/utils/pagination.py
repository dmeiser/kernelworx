"""DynamoDB pagination helpers for Lambda handlers.

Provides synchronous query/scan wrappers that follow LastEvaluatedKey so callers
do not silently truncate results at DynamoDB's 1 MB page limit.
"""

import time
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

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

_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 0.05
_THROUGHPUT_ERROR = "ProvisionedThroughputExceededException"


def _is_throughput_error(exc: BaseException) -> bool:
    """Return True if the exception is a DynamoDB throughput error."""
    if not isinstance(exc, ClientError):
        return False
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return response.get("Error", {}).get("Code") == _THROUGHPUT_ERROR


def _calculate_backoff(attempt: int) -> float:
    """Exponential backoff with jitter placeholder (deterministic for tests)."""
    return _BASE_BACKOFF_SECONDS * (2**attempt)


def _paginated_query(
    table: "Table",
    query_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield items from a DynamoDB query, following pagination and retrying throughput errors."""
    kwargs = dict(query_kwargs)
    yielded = 0
    attempt = 0

    while True:
        try:
            response = table.query(**kwargs)
            attempt = 0
        except ClientError as exc:
            if _is_throughput_error(exc) and attempt < _MAX_RETRIES:
                attempt += 1
                backoff = _calculate_backoff(attempt)
                logger.warning(
                    "DynamoDB query throttled, retrying",
                    attempt=attempt,
                    backoff=backoff,
                )
                time.sleep(backoff)
                continue
            raise

        for item in response.get("Items", []):
            if max_items is not None and yielded >= max_items:
                return
            yield item
            yielded += 1

        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break
        kwargs["ExclusiveStartKey"] = last_evaluated_key


def _paginated_scan(
    table: "Table",
    scan_kwargs: Dict[str, Any],
    max_items: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield items from a DynamoDB scan, following pagination and retrying throughput errors."""
    kwargs = dict(scan_kwargs)
    yielded = 0
    attempt = 0

    while True:
        try:
            response = table.scan(**kwargs)
            attempt = 0
        except ClientError as exc:
            if _is_throughput_error(exc) and attempt < _MAX_RETRIES:
                attempt += 1
                backoff = _calculate_backoff(attempt)
                logger.warning(
                    "DynamoDB scan throttled, retrying",
                    attempt=attempt,
                    backoff=backoff,
                )
                time.sleep(backoff)
                continue
            raise

        for item in response.get("Items", []):
            if max_items is not None and yielded >= max_items:
                return
            yield item
            yielded += 1

        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break
        kwargs["ExclusiveStartKey"] = last_evaluated_key


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
        All items matching the query, aggregated across pages.
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
        Iterable of items matching the query.
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
        All items matching the scan, aggregated across pages.
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
        Iterable of items matching the scan.
    """
    yield from _paginated_scan(table, scan_kwargs, max_items=max_items)
