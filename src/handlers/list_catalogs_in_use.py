"""
List catalogs in use Lambda handler.

Returns all catalog IDs used by campaigns for profiles the user owns or has access to via shares.

This Lambda is necessary because:
1. We need to query profiles owned by the account (1 query)
2. We need to query campaigns for each owned profile (N queries)
3. We need to query campaigns for shared profiles (1 shares query + N campaign queries)
4. A pipeline resolver can't dynamically query N profiles

Uses aioboto3 for async parallel queries:
- owned_profile_ids and shared_profile_ids run concurrently
- owned_catalog_ids and shared_catalog_ids wait for their respective profile_ids, then run N queries in
  parallel, bounded to the concurrency and chunk caps campaign_reporting uses (#541)

GraphQL query: listCatalogsInUse
Returns: [ID!]! (list of catalog IDs)
"""

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple, cast

import aioboto3

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
# admin_operations owns the transient/permanent lookup-error classification (its
# `_THROTTLING_ERROR_CODES` is the canonical set), so it is imported here rather
# than redeclared and the two copies cannot drift. One-way: admin_operations does
# not import this module.
from .admin_operations import _raise_gather_failures

# The query-bounding caps are owned by the sibling report module so the two
# modules cannot drift (#541): one concurrency cap and one chunk cap in the
# codebase, not two.
from .campaign_reporting import _ORDER_QUERY_CONCURRENCY, _PROFILE_BATCH_LIMIT

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import get_required_env
    from utils.logging import get_correlation_id, get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import get_required_env
    from ..utils.logging import get_correlation_id, get_logger

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


async def _extract_field_values(items: list[Dict[str, Any]], field_name: str) -> List[str]:
    """Extract field values from DynamoDB items."""
    return [item[field_name] for item in items if item.get(field_name)]


def _share_item_has_accessible_permissions(item: Dict[str, Any]) -> bool:
    """Check if a share item grants READ or WRITE access.

    Defensive filter for legacy shares that were created with an empty or
    unsupported permissions array (#242).
    """
    permissions = item.get("permissions", [])
    if not isinstance(permissions, (list, set)) or not permissions:
        return False
    for perm in permissions:
        if isinstance(perm, str) and perm.upper() in {"READ", "WRITE"}:
            return True
    return False


async def _handle_pagination(table: Any, query_params: Dict[str, Any], field_name: str) -> List[str]:
    """Handle DynamoDB pagination for query operations."""
    results: List[str] = []
    response = await table.query(**query_params)
    results.extend(await _extract_field_values(response.get("Items", []), field_name))

    while response.get("LastEvaluatedKey"):
        query_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = await table.query(**query_params)
        results.extend(await _extract_field_values(response.get("Items", []), field_name))

    return results


async def _async_get_owned_profile_ids(dynamodb: Any, profiles_table_name: str, owner_account_id: str) -> List[str]:
    """Async: Query profiles owned by this account."""
    table = await dynamodb.Table(profiles_table_name)
    query_params = {
        "KeyConditionExpression": "ownerAccountId = :ownerAccountId",
        "ExpressionAttributeValues": {":ownerAccountId": owner_account_id},
        "ProjectionExpression": "profileId",
    }
    return await _handle_pagination(table, query_params, "profileId")


async def _async_get_campaigns_for_profile(dynamodb: Any, campaigns_table_name: str, profile_id: str) -> Set[str]:
    """Async: Query campaigns for a specific profile and return catalog IDs."""
    table = await dynamodb.Table(campaigns_table_name)
    query_params = {
        "KeyConditionExpression": "profileId = :profileId",
        "ExpressionAttributeValues": {":profileId": profile_id},
        "ProjectionExpression": "catalogId",
    }
    catalog_list = await _handle_pagination(table, query_params, "catalogId")
    return set(catalog_list)


async def _async_get_shared_profile_ids(dynamodb: Any, shares_table_name: str, target_account_id: str) -> List[str]:
    """Async: Get profile IDs that are shared with this account."""
    table = await dynamodb.Table(shares_table_name)
    query_params = {
        "IndexName": "targetAccountId-index",
        "KeyConditionExpression": "targetAccountId = :targetAccountId",
        "ExpressionAttributeValues": {":targetAccountId": target_account_id},
        # "permissions" is a DynamoDB reserved word; it must be referenced via
        # an expression attribute name or the query is rejected with a
        # ValidationException.
        "ProjectionExpression": "profileId, #permissions",
        "ExpressionAttributeNames": {"#permissions": "permissions"},
    }
    results: List[str] = []
    response = await table.query(**query_params)
    results.extend(
        item["profileId"]
        for item in response.get("Items", [])
        if item.get("profileId") and _share_item_has_accessible_permissions(item)
    )

    while response.get("LastEvaluatedKey"):
        query_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = await table.query(**query_params)
        results.extend(
            item["profileId"]
            for item in response.get("Items", [])
            if item.get("profileId") and _share_item_has_accessible_permissions(item)
        )

    return results


async def _async_get_shared_campaign_catalog_ids(
    dynamodb: Any, campaigns_table_name: str, profile_ids: List[str], request_logger: Any = logger
) -> Set[str]:
    """Async: Query campaigns for all profiles with bounded concurrency.

    Profile ids are processed in chunks no larger than
    ``campaign_reporting._PROFILE_BATCH_LIMIT`` and each per-profile query
    (its pagination loop included) holds one of
    ``campaign_reporting._ORDER_QUERY_CONCURRENCY`` semaphore slots, so at most
    that many DynamoDB queries are ever in flight at once - the same bounding
    strategy the sibling report module uses (#541).

    A per-profile query failure is raised (see
    `admin_operations._raise_gather_failures`) instead of being logged and
    discarded, so the caller never treats a silently truncated set as the
    authoritative "in use" answer.
    """
    if not profile_ids:
        return set()

    semaphore = asyncio.Semaphore(_ORDER_QUERY_CONCURRENCY)

    async def _bounded_query(profile_id: str) -> Set[str]:
        async with semaphore:
            return await _async_get_campaigns_for_profile(dynamodb, campaigns_table_name, profile_id)

    catalog_ids: Set[str] = set()
    # Chunk the profile list so no more than _PROFILE_BATCH_LIMIT tasks exist
    # per gather wave; a failing chunk still raises via _raise_gather_failures
    # before the next chunk starts, never returning a truncated set.
    for start in range(0, len(profile_ids), _PROFILE_BATCH_LIMIT):
        chunk = profile_ids[start : start + _PROFILE_BATCH_LIMIT]
        results = await asyncio.gather(*(_bounded_query(pid) for pid in chunk), return_exceptions=True)

        # If any profile query failed we cannot answer authoritatively; fail the
        # whole request instead of returning a truncated set (#556).
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            _raise_gather_failures(
                "list catalogs in use",
                request_logger,
                failures,
                busy_message="Temporarily unable to list catalogs in use. Please retry.",
                failed=len(failures),
                total=len(results),
            )

        for result in results:
            catalog_ids.update(cast(Set[str], result))

    return catalog_ids


async def _async_get_all_catalog_ids(
    account_id: str, request_logger: Any = logger
) -> Tuple[Set[str], List[str], Set[str]]:
    """
    Run all queries with optimal parallelism.

    Flow:
    - owned_profile_ids and shared_profile_ids run concurrently
    - owned_catalog_ids and shared_catalog_ids wait for their respective profile_ids, then runs N queries in parallel
    """
    campaigns_table_name = get_required_env("CAMPAIGNS_TABLE_NAME")
    profiles_table_name = get_required_env("PROFILES_TABLE_NAME")
    shares_table_name = get_required_env("SHARES_TABLE_NAME")

    session = aioboto3.Session()
    async with session.resource("dynamodb") as dynamodb:
        # Step 1 & 2: Run owned profiles and shared profiles queries in parallel
        owned_profiles_task = _async_get_owned_profile_ids(dynamodb, profiles_table_name, account_id)
        shared_profiles_task = _async_get_shared_profile_ids(dynamodb, shares_table_name, account_id)

        owned_profile_ids, shared_profile_ids = await asyncio.gather(owned_profiles_task, shared_profiles_task)

        # Step 3 & 4: Query campaigns for both owned and shared profiles in parallel
        owned_catalogs_task = _async_get_shared_campaign_catalog_ids(
            dynamodb, campaigns_table_name, owned_profile_ids, request_logger
        )
        shared_catalogs_task = _async_get_shared_campaign_catalog_ids(
            dynamodb, campaigns_table_name, shared_profile_ids, request_logger
        )

        owned_catalog_ids, shared_catalog_ids = await asyncio.gather(owned_catalogs_task, shared_catalogs_task)

        return owned_catalog_ids, shared_profile_ids, shared_catalog_ids


@with_error_handling(error_message="Failed to list catalogs in use")
def handler(event: Dict[str, Any], context: Any) -> List[str]:
    """
    List all catalog IDs in use by campaigns the user has access to.

    Args:
        event: AppSync event with identity.sub containing Cognito user ID

    Returns:
        List of catalog IDs (deduplicated)
    """
    request_logger = get_logger(__name__, get_correlation_id(event))
    caller_sub = event["identity"]["sub"]

    # Add ACCOUNT# prefix for consistency with data model
    account_id_with_prefix = f"ACCOUNT#{caller_sub}" if not caller_sub.startswith("ACCOUNT#") else caller_sub

    request_logger.info("Listing catalogs in use", account_id=account_id_with_prefix)

    # Run all queries with optimal parallelism:
    # - owned_catalog_ids and shared_profile_ids run concurrently
    # - shared_catalog_ids waits for shared_profile_ids, then runs N queries in parallel
    owned_catalog_ids, shared_profile_ids, shared_catalog_ids = asyncio.run(
        _async_get_all_catalog_ids(account_id_with_prefix, request_logger)
    )

    request_logger.info("Found owned campaign catalogs", count=len(owned_catalog_ids))
    request_logger.info("Found shared profiles", count=len(shared_profile_ids))
    request_logger.info("Found shared campaign catalogs", count=len(shared_catalog_ids))

    # Combine and deduplicate
    all_catalog_ids = owned_catalog_ids | shared_catalog_ids
    request_logger.info("Total unique catalogs in use", count=len(all_catalog_ids))

    return sorted(all_catalog_ids)
