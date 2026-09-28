"""
Admin operations handlers for superadmin functionality.

Provides:
- adminResetUserPassword: Send password reset email to user
- adminPurgeUserAccount: Delete the Cognito user (the commit point), then
  sweep the client-unreachable residue and the accounts record
- createManagedCatalog: Create an ADMIN_MANAGED global catalog

User deletion is client-side by decision (#521). The client issues the
per-entity ``adminDeleteUser*`` mutations it can reach, reads the profile IDs
with ``adminGetUserProfiles`` before deleting the profile rows, and calls
``adminPurgeUserAccount`` with them as ``profileIds``. After verifying the
client's cascade finished, the purge deletes the Cognito user first (the
commit point, #551), then sweeps the four classes the browser cannot reach
itself — invites for the account's profiles, inbound shares on other owners'
profiles, S3 report objects, and payment-QR S3 objects — reusing the shared
``deletion_cascade`` helpers, and finally the ``accounts`` record. Catalogs
are never deleted.

Audit attribution (#507): AppSync logs at ERROR level only, so these handlers
are the only record that an admin operation happened at all. Every admin audit
line therefore carries the acting administrator's ``sub`` as ``actor_sub``, and
the ``_require_admin_and_get_*`` helpers return the actor alongside the target
so it cannot be silently dropped: the target is the account, profile, or
campaign the request names, the actor is the caller, and they are different
principals.
"""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Callable, Dict, NoReturn, Optional, cast

from botocore.exceptions import ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import (
    delete_inbound_shares,
    delete_invites_for_owned_profiles,
    delete_user_campaigns,
    delete_user_orders,
    delete_user_profiles,
    delete_user_s3_reports,
    delete_user_shares,
    get_user_profiles,
    normalize_account_id,
)

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import require_admin_mfa
    from utils.boto import get_cognito_client
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import EMAIL_SEARCH_KEY, TRANSIENT_ERROR_CODES, batch_get_chunked, get_required_env, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger, mask_email
    from utils.payment_methods import delete_all_user_qr_codes
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import require_admin_mfa
    from ..utils.boto import get_cognito_client
    from ..utils.cognito_filters import cognito_user_filter
    from ..utils.dynamodb import EMAIL_SEARCH_KEY, TRANSIENT_ERROR_CODES, batch_get_chunked, get_required_env, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger, mask_email
    from ..utils.payment_methods import delete_all_user_qr_codes

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

# Handle both Lambda (absolute) and unit test (relative) imports.  mypy sees the
# relative path it can resolve; the runtime fallback tries absolute first for Lambda.
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.pagination import query_all_items
else:  # pragma: no cover
    try:
        from utils.pagination import query_all_items
    except ModuleNotFoundError:
        from ..utils.pagination import query_all_items


# DynamoDB/Cognito throttling codes: the lookup is retryable, so surface a
# RESOURCE_BUSY error instead of silently incomplete admin data (#291, #456).
# This is the canonical transient/permanent split for these lookups: sibling
# handlers import it (see _raise_gather_failures, used by #556) rather than
# redeclaring their own copy. Only redeclare a local set when the caller's AWS
# surface genuinely differs (e.g. the DynamoDB BatchGetItem throttle code).
# The set itself is owned by utils.dynamodb and shared with the
# ownership-transfer share repair (#549), so the rule has one home.
_THROTTLING_ERROR_CODES = TRANSIENT_ERROR_CODES


def _throttling_error_code(error: BaseException) -> str:
    """Return the AWS error code of a ClientError, or "" for anything else.

    The single place the transient/permanent decision is read: a non-ClientError
    and a ClientError with an unrecognized code both return a value outside
    `_THROTTLING_ERROR_CODES`, i.e. permanent.
    """
    if not isinstance(error, ClientError):
        return ""
    return error.response.get("Error", {}).get("Code", "")


def _raise_batch_lookup_error(
    operation: str,
    logger: Any,
    error: BaseException,
    *,
    throttling_codes: frozenset[str] = _THROTTLING_ERROR_CODES,
    busy_message: str = "Temporarily unable to load data. Please retry.",
    **context: Any,
) -> NoReturn:
    """Translate a failed batch lookup into a typed AppError (#291).

    Throttling conditions become a retryable RESOURCE_BUSY so the admin UI can
    show a retry prompt; any other ClientError or unexpected exception becomes
    an INTERNAL_ERROR after an error-level log. Never returns: always raises.

    `throttling_codes` and `busy_message` let a caller reuse the classification
    with a service-specific code set or user-facing wording.
    """
    if isinstance(error, ClientError):
        error_code = _throttling_error_code(error)
        if error_code in throttling_codes:
            logger.warning(f"{operation} throttled", error=str(error), error_code=error_code, **context)
            raise AppError(ErrorCode.RESOURCE_BUSY, busy_message) from error
        logger.error(f"{operation} failed", error=str(error), error_code=error_code, **context)
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to {operation}") from error
    logger.error(f"{operation} failed unexpectedly", error=str(error), **context)
    raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to {operation}") from error


def _raise_gather_failures(
    operation: str,
    logger: Any,
    failures: list[BaseException],
    *,
    throttling_codes: frozenset[str] = _THROTTLING_ERROR_CODES,
    busy_message: str = "Temporarily unable to load data. Please retry.",
    **context: Any,
) -> NoReturn:
    """Refuse a partial answer when a parallel gather collected any failure.

    For N per-item lookups run concurrently, where returning the survivors would
    be an authoritative-looking but incomplete answer (#556). A single transient
    failure keeps the whole request retryable; otherwise the first failure is
    reported as permanent. Never returns: always raises.
    """
    for failure in failures:
        if _throttling_error_code(failure) in throttling_codes:
            _raise_batch_lookup_error(
                operation, logger, failure, throttling_codes=throttling_codes, busy_message=busy_message, **context
            )
    _raise_batch_lookup_error(
        operation, logger, failures[0], throttling_codes=throttling_codes, busy_message=busy_message, **context
    )


def _get_user_groups(cognito: Any, user_pool_id: str, username: str, logger: Any) -> list[str]:
    """Get the groups a user belongs to; failures raise a typed AppError (#291)."""
    try:
        response = cognito.admin_list_groups_for_user(
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
    exception is translated via _raise_batch_lookup_error.
    """
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
        db_account_id = account_id if account_id.startswith("ACCOUNT#") else f"ACCOUNT#{account_id}"
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
        response = cognito.list_users(**list_params)
    except ClientError as e:
        logger.error("Cognito list_users failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list users")

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


def _actor_sub(event: Dict[str, Any]) -> str:
    """Return the acting administrator's Cognito ``sub`` for audit logging (#507).

    Read only after ``require_admin_mfa`` has approved the caller, so resolving
    the actor can never change an authorization decision. A missing ``sub``
    yields an empty string rather than raising, so auditing can never turn a
    permitted operation into a failure.
    """
    sub = event.get("identity", {}).get("sub")
    return str(sub) if sub else ""


def _require_admin_and_get_target_account_id(event: Dict[str, Any]) -> tuple[str, str]:
    """Require admin + MFA, returning ``(target_account_id, actor_sub)`` (#507).

    The two values are returned together so the actor travels with the target:
    every admin audit line downstream records both, which is what makes an
    administrative action attributable after the fact. ``target_account_id`` is
    the account named by the request — usually somebody else — and ``actor_sub``
    is the calling administrator's own Cognito ``sub``. They are distinct
    principals and must not be conflated (the historical helper name invited
    exactly that reading).
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    account_id = str(arguments.get("accountId", "")).strip()

    if not account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

    return account_id, actor_sub


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


def _scan_accounts_page(paginator_params: Dict[str, Any]) -> tuple[list[Dict[str, Any]], Dict[str, Any] | None]:
    """Scan one page of accounts. Returns (items, last_evaluated_key)."""
    response = tables.accounts.scan(**paginator_params)
    items = response.get("Items", [])
    last_key = response.get("LastEvaluatedKey")
    return items, last_key


# Limit search results to prevent overwhelming responses.
_ACCOUNT_SEARCH_MAX_RESULTS = 50
# Safety limit on how many account items a search scan may read.
_ACCOUNTS_SCAN_SAFETY_LIMIT = 1000
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
    paginator_params: Dict[str, Any], query_lower: str, matches: list[Dict[str, Any]], max_results: int
) -> tuple[int, Dict[str, Any] | None]:
    """Scan one page and append its matching accounts to matches. Returns (page_size, last_key)."""
    items, last_key = _scan_accounts_page(paginator_params)
    _filter_matching_accounts(items, query_lower, matches, max_results)
    return len(items), last_key


def _warn_if_accounts_scan_truncated(
    scanned_count: int, last_key: Dict[str, Any] | None, query: str, logger: Any
) -> None:
    """Warn when the account scan stopped at the safety limit with more pages left."""
    if scanned_count >= _ACCOUNTS_SCAN_SAFETY_LIMIT and last_key:
        logger.warning(
            "DynamoDB accounts search reached max scan limit; results may be truncated",
            query=mask_email(query),
            scanned_count=scanned_count,
        )


def _scan_accounts_matches(query: str, query_lower: str, max_results: int, logger: Any) -> list[Dict[str, Any]]:
    """Scan the Accounts table, collecting matches until the result/scan limits are hit."""
    matches: list[Dict[str, Any]] = []
    scanned_count = 0
    paginator_params: Dict[str, Any] = {}
    last_key: Dict[str, Any] | None = None
    while scanned_count < _ACCOUNTS_SCAN_SAFETY_LIMIT and len(matches) < max_results:
        count, last_key = _scan_accounts_page_into(paginator_params, query_lower, matches, max_results)
        scanned_count += count
        if not last_key:
            break
        paginator_params["ExclusiveStartKey"] = last_key
    _warn_if_accounts_scan_truncated(scanned_count, last_key, query, logger)
    return matches


def _search_accounts_in_dynamodb(query: str, logger: Any) -> list[Dict[str, Any]]:
    """Search the accounts table for accounts matching a partial query.

    Searches email, givenName, and familyName fields. An email fragment is
    answered by the emailSearchIndex GSI, whose constant HASH key plus ``email``
    RANGE key make a ``begins_with`` key condition legal: one index query, no
    table scan (#586). A name fragment is a substring search that no prefix
    index can answer, so it is still served by a full scan of the accounts
    table, bounded by the `_ACCOUNTS_SCAN_SAFETY_LIMIT` safety limit and
    truncated at `_ACCOUNT_SEARCH_MAX_RESULTS` matches. Either path falls back
    to the scan when the index has no answer.

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
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=cognito_user_filter("sub", sub),
            Limit=1,
        )
        users = response.get("Users", [])
        return users[0] if users else None
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in _THROTTLING_ERROR_CODES:
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
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=cognito_user_filter("email_prefix", query),  # Prefix match on email
            Limit=50,  # Reasonable limit for search results
        )
        return list(response.get("Users", []))
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in _THROTTLING_ERROR_CODES:
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


def _find_cognito_user_by_sub(
    cognito: Any, user_pool_id: str, account_id: str, logger: Any
) -> tuple[str | None, str | None]:
    """Find Cognito user by sub and return (username, email).

    Only an empty Cognito response indicates the user is already absent.
    Lookup failures (throttling, InternalErrorException, etc.) raise an
    AppError so the caller does not proceed to delete DynamoDB data while
    the Cognito user still exists.
    """
    raw_sub = account_id[8:] if account_id.startswith("ACCOUNT#") else account_id
    try:
        users_response = cognito.list_users(
            UserPoolId=user_pool_id,
            # Built in one step so the value that was checked is the value sent (#124, #560).
            Filter=cognito_user_filter("sub", raw_sub),
            Limit=1,
        )
        users = users_response.get("Users", [])
        if users:
            username = users[0]["Username"]
            attributes = {attr["Name"]: attr["Value"] for attr in users[0].get("Attributes", [])}
            email = attributes.get("email", "")
            return username, email
    except ClientError as e:
        logger.error("Cognito lookup by sub failed", error=str(e), account_id=account_id)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to look up Cognito user") from e
    return None, None


def _delete_user_from_cognito(
    cognito: Any, user_pool_id: str, username: str, email: str, logger: Any, actor_sub: str = ""
) -> None:
    """Delete user from Cognito, treating UserNotFoundException as idempotent success."""
    masked_email = mask_email(email)
    try:
        cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
        logger.info(
            "Deleted user from Cognito",
            username=mask_email(username),
            email=masked_email,
            actor_sub=actor_sub,
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "UserNotFoundException":
            logger.info(
                "Cognito user already deleted",
                username=mask_email(username),
                email=masked_email,
                actor_sub=actor_sub,
            )
            return
        logger.error("Cognito admin_delete_user failed", error=str(e), error_code=error_code)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user from Cognito") from e


def _account_exists_in_dynamodb(account_id: str, logger: Any, actor_sub: str = "") -> bool:
    """Check whether an account record exists in DynamoDB."""
    db_account_id = normalize_account_id(account_id)
    try:
        response = tables.accounts.get_item(Key={"accountId": db_account_id}, ProjectionExpression="accountId")
        exists = "Item" in response
        if not exists:
            logger.info("Account not found in DynamoDB", account_id=db_account_id, actor_sub=actor_sub)
        return exists
    except ClientError as e:
        logger.error("Failed to check account existence in DynamoDB", error=str(e), account_id=db_account_id)
        raise


def _find_user_by_email(cognito: Any, user_pool_id: str, email: str, logger: Any) -> str:
    """Find username by email. Returns username."""
    try:
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            # Built in one step so the value that was checked is the value sent (#124, #560).
            Filter=cognito_user_filter("email", email),
            Limit=1,
        )
    except ClientError as e:
        logger.error("Cognito list_users failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to search for user")

    users = response.get("Users", [])
    if not users:
        raise AppError(ErrorCode.NOT_FOUND, f"User with email '{email}' not found")

    return str(users[0]["Username"])


def _initiate_password_reset(cognito: Any, user_pool_id: str, username: str, email: str, logger: Any) -> None:
    """Initiate Cognito password reset for user."""
    try:
        cognito.admin_reset_user_password(
            UserPoolId=user_pool_id,
            Username=username,
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "UserNotFoundException":
            raise AppError(ErrorCode.NOT_FOUND, f"User with email '{email}' not found")
        if error_code == "InvalidParameterException":
            raise AppError(ErrorCode.INVALID_INPUT, "Cannot reset password for this user type")
        logger.error("Cognito admin_reset_user_password failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to initiate password reset")


@with_error_handling(error_message="Failed to reset password")
def admin_reset_user_password(event: Dict[str, Any], context: Any) -> bool:
    """
    Send password reset email to user (admin only).

    AppSync Lambda resolver for adminResetUserPassword mutation.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        True if password reset was initiated successfully

    Raises:
        AppError: If not admin, user not found, or Cognito error
    """
    logger = get_logger(__name__)

    # Verify caller is admin and extract email
    require_admin_mfa(event)

    arguments = event.get("arguments", {})
    email = arguments.get("email", "").strip().lower()

    if not email:
        raise AppError(ErrorCode.INVALID_INPUT, "Email is required")

    user_pool_id = get_required_env("USER_POOL_ID")
    cognito = get_cognito_client()

    # Find user and initiate reset
    username = _find_user_by_email(cognito, user_pool_id, email, logger)
    _initiate_password_reset(cognito, user_pool_id, username, email, logger)

    actor_sub = _actor_sub(event)
    logger.info(
        "Password reset initiated",
        email=mask_email(email),
        username=mask_email(username),
        actor_sub=actor_sub,
    )
    return True


def _check_not_self_deletion(caller_id: str, account_id: str) -> None:
    """Prevent admin from deleting their own account.

    Normalize both IDs to their canonical ACCOUNT# form before comparing so a
    caller passing ``ACCOUNT#<own-sub>`` cannot bypass the guard (#125).
    """
    if normalize_account_id(account_id) == normalize_account_id(caller_id):
        raise AppError(ErrorCode.INVALID_INPUT, "Cannot delete your own account")


@with_error_handling(error_message="Failed to purge user account")
def admin_purge_user_account(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete the account record and the Cognito user (admin only).

    AppSync Lambda resolver for the adminPurgeUserAccount mutation. This is the
    deliberately minimal server-side operation that user deletion cannot be
    completed without (#521): the browser holds no AWS credentials, so it can
    neither delete the ``accounts`` table row nor call Cognito
    ``AdminDeleteUser``. Everything else a browser CAN delete (orders,
    campaigns, shares, profiles) is deleted by the client through the
    per-entity ``adminDeleteUser*`` mutations, and catalogs are never deleted.

    The caller supplies the profile IDs it read via ``adminGetUserProfiles``
    BEFORE deleting the profile rows, as the ``profileIds`` argument. The purge
    first verifies each of them is actually gone with a strongly consistent
    read — a surviving profile means the client cascade has not completed, so
    it refuses with CONFLICT and deletes nothing — then deletes the Cognito
    user (the commit point, #551) and sweeps the four classes the browser
    cannot reach, reusing the shared deletion_cascade helpers: invites for
    the account's profiles, inbound shares on other owners' profiles, S3
    report objects, and payment-QR S3 objects. Invites and reports are keyed
    by profileId, which survives the deleted profile rows.

    Call this after the client's per-entity deletes, so a failure there leaves
    the account intact rather than half-deleted.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        True if the account was purged successfully

    Raises:
        AppError: If not admin, self-purge is attempted, the user does not
            exist, a supplied profile still exists (CONFLICT), or a deletion
            error occurs. An absent Cognito user is treated as idempotent
            success.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    profile_ids = _validate_profile_ids_argument(event.get("arguments", {}).get("profileIds"))

    # The self-deletion guard keeps its own raw read of the caller's sub so its
    # decision is bit-for-bit what it was before #507; actor_sub is audit only.
    caller_id = event.get("identity", {}).get("sub")
    _check_not_self_deletion(str(caller_id), account_id)

    user_pool_id = get_required_env("USER_POOL_ID")
    cognito = get_cognito_client()

    username, email = _find_cognito_user_by_sub(cognito, user_pool_id, account_id, logger)
    account_exists = _account_exists_in_dynamodb(account_id, logger, actor_sub)

    if not username and not account_exists:
        raise AppError(ErrorCode.NOT_FOUND, f"User not found: {account_id}")

    # The purge runs after the client's per-entity deletes (#521). It verifies
    # rather than trusts: while any supplied profile still exists the cascade
    # has not completed, so nothing is deleted and the account stays intact.
    _assert_profiles_deleted(account_id, profile_ids, logger, actor_sub)

    # Delete the Cognito user FIRST so the Cognito call is the commit point (#551).
    # A data-phase failure afterwards leaves records the user can no longer reach
    # (no sign-in, so no post_authentication re-bootstrap) and a re-run of the
    # data phase is safe; a Cognito failure leaves every record intact. Deleting
    # data first would leave a sign-in-capable Cognito user whose records are
    # gone, silently re-bootstrapped as an empty account on next sign-in.
    if username:
        _delete_user_from_cognito(cognito, user_pool_id, username, email or "", logger, actor_sub)
    else:
        logger.info("Cognito user already absent; proceeding with DynamoDB cleanup", account_id=account_id, actor_sub=actor_sub)

    # Everything below runs after the Cognito commit: a failure here is logged
    # loudly with an error_code-tagged field and re-raised, so the partial delete
    # is detectable while the leftover records stay inert.
    try:
        profiles_for_sweep = [{"profileId": profile_id} for profile_id in profile_ids]
        delete_invites_for_owned_profiles(profiles_for_sweep, logger)
        delete_inbound_shares(account_id, logger)
        delete_user_s3_reports(profiles_for_sweep, logger)
        delete_all_user_qr_codes(account_id, logger)

        if account_exists:
            db_account_id = normalize_account_id(account_id)
            try:
                tables.accounts.delete_item(Key={"accountId": db_account_id})
                logger.info("Deleted account record", account_id=db_account_id, actor_sub=actor_sub)
            except ClientError as e:
                logger.error("Failed to delete account record", error=str(e), account_id=db_account_id)
                raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete account record") from e
        else:
            logger.info("Account record already absent", account_id=account_id, actor_sub=actor_sub)
    except Exception as e:
        logger.error(
            "Cognito user already deleted but user data cleanup failed; "
            "leftover records are inert because the user can no longer sign in",
            account_id=account_id,
            error=str(e),
            error_code=ErrorCode.INTERNAL_ERROR,
        )
        raise

    logger.info("User account purged", account_id=account_id, email=mask_email(email), actor_sub=actor_sub)
    return True


def _validate_profile_ids_argument(profile_ids: Any) -> list[str]:
    """Validate the client-supplied profileIds list for the purge (#521).

    The schema requires ``[ID!]!``; this guards the Lambda entry point itself,
    which a caller can reach without going through GraphQL validation.
    """
    if not isinstance(profile_ids, list) or not all(
        isinstance(profile_id, str) and profile_id.strip() for profile_id in profile_ids
    ):
        raise AppError(ErrorCode.INVALID_INPUT, "profileIds must be a list of profile IDs")
    return profile_ids


def _assert_profiles_deleted(account_id: str, profile_ids: list[str], logger: Any, actor_sub: str = "") -> None:
    """Refuse the purge while any client-reported-deleted profile still exists (#521).

    The strongly consistent read is required because the profile rows were
    just deleted by a different writer (the client's cascade moments earlier).
    """
    db_account_id = normalize_account_id(account_id)
    for profile_id in profile_ids:
        try:
            response = tables.profiles.get_item(
                Key={"ownerAccountId": db_account_id, "profileId": profile_id},
                ConsistentRead=True,
            )
        except ClientError as e:
            _raise_batch_lookup_error("verify profile deletion", logger, e, profile_id=profile_id)
        if "Item" in response:
            logger.warning("Purge refused: profile still present", profile_id=profile_id, actor_sub=actor_sub)
            raise AppError(
                ErrorCode.CONFLICT,
                "The account's profiles must be deleted before the account can be purged",
            )


def _parse_product_price(price: Any) -> Decimal:
    """Convert a product price (number or numeric string) to a validated Decimal.

    A missing price, a non-numeric/unparsable value, or a negative price
    raises INVALID_INPUT.
    """
    if price is None:
        raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")

    try:
        price_decimal = Decimal(str(price))
    except InvalidOperation, ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, "Product price must be a valid number")

    if price_decimal < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")
    return price_decimal


def _validate_and_process_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and process a catalog product, returning processed product dict.

    Price may arrive as a number or a numeric string (e.g. from AppSync JSON
    deserialization); it is converted to Decimal before validation and storage.
    Non-numeric or unparsable values raise INVALID_INPUT.
    """
    product_name = product.get("productName", "").strip()

    if not product_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Product name is required")

    processed_product: Dict[str, Any] = {
        "productId": f"PRODUCT#{uuid.uuid4()}",
        "productName": product_name,
        "price": _parse_product_price(product.get("price")),
        "sortOrder": product.get("sortOrder", 0),
    }

    description = product.get("description", "").strip()
    if description:
        processed_product["description"] = description

    return processed_product


def _validate_catalog_input(catalog_input: Dict[str, Any]) -> tuple[str, bool, list[Dict[str, Any]]]:
    """Validate catalog input and extract name, isPublic, products."""
    catalog_name = catalog_input.get("catalogName", "").strip()
    is_public = catalog_input.get("isPublic", True)
    products = catalog_input.get("products", [])

    if not catalog_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Catalog name is required")
    if not products:
        raise AppError(ErrorCode.INVALID_INPUT, "Products array cannot be empty")

    return catalog_name, is_public, products


def _build_catalog_item(
    catalog_id: str,
    catalog_name: str,
    is_public: bool,
    caller_id: str,
    processed_products: list[Dict[str, Any]],
    now: str,
) -> Dict[str, Any]:
    """Build the catalog item dictionary for DynamoDB."""
    return {
        "catalogId": catalog_id,
        "catalogName": catalog_name,
        "catalogType": "ADMIN_MANAGED",  # Key difference from regular createCatalog
        "ownerAccountId": f"ACCOUNT#{caller_id}",  # Track who created it
        "isPublic": is_public,
        "isPublicStr": "true" if is_public else "false",  # For GSI queries
        "products": processed_products,
        "createdAt": now,
        "updatedAt": now,
    }


def _persist_catalog(catalog_item: Dict[str, Any], logger: Any) -> None:
    """Persist catalog to DynamoDB."""
    try:
        tables.catalogs.put_item(Item=catalog_item)
    except ClientError as e:
        logger.error("Failed to create catalog", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create catalog")


def _require_admin_and_get_actor_sub(event: Dict[str, Any]) -> str:
    """Require admin + MFA and return the acting administrator's own ``sub`` (#507).

    The actor counterpart to `_require_admin_and_get_target_account_id`: this
    one returns the caller, whose sub is what the audit line must record.
    """
    require_admin_mfa(event)

    identity = event.get("identity", {})
    caller_id = identity.get("sub")
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

    return str(caller_id)


@with_error_handling(error_message="Failed to create catalog")
def create_managed_catalog(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create an ADMIN_MANAGED catalog (admin only).

    AppSync Lambda resolver for createManagedCatalog mutation.
    Creates a global catalog that is available to all users.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        Created Catalog object

    Raises:
        AppError: If not admin, validation fails, or creation error
    """
    logger = get_logger(__name__)

    caller_id = _require_admin_and_get_actor_sub(event)

    arguments = event.get("arguments", {})
    catalog_input = arguments.get("input", {})

    catalog_name, is_public, products = _validate_catalog_input(catalog_input)

    catalog_id = f"CATALOG#{uuid.uuid4()}"
    now = datetime.now(timezone.utc).isoformat()

    processed_products = [_validate_and_process_product(product) for product in products]

    catalog_item = _build_catalog_item(catalog_id, catalog_name, is_public, caller_id, processed_products, now)

    _persist_catalog(catalog_item, logger)

    logger.info(
        "Created managed catalog",
        catalog_id=catalog_id,
        catalog_name=catalog_name,
        actor_sub=caller_id,
    )

    return catalog_item


def _user_profiles_for(account_id: str) -> list[Dict[str, Any]]:
    """Sweep the profiles table once for a per-domain admin deletion."""
    return get_user_profiles(normalize_account_id(account_id))


@with_error_handling(error_message="Failed to delete user orders")
def admin_delete_user_orders(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all orders for all campaigns of all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted order is gone
    from the orders table before returning success.

    Returns the count of deleted orders.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_orders(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user orders", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user campaigns")
def admin_delete_user_campaigns(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all campaigns for all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted campaign is gone
    from the campaigns table before returning success.

    Returns the count of deleted campaigns.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_campaigns(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user campaigns", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user shares")
def admin_delete_user_shares(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all shares for all profiles owned by a user (admin only).

    Returns the count of deleted shares.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_shares(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user shares", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user profiles")
def admin_delete_user_profiles(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all profiles owned by a user (admin only).

    Returns the count of deleted profiles.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_profiles(account_id, _user_profiles_for(account_id), logger)
    logger.info("Admin deleted user profiles", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to get user profiles")
def admin_get_user_profiles(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all profiles owned by a user (admin only).

    Returns the list of profiles with full details.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query profiles by ownerAccountId
    profiles = query_all_items(
        tables.profiles,
        {
            "KeyConditionExpression": "ownerAccountId = :owner",
            "ExpressionAttributeValues": {":owner": db_account_id},
        },
    )

    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles), actor_sub=actor_sub)
    return profiles


@with_error_handling(error_message="Failed to get user catalogs")
def admin_get_user_catalogs(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all catalogs owned by a user (admin only).

    Returns the list of catalogs with full details.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query catalogs by ownerAccountId using GSI
    catalogs = query_all_items(
        tables.catalogs,
        {
            "IndexName": "ownerAccountId-index",
            "KeyConditionExpression": "ownerAccountId = :owner",
            "FilterExpression": "attribute_not_exists(isDeleted) OR isDeleted = :false",
            "ExpressionAttributeValues": {
                ":owner": db_account_id,
                ":false": False,
            },
        },
    )

    logger.info("Retrieved user catalogs", account_id=account_id, count=len(catalogs), actor_sub=actor_sub)
    return catalogs


def _extract_unique_catalog_ids(campaigns: list[Dict[str, Any]]) -> list[str]:
    """Extract the de-duplicated catalogIds from a campaign array, preserving first-seen order."""
    catalog_ids: list[str] = []
    seen: set[str] = set()
    for campaign in campaigns:
        catalog_id = campaign.get("catalogId")
        if catalog_id and catalog_id not in seen:
            seen.add(catalog_id)
            catalog_ids.append(catalog_id)
    return catalog_ids


def _batch_get_catalog_items(
    catalog_ids: list[str], catalogs_table_name: str, logger: Any
) -> Dict[str, Dict[str, Any]]:
    """Batch-get the catalogs by id; the shared helper owns the 100-key chunking.

    Raises AppError if keys stay unprocessed after the retries (#557).
    """
    catalog_map: Dict[str, Dict[str, Any]] = {}

    def _store_catalog(item: Dict[str, Any]) -> None:
        catalog_map[item["catalogId"]] = item

    batch_get_chunked(
        catalogs_table_name,
        [{"catalogId": catalog_id} for catalog_id in catalog_ids],
        _store_catalog,
        consistent_read=False,
        logger=logger,
    )
    return catalog_map


def _campaign_catalog_value(catalog: Dict[str, Any] | None, treat_deleted_as_null: bool) -> Dict[str, Any] | None:
    """Map a fetched catalog to its Campaign/SharedCampaign catalog contract value."""
    if catalog is not None and treat_deleted_as_null and catalog.get("isDeleted") is True:
        return None
    return catalog


def _attach_campaign_catalogs(
    campaigns: list[Dict[str, Any]], catalog_map: Dict[str, Dict[str, Any]], treat_deleted_as_null: bool
) -> None:
    """Attach each campaign's fetched catalog, mapping missing/soft-deleted per contract."""
    for campaign in campaigns:
        catalog_id = campaign.get("catalogId")
        if not catalog_id:
            continue
        campaign["catalog"] = _campaign_catalog_value(catalog_map.get(catalog_id), treat_deleted_as_null)


def _batch_get_campaign_catalogs(campaigns: list[Dict[str, Any]], treat_deleted_as_null: bool, logger: Any) -> None:
    """Batch-fetch the catalogs referenced by campaigns and attach each as `catalog`.

    Mirrors the #332 list-query pipeline batching (batch_get_catalogs_fn.js /
    batch_get_shared_campaign_catalogs_fn.js) inside the admin Lambda, which
    can chunk and loop where AppSync pipeline functions cannot. AppSync always
    executes the attached Campaign.catalog / SharedCampaign.catalog field
    resolver; since check_source_catalog_fn.js short-circuits when the source
    already carries `catalog`, attaching it here replaces the per-item GetItem
    (N+1) the admin campaign lists previously paid.

    Deleted-catalog contract matches the field resolvers: Campaign.catalog
    returns the raw item including soft-deleted catalogs (treat_deleted_as_null
    = False); SharedCampaign.catalog maps soft-deleted or missing catalogs to
    None (treat_deleted_as_null = True).
    """
    catalog_ids = _extract_unique_catalog_ids(campaigns)
    if not catalog_ids:
        return

    catalogs_table_name = get_required_env("CATALOGS_TABLE_NAME")
    # batch_get_chunked already translates every lookup failure (retryable
    # RESOURCE_BUSY on a throttle, INTERNAL_ERROR otherwise), so the typed
    # AppError propagates unchanged (#557).
    catalog_map = _batch_get_catalog_items(catalog_ids, catalogs_table_name, logger)

    _attach_campaign_catalogs(campaigns, catalog_map, treat_deleted_as_null)


def _get_campaigns_for_profiles(profiles: list[Dict[str, Any]], logger: Any, actor_sub: str) -> list[Dict[str, Any]]:
    """Query campaigns for each profile."""
    all_campaigns = []
    for profile in profiles:
        profile_id = profile.get("profileId")
        if profile_id:
            campaigns = query_all_items(
                tables.campaigns,
                {
                    "KeyConditionExpression": "profileId = :pid",
                    "ExpressionAttributeValues": {":pid": profile_id},
                },
            )
            all_campaigns.extend(campaigns)
            logger.info(
                "Retrieved campaigns for profile",
                profile_id=profile_id,
                count=len(campaigns),
                actor_sub=actor_sub,
            )
    return all_campaigns


@with_error_handling(error_message="Failed to get user campaigns")
def admin_get_user_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all campaigns for a user's profiles.

    Admin-only operation. Returns all campaigns across all profiles owned by the account.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # First, get all profiles owned by this account
    profiles = get_user_profiles(db_account_id)
    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles), actor_sub=actor_sub)

    # Now query campaigns for each profile
    all_campaigns = _get_campaigns_for_profiles(profiles, logger, actor_sub)
    # Pre-resolve catalogs in one chunked BatchGetItem so the Campaign.catalog
    # field resolver short-circuits instead of doing per-item GetItem reads (#332).
    _batch_get_campaign_catalogs(all_campaigns, treat_deleted_as_null=False, logger=logger)
    logger.info("Retrieved user campaigns", account_id=account_id, count=len(all_campaigns), actor_sub=actor_sub)
    return all_campaigns


@with_error_handling(error_message="Failed to get user shared campaigns")
def admin_get_user_shared_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shared campaigns created by a user.

    Admin-only operation.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query shared campaigns by createdBy using GSI1
    campaigns = query_all_items(
        tables.shared_campaigns,
        {
            "IndexName": "GSI1",
            "KeyConditionExpression": "createdBy = :creator",
            "ExpressionAttributeValues": {
                ":creator": db_account_id,
            },
        },
    )

    # Pre-resolve catalogs in one chunked BatchGetItem so the SharedCampaign.catalog
    # field resolver short-circuits instead of doing per-item GetItem reads (#332).
    _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=True, logger=logger)

    logger.info(
        "Retrieved user shared campaigns",
        account_id=account_id,
        count=len(campaigns),
        actor_sub=actor_sub,
    )
    return campaigns


def _convert_permissions_to_lists(shares: list[Dict[str, Any]]) -> None:
    """Convert DynamoDB permission sets to lists for JSON serialization."""
    for share in shares:
        if "permissions" in share and isinstance(share["permissions"], set):
            share["permissions"] = list(share["permissions"])


def _query_profile_shares(db_profile_id: str) -> list[Dict[str, Any]]:
    """Query all shares for a profile."""
    return query_all_items(
        tables.shares,
        {
            "KeyConditionExpression": "profileId = :pid",
            "ExpressionAttributeValues": {":pid": db_profile_id},
        },
    )


def _require_admin_and_get_target_profile_id(event: Dict[str, Any]) -> tuple[str, str]:
    """Require admin + MFA, returning ``(db_profile_id, actor_sub)`` (#507).

    ``db_profile_id`` is the target profile named by the request; ``actor_sub``
    is the calling administrator, returned alongside so the audit line can
    attribute the operation.
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()

    if not profile_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID is required")

    # Add PROFILE# prefix if not present
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"
    return db_profile_id, actor_sub


@with_error_handling(error_message="Failed to get profile shares")
def admin_get_profile_shares(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shares for a specific profile.

    Admin-only operation. Returns all users who have access to this profile.
    """
    logger = get_logger(__name__)

    db_profile_id, actor_sub = _require_admin_and_get_target_profile_id(event)

    # Query shares and convert sets to lists
    shares = _query_profile_shares(db_profile_id)
    _convert_permissions_to_lists(shares)

    logger.info("Retrieved profile shares", profile_id=db_profile_id, count=len(shares), actor_sub=actor_sub)
    return shares


def _normalize_profile_and_account_ids(profile_id: str, target_account_id: str) -> tuple[str, str]:
    """Normalize profile ID and target account ID with prefixes."""
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"
    db_target_id = target_account_id if target_account_id.startswith("ACCOUNT#") else f"ACCOUNT#{target_account_id}"
    return db_profile_id, db_target_id


def _require_admin_and_get_share_ids(event: Dict[str, Any]) -> tuple[str, str, str]:
    """Require admin + MFA, returning ``(profile_id, target_account_id, actor_sub)`` (#507).

    The first two are the share the request names; the third is the calling
    administrator, carried so the revocation can be attributed.
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()
    target_account_id = arguments.get("targetAccountId", "").strip()

    if not profile_id or not target_account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID and target account ID are required")

    return profile_id, target_account_id, actor_sub


@with_error_handling(error_message="Failed to delete share")
def admin_delete_share(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete a specific share (revoke access).

    Admin-only operation. Allows admin to remove someone's access to a profile.
    """
    logger = get_logger(__name__)

    profile_id, target_account_id, actor_sub = _require_admin_and_get_share_ids(event)
    db_profile_id, db_target_id = _normalize_profile_and_account_ids(profile_id, target_account_id)

    tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_target_id})

    logger.info(
        "Deleted share",
        profile_id=profile_id,
        target_account_id=target_account_id,
        actor_sub=actor_sub,
    )
    return True


def _get_campaign_profile_id(db_campaign_id: str, campaign_id: str) -> str:
    """Get profile ID for a campaign via GSI lookup."""
    response = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": db_campaign_id},
    )

    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, f"Campaign not found: {campaign_id}")

    return str(items[0]["profileId"])


def _update_campaign_shared_code(
    profile_id: str, db_campaign_id: str, shared_campaign_code: Optional[str]
) -> Dict[str, Any]:
    """Update campaign's sharedCampaignCode field and return the stored item."""
    updated_at = datetime.now(timezone.utc).isoformat()

    if shared_campaign_code is None:
        update_expr = "REMOVE sharedCampaignCode SET updatedAt = :updated"
        expr_vals = {":updated": updated_at}
    else:
        update_expr = "SET sharedCampaignCode = :code, updatedAt = :updated"
        expr_vals = {":code": shared_campaign_code, ":updated": updated_at}

    response = tables.campaigns.update_item(
        Key={"profileId": profile_id, "campaignId": db_campaign_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_vals,
        ReturnValues="ALL_NEW",
    )

    return cast(Dict[str, Any], response.get("Attributes", {}))


def _require_admin_and_get_target_campaign_id(event: Dict[str, Any]) -> tuple[str, Optional[str], str]:
    """Require admin + MFA, returning ``(campaign_id, shared_campaign_code, actor_sub)`` (#507).

    ``campaign_id`` is the target campaign named by the request; ``actor_sub``
    is the calling administrator, carried so the update can be attributed.
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    campaign_id = arguments.get("campaignId", "").strip()
    shared_campaign_code = arguments.get("sharedCampaignCode")

    if not campaign_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Campaign ID is required")

    return campaign_id, shared_campaign_code, actor_sub


@with_error_handling(error_message="Failed to update campaign shared code")
def admin_update_campaign_shared_code(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update a campaign's sharedCampaignCode field and return the stored campaign item.

    Admin-only operation. Allows associating a campaign with a shared campaign.
    """
    logger = get_logger(__name__)

    campaign_id, shared_campaign_code, actor_sub = _require_admin_and_get_target_campaign_id(event)

    # Add CAMPAIGN# prefix if not present
    db_campaign_id = campaign_id if campaign_id.startswith("CAMPAIGN#") else f"CAMPAIGN#{campaign_id}"

    # Get campaign profile, update shared code, and return the stored item
    profile_id = _get_campaign_profile_id(db_campaign_id, campaign_id)
    updated_campaign = _update_campaign_shared_code(profile_id, db_campaign_id, shared_campaign_code)

    logger.info(
        "Updated campaign shared code",
        campaign_id=campaign_id,
        shared_campaign_code=shared_campaign_code,
        actor_sub=actor_sub,
    )
    return updated_campaign


# Operation dispatcher map
_OPERATION_HANDLERS = {
    "adminListUsers": admin_list_users,
    "adminSearchUser": admin_search_user,
    "adminResetUserPassword": admin_reset_user_password,
    "adminPurgeUserAccount": admin_purge_user_account,
    "adminDeleteUserOrders": admin_delete_user_orders,
    "adminDeleteUserCampaigns": admin_delete_user_campaigns,
    "adminDeleteUserShares": admin_delete_user_shares,
    "adminDeleteUserProfiles": admin_delete_user_profiles,
    "createManagedCatalog": create_managed_catalog,
    "adminGetUserProfiles": admin_get_user_profiles,
    "adminGetUserCatalogs": admin_get_user_catalogs,
    "adminGetUserCampaigns": admin_get_user_campaigns,
    "adminGetUserSharedCampaigns": admin_get_user_shared_campaigns,
    "adminGetProfileShares": admin_get_profile_shares,
    "adminDeleteShare": admin_delete_share,
    "adminUpdateCampaignSharedCode": admin_update_campaign_shared_code,
}


@with_error_handling(error_message="Failed to execute admin operation")
def lambda_handler(event: Dict[str, Any], context: Any) -> Any:
    """
    Main Lambda handler that dispatches to specific admin operations.

    Determines which operation to call based on the GraphQL field name.
    Wrapped in ``with_error_handling`` (#329) so dispatch-level errors also
    return the structured ``__isError`` payload instead of raising.

    Args:
        event: AppSync event
        context: Lambda context

    Returns:
        Result from the specific operation handler, or a structured error
        payload when the operation fails.
    """
    field_name = event.get("info", {}).get("fieldName", "")
    handler = _OPERATION_HANDLERS.get(field_name)

    if not handler:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown admin operation: {field_name}")

    return handler(event, context)
