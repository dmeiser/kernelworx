"""
Account operations Lambda handlers.

Handles user account management including updating DynamoDB account metadata.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.validation import validate_unit_number
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger
    from ..utils.validation import validate_unit_number

logger = get_logger(__name__)


# Fields that can be updated directly (no transformation needed)
SIMPLE_UPDATE_FIELDS = ["givenName", "familyName", "city", "state", "unitType"]


def _build_update_expressions(
    input_data: Dict[str, Any],
) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    """Build DynamoDB update expressions from input data."""
    update_expressions: list[str] = []
    expression_attribute_names: dict[str, str] = {}
    expression_attribute_values: dict[str, Any] = {}

    # Handle simple fields
    for field in SIMPLE_UPDATE_FIELDS:
        if input_data.get(field) is not None:
            update_expressions.append(f"#{field} = :{field}")
            expression_attribute_names[f"#{field}"] = field
            expression_attribute_values[f":{field}"] = input_data[field]

    # Handle unitNumber specially (needs validation/conversion)
    if "unitNumber" in input_data:
        unit_number = validate_unit_number(input_data["unitNumber"])
        if unit_number is not None:
            update_expressions.append("#unitNumber = :unitNumber")
            expression_attribute_names["#unitNumber"] = "unitNumber"
            expression_attribute_values[":unitNumber"] = unit_number

    # Always update updatedAt
    update_expressions.append("#updatedAt = :updatedAt")
    expression_attribute_names["#updatedAt"] = "updatedAt"
    expression_attribute_values[":updatedAt"] = datetime.now(timezone.utc).isoformat()

    return update_expressions, expression_attribute_names, expression_attribute_values


def update_my_account(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update the authenticated user's account metadata in DynamoDB.

    Updates optional user attributes: givenName, familyName, city, state, unitType, unitNumber.
    Email cannot be changed (stored in Cognito, immutable via this API).

    Args:
        event: AppSync event with input containing optional metadata fields
        context: Lambda context

    Returns:
        Updated Account object from DynamoDB

    Raises:
        AppError: If no fields provided or account not found
    """
    logger.info("update_my_account handler invoked")

    account_id = event["identity"]["sub"]
    logger.info(f"Updating account for: {account_id}")

    input_data = event.get("arguments", {}).get("input", {})
    update_expressions, expression_attribute_names, expression_attribute_values = _build_update_expressions(input_data)

    # If no user-provided attributes, return error (only updatedAt was added)
    if len(update_expressions) == 1:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "At least one field must be provided (givenName, familyName, city, state, unitType, or unitNumber)",
        )

    account_id_key = f"ACCOUNT#{account_id}"

    try:
        response = tables.accounts.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET " + ", ".join(update_expressions),
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
            ConditionExpression="attribute_exists(accountId)",
            ReturnValues="ALL_NEW",
        )

        updated_item = response["Attributes"]
        logger.info(f"Updated account: {json.dumps(updated_item, default=str)}")

        return {
            "accountId": updated_item.get("accountId"),
            "email": updated_item.get("email"),
            "givenName": updated_item.get("givenName"),
            "familyName": updated_item.get("familyName"),
            "phoneNumber": updated_item.get("phoneNumber"),
            "createdAt": updated_item.get("createdAt"),
            "updatedAt": updated_item.get("updatedAt"),
        }

    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise AppError(ErrorCode.NOT_FOUND, f"Account {account_id} not found")
        logger.error(f"Failed to update account: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to update account: {str(e)}")
        raise


def _delete_all_user_data(account_id: str, context: Any, logger: Any) -> None:
    """Delete all user data from DynamoDB using admin delete functions."""
    from .admin_operations import (
        admin_delete_user_catalogs,
        admin_delete_user_campaigns,
        admin_delete_user_orders,
        admin_delete_user_profiles,
        admin_delete_user_shares,
    )

    pseudo_event = {
        "identity": {"sub": account_id, "claims": {"cognito:groups": ["ADMIN"]}},
        "arguments": {"accountId": account_id},
    }

    admin_delete_user_orders(pseudo_event, context)
    admin_delete_user_campaigns(pseudo_event, context)
    admin_delete_user_shares(pseudo_event, context)
    admin_delete_user_profiles(pseudo_event, context)
    admin_delete_user_catalogs(pseudo_event, context)

    account_id_key = f"ACCOUNT#{account_id}"
    tables.accounts.delete_item(Key={"accountId": account_id_key})
    logger.info("Deleted all user data from DynamoDB")


def _delete_user_from_cognito(cognito: Any, user_pool_id: str, account_id: str, logger: Any) -> None:
    """Delete user from Cognito User Pool."""
    try:
        users_response = cognito.list_users(UserPoolId=user_pool_id, Filter=f'sub = "{account_id}"', Limit=1)
        users = users_response.get("Users", [])
        if users:
            username = users[0]["Username"]
            cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
            logger.info(f"Deleted user from Cognito: {username}")
        else:
            logger.warning(f"User not found in Cognito with sub: {account_id}")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code != "UserNotFoundException":
            raise


def delete_my_account(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete the authenticated user's account and all associated data.

    This is a self-service account deletion that:
    1. Deletes all user data from DynamoDB (profiles, campaigns, orders, shares, catalogs, invites)
    2. Deletes the user from Cognito User Pool

    Args:
        event: AppSync event with identity
        context: Lambda context

    Returns:
        True if account was deleted successfully

    Raises:
        AppError: If deletion error occurs
    """
    logger.info("delete_my_account handler invoked")

    account_id = event["identity"]["sub"]
    logger.info(f"Deleting account for: {account_id}")

    user_pool_id = os.environ.get("USER_POOL_ID")
    if not user_pool_id:
        raise AppError(ErrorCode.INTERNAL_ERROR, "USER_POOL_ID not configured")

    cognito = boto3.client("cognito-idp")

    try:
        _delete_all_user_data(account_id, context, logger)
        _delete_user_from_cognito(cognito, user_pool_id, account_id, logger)
        logger.info("Account deletion completed successfully")
        return True

    except ClientError as e:
        logger.error(f"Cognito error during account deletion: {str(e)}")
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to delete account from Cognito: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to delete account: {str(e)}")
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to delete account: {str(e)}")
