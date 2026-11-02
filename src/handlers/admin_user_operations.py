"""
Admin user listing & search handlers (extracted from admin_operations, #773).

Provides:
- adminListUsers: List Cognito users enriched with DynamoDB account data
- adminSearchUser: Search users by email, name, or accountId

Both handlers stay registered on the shared admin-operations Lambda:
``admin_operations`` imports them for its operation dispatcher map, so the
Lambda entry point (``handlers.admin_operations.lambda_handler``) and the
AppSync handler mapping are unchanged.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, Dict, cast

from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import require_admin_mfa
    from utils.boto import get_cognito_client
    from utils.cognito import retry_on_transient_errors
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import (
        EMAIL_SEARCH_KEY,
        TRANSIENT_ERROR_CODES,
        batch_get_chunked,
        get_required_env,
        tables,
    )
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id
    from utils.logging import get_logger, mask_email
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import require_admin_mfa
    from ..utils.boto import get_cognito_client
    from ..utils.cognito import retry_on_transient_errors
    from ..utils.cognito_filters import cognito_user_filter
    from ..utils.dynamodb import (
        EMAIL_SEARCH_KEY,
        TRANSIENT_ERROR_CODES,
        batch_get_chunked,
        get_required_env,
        tables,
    )
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id
    from ..utils.logging import get_logger, mask_email

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


def _get_user_groups(cognito: Any, user_pool_id: str, username: str, logger: Any) -> list[str]:
    """Get the groups a user belongs to; failures raise a typed AppError (#291).

    The import is function-level: a top-level import would be circular
    (`admin_operations` imports this module for its operation dispatcher map).
    """
    from .admin_operations import _raise_batch_lookup_error

    try:
        response = retry_on_transient_errors(
            cognito.admin_list_groups_for_user,
            UserPoolId=user_pool_id,
            Username=username,
        )
        return [group["GroupName"] for group in response.get("Groups", [])]
    except ClientError as e:
        _raise_batch_lookup_error("load user groups", logger, e, username=mask_email(username))


def _batch_get_user_groups(cognito: Any, user_pool_id: str, usernames: list[str], logger: Any) -> dict[str, list[str]]:
    """Fetch Cognito groups for multiple users in parallel.

    Cognito does not expose a batch group-membership API, so we parallelize
    the per-user calls to avoid the N+1 fan-out. Lookup failures raise an
    AppError (retryable RESOURCE_BUSY on throttling) so the admin UI shows an
    error instead of silently incomplete group data (#291).
    """
    unique_usernames = list(dict.fromkeys(u for u in usernames if u))
    if not unique_usernames:
        return {}

    def _fetch(username: str) -> tuple[str, list[str]]:
        return username, _get_user_groups(cognito, user_pool_id, username, logger)

    return _collect_parallel_keyed_results(_fetch, unique_usernames, "load user groups", logger)


def _collect_parallel_keyed_results(
    fetch: Callable[[Any], tuple[Any, Any]], items: list[Any], operation: str, logger: Any
) -> dict[Any, Any]:
    """Run per-item fetch calls in parallel and collect (key, value) pairs into a dict.

    AppErrors (including retryable RESOURCE_BUSY) propagate unchanged; any other
    exception is translated via _raise_batch_lookup_error. The import is
    function-level: a top-level import would be circular (`admin_operations`
    imports this module for its operation dispatcher map).
    """
    from .admin_operations import _raise_batch_lookup_error

    results: dict[Any, Any] = {}
    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            for key, value in executor.map(fetch, items):
                results[key] = value
    except AppError:
        raise
    except Exception as e:
        _raise_batch_lookup_error(operation, logger, e)
    return results


def _dedup_account_keys(account_ids: list[str]) -> list[Dict[str, str]]:
    """Build the de-duplicated BatchGetItem keys for the Accounts table."""
    seen: set[str] = set()
    keys: list[Dict[str, str]] = []
    for account_id in account_ids:
        db_account_id = ensure_account_id(account_id)
        if db_account_id in seen:
            continue
        seen.add(db_account_id)
        keys.append({"accountId": db_account_id})
    return keys


def _apply_display_name_item(item: Dict[str, Any], display_names: dict[str, str]) -> None:
    """Store an account item's display name (when it has one) in the map."""
    raw_id = item.get("accountId", "")
    key = raw_id[8:] if raw_id.startswith("ACCOUNT#") else raw_id
    given_name = str(item.get("givenName", ""))
    family_name = str(item.get("familyName", ""))
    if given_name or family_name:
        display_names[key] = f"{given_name} {family_name}".strip()


def _batch_get_display_names(account_ids: list[str], logger: Any) -> dict[str, str]:
    """Batch fetch display names from the Accounts table using BatchGetItem.

    Lookup failures raise an AppError (retryable RESOURCE_BUSY on throttling)
    so the admin UI shows an error instead of silently incomplete names (#291).
    """
    display_names: dict[str, str] = {}
    keys = _dedup_account_keys(account_ids)
    if not keys:
        return display_names

    accounts_table_name = get_required_env("ACCOUNTS_TABLE_NAME")

    def _store_display_name(item: Dict[str, Any]) -> None:
        _apply_display_name_item(item, display_names)

    batch_get_chunked(
        accounts_table_name,
        keys,
        _store_display_name,
        consistent_read=False,
        logger=logger,
    )
    return display_names


def _list_cognito_users(
    cognito: Any, user_pool_id: str, limit: int, next_token: str | None, logger: Any
) -> tuple[list[Dict[str, Any]], str | None]:
    """Call Cognito list_users API and return (users, pagination_token)."""
    list_params: Dict[str, Any] = {"UserPoolId": user_pool_id, "Limit": limit}
    if next_token:
        list_params["PaginationToken"] = next_token

    try:
        response = retry_on_transient_errors(cognito.list_users, **list_params)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in TRANSIENT_ERROR_CODES:
            logger.warning("Cognito list_users throttled", error=str(e), error_code=error_code)
            raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to load data. Please retry.") from e
        logger.error("Cognito list_users failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list users") from e

    return response.get("Users", []), response.get("PaginationToken")


@with_error_handling(error_message="Failed to list users")
def admin_list_users(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    List all Cognito users with their DynamoDB Account data (admin only).

    AppSync Lambda resolver for adminListUsers query.
    Retrieves users from Cognito and enriches with DynamoDB Account data.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        AdminUserConnection with users array and optional nextToken

    Raises:
        AppError: If not admin or Cognito error
    """
    from .admin_operations import _actor_sub

    logger = get_logger(__name__)

    require_admin_mfa(event)

    arguments = event.get("arguments", {})
    raw_limit = arguments.get("limit")
    limit = max(1, min(raw_limit or 20, 60))
    next_token = arguments.get("nextToken")

    user_pool_id = get_required_env("USER_POOL_ID")
    cognito = get_cognito_client()

    cognito_users, pagination_token = _list_cognito_users(cognito, user_pool_id, limit, next_token, logger)

    # Batch DynamoDB display-name lookups and parallelize Cognito group lookups
    # to avoid the per-user N+1 fan-out.
    account_ids = [_extract_cognito_attributes(user)[1].get("sub", user.get("Username", "")) for user in cognito_users]
    usernames = [user.get("Username", "") for user in cognito_users]
    display_names = _batch_get_display_names(account_ids, logger)
    groups_map = _batch_get_user_groups(cognito, user_pool_id, usernames, logger)

    actor_sub = _actor_sub(event)
    admin_users = _build_admin_users_from_cognito(cognito_users, display_names, groups_map)

    logger.info(
        "Listed users",
        count=len(admin_users),
        has_more=bool(pagination_token),
        actor_sub=actor_sub,
    )
    return {"users": admin_users, "nextToken": pagination_token}


def _execute_search_strategy(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Execute search strategy based on query format."""
    if query.startswith("ACCOUNT#"):
        return _search_by_account_prefix(query, cognito, user_pool_id, logger)
    if _looks_like_uuid(query):
        return _search_by_uuid(query, cognito, user_pool_id, logger)
    return _search_by_general_query(query, cognito, user_pool_id, logger)


@with_error_handling(error_message="Failed to search user")
def admin_search_user(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Search for users by email, name, or accountId (admin only).

    AppSync Lambda resolver for adminSearchUser query.
    Search strategy:
    1. If query looks like UUID or ACCOUNT#UUID, search Cognito by sub directly (single result)
    2. Otherwise (minimum `_ACCOUNT_SEARCH_MIN_QUERY_LENGTH` characters):
       a. Search DynamoDB Accounts table: an email fragment uses the
          emailSearchIndex GSI (prefix query); every other query (a name
          fragment) scans the table, bounded by the
          `_ACCOUNTS_SCAN_SAFETY_LIMIT` safety limit. Both cover logged-in
          users.
       b. Search Cognito with prefix matching (all users, including those who haven't logged in)
       c. Merge results, deduplicate by accountId

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        List of AdminUser objects matching the query (empty list if none found)

    Raises:
        AppError: If not admin, missing query, or Cognito error
    """
    logger = get_logger(__name__)

    require_admin_mfa(event)

    query = str(event.get("arguments", {}).get("query", "")).strip()
    if not query:
        raise AppError(ErrorCode.INVALID_INPUT, "Search query is required")

    _validate_search_query(query)

    user_pool_id = get_required_env("USER_POOL_ID")
    cognito = get_cognito_client()

    # Determine search strategy based on query format.
    # The map values are Cognito user dicts so we can batch enrich them.
    results_map = _execute_search_strategy(query, cognito, user_pool_id, logger)
    cognito_users = list(results_map.values())

    # Batch DynamoDB display-name lookups and parallelize Cognito group lookups.
    account_ids = [_extract_cognito_attributes(user)[1].get("sub", user.get("Username", "")) for user in cognito_users]
    usernames = [user.get("Username", "") for user in cognito_users]
    display_names = _batch_get_display_names(account_ids, logger)
    groups_map = _batch_get_user_groups(cognito, user_pool_id, usernames, logger)

    return _build_admin_users_from_cognito(cognito_users, display_names, groups_map)


def _search_by_account_prefix(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Search by ACCOUNT# prefix and return Cognito-user results map."""
    sub_value = query[8:]  # Remove "ACCOUNT#"
    cognito_user = _search_user_by_sub(cognito, user_pool_id, sub_value, logger)
    if cognito_user:
        attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}
        account_id = attributes.get("sub", cognito_user.get("Username", ""))
        return {account_id: cognito_user}
    return {}


def _search_by_uuid(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Search by UUID (sub) and return Cognito-user results map."""
    cognito_user = _search_user_by_sub(cognito, user_pool_id, query, logger)
    if cognito_user:
        attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}
        account_id = attributes.get("sub", cognito_user.get("Username", ""))
        return {account_id: cognito_user}
    return {}


def _add_dynamodb_users_to_map(
    results_map: dict[str, Dict[str, Any]], query: str, cognito: Any, user_pool_id: str, logger: Any
) -> None:
    """Search DynamoDB and add matching Cognito users to results map."""
    accounts = _search_accounts_in_dynamodb(query, logger)
    for account in accounts:
        account_id = account.get("accountId", "")
        if account_id.startswith("ACCOUNT#"):
            sub_value = account_id[8:]
            cognito_user = _search_user_by_sub(cognito, user_pool_id, sub_value, logger)
            if cognito_user:
                attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}
                key = attributes.get("sub", cognito_user.get("Username", ""))
                results_map[key] = cognito_user


def _add_cognito_users_to_map(
    results_map: dict[str, Dict[str, Any]], query: str, cognito: Any, user_pool_id: str, logger: Any
) -> None:
    """Search Cognito by email and add users to results map."""
    cognito_users = _search_users_in_cognito_by_email_prefix(cognito, user_pool_id, query, logger)
    for cognito_user in cognito_users:
        attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}
        account_id = attributes.get("sub", cognito_user.get("Username", ""))
        if account_id not in results_map:
            results_map[account_id] = cognito_user


def _search_by_general_query(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Search DynamoDB and Cognito by general query and return merged results map."""
    results_map: dict[str, Dict[str, Any]] = {}
    _add_dynamodb_users_to_map(results_map, query, cognito, user_pool_id, logger)
    _add_cognito_users_to_map(results_map, query, cognito, user_pool_id, logger)
    return results_map


def _matches_query(item: Dict[str, Any], query_lower: str) -> bool:
    """Check if account item matches query (case-insensitive)."""
    email = str(item.get("email", "")).lower()
    given_name = str(item.get("givenName", "")).lower()
    family_name = str(item.get("familyName", "")).lower()
    return query_lower in email or query_lower in given_name or query_lower in family_name


def _filter_matching_accounts(
    items: list[Dict[str, Any]], query_lower: str, matches: list[Dict[str, Any]], max_results: int
) -> None:
    """Filter accounts that match the query and add to matches list."""
    for item in items:
        if len(matches) >= max_results:
            break
        if _matches_query(item, query_lower):
            matches.append(item)


def _scan_accounts_page(
    paginator_params: Dict[str, Any], page_size: int
) -> tuple[list[Dict[str, Any]], Dict[str, Any] | None, int]:
    """Scan one bounded page of accounts. Returns (items, last_evaluated_key).

    ``Limit`` caps how many items this request reads and ``ProjectionExpression``
    caps what each read item costs on the wire, so no single request can pull a
    whole 1 MB page of full account items (``preferences`` included) into the
    Lambda. The projection carries every attribute ``_matches_query`` reads plus
    the ``accountId`` the caller reads, so the match result is unchanged.
    """
    response = tables.accounts.scan(
        ProjectionExpression=_ACCOUNT_SCAN_PROJECTION,
        Limit=page_size,
        **paginator_params,
    )
    items = response.get("Items", [])
    last_key = response.get("LastEvaluatedKey")
    # ``ScannedCount`` is the number of items DynamoDB evaluated for this page;
    # ``len(items)`` is only the subset it returned. The safety budget must bound
    # the former so a table of removed/filtered items cannot blow past it.
    scanned_count = response.get("ScannedCount", len(items))
    return items, last_key, scanned_count


# Limit search results to prevent overwhelming responses.
_ACCOUNT_SEARCH_MAX_RESULTS = 50
# Safety limit on how many account items a search scan may read.
_ACCOUNTS_SCAN_SAFETY_LIMIT = 1000
# Items one Scan request may read. DynamoDB already stops a page at 1 MB of raw
# item data, but that cap is in bytes, not items: with no explicit ``Limit`` a
# single request can return several times the safety limit below, so the budget
# was only ever enforced between pages (#775).
_ACCOUNTS_SCAN_PAGE_SIZE = 250
# Hard cap on Scan requests one search may issue. The item budget alone does not
# guarantee termination: a page that returns no items but does return a
# ``LastEvaluatedKey`` advances the scan position without advancing the count.
# At the page size above the budget needs 4 pages, so 20 leaves room for
# DynamoDB's byte-capped pages while still bounding the round trips.
_ACCOUNTS_SCAN_MAX_PAGES = 20
# The only account attributes a search reads or returns: the three it matches on
# plus the key the caller consumes. Scan read cost is unchanged by a projection
# (DynamoDB bills a scan on the full item size either way); what it bounds is the
# bytes and memory one page moves (#775).
_ACCOUNT_SCAN_PROJECTION = "accountId, email, givenName, familyName"
# Shortest query an admin may search for. The only way to match a partial query
# is a full accounts-table scan, and a one or two character query can match
# most of the table while telling the admin nothing, so it is rejected outright
# instead of returning a truncated arbitrary subset (#576).
_ACCOUNT_SEARCH_MIN_QUERY_LENGTH = 3

# Accounts GSI for email prefix search: constant HASH key + email RANGE key, so
# begins_with(email, :prefix) is a legal key condition (#586). Declared in
# tofu/application/modules/dynamodb/main.tf; the index is sparse, so an account
# is only searchable once it carries the constant emailSearchKey attribute.
_EMAIL_SEARCH_INDEX = "emailSearchIndex"
_EMAIL_PREFIX_KEY_CONDITION = "emailSearchKey = :searchKey AND begins_with(email, :prefix)"


def _looks_like_email_query(query: str) -> bool:
    """Check whether the query is an email fragment (it contains the local/domain separator).

    Only email-shaped queries are answered by the prefix index; a bare name
    fragment (which ``_is_valid_email_prefix`` also accepts) is a substring
    search, and no prefix index can answer that.
    """
    return "@" in query


def _query_email_search_index(
    query: str, query_lower: str, max_results: int, logger: Any
) -> list[Dict[str, Any]] | None:
    """Answer an email prefix query with one Query against the emailSearchIndex GSI.

    That index is a constant HASH key (``emailSearchKey``) plus ``email`` as the
    RANGE key, which is what makes ``begins_with(email, :prefix)`` a legal key
    condition; the exact-lookup ``email-index`` is HASH-only and so can only be
    matched with equality and cannot answer a partial email (#576).

    Returns the matching items (capped at ``max_results``), or None when the
    index cannot answer the query -- index unavailable, or nothing indexed --
    in which case the caller falls back to the scan. The scan fallback is what
    keeps accounts that predate the index (and so carry no ``emailSearchKey``)
    findable until the backfill has covered every row.
    """
    try:
        response = tables.accounts.query(
            IndexName=_EMAIL_SEARCH_INDEX,
            KeyConditionExpression=_EMAIL_PREFIX_KEY_CONDITION,
            ExpressionAttributeValues={":searchKey": EMAIL_SEARCH_KEY, ":prefix": query_lower},
            Limit=max_results,
        )
    except ClientError as e:
        logger.warning(
            "DynamoDB email prefix query failed, falling back to scan",
            error=str(e),
            query=mask_email(query),
        )
        return None
    index_items = cast(list[Dict[str, Any]], response.get("Items", []))
    if not index_items:
        return None
    if response.get("LastEvaluatedKey"):
        logger.warning(
            "DynamoDB email prefix search hit the result limit; results may be truncated",
            query=mask_email(query),
            max_results=max_results,
        )
    return index_items[:max_results]


def _scan_accounts_page_into(
    paginator_params: Dict[str, Any],
    query_lower: str,
    matches: list[Dict[str, Any]],
    max_results: int,
    page_size: int,
) -> tuple[int, Dict[str, Any] | None]:
    """Scan one page and append its matching accounts to matches. Returns (scanned_count, last_key).

    ``scanned_count`` is the number of items DynamoDB *evaluated* (``ScannedCount``),
    not the number it returned, so the safety budget bounds scan capacity even
    when a page evaluates items that are filtered out or removed.
    """
    items, last_key, scanned_count = _scan_accounts_page(paginator_params, page_size)
    _filter_matching_accounts(items, query_lower, matches, max_results)
    return scanned_count, last_key


def _scan_is_truncated(scanned_count: int, pages: int, last_count: int, last_key: Dict[str, Any] | None) -> bool:
    """Return True when the scan stopped with pages left unread.

    A page that returned no items while handing back a ``LastEvaluatedKey``
    stopped the walk without consuming the item budget, so it is truncation too.
    """
    if not last_key:
        return False
    return scanned_count >= _ACCOUNTS_SCAN_SAFETY_LIMIT or pages >= _ACCOUNTS_SCAN_MAX_PAGES or last_count == 0


def _warn_if_accounts_scan_truncated(
    scanned_count: int, pages: int, last_count: int, last_key: Dict[str, Any] | None, query: str, logger: Any
) -> None:
    """Warn when the account scan stopped with more pages left."""
    if _scan_is_truncated(scanned_count, pages, last_count, last_key):
        logger.warning(
            "DynamoDB accounts search reached max scan limit; results may be truncated",
            query=mask_email(query),
            scanned_count=scanned_count,
        )


def _scan_accounts_matches(query: str, query_lower: str, max_results: int, logger: Any) -> list[Dict[str, Any]]:
    """Scan the Accounts table in bounded pages, collecting matches until a limit is hit.

    A name fragment is a substring search, so no index on this table can answer
    it and the scan is required (#775). What is bounded is its cost: each page
    asks DynamoDB for at most what the item budget still allows, so the scan
    never reads more than `_ACCOUNTS_SCAN_SAFETY_LIMIT` items and never issues
    more than `_ACCOUNTS_SCAN_MAX_PAGES` requests, whatever page shape the
    service returns. The previous loop only checked the budget between pages,
    so one unbounded 1 MB page could overshoot it several times over.
    """
    matches: list[Dict[str, Any]] = []
    scanned_count = 0
    pages = 0
    last_count = 0
    paginator_params: Dict[str, Any] = {}
    last_key: Dict[str, Any] | None = None
    while scanned_count < _ACCOUNTS_SCAN_SAFETY_LIMIT and len(matches) < max_results:
        if pages >= _ACCOUNTS_SCAN_MAX_PAGES:
            break
        page_size = min(_ACCOUNTS_SCAN_PAGE_SIZE, _ACCOUNTS_SCAN_SAFETY_LIMIT - scanned_count)
        count, last_key = _scan_accounts_page_into(paginator_params, query_lower, matches, max_results, page_size)
        scanned_count += count
        last_count = count
        pages += 1
        if not last_key or count == 0:
            break
        paginator_params["ExclusiveStartKey"] = last_key
    _warn_if_accounts_scan_truncated(scanned_count, pages, last_count, last_key, query, logger)
    return matches


def _search_accounts_in_dynamodb(query: str, logger: Any) -> list[Dict[str, Any]]:
    """Search the accounts table for accounts matching a partial query.

    Searches email, givenName, and familyName fields. An email fragment is
    answered by the emailSearchIndex GSI, whose constant HASH key plus ``email``
    RANGE key make a ``begins_with`` key condition legal: one index query, no
    table scan (#586). A name fragment is a substring search that no prefix
    index can answer, so it is still served by a full scan of the accounts
    table, paginated with `LastEvaluatedKey` and bounded per request by
    `_ACCOUNTS_SCAN_PAGE_SIZE` items up to the `_ACCOUNTS_SCAN_SAFETY_LIMIT`
    item budget, then truncated at `_ACCOUNT_SEARCH_MAX_RESULTS` matches. Either
    path falls back to the scan when the index has no answer.

    Returns all matching accounts (up to max_results limit).
    """
    query_lower = query.lower()

    try:
        if _looks_like_email_query(query):
            index_items = _query_email_search_index(query, query_lower, _ACCOUNT_SEARCH_MAX_RESULTS, logger)
            if index_items is not None:
                return index_items
        return _scan_accounts_matches(query, query_lower, _ACCOUNT_SEARCH_MAX_RESULTS, logger)
    except ClientError as e:
        logger.warning("DynamoDB search failed", error=str(e), query=mask_email(query))
        return []


def _looks_like_uuid(value: str) -> bool:
    """Check if a string looks like a UUID."""
    # UUID format: 8-4-4-4-12 hex characters
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    return bool(re.match(uuid_pattern, value.lower()))


def _is_valid_email_prefix(value: str) -> bool:
    """Check if a string is a valid email prefix (local part or local@partial-domain)."""
    try:
        cognito_user_filter("email_prefix", value)
    except AppError:
        return False
    return True


def _validate_search_query(query: str) -> None:
    """Validate that the admin search query is a safe UUID, email prefix, or ACCOUNT#UUID.

    A non-UUID query is served by a full accounts-table scan, so a query below
    `_ACCOUNT_SEARCH_MIN_QUERY_LENGTH` is rejected rather than scanning the
    table for a result that cannot narrow anything down (#576).
    """
    if query.startswith("ACCOUNT#"):
        if _looks_like_uuid(query[8:]):
            return
    elif _looks_like_uuid(query):
        return
    elif _is_valid_email_prefix(query):
        if len(query) < _ACCOUNT_SEARCH_MIN_QUERY_LENGTH:
            raise AppError(
                ErrorCode.INVALID_INPUT,
                f"Search query must be at least {_ACCOUNT_SEARCH_MIN_QUERY_LENGTH} characters",
            )
        return

    raise AppError(
        ErrorCode.INVALID_INPUT,
        "Search query must be a valid UUID, email prefix, or ACCOUNT#UUID",
    )


def _search_user_by_sub(cognito: Any, user_pool_id: str, sub: str, logger: Any) -> Dict[str, Any] | None:
    """Search for a Cognito user by sub (account ID)."""
    try:
        response = retry_on_transient_errors(
            cognito.list_users,
            UserPoolId=user_pool_id,
            Filter=cognito_user_filter("sub", sub),
            Limit=1,
        )
        users = response.get("Users", [])
        return users[0] if users else None
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in TRANSIENT_ERROR_CODES:
            logger.warning("Cognito search by sub throttled", error=str(e), error_code=error_code, sub=sub)
            raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to load data. Please retry.") from e
        logger.warning("Cognito search by sub failed", error=str(e), sub=sub)
        return None


def _search_users_in_cognito_by_email_prefix(
    cognito: Any, user_pool_id: str, query: str, logger: Any
) -> list[Dict[str, Any]]:
    """
    Search Cognito users by email prefix.

    Uses Cognito's email ^= filter for prefix matching.
    This finds users who haven't logged in yet (no DynamoDB record).

    Returns up to 50 matching users.
    """
    try:
        response = retry_on_transient_errors(
            cognito.list_users,
            UserPoolId=user_pool_id,
            Filter=cognito_user_filter("email_prefix", query),  # Prefix match on email
            Limit=50,  # Reasonable limit for search results
        )
        return list(response.get("Users", []))
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in TRANSIENT_ERROR_CODES:
            logger.warning(
                "Cognito email prefix search throttled",
                error=str(e),
                error_code=error_code,
                query=mask_email(query),
            )
            raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to load data. Please retry.") from e
        logger.warning("Cognito email prefix search failed", error=str(e), query=mask_email(query))
        return []


def _extract_cognito_attributes(cognito_user: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
    """Extract username and attributes from Cognito user."""
    username = cognito_user.get("Username", "")
    attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}
    return username, attributes


def _build_admin_users_from_cognito(
    cognito_users: list[Dict[str, Any]],
    display_names: dict[str, str],
    groups_map: dict[str, list[str]],
) -> list[Dict[str, Any]]:
    """Build AdminUser objects from Cognito users plus cached display names and groups."""
    admin_users = []
    for cognito_user in cognito_users:
        username, attributes = _extract_cognito_attributes(cognito_user)
        account_id = attributes.get("sub", username)
        groups = groups_map.get(username, [])
        created_at = cognito_user.get("UserCreateDate")
        last_modified_at = cognito_user.get("UserLastModifiedDate")
        admin_users.append(
            {
                "accountId": account_id,
                "email": attributes.get("email", ""),
                "displayName": display_names.get(account_id),
                "status": cognito_user.get("UserStatus", "UNKNOWN"),
                "enabled": cognito_user.get("Enabled", True),
                "emailVerified": attributes.get("email_verified", "false").lower() == "true",
                "isAdmin": "ADMIN" in groups,
                "createdAt": created_at.isoformat() if created_at else None,
                "lastModifiedAt": last_modified_at.isoformat() if last_modified_at else None,
            }
        )
    return admin_users
