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
- owned_catalog_ids and shared_catalog_ids wait for their respective profile_ids, then run N queries in parallel

GraphQL query: listCatalogsInUse
Returns: [ID!]! (list of catalog IDs)
"""

import asyncio
from typing import Any, Callable, Dict, List, Set, Tuple

import aioboto3

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import get_required_env
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_correlation_id, get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import get_required_env
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_correlation_id, get_logger


logger = get_logger(__name__)


def _has_effective_permission(permissions: Any) -> bool:
    """Check if permissions grant at least one effective READ or WRITE right."""
    if not isinstance(permissions, (list, set)):
        return False
    return any(p in ("READ", "WRITE") for p in permissions)


async def _extract_field_values(items: list[Dict[str, Any]], field_name: str) -> List[str]:
    """Extract field values from DynamoDB items."""
    return [item[field_name] for item in items if item.get(field_name)]


async def _handle_pagination(
    table: Any, query_params: Dict[str, Any], field_name: str, filter_fn: Callable[[Dict[str, Any]], bool] | None = None
) -> List[str]:
    """Handle DynamoDB pagination for query operations, optionally filtering items."""
    results: List[str] = []
    response = await table.query(**query_params)
    items = response.get("Items", [])
    if filter_fn:
        items = [item for item in items if filter_fn(item)]
    results.extend(await _extract_field_values(items, field_name))

    while response.get("LastEvaluatedKey"):
        query_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = await table.query(**query_params)
        items = response.get("Items", [])
        if filter_fn:
            items = [item for item in items if filter_fn(item)]
        results.extend(await _extract_field_values(items, field_name))

    return results


async def _async_get_owned_profile_ids(
    dynamodb: Any, profiles_table_name: str, owner_account_id: str, request_logger: Any = logger
) -> List[str]:
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
    """Async: Get profile IDs that are shared with this account.

    Only returns profiles where the share grants at least one effective READ or WRITE permission.
    """
    table = await dynamodb.Table(shares_table_name)
    query_params = {
        "IndexName": "targetAccountId-index",
        "KeyConditionExpression": "targetAccountId = :targetAccountId",
        "ExpressionAttributeValues": {":targetAccountId": target_account_id},
        "ProjectionExpression": "profileId, permissions",
    }
    return await _handle_pagination(
        table,
        query_params,
        "profileId",
        filter_fn=lambda item: _has_effective_permission(item.get("permissions")),
    )


async def _async_get_shared_campaign_catalog_ids(
    dynamodb: Any, campaigns_table_name: str, profile_ids: List[str], request_logger: Any = logger
) -> Set[str]:
    """Async: Query campaigns for all profiles in parallel."""
    if not profile_ids:
        return set()

    # Create tasks for all profile queries
    tasks = [_async_get_campaigns_for_profile(dynamodb, campaigns_table_name, pid) for pid in profile_ids]

    # Run all queries concurrently and collect results
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results, logging any exceptions without failing the overall operation
    catalog_ids: Set[str] = set()
    for result in results:
        if isinstance(result, set):
            catalog_ids.update(result)
        elif isinstance(result, BaseException):
            request_logger.error("Failed to query campaign catalogs", error=str(result), exc_info=result)

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

    try:
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

    except AppError:
        raise
    except Exception as e:
        request_logger.error("Failed to list catalogs in use", error=str(e), exc_info=True)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list catalogs in use")
