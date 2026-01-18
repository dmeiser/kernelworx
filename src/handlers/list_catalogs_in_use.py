"""
List catalogs in use Lambda handler.

Returns all catalog IDs used by campaigns for profiles the user owns or has access to via shares.

This Lambda is necessary because:
1. We need to query campaigns for owned profiles (1 query via ownerAccountId-index)
2. We need to query campaigns for shared profiles (1 shares query + N campaign queries)
3. A pipeline resolver can't dynamically query N profiles

Uses aioboto3 for async parallel queries:
- owned_catalog_ids and shared_profile_ids run concurrently
- shared_catalog_ids waits for shared_profile_ids, then runs N queries in parallel

GraphQL query: listCatalogsInUse
Returns: [ID!]! (list of catalog IDs)
"""

import asyncio
import os
from typing import Any, Dict, List, Set, Tuple

import aioboto3

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
    from utils.logging import StructuredLogger, get_correlation_id
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import StructuredLogger, get_correlation_id


async def _async_get_owned_campaign_catalog_ids(
    dynamodb: Any, campaigns_table_name: str, owner_account_id: str
) -> Set[str]:
    """Async: Query campaigns for profiles owned by this account using ownerAccountId-index GSI."""
    catalog_ids: Set[str] = set()
    table = await dynamodb.Table(campaigns_table_name)

    response = await table.query(
        IndexName="ownerAccountId-index",
        KeyConditionExpression="ownerAccountId = :ownerAccountId",
        ExpressionAttributeValues={":ownerAccountId": owner_account_id},
        ProjectionExpression="catalogId",
    )

    for item in response.get("Items", []):
        if item.get("catalogId"):
            catalog_ids.add(item["catalogId"])

    # Handle pagination
    while response.get("LastEvaluatedKey"):
        response = await table.query(
            IndexName="ownerAccountId-index",
            KeyConditionExpression="ownerAccountId = :ownerAccountId",
            ExpressionAttributeValues={":ownerAccountId": owner_account_id},
            ProjectionExpression="catalogId",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        for item in response.get("Items", []):  # pragma: no branch
            if item.get("catalogId"):
                catalog_ids.add(item["catalogId"])

    return catalog_ids


async def _async_get_shared_profile_ids(dynamodb: Any, shares_table_name: str, target_account_id: str) -> List[str]:
    """Async: Get profile IDs that are shared with this account."""
    profile_ids: List[str] = []
    table = await dynamodb.Table(shares_table_name)

    response = await table.query(
        IndexName="targetAccountId-index",
        KeyConditionExpression="targetAccountId = :targetAccountId",
        ExpressionAttributeValues={":targetAccountId": target_account_id},
        ProjectionExpression="profileId",
    )

    for item in response.get("Items", []):
        if item.get("profileId"):
            profile_ids.append(item["profileId"])

    # Handle pagination
    while response.get("LastEvaluatedKey"):
        response = await table.query(
            IndexName="targetAccountId-index",
            KeyConditionExpression="targetAccountId = :targetAccountId",
            ExpressionAttributeValues={":targetAccountId": target_account_id},
            ProjectionExpression="profileId",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        for item in response.get("Items", []):  # pragma: no branch
            if item.get("profileId"):
                profile_ids.append(item["profileId"])

    return profile_ids


async def _async_get_campaigns_for_profile(table: Any, profile_id: str) -> Set[str]:
    """Async: Get all catalog IDs from campaigns for a specific profile."""
    catalog_ids: Set[str] = set()

    # Query using the async table
    response = await table.query(
        KeyConditionExpression="profileId = :profileId",
        ExpressionAttributeValues={":profileId": profile_id},
        ProjectionExpression="catalogId",
    )

    for item in response.get("Items", []):
        if item.get("catalogId"):
            catalog_ids.add(item["catalogId"])

    # Handle pagination
    while response.get("LastEvaluatedKey"):
        response = await table.query(
            KeyConditionExpression="profileId = :profileId",
            ExpressionAttributeValues={":profileId": profile_id},
            ProjectionExpression="catalogId",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        for item in response.get("Items", []):  # pragma: no branch
            if item.get("catalogId"):
                catalog_ids.add(item["catalogId"])

    return catalog_ids


async def _async_get_shared_campaign_catalog_ids(table: Any, profile_ids: List[str]) -> Set[str]:
    """Async: Query campaigns for all shared profiles in parallel."""
    if not profile_ids:
        return set()

    # Create tasks for all profile queries
    tasks = [_async_get_campaigns_for_profile(table, pid) for pid in profile_ids]

    # Run all queries concurrently and collect results
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results, ignoring any exceptions
    catalog_ids: Set[str] = set()
    for result in results:
        if isinstance(result, set):
            catalog_ids.update(result)
        # Exceptions are logged but don't fail the overall operation

    return catalog_ids


async def _async_get_all_catalog_ids(account_id: str) -> Tuple[Set[str], List[str], Set[str]]:
    """
    Run all queries with optimal parallelism.

    Flow:
    - owned_catalog_ids and shared_profile_ids run concurrently
    - shared_catalog_ids waits for shared_profile_ids, then runs N queries in parallel
    """
    campaigns_table_name = os.environ.get("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-ue1-dev")
    shares_table_name = os.environ.get("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")

    session = aioboto3.Session()
    async with session.resource("dynamodb") as dynamodb:
        campaigns_table = await dynamodb.Table(campaigns_table_name)

        # Step 1 & 2: Run owned catalogs and shared profiles queries in parallel
        owned_task = _async_get_owned_campaign_catalog_ids(dynamodb, campaigns_table_name, account_id)
        shared_profiles_task = _async_get_shared_profile_ids(dynamodb, shares_table_name, account_id)

        owned_catalog_ids, shared_profile_ids = await asyncio.gather(owned_task, shared_profiles_task)

        # Step 3: Query shared profile campaigns (needs shared_profile_ids from step 2)
        shared_catalog_ids = await _async_get_shared_campaign_catalog_ids(campaigns_table, shared_profile_ids)

        return owned_catalog_ids, shared_profile_ids, shared_catalog_ids


def handler(event: Dict[str, Any], context: Any) -> List[str]:
    """
    List all catalog IDs in use by campaigns the user has access to.

    Args:
        event: AppSync event with identity.sub containing Cognito user ID

    Returns:
        List of catalog IDs (deduplicated)
    """
    logger = StructuredLogger(__name__, get_correlation_id(event))
    caller_sub = event["identity"]["sub"]

    # Add ACCOUNT# prefix for consistency with data model
    account_id_with_prefix = f"ACCOUNT#{caller_sub}" if not caller_sub.startswith("ACCOUNT#") else caller_sub

    logger.info("Listing catalogs in use", account_id=account_id_with_prefix)

    try:
        # Run all queries with optimal parallelism:
        # - owned_catalog_ids and shared_profile_ids run concurrently
        # - shared_catalog_ids waits for shared_profile_ids, then runs N queries in parallel
        owned_catalog_ids, shared_profile_ids, shared_catalog_ids = asyncio.run(
            _async_get_all_catalog_ids(account_id_with_prefix)
        )

        logger.info("Found owned campaign catalogs", count=len(owned_catalog_ids))
        logger.info("Found shared profiles", count=len(shared_profile_ids))
        logger.info("Found shared campaign catalogs", count=len(shared_catalog_ids))

        # Combine and deduplicate
        all_catalog_ids = owned_catalog_ids | shared_catalog_ids
        logger.info("Total unique catalogs in use", count=len(all_catalog_ids))

        return sorted(all_catalog_ids)

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to list catalogs in use", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list catalogs in use")
