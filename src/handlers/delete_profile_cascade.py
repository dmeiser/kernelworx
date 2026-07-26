"""
Cascade-delete a profile and all related data (API Gateway proxy event shape).

Restored from the AppSync-shaped ``main`` version. Reads caller id from
``requestContext.authorizer.claims.sub`` and the profileId from the path
(``/api/profiles/{id}/cascade-delete``) or request body.
"""

from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id, ensure_profile_id
    from utils.logging import get_logger
    from utils.proxy_event import get_caller_id, parse_body
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.dynamodb import tables
    from src.utils.errors import AppError, ErrorCode
    from src.utils.ids import ensure_account_id, ensure_profile_id
    from src.utils.logging import get_logger
    from src.utils.proxy_event import get_caller_id, parse_body

logger = get_logger(__name__)

BATCH_SIZE = 25


def _query_all_items(
    table: Any,
    key_condition: str,
    expression_values: Dict[str, Any],
    index_name: Optional[str] = None,
    projection: Optional[str] = None,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    last_evaluated_key = None
    while True:
        query_kwargs: Dict[str, Any] = {
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeValues": expression_values,
        }
        if index_name is not None:
            query_kwargs["IndexName"] = index_name
        if projection is not None:
            query_kwargs["ProjectionExpression"] = projection
        if last_evaluated_key is not None:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break
    return items


def _batch_delete_keys(table: Any, keys: List[Dict[str, str]], primary_keys: List[str]) -> int:
    if not keys:
        return 0
    deleted = 0
    for i in range(0, len(keys), BATCH_SIZE):
        batch = keys[i : i + BATCH_SIZE]
        try:
            with table.batch_writer(overwrite_by_pkeys=primary_keys) as writer:
                for key in batch:
                    writer.delete_item(Key=key)
            deleted += len(batch)
        except ClientError as e:
            logger.error("Error deleting batch", error=str(e))
            raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to delete batch from {table.name}") from e
    return deleted


def _get_profile_owner_id(profile_id: str) -> str:
    response = tables.profiles.query(
        IndexName="profileId-index",
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": profile_id},
        Limit=1,
    )
    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")
    return str(items[0]["ownerAccountId"])


def _collect_order_keys(campaigns: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    order_keys = []
    for campaign in campaigns:
        campaign_id = campaign.get("campaignId")
        if not campaign_id:
            continue
        orders = _query_all_items(
            tables.orders, "campaignId = :cid", {":cid": campaign_id}, projection="campaignId, orderId"
        )
        for order in orders:
            order_keys.append({"campaignId": str(order["campaignId"]), "orderId": str(order["orderId"])})
    return order_keys


def _delete_profile(owner_account_id: str, profile_id: str) -> None:
    try:
        tables.profiles.delete_item(Key={"ownerAccountId": owner_account_id, "profileId": profile_id})
    except Exception as e:
        logger.error("Error deleting profile metadata", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete profile metadata")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Cascade-delete a profile and all related data."""
    import json

    profile_id = (event.get("pathParameters") or {}).get("id") or parse_body(event).get("profileId") or ""
    if not profile_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "profileId is required"}),
        }
    db_profile_id = ensure_profile_id(profile_id) or profile_id
    caller_account_id = get_caller_id(event)
    if not caller_account_id:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Authentication required"}),
        }

    try:
        owner_account_id = _get_profile_owner_id(db_profile_id)
        db_caller_id = ensure_account_id(caller_account_id) or f"ACCOUNT#{caller_account_id}"
        if owner_account_id != db_caller_id:
            return {
                "statusCode": 403,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Only profile owner can delete a profile"}),
            }

        logger.info("Starting cascade delete", profile_id=db_profile_id)
        shares = _query_all_items(tables.shares, "profileId = :pid", {":pid": db_profile_id})
        invites = _query_all_items(
            tables.invites, "profileId = :pid", {":pid": db_profile_id}, index_name="profileId-index"
        )
        campaigns = _query_all_items(tables.campaigns, "profileId = :pid", {":pid": db_profile_id})
        order_keys = _collect_order_keys(campaigns)

        orders_deleted = _batch_delete_keys(tables.orders, order_keys, ["campaignId", "orderId"])
        campaigns_deleted = _batch_delete_keys(
            tables.campaigns,
            [
                {"profileId": db_profile_id, "campaignId": str(c["campaignId"])}
                for c in campaigns
                if c.get("campaignId")
            ],
            ["profileId", "campaignId"],
        )
        shares_deleted = _batch_delete_keys(
            tables.shares,
            [
                {"profileId": db_profile_id, "targetAccountId": str(s["targetAccountId"])}
                for s in shares
                if s.get("targetAccountId")
            ],
            ["profileId", "targetAccountId"],
        )
        invites_deleted = _batch_delete_keys(
            tables.invites,
            [{"inviteCode": str(i["inviteCode"])} for i in invites if i.get("inviteCode")],
            ["inviteCode"],
        )
        _delete_profile(owner_account_id, db_profile_id)

        logger.info(
            "Cascade delete complete",
            profile_id=db_profile_id,
            orders=orders_deleted,
            campaigns=campaigns_deleted,
            shares=shares_deleted,
            invites=invites_deleted,
        )
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": True, "profileId": db_profile_id}),
        }
    except AppError as e:
        status = {ErrorCode.NOT_FOUND: 404, ErrorCode.FORBIDDEN: 403}.get(e.error_code, 500)
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": e.message}),
        }
    except Exception as e:
        logger.error("Cascade delete failed", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint. Route POST /api/profiles/{id}/cascade-delete."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "POST")
    path = event.get("path") or "/"
    if path.startswith("/api/profiles/") and path.endswith("/cascade-delete") and method == "POST":
        middle = path[len("/api/profiles/") : -len("/cascade-delete")]
        event["pathParameters"] = {"id": unquote(middle)}
        return lambda_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
