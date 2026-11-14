"""DynamoDB pagination helpers for Lambda handlers.

Provides a synchronous query wrapper that follows LastEvaluatedKey so callers
do not silently truncate results at DynamoDB's 1 MB page limit. It retries
``ProvisionedThroughputExceededException`` with exponential backoff, and a
generator variant is available to bound memory growth on large result sets.
"""

import base64
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from botocore.exceptions import ClientError

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.service_resource import Table

from .errors import AppError, ErrorCode
from .logging import get_logger

logger = get_logger(__name__)

# Shared retry constants: the query wrapper below and the BatchGetItem helper
# in ``utils.dynamodb`` back off identically so a fix to one cannot drift from
# the others (#557).
MAX_RETRY_ATTEMPTS: int = 3
BASE_BACKOFF_SECONDS: float = 0.05


def _b64decode(token: str) -> str:
    """Decode a URL-safe base64 cursor payload."""
    return base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")


def _b64encode(payload: str) -> bytes:
    """Encode a cursor payload as a URL-safe base64 token."""
    return base64.urlsafe_b64encode(payload.encode("utf-8"))


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


# --- Show & Sell page contract (API contract §3.1, impact map §3.4) --------------
#
# Every Stage 1 list resolver takes ``PageInput`` and returns a connection of
# ``items`` plus ``pageInfo``. The cursor is opaque, server-issued, and BOUND to
# the scope that issued it: a token handed back against a different Unit, Unit
# Campaign, or filter set is rejected rather than silently repositioning the
# caller inside another tenant's result set.

DEFAULT_PAGE_LIMIT: int = 50
MAX_PAGE_LIMIT: int = 100

_CURSOR_VERSION = 1
_CURSOR_MAX_LENGTH = 512


def parse_page_limit(page: Optional[Mapping[str, Any]]) -> int:
    """Resolve ``page.limit`` to the default-50/max-100 range."""
    if page is None:
        return DEFAULT_PAGE_LIMIT
    raw = page.get("limit")
    if raw is None:
        return DEFAULT_PAGE_LIMIT
    try:
        limit = int(raw)
    except TypeError, ValueError:
        raise AppError(ErrorCode.INVALID_INPUT, "page.limit must be an integer") from None
    if limit < 1 or limit > MAX_PAGE_LIMIT:
        raise AppError(ErrorCode.INVALID_INPUT, f"page.limit must be between 1 and {MAX_PAGE_LIMIT}")
    return limit


def parse_page_cursor(page: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Read ``page.cursor`` as an opaque token, or None for the first page."""
    if page is None:
        return None
    raw = page.get("cursor")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw or len(raw) > _CURSOR_MAX_LENGTH:
        raise AppError(ErrorCode.INVALID_INPUT, "page.cursor is not a valid cursor")
    return raw


def encode_page_cursor(scope: str, offset: int) -> str:
    """Issue the cursor for the next page of ``scope``'s results."""
    return _b64encode(json.dumps({"v": _CURSOR_VERSION, "s": scope, "o": offset}, separators=(",", ":"))).decode()


def decode_page_cursor(scope: str, cursor: Optional[str]) -> int:
    """Return the offset a cursor asks for, rejecting anything not bound to ``scope``.

    A cursor minted for another Unit or another filter set, a token this server
    never issued, and a tampered or truncated token all fail the same way: an
    opaque cursor is a positional claim inside one specific result set, and
    honoring it elsewhere is a tenant-isolation bug, not a pagination detail.
    """
    if cursor is None:
        return 0
    try:
        payload = json.loads(_b64decode(cursor))
    except ValueError, UnicodeDecodeError:
        raise AppError(ErrorCode.INVALID_INPUT, "page.cursor is not a valid cursor") from None
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION or payload.get("s") != scope:
        raise AppError(ErrorCode.INVALID_INPUT, "page.cursor was issued for a different request")
    offset = payload.get("o")
    if not isinstance(offset, int) or offset < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "page.cursor is not a valid cursor")
    return offset


def paginate_page(items: Sequence[Any], scope: str, page: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Apply one validated ``PageInput`` to an ordered, fully-read result list.

    The caller supplies the complete ordered list (Stage 1 collections are read
    with ``query_all_items``, which follows ``LastEvaluatedKey`` to the end), so
    a filtered page can never be short because DynamoDB applied a filter after
    ``Limit``. The returned shape is the SDL connection: ``items`` plus
    ``pageInfo`` with ``endCursor`` only while more results remain.
    """
    limit = parse_page_limit(page)
    offset = decode_page_cursor(scope, parse_page_cursor(page))
    window = list(items[offset : offset + limit])
    has_more = offset + len(window) < len(items)
    end_cursor = encode_page_cursor(scope, offset + len(window)) if has_more else None
    return {"items": window, "pageInfo": {"endCursor": end_cursor, "hasNextPage": has_more}}
