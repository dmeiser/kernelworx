"""
Transfer profile ownership to another account (API Gateway proxy event shape).

Restored from the AppSync-shaped ``main`` version. Reads caller id from
``requestContext.authorizer.claims.sub`` and the input (profileId +
newOwnerAccountId) from the request body (form-encoded or JSON).
"""

import os
from typing import Any, Dict

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id, ensure_profile_id
    from utils.logging import get_logger
    from utils.proxy_event import get_caller_id, is_admin, parse_body
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.dynamodb import tables
    from src.utils.errors import AppError, ErrorCode
    from src.utils.ids import ensure_account_id, ensure_profile_id
    from src.utils.logging import get_logger
    from src.utils.proxy_event import get_caller_id, is_admin, parse_body

logger = get_logger(__name__)
_type_serializer = TypeSerializer()


def _get_and_verify_profile(db_profile_id: str, db_caller_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    profile_response = tables.profiles.query(
        IndexName="profileId-index", KeyConditionExpression=Key("profileId").eq(db_profile_id)
    )
    if not profile_response.get("Items"):
        raise AppError(ErrorCode.NOT_FOUND, f"Profile not found: {db_profile_id}")
    profile: Dict[str, Any] = profile_response["Items"][0]
    caller_is_owner = profile.get("ownerAccountId") == db_caller_id
    caller_is_admin = is_admin(event)
    if not caller_is_owner and not caller_is_admin:
        raise AppError(ErrorCode.FORBIDDEN, "Only the profile owner or an admin can transfer ownership")
    return profile


def _verify_new_owner_has_share(db_profile_id: str, db_new_owner_id: str, caller_is_admin: bool) -> None:
    if not caller_is_admin:
        share_response = tables.shares.get_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
        if "Item" not in share_response:
            raise AppError(ErrorCode.INVALID_INPUT, "New owner must have existing access to the profile")


def _transfer_ownership(profile: Dict[str, Any], db_profile_id: str, db_new_owner_id: str) -> None:
    old_owner_id = profile["ownerAccountId"]
    new_profile = {**profile, "ownerAccountId": db_new_owner_id}
    old_key = {"ownerAccountId": old_owner_id, "profileId": db_profile_id}
    endpoint_url = os.getenv("DYNAMODB_ENDPOINT")
    dynamodb_client = boto3.client("dynamodb", endpoint_url=endpoint_url)
    table_name = tables.profiles.name
    try:
        dynamodb_client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": table_name,
                        "Key": {k: _type_serializer.serialize(v) for k, v in old_key.items()},
                        "ConditionExpression": "attribute_exists(ownerAccountId)",
                    }
                },
                {
                    "Put": {
                        "TableName": table_name,
                        "Item": {k: _type_serializer.serialize(v) for k, v in new_profile.items()},
                        "ConditionExpression": "attribute_not_exists(ownerAccountId)",
                    }
                },
            ]
        )
    except ClientError as e:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to transfer profile ownership: {e}") from e
    profile["ownerAccountId"] = db_new_owner_id


def _delete_share_if_exists(db_profile_id: str, db_new_owner_id: str) -> None:
    try:
        tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
    except Exception:
        pass


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Transfer profile ownership to another account."""
    import json

    logger.info("transfer_profile_ownership invoked")
    caller_account_id = get_caller_id(event)
    input_data = parse_body(event)
    profile_id = input_data.get("profileId") or (event.get("pathParameters") or {}).get("id") or ""
    new_owner_account_id = input_data.get("newOwnerAccountId") or ""

    if not profile_id or not new_owner_account_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "profileId and newOwnerAccountId are required"}),
        }

    db_profile_id = ensure_profile_id(profile_id) or ""
    db_new_owner_id = ensure_account_id(new_owner_account_id) or ""
    db_caller_id = ensure_account_id(caller_account_id) or ""

    try:
        profile = _get_and_verify_profile(db_profile_id, db_caller_id, event)
        caller_is_admin = is_admin(event)
        _verify_new_owner_has_share(db_profile_id, db_new_owner_id, caller_is_admin)
        _transfer_ownership(profile, db_profile_id, db_new_owner_id)
        _delete_share_if_exists(db_profile_id, db_new_owner_id)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": True, "profileId": db_profile_id, "newOwnerAccountId": db_new_owner_id}),
        }
    except AppError as e:
        status = {ErrorCode.FORBIDDEN: 403, ErrorCode.NOT_FOUND: 404, ErrorCode.INVALID_INPUT: 400}.get(
            e.error_code, 500
        )
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": e.message}),
        }
    except Exception as e:
        logger.error("Failed to transfer ownership", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint. Route POST /api/profiles/{id}/transfer."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "POST")
    path = event.get("path") or "/"
    if path.startswith("/api/profiles/") and path.endswith("/transfer") and method == "POST":
        middle = path[len("/api/profiles/") : -len("/transfer")]
        event["pathParameters"] = {"id": unquote(middle)}
        return lambda_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
