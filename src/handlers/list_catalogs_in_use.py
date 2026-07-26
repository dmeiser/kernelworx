"""
List all catalog IDs in use by campaigns the user has access to (API Gateway proxy event shape).

Restored from the AppSync-shaped ``main`` version (which used aioboto3). The
HTMX app calls this synchronously over REST, so the implementation was
converted to the synchronous boto3 table resource to keep the handler simple
and to share the existing ``tables`` accessors.

Returns a JSON list of catalog IDs.
"""

import json
from typing import Any, Dict, List, Optional, Set

try:  # pragma: no cover
    from utils.dynamodb import get_required_env, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.proxy_event import get_caller_id
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.dynamodb import get_required_env, tables
    from src.utils.errors import AppError, ErrorCode
    from src.utils.logging import get_logger
    from src.utils.proxy_event import get_caller_id

logger = get_logger(__name__)


def _query_all(
    table: Any,
    key_condition: str,
    expr_values: Dict[str, Any],
    index_name: Optional[str] = None,
    projection: Optional[str] = None,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    last_evaluated_key = None
    while True:
        kwargs: Dict[str, Any] = {"KeyConditionExpression": key_condition, "ExpressionAttributeValues": expr_values}
        if index_name:
            kwargs["IndexName"] = index_name
        if projection:
            kwargs["ProjectionExpression"] = projection
        if last_evaluated_key:
            kwargs["ExclusiveStartKey"] = last_evaluated_key
        res = table.query(**kwargs)
        items.extend(res.get("Items", []))
        last_evaluated_key = res.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
    return items


def _get_owned_profile_ids(profiles_table_name: str, owner_account_id: str) -> List[str]:
    items = _query_all(
        tables.profiles,
        "ownerAccountId = :owner",
        {":owner": owner_account_id},
        projection="profileId",
    )
    return [i["profileId"] for i in items if i.get("profileId")]


def _get_shared_profile_ids(shares_table_name: str, target_account_id: str) -> List[str]:
    items = _query_all(
        tables.shares,
        "targetAccountId = :target",
        {":target": target_account_id},
        index_name="targetAccountId-index",
        projection="profileId",
    )
    return [i["profileId"] for i in items if i.get("profileId")]


def _get_catalog_ids_for_profile(profiles: List[str], campaigns_table_name: str) -> Set[str]:
    catalog_ids: Set[str] = set()
    for profile_id in profiles:
        items = _query_all(
            tables.campaigns,
            "profileId = :pid",
            {":pid": profile_id},
            projection="catalogId",
        )
        for item in items:
            cid = item.get("catalogId")
            if cid:
                catalog_ids.add(cid)
    return catalog_ids


def _get_all_catalog_ids(account_id: str) -> Set[str]:
    profiles_table_name = get_required_env("PROFILES_TABLE_NAME")
    campaigns_table_name = get_required_env("CAMPAIGNS_TABLE_NAME")
    shares_table_name = get_required_env("SHARES_TABLE_NAME")

    owned_profile_ids = _get_owned_profile_ids(profiles_table_name, account_id)
    shared_profile_ids = _get_shared_profile_ids(shares_table_name, account_id)
    owned_catalog_ids = _get_catalog_ids_for_profile(owned_profile_ids, campaigns_table_name)
    shared_catalog_ids = _get_catalog_ids_for_profile(shared_profile_ids, campaigns_table_name)
    return owned_catalog_ids | shared_catalog_ids


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """List all catalog IDs in use by campaigns the user has access to."""
    logger.info("list_catalogs_in_use invoked")
    caller_sub = get_caller_id(event)
    account_id_with_prefix = f"ACCOUNT#{caller_sub}" if not caller_sub.startswith("ACCOUNT#") else caller_sub
    logger.info("Listing catalogs in use", account_id=account_id_with_prefix)
    try:
        all_catalog_ids = _get_all_catalog_ids(account_id_with_prefix)
        logger.info("Total unique catalogs in use", count=len(all_catalog_ids))
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(sorted(all_catalog_ids)),
        }
    except AppError as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": e.message}),
        }
    except Exception as e:
        logger.error("Failed to list catalogs in use", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to list catalogs in use"}),
        }
