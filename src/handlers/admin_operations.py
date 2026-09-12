"""
Admin operations handlers for superadmin functionality.

Provides:
- adminResetUserPassword: Send password reset email to user
- adminDeleteUser: Delete user from Cognito and DynamoDB
- createManagedCatalog: Create an ADMIN_MANAGED global catalog
"""

import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Callable, Dict, NoReturn, Optional, cast

import boto3
from botocore.exceptions import ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .campaign_operations import _verify_campaign_deleted, _verify_order_keys_deleted

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import is_admin
    from utils.dynamodb import get_dynamodb_resource, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger, mask_email
    from utils.payment_methods import delete_all_user_qr_codes
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import is_admin
    from ..utils.dynamodb import get_dynamodb_resource, tables
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


def _get_required_env(name: str) -> str:
    """Get required environment variable or raise error."""
    value = os.environ.get(name)
    if not value:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Missing required environment variable: {name}")
    return value


def _get_cognito_client() -> Any:
    """Get Cognito IDP client, supporting localstack endpoint."""
    endpoint_url = os.environ.get("COGNITO_ENDPOINT")
    if endpoint_url:
        return boto3.client("cognito-idp", endpoint_url=endpoint_url)
    return boto3.client("cognito-idp")


# DynamoDB/Cognito throttling codes: the lookup is retryable, so surface a
# RESOURCE_BUSY error instead of silently incomplete admin data (#291).
_THROTTLING_ERROR_CODES = frozenset({"ProvisionedThroughputExceededException", "ThrottlingException"})


def _raise_batch_lookup_error(operation: str, logger: Any, error: Exception, **context: Any) -> NoReturn:
    """Translate a failed batch lookup into a typed AppError (#291).

    Throttling conditions become a retryable RESOURCE_BUSY so the admin UI can
    show a retry prompt; any other ClientError or unexpected exception becomes
    an INTERNAL_ERROR after an error-level log. Never returns: always raises.
    """
    if isinstance(error, ClientError):
        error_code = error.response.get("Error", {}).get("Code", "")
        if error_code in _THROTTLING_ERROR_CODES:
            logger.warning(f"{operation} throttled", error=str(error), error_code=error_code, **context)
            raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to load data. Please retry.") from error
        logger.error(f"{operation} failed", error=str(error), error_code=error_code, **context)
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to {operation}") from error
    logger.error(f"{operation} failed unexpectedly", error=str(error), **context)
    raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to {operation}") from error


def _batch_get_unprocessed_keys(response: Dict[str, Any], table_name: str) -> list[Dict[str, Any]]:
    """Extract the unprocessed keys DynamoDB reports for a table in a BatchGetItem response."""
    return cast(list[Dict[str, Any]], response.get("UnprocessedKeys", {}).get(table_name, {}).get("Keys", []))


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


# DynamoDB caps BatchGetItem at 100 keys per request.
_ACCOUNTS_BATCH_GET_LIMIT = 100


def _dedupe_account_keys(account_ids: list[str]) -> list[Dict[str, str]]:
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


def _fetch_display_name_attempt(
    keys_to_fetch: list[Dict[str, str]],
    accounts_table_name: str,
    display_names: dict[str, str],
    attempt: int,
    logger: Any,
) -> list[Dict[str, Any]]:
    """Run one BatchGetItem attempt; store returned names and return unprocessed keys."""
    response = get_dynamodb_resource().batch_get_item(RequestItems={accounts_table_name: {"Keys": keys_to_fetch}})
    for item in response.get("Responses", {}).get(accounts_table_name, []):
        _apply_display_name_item(item, display_names)

    unprocessed = _batch_get_unprocessed_keys(response, accounts_table_name)
    if unprocessed and attempt < 2:
        logger.warning(
            "Unprocessed display-name keys, retrying",
            attempt=attempt + 1,
            count=len(unprocessed),
        )
        time.sleep(0.05 * (2**attempt))
    return unprocessed


def _fetch_display_names_chunk(
    keys: list[Dict[str, str]], accounts_table_name: str, display_names: dict[str, str], logger: Any
) -> None:
    """Fetch one 100-key chunk, retrying unprocessed keys for up to 3 attempts."""
    keys_to_fetch = keys
    for attempt in range(3):
        if not keys_to_fetch:
            break
        keys_to_fetch = _fetch_display_name_attempt(keys_to_fetch, accounts_table_name, display_names, attempt, logger)


def _batch_get_display_names(account_ids: list[str], logger: Any) -> dict[str, str]:
    """Batch fetch display names from the Accounts table using BatchGetItem.

    Lookup failures raise an AppError (retryable RESOURCE_BUSY on throttling)
    so the admin UI shows an error instead of silently incomplete names (#291).
    """
    display_names: dict[str, str] = {}
    keys = _dedupe_account_keys(account_ids)
    if not keys:
        return display_names

    accounts_table_name = _get_required_env("ACCOUNTS_TABLE_NAME")

    try:
        for i in range(0, len(keys), _ACCOUNTS_BATCH_GET_LIMIT):
            _fetch_display_names_chunk(
                keys[i : i + _ACCOUNTS_BATCH_GET_LIMIT], accounts_table_name, display_names, logger
            )
    except Exception as e:
        _raise_batch_lookup_error("load display names", logger, e)

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

    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    limit = max(1, min(arguments.get("limit", 20), 60))
    next_token = arguments.get("nextToken")

    user_pool_id = _get_required_env("USER_POOL_ID")
    cognito = _get_cognito_client()

    cognito_users, pagination_token = _list_cognito_users(cognito, user_pool_id, limit, next_token, logger)

    # Batch DynamoDB display-name lookups and parallelize Cognito group lookups
    # to avoid the per-user N+1 fan-out.
    account_ids = [_extract_cognito_attributes(user)[1].get("sub", user.get("Username", "")) for user in cognito_users]
    usernames = [user.get("Username", "") for user in cognito_users]
    display_names = _batch_get_display_names(account_ids, logger)
    groups_map = _batch_get_user_groups(cognito, user_pool_id, usernames, logger)

    admin_users = _build_admin_users_from_cognito(cognito_users, display_names, groups_map)

    logger.info("Listed users", count=len(admin_users), has_more=bool(pagination_token))
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
    2. Otherwise:
       a. Search DynamoDB Accounts table with fuzzy matching (logged-in users)
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

    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    query = str(event.get("arguments", {}).get("query", "")).strip()
    if not query:
        raise AppError(ErrorCode.INVALID_INPUT, "Search query is required")

    _validate_search_query(query)

    user_pool_id = _get_required_env("USER_POOL_ID")
    cognito = _get_cognito_client()

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


def _validate_admin_and_get_account_id(event: Dict[str, Any]) -> str:
    """Validate admin access and extract account ID from event."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    account_id = str(arguments.get("accountId", "")).strip()

    if not account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

    return account_id


def _normalize_account_id(account_id: str) -> str:
    """Add ACCOUNT# prefix if not present."""
    return account_id if account_id.startswith("ACCOUNT#") else f"ACCOUNT#{account_id}"


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


def _looks_like_full_email(query: str) -> bool:
    """Check whether the query is a full email (local@domain.tld)."""
    return "@" in query and bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", query))


def _try_email_index_gsi(query: str, query_lower: str, max_results: int, logger: Any) -> list[Dict[str, Any]] | None:
    """Look a full email up via the email-index GSI.

    Returns the matching items (capped at max_results), or None when the
    query is not a full email or the GSI lookup fails or returns nothing,
    in which case the caller falls back to a scan.
    """
    if not _looks_like_full_email(query):
        return None
    try:
        gsi_response = tables.accounts.query(
            IndexName="email-index",
            KeyConditionExpression="email = :email",
            ExpressionAttributeValues={":email": query_lower},
        )
        gsi_items = cast(list[Dict[str, Any]], gsi_response.get("Items", []))
        if gsi_items:
            return gsi_items[:max_results]
    except ClientError as e:
        logger.warning(
            "DynamoDB email-index query failed, falling back to scan",
            error=str(e),
            query=mask_email(query),
        )
    return None


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
    """
    Search DynamoDB Accounts table with case-insensitive partial matching.

    Searches email, givenName, and familyName fields.
    For exact email queries, utilizes the email-index GSI for fast O(1) lookup.
    Returns all matching accounts (up to max_results limit).
    """
    query_lower = query.lower()

    try:
        gsi_items = _try_email_index_gsi(query, query_lower, _ACCOUNT_SEARCH_MAX_RESULTS, logger)
        if gsi_items is not None:
            return gsi_items
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
    email_prefix_pattern = r"^[a-zA-Z0-9._%+-]+(?:@[a-zA-Z0-9.-]*)?$"
    return bool(re.match(email_prefix_pattern, value)) and len(value) <= 254


_COGNITO_FILTER_METACHARS = frozenset('"\\')


def _reject_cognito_filter_metachars(value: str, field_label: str) -> None:
    """Reject characters that can break a Cognito ListUsers filter literal.

    Cognito filters are double-quoted and use backslash as the escape
    character for inner double quotes. A value containing a quote or a
    trailing backslash can escape the terminating quote and break the
    filter. Reject double quotes, backslashes, and whitespace consistently
    for any value that will be interpolated into a filter.
    """
    if any(ch in _COGNITO_FILTER_METACHARS for ch in value):
        raise AppError(ErrorCode.INVALID_INPUT, f"Invalid {field_label}")
    if any(ch.isspace() for ch in value):
        raise AppError(ErrorCode.INVALID_INPUT, f"Invalid {field_label}")


def _validate_email_for_filter(email: str) -> None:
    """Validate an email before interpolating it into a Cognito ListUsers filter.

    Reject Cognito filter metacharacters (double quotes, backslashes,
    whitespace) and require a basic local@domain shape. See issue #124.
    """
    if not email or len(email) > 254:
        raise AppError(ErrorCode.INVALID_INPUT, "Email is required")
    _reject_cognito_filter_metachars(email, "email")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid email")


def _validate_sub_for_filter(sub: str) -> None:
    """Validate a sub/account ID before interpolating it into a Cognito filter.

    Reject Cognito filter metacharacters (double quotes, backslashes,
    whitespace) and oversized values so malformed values surface as
    INVALID_INPUT instead of a Cognito parse error. See issue #124.
    Non-UUID account IDs are allowed through so that deletion requests for
    non-existent users resolve to NOT_FOUND rather than INVALID_INPUT.
    """
    if not sub or len(sub) > 256:
        raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")
    _reject_cognito_filter_metachars(sub, "account ID")


def _validate_search_query(query: str) -> None:
    """Validate that the admin search query is a safe UUID, email prefix, or ACCOUNT#UUID."""
    if query.startswith("ACCOUNT#"):
        if _looks_like_uuid(query[8:]):
            return
    elif _looks_like_uuid(query):
        return
    elif _is_valid_email_prefix(query):
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
            Filter=f'sub = "{sub}"',
            Limit=1,
        )
        users = response.get("Users", [])
        return users[0] if users else None
    except ClientError as e:
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
            Filter=f'email ^= "{query}"',  # Prefix match on email
            Limit=50,  # Reasonable limit for search results
        )
        return list(response.get("Users", []))
    except ClientError as e:
        logger.warning("Cognito email prefix search failed", error=str(e), query=query)
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
    # Validate before interpolating into the Cognito filter to prevent
    # quote-injection / filter breakage (#124).
    _validate_sub_for_filter(raw_sub)
    try:
        users_response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=f'sub = "{raw_sub}"',
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


def _delete_user_from_cognito(cognito: Any, user_pool_id: str, username: str, email: str, logger: Any) -> None:
    """Delete user from Cognito, treating UserNotFoundException as idempotent success."""
    masked_email = mask_email(email)
    try:
        cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
        logger.info("Deleted user from Cognito", username=mask_email(username), email=masked_email)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "UserNotFoundException":
            logger.info("Cognito user already deleted", username=mask_email(username), email=masked_email)
            return
        logger.error("Cognito admin_delete_user failed", error=str(e), error_code=error_code)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user from Cognito") from e


def _account_exists_in_dynamodb(account_id: str, logger: Any) -> bool:
    """Check whether an account record exists in DynamoDB."""
    db_account_id = _normalize_account_id(account_id)
    try:
        response = tables.accounts.get_item(Key={"accountId": db_account_id}, ProjectionExpression="accountId")
        exists = "Item" in response
        if not exists:
            logger.info("Account not found in DynamoDB", account_id=db_account_id)
        return exists
    except ClientError as e:
        logger.error("Failed to check account existence in DynamoDB", error=str(e), account_id=db_account_id)
        raise


def _delete_account_from_dynamodb(account_id: str, logger: Any) -> None:
    """Delete account from DynamoDB.

    Non-existent items are silently successful (DynamoDB delete_item does not
    raise for missing keys). Other ClientErrors are propagated so that Cognito
    deletion is not attempted while account data remains.
    """
    db_account_id = _normalize_account_id(account_id)
    try:
        tables.accounts.delete_item(Key={"accountId": db_account_id})
        logger.info("Deleted account from DynamoDB", account_id=db_account_id)
    except ClientError as e:
        logger.error("Failed to delete account from DynamoDB", error=str(e), account_id=db_account_id)
        raise


def _find_user_by_email(cognito: Any, user_pool_id: str, email: str, logger: Any) -> str:
    """Find username by email. Returns username."""
    # Validate before interpolating into the Cognito filter to prevent
    # quote-injection / filter breakage (#124).
    _validate_email_for_filter(email)
    try:
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=f'email = "{email}"',
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
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    email = arguments.get("email", "").strip().lower()

    if not email:
        raise AppError(ErrorCode.INVALID_INPUT, "Email is required")

    user_pool_id = _get_required_env("USER_POOL_ID")
    cognito = _get_cognito_client()

    # Find user and initiate reset
    username = _find_user_by_email(cognito, user_pool_id, email, logger)
    _initiate_password_reset(cognito, user_pool_id, username, email, logger)

    logger.info("Password reset initiated", email=mask_email(email), username=mask_email(username))
    return True


def _check_not_self_deletion(caller_id: str, account_id: str) -> None:
    """Prevent admin from deleting their own account.

    Normalize both IDs to their canonical ACCOUNT# form before comparing so a
    caller passing ``ACCOUNT#<own-sub>`` cannot bypass the guard (#125).
    """
    if _normalize_account_id(account_id) == _normalize_account_id(caller_id):
        raise AppError(ErrorCode.INVALID_INPUT, "Cannot delete your own account")


@with_error_handling(error_message="Failed to delete user")
def admin_delete_user(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete user from Cognito and DynamoDB (admin only).

    AppSync Lambda resolver for adminDeleteUser mutation.
    Deletes user from Cognito User Pool and removes Account record from DynamoDB.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        True if user was deleted successfully

    Raises:
        AppError: If not admin, self-deletion is attempted, or a deletion error occurs.
        An absent Cognito user is treated as idempotent success.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)

    identity = event.get("identity", {})
    caller_id = identity.get("sub")
    _check_not_self_deletion(str(caller_id), account_id)

    user_pool_id = _get_required_env("USER_POOL_ID")
    cognito = _get_cognito_client()

    username, email = _find_cognito_user_by_sub(cognito, user_pool_id, account_id, logger)
    account_exists = _account_exists_in_dynamodb(account_id, logger)

    if not username and not account_exists:
        raise AppError(ErrorCode.NOT_FOUND, f"User not found: {account_id}")

    # Delete DynamoDB data first so a partially-deleted Cognito state does not
    # leave account records orphaned.
    _delete_invites_for_owned_profiles(account_id, logger)
    _delete_inbound_shares(account_id, logger)
    _delete_account_from_dynamodb(account_id, logger)

    # Delete payment method QR codes from S3 per captain decision
    delete_all_user_qr_codes(account_id, logger)

    if username:
        _delete_user_from_cognito(cognito, user_pool_id, username, email or "", logger)
    else:
        logger.info("Cognito user already absent; DynamoDB cleanup completed", account_id=account_id)

    logger.info("User deleted successfully", account_id=account_id, email=mask_email(email))
    return True


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


def _validate_admin_and_get_caller_id(event: Dict[str, Any]) -> str:
    """Validate admin access and extract caller ID."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

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

    caller_id = _validate_admin_and_get_caller_id(event)

    arguments = event.get("arguments", {})
    catalog_input = arguments.get("input", {})

    catalog_name, is_public, products = _validate_catalog_input(catalog_input)

    catalog_id = f"CATALOG#{uuid.uuid4()}"
    now = datetime.now(timezone.utc).isoformat()

    processed_products = [_validate_and_process_product(product) for product in products]

    catalog_item = _build_catalog_item(catalog_id, catalog_name, is_public, caller_id, processed_products, now)

    _persist_catalog(catalog_item, logger)

    logger.info("Created managed catalog", catalog_id=catalog_id, catalog_name=catalog_name)

    return catalog_item


def _delete_orders_for_campaign(campaign_id: str, logger: Any) -> int:
    """Delete all orders for a campaign and verify deletion. Returns count deleted."""
    orders = query_all_items(
        tables.orders,
        {
            "KeyConditionExpression": "campaignId = :cid",
            "ExpressionAttributeValues": {":cid": campaign_id},
        },
    )

    deleted_count = 0
    for order in orders:
        tables.orders.delete_item(Key={"campaignId": campaign_id, "orderId": order["orderId"]})
        deleted_count += 1

    if orders:
        _verify_order_keys_deleted(orders)

    return deleted_count


def _delete_user_orders(account_id: str, logger: Any) -> int:
    """Delete all orders for all campaigns of all profiles owned by a user.

    Verifies with strongly consistent reads that each deleted order is gone
    from the orders table before returning. Raises AppError if a deleted order
    is still present.

    Returns:
        Count of orders deleted.
    """
    db_account_id = _normalize_account_id(account_id)
    deleted_count = 0

    profiles = _get_user_profiles(db_account_id, logger)
    for profile in profiles:
        profile_id = profile["profileId"]
        campaigns = query_all_items(
            tables.campaigns,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
            },
        )
        for campaign in campaigns:
            deleted_count += _delete_orders_for_campaign(campaign["campaignId"], logger)

    logger.info("Deleted user orders", account_id=account_id, count=deleted_count)
    return deleted_count


def _delete_user_campaigns(account_id: str, logger: Any) -> int:
    """Delete all campaigns for all profiles owned by a user.

    Verifies with strongly consistent reads that each deleted campaign is gone
    from the campaigns table before returning. Raises AppError if a deleted
    campaign is still present.

    Returns:
        Count of campaigns deleted.
    """
    db_account_id = _normalize_account_id(account_id)
    deleted_count = 0

    profiles = _get_user_profiles(db_account_id, logger)
    for profile in profiles:
        profile_id = profile["profileId"]
        campaigns = query_all_items(
            tables.campaigns,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
            },
        )
        for campaign in campaigns:
            campaign_id = campaign["campaignId"]
            tables.campaigns.delete_item(Key={"profileId": profile_id, "campaignId": campaign_id})
            _verify_campaign_deleted(profile_id, campaign_id)
            deleted_count += 1

    logger.info("Deleted user campaigns", account_id=account_id, count=deleted_count)
    return deleted_count


def _delete_user_shares(account_id: str, logger: Any) -> int:
    """Delete all shares for all profiles owned by a user. Returns count deleted."""
    db_account_id = _normalize_account_id(account_id)
    deleted_count = 0

    profiles = _get_user_profiles(db_account_id, logger)
    for profile in profiles:
        profile_id = profile["profileId"]
        shares = query_all_items(
            tables.shares,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
            },
        )
        for share in shares:
            tables.shares.delete_item(Key={"profileId": profile_id, "targetAccountId": share["targetAccountId"]})
            deleted_count += 1

    logger.info("Deleted user shares", account_id=account_id, count=deleted_count)
    return deleted_count


def _delete_user_profiles(account_id: str, logger: Any) -> int:
    """Delete all profiles owned by a user. Returns count deleted."""
    db_account_id = _normalize_account_id(account_id)
    deleted_count = 0

    profiles = _get_user_profiles(db_account_id, logger)
    for profile in profiles:
        tables.profiles.delete_item(Key={"ownerAccountId": db_account_id, "profileId": profile["profileId"]})
        deleted_count += 1

    logger.info("Deleted user profiles", account_id=account_id, count=deleted_count)
    return deleted_count


@with_error_handling(error_message="Failed to delete user orders")
def admin_delete_user_orders(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all orders for all campaigns of all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted order is gone
    from the orders table before returning success.

    Returns the count of deleted orders.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    return _delete_user_orders(account_id, logger)


@with_error_handling(error_message="Failed to delete user campaigns")
def admin_delete_user_campaigns(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all campaigns for all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted campaign is gone
    from the campaigns table before returning success.

    Returns the count of deleted campaigns.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    return _delete_user_campaigns(account_id, logger)


@with_error_handling(error_message="Failed to delete user shares")
def admin_delete_user_shares(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all shares for all profiles owned by a user (admin only).

    Returns the count of deleted shares.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    return _delete_user_shares(account_id, logger)


@with_error_handling(error_message="Failed to delete user profiles")
def admin_delete_user_profiles(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all profiles owned by a user (admin only).

    Returns the count of deleted profiles.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    return _delete_user_profiles(account_id, logger)


def _delete_invites_for_owned_profiles(account_id: str, logger: Any) -> int:
    """Delete all invites for profiles owned by the account."""
    db_account_id = _normalize_account_id(account_id)
    deleted_count = 0

    profiles = _get_user_profiles(db_account_id, logger)
    for profile in profiles:
        profile_id = profile["profileId"]
        invites = query_all_items(
            tables.invites,
            {
                "KeyConditionExpression": "profileId = :pid",
                "ExpressionAttributeValues": {":pid": profile_id},
                "IndexName": "profileId-index",
            },
        )
        for invite in invites:
            tables.invites.delete_item(Key={"inviteCode": invite["inviteCode"]})
            deleted_count += 1

    logger.info("Deleted invites for owned profiles", account_id=account_id, count=deleted_count)
    return deleted_count


def _delete_inbound_shares(account_id: str, logger: Any) -> int:
    """Delete all inbound shares where the account is the target."""
    db_account_id = _normalize_account_id(account_id)
    deleted_count = 0

    shares = query_all_items(
        tables.shares,
        {
            "KeyConditionExpression": "targetAccountId = :tid",
            "ExpressionAttributeValues": {":tid": db_account_id},
            "IndexName": "targetAccountId-index",
        },
    )
    for share in shares:
        tables.shares.delete_item(
            Key={
                "profileId": share["profileId"],
                "targetAccountId": share["targetAccountId"],
            }
        )
        deleted_count += 1

    logger.info("Deleted inbound shares", account_id=account_id, count=deleted_count)
    return deleted_count


def _soft_delete_catalog(catalog_id: str) -> None:
    """Soft delete a catalog by setting isDeleted = true."""
    tables.catalogs.update_item(
        Key={"catalogId": catalog_id},
        UpdateExpression="SET isDeleted = :true",
        ExpressionAttributeValues={":true": True},
    )


def _query_and_delete_catalogs(db_account_id: str) -> int:
    """Query for user's catalogs via the ownerAccountId GSI and soft delete them. Returns count."""
    catalogs = query_all_items(
        tables.catalogs,
        {
            "IndexName": "ownerAccountId-index",
            "KeyConditionExpression": "ownerAccountId = :owner",
            "FilterExpression": "attribute_not_exists(isDeleted) OR isDeleted = :false",
            "ExpressionAttributeValues": {":owner": db_account_id, ":false": False},
        },
    )

    deleted_count = 0
    for catalog in catalogs:
        _soft_delete_catalog(catalog["catalogId"])
        deleted_count += 1

    return deleted_count


def _delete_user_catalogs(account_id: str, logger: Any) -> int:
    """Soft delete all catalogs owned by a user. Returns count."""
    db_account_id = _normalize_account_id(account_id)
    deleted_count = _query_and_delete_catalogs(db_account_id)
    logger.info("Soft-deleted user catalogs", account_id=account_id, count=deleted_count)
    return deleted_count


@with_error_handling(error_message="Failed to delete user catalogs")
def admin_delete_user_catalogs(event: Dict[str, Any], context: Any) -> int:
    """
    Soft delete all catalogs owned by a user (admin only).

    Sets isDeleted=true on each catalog instead of removing from database.
    Returns the count of soft-deleted catalogs.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    return _delete_user_catalogs(account_id, logger)


@with_error_handling(error_message="Failed to get user profiles")
def admin_get_user_profiles(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all profiles owned by a user (admin only).

    Returns the list of profiles with full details.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    db_account_id = _normalize_account_id(account_id)

    # Query profiles by ownerAccountId
    profiles = query_all_items(
        tables.profiles,
        {
            "KeyConditionExpression": "ownerAccountId = :owner",
            "ExpressionAttributeValues": {":owner": db_account_id},
        },
    )

    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles))
    return profiles


@with_error_handling(error_message="Failed to get user catalogs")
def admin_get_user_catalogs(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all catalogs owned by a user (admin only).

    Returns the list of catalogs with full details.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    db_account_id = _normalize_account_id(account_id)

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

    logger.info("Retrieved user catalogs", account_id=account_id, count=len(catalogs))
    return catalogs


def _get_user_profiles(db_account_id: str, logger: Any) -> list[Dict[str, Any]]:
    """Get all profiles owned by an account."""
    return query_all_items(
        tables.profiles,
        {
            "KeyConditionExpression": "ownerAccountId = :owner",
            "ExpressionAttributeValues": {":owner": db_account_id},
        },
    )


# DynamoDB caps BatchGetItem at 100 keys per request.
_CATALOG_BATCH_GET_LIMIT = 100


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


def _fetch_catalog_batch_attempt(
    keys_to_fetch: list[Dict[str, str]],
    catalogs_table_name: str,
    catalog_map: Dict[str, Dict[str, Any]],
    attempt: int,
    logger: Any,
) -> list[Dict[str, Any]]:
    """Run one BatchGetItem attempt; store returned items and return unprocessed keys."""
    response = get_dynamodb_resource().batch_get_item(RequestItems={catalogs_table_name: {"Keys": keys_to_fetch}})
    for item in response.get("Responses", {}).get(catalogs_table_name, []):
        catalog_map[item["catalogId"]] = item

    unprocessed = _batch_get_unprocessed_keys(response, catalogs_table_name)
    if unprocessed and attempt < 2:
        logger.warning(
            "Unprocessed catalog keys, retrying",
            attempt=attempt + 1,
            count=len(unprocessed),
        )
        time.sleep(0.05 * (2**attempt))
    return unprocessed


def _fetch_catalog_keys_with_retry(
    keys: list[Dict[str, str]], catalogs_table_name: str, catalog_map: Dict[str, Dict[str, Any]], logger: Any
) -> list[Dict[str, Any]]:
    """Fetch one 100-key chunk, retrying unprocessed keys for up to 3 attempts.

    Returns the keys still unprocessed after the final attempt.
    """
    keys_to_fetch = keys
    for attempt in range(3):
        if not keys_to_fetch:
            break
        keys_to_fetch = _fetch_catalog_batch_attempt(keys_to_fetch, catalogs_table_name, catalog_map, attempt, logger)
    return keys_to_fetch


def _batch_get_catalog_items(
    catalog_ids: list[str], catalogs_table_name: str, logger: Any
) -> Dict[str, Dict[str, Any]]:
    """Chunked BatchGetItem over catalog ids; raises AppError if keys stay unprocessed."""
    catalog_map: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(catalog_ids), _CATALOG_BATCH_GET_LIMIT):
        batch = [{"catalogId": catalog_id} for catalog_id in catalog_ids[i : i + _CATALOG_BATCH_GET_LIMIT]]
        keys_to_fetch = _fetch_catalog_keys_with_retry(batch, catalogs_table_name, catalog_map, logger)
        if keys_to_fetch:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"DynamoDB BatchGetItem failed to return {len(keys_to_fetch)} keys after retries",
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

    catalogs_table_name = _get_required_env("CATALOGS_TABLE_NAME")
    try:
        catalog_map = _batch_get_catalog_items(catalog_ids, catalogs_table_name, logger)
    except AppError:
        raise
    except Exception as e:
        _raise_batch_lookup_error("load campaign catalogs", logger, e)

    _attach_campaign_catalogs(campaigns, catalog_map, treat_deleted_as_null)


def _get_campaigns_for_profiles(profiles: list[Dict[str, Any]], logger: Any) -> list[Dict[str, Any]]:
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
            logger.info("Retrieved campaigns for profile", profile_id=profile_id, count=len(campaigns))
    return all_campaigns


@with_error_handling(error_message="Failed to get user campaigns")
def admin_get_user_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all campaigns for a user's profiles.

    Admin-only operation. Returns all campaigns across all profiles owned by the account.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    db_account_id = _normalize_account_id(account_id)

    # First, get all profiles owned by this account
    profiles = _get_user_profiles(db_account_id, logger)
    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles))

    # Now query campaigns for each profile
    all_campaigns = _get_campaigns_for_profiles(profiles, logger)
    # Pre-resolve catalogs in one chunked BatchGetItem so the Campaign.catalog
    # field resolver short-circuits instead of doing per-item GetItem reads (#332).
    _batch_get_campaign_catalogs(all_campaigns, treat_deleted_as_null=False, logger=logger)
    logger.info("Retrieved user campaigns", account_id=account_id, count=len(all_campaigns))
    return all_campaigns


@with_error_handling(error_message="Failed to get user shared campaigns")
def admin_get_user_shared_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shared campaigns created by a user.

    Admin-only operation.
    """
    logger = get_logger(__name__)

    account_id = _validate_admin_and_get_account_id(event)
    db_account_id = _normalize_account_id(account_id)

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

    logger.info("Retrieved user shared campaigns", account_id=account_id, count=len(campaigns))
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


def _validate_admin_and_get_profile_id(event: Dict[str, Any]) -> str:
    """Validate admin access and extract profile ID with prefix."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()

    if not profile_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID is required")

    # Add PROFILE# prefix if not present
    return profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"


@with_error_handling(error_message="Failed to get profile shares")
def admin_get_profile_shares(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shares for a specific profile.

    Admin-only operation. Returns all users who have access to this profile.
    """
    logger = get_logger(__name__)

    db_profile_id = _validate_admin_and_get_profile_id(event)

    # Query shares and convert sets to lists
    shares = _query_profile_shares(db_profile_id)
    _convert_permissions_to_lists(shares)

    logger.info("Retrieved profile shares", profile_id=db_profile_id, count=len(shares))
    return shares


def _normalize_profile_and_account_ids(profile_id: str, target_account_id: str) -> tuple[str, str]:
    """Normalize profile ID and target account ID with prefixes."""
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"
    db_target_id = target_account_id if target_account_id.startswith("ACCOUNT#") else f"ACCOUNT#{target_account_id}"
    return db_profile_id, db_target_id


def _validate_and_get_share_ids(event: Dict[str, Any]) -> tuple[str, str]:
    """Validate admin and extract profile/account IDs."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()
    target_account_id = arguments.get("targetAccountId", "").strip()

    if not profile_id or not target_account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID and target account ID are required")

    return profile_id, target_account_id


@with_error_handling(error_message="Failed to delete share")
def admin_delete_share(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete a specific share (revoke access).

    Admin-only operation. Allows admin to remove someone's access to a profile.
    """
    logger = get_logger(__name__)

    profile_id, target_account_id = _validate_and_get_share_ids(event)
    db_profile_id, db_target_id = _normalize_profile_and_account_ids(profile_id, target_account_id)

    tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_target_id})

    logger.info("Deleted share", profile_id=profile_id, target_account_id=target_account_id)
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


def _validate_admin_and_get_campaign_id(event: Dict[str, Any]) -> tuple[str, Optional[str]]:
    """Validate admin access and extract campaign ID and shared code."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    campaign_id = arguments.get("campaignId", "").strip()
    shared_campaign_code = arguments.get("sharedCampaignCode")

    if not campaign_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Campaign ID is required")

    return campaign_id, shared_campaign_code


@with_error_handling(error_message="Failed to update campaign shared code")
def admin_update_campaign_shared_code(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update a campaign's sharedCampaignCode field and return the stored campaign item.

    Admin-only operation. Allows associating a campaign with a shared campaign.
    """
    logger = get_logger(__name__)

    campaign_id, shared_campaign_code = _validate_admin_and_get_campaign_id(event)

    # Add CAMPAIGN# prefix if not present
    db_campaign_id = campaign_id if campaign_id.startswith("CAMPAIGN#") else f"CAMPAIGN#{campaign_id}"

    # Get campaign profile, update shared code, and return the stored item
    profile_id = _get_campaign_profile_id(db_campaign_id, campaign_id)
    updated_campaign = _update_campaign_shared_code(profile_id, db_campaign_id, shared_campaign_code)

    logger.info("Updated campaign shared code", campaign_id=campaign_id, shared_campaign_code=shared_campaign_code)
    return updated_campaign


# Operation dispatcher map
_OPERATION_HANDLERS = {
    "adminListUsers": admin_list_users,
    "adminSearchUser": admin_search_user,
    "adminResetUserPassword": admin_reset_user_password,
    "adminDeleteUser": admin_delete_user,
    "adminDeleteUserOrders": admin_delete_user_orders,
    "adminDeleteUserCampaigns": admin_delete_user_campaigns,
    "adminDeleteUserShares": admin_delete_user_shares,
    "adminDeleteUserProfiles": admin_delete_user_profiles,
    "adminDeleteUserCatalogs": admin_delete_user_catalogs,
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
