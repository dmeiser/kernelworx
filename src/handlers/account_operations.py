"""
Account operations Lambda handlers (API Gateway proxy event shape).

Handles user account management:
- update_my_account: update DynamoDB account metadata from a form/JSON POST.
- delete_my_account: delete the caller's account, all DynamoDB data, and the
  Cognito user.

Restored from the AppSync-shaped ``main`` version and adapted to read the
caller id from ``requestContext.authorizer.claims.sub`` and the payload from
``event["body"]``. The cascade-deletion internals were inlined to avoid
pulling the AppSync-shaped ``admin_operations`` module into the Lambda
package.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id
    from utils.logging import get_logger
    from utils.proxy_event import get_caller_id, parse_body
    from utils.validation import validate_unit_number
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.dynamodb import tables
    from src.utils.errors import AppError, ErrorCode
    from src.utils.ids import ensure_account_id
    from src.utils.logging import get_logger
    from src.utils.proxy_event import get_caller_id, parse_body
    from src.utils.validation import validate_unit_number

logger = get_logger(__name__)

SIMPLE_UPDATE_FIELDS = ["givenName", "familyName", "city", "state", "unitType"]


def _build_update_expressions(input_data: Dict[str, Any]):
    update_expressions = []
    expression_attribute_names: Dict[str, str] = {}
    expression_attribute_values: Dict[str, Any] = {}

    for field in SIMPLE_UPDATE_FIELDS:
        if input_data.get(field) is not None:
            update_expressions.append(f"#{field} = :{field}")
            expression_attribute_names[f"#{field}"] = field
            expression_attribute_values[f":{field}"] = input_data[field]

    if "unitNumber" in input_data:
        unit_number = validate_unit_number(input_data["unitNumber"])
        if unit_number is not None:
            update_expressions.append("#unitNumber = :unitNumber")
            expression_attribute_names["#unitNumber"] = "unitNumber"
            expression_attribute_values[":unitNumber"] = unit_number

    update_expressions.append("#updatedAt = :updatedAt")
    expression_attribute_names["#updatedAt"] = "updatedAt"
    expression_attribute_values[":updatedAt"] = datetime.now(timezone.utc).isoformat()

    return update_expressions, expression_attribute_names, expression_attribute_values


def update_my_account(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Update the authenticated user's account metadata in DynamoDB."""
    import json

    logger.info("update_my_account handler invoked")
    caller_id = get_caller_id(event)
    input_data = parse_body(event)

    update_expressions, names, values = _build_update_expressions(input_data)
    if len(update_expressions) == 1:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "error": "At least one field must be provided (givenName, familyName, city, state, unitType, or unitNumber)"
                }
            ),
        }

    account_id_key = ensure_account_id(caller_id) or f"ACCOUNT#{caller_id}"
    try:
        response = tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET " + ", ".join(update_expressions),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(accountId)",
            ReturnValues="ALL_NEW",
        )
        updated_item = response.get("Attributes", {})
        logger.info("Updated account", account_id=account_id_key)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "accountId": updated_item.get("accountId"),
                    "email": updated_item.get("email"),
                    "givenName": updated_item.get("givenName"),
                    "familyName": updated_item.get("familyName"),
                    "phoneNumber": updated_item.get("phoneNumber"),
                    "createdAt": updated_item.get("createdAt"),
                    "updatedAt": updated_item.get("updatedAt"),
                },
                default=str,
            ),
        }
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": f"Account {caller_id} not found"}),
            }
        logger.error("Failed to update account", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def _get_user_profiles(db_account_id: str):
    try:
        res = tables.profiles.query(
            IndexName="profileId-index",
            KeyConditionExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": db_account_id},
        )
        return res.get("Items", [])
    except Exception:
        # Fallback for schemas without the GSI: scan + filter.
        scan = tables.profiles.scan(
            FilterExpression="ownerAccountId = :owner", ExpressionAttributeValues={":owner": db_account_id}
        )
        return scan.get("Items", [])


def _query_all(table, key_condition, expr_values, index_name=None):
    items = []
    kwargs: Dict[str, Any] = {"KeyConditionExpression": key_condition, "ExpressionAttributeValues": expr_values}
    if index_name:
        kwargs["IndexName"] = index_name
    while True:
        res = table.query(**kwargs)
        items.extend(res.get("Items", []))
        lek = res.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def _delete_user_orders(account_id: str) -> int:
    db_account_id = ensure_account_id(account_id) or f"ACCOUNT#{account_id}"
    deleted = 0
    for profile in _get_user_profiles(db_account_id):
        profile_id = profile["profileId"]
        campaigns = _query_all(tables.campaigns, "profileId = :pid", {":pid": profile_id})
        for campaign in campaigns:
            campaign_id = campaign["campaignId"]
            orders = _query_all(tables.orders, "campaignId = :cid", {":cid": campaign_id})
            for order in orders:
                tables.orders.delete_item(Key={"campaignId": campaign_id, "orderId": order["orderId"]})
                deleted += 1
    return deleted


def _delete_user_campaigns(account_id: str) -> int:
    db_account_id = ensure_account_id(account_id) or f"ACCOUNT#{account_id}"
    deleted = 0
    for profile in _get_user_profiles(db_account_id):
        profile_id = profile["profileId"]
        campaigns = _query_all(tables.campaigns, "profileId = :pid", {":pid": profile_id})
        for campaign in campaigns:
            tables.campaigns.delete_item(Key={"profileId": profile_id, "campaignId": campaign["campaignId"]})
            deleted += 1
    return deleted


def _delete_user_shares(account_id: str) -> int:
    db_account_id = ensure_account_id(account_id) or f"ACCOUNT#{account_id}"
    deleted = 0
    for profile in _get_user_profiles(db_account_id):
        profile_id = profile["profileId"]
        shares = _query_all(tables.shares, "profileId = :pid", {":pid": profile_id})
        for share in shares:
            tables.shares.delete_item(Key={"profileId": profile_id, "targetAccountId": share["targetAccountId"]})
            deleted += 1
    return deleted


def _delete_user_profiles(account_id: str) -> int:
    db_account_id = ensure_account_id(account_id) or f"ACCOUNT#{account_id}"
    deleted = 0
    for profile in _get_user_profiles(db_account_id):
        tables.profiles.delete_item(Key={"ownerAccountId": db_account_id, "profileId": profile["profileId"]})
        deleted += 1
    return deleted


def _delete_user_catalogs(account_id: str) -> int:
    db_account_id = ensure_account_id(account_id) or f"ACCOUNT#{account_id}"
    deleted = 0
    scan_kwargs: Dict[str, Any] = {
        "FilterExpression": "ownerAccountId = :owner AND (attribute_not_exists(isDeleted) OR isDeleted = :false)",
        "ExpressionAttributeValues": {":owner": db_account_id, ":false": False},
    }
    while True:
        res = tables.catalogs.scan(**scan_kwargs)
        for catalog in res.get("Items", []):
            tables.catalogs.update_item(
                Key={"catalogId": catalog["catalogId"]},
                UpdateExpression="SET isDeleted = :true",
                ExpressionAttributeValues={":true": True},
            )
            deleted += 1
        lek = res.get("LastEvaluatedKey")
        if not lek:
            break
        scan_kwargs["ExclusiveStartKey"] = lek
    return deleted


def _delete_all_user_data(account_id: str) -> None:
    _delete_user_orders(account_id)
    _delete_user_campaigns(account_id)
    _delete_user_shares(account_id)
    _delete_user_profiles(account_id)
    _delete_user_catalogs(account_id)
    db_account_id = ensure_account_id(account_id) or f"ACCOUNT#{account_id}"
    tables.accounts.delete_item(Key={"accountId": db_account_id})


def _delete_user_from_cognito(cognito, user_pool_id: str, account_id: str) -> None:
    try:
        users_response = cognito.list_users(UserPoolId=user_pool_id, Filter=f'sub = "{account_id}"', Limit=1)
        users = users_response.get("Users", [])
        if users:
            username = users[0]["Username"]
            cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
            logger.info("Deleted user from Cognito", username=username)
        else:
            logger.warning("User not found in Cognito", sub=account_id)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "UserNotFoundException":
            raise


def delete_my_account(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete the authenticated user's account and all associated data."""
    import json

    logger.info("delete_my_account handler invoked")
    caller_id = get_caller_id(event)
    user_pool_id = os.environ.get("USER_POOL_ID")
    if not user_pool_id:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "USER_POOL_ID not configured"}),
        }
    cognito = boto3.client("cognito-idp")
    try:
        _delete_all_user_data(caller_id)
        _delete_user_from_cognito(cognito, user_pool_id, caller_id)
        logger.info("Account deletion completed", account_id=caller_id)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": True}),
        }
    except ClientError as e:
        logger.error("Cognito error during account deletion", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Failed to delete account from Cognito: {e}"}),
        }
    except Exception as e:
        logger.error("Failed to delete account", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Failed to delete account: {e}"}),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for account operations."""
    import json

    method = event.get("httpMethod", "POST")
    path = event.get("path") or "/"
    if path == "/api/account" and method == "POST":
        return update_my_account(event, context)
    if path == "/api/account/delete" and method == "POST":
        return delete_my_account(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
