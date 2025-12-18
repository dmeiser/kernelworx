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
    from utils.errors import AppError, ErrorCode  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger

logger = get_logger(__name__)

dynamodb = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def get_accounts_table() -> Any:
    """Get DynamoDB accounts table instance (multi-table design)."""
    table_name = os.environ.get("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    return dynamodb.Table(table_name)


def update_my_account(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update the authenticated user's account metadata in DynamoDB.

    Updates optional user attributes: givenName, familyName, city, state, unitNumber.
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

    # Get caller's accountId from Cognito claims (AppSync identity)
    account_id = event["identity"]["sub"]
    logger.info(f"Updating account for: {account_id}")

    # Extract input
    input_data = event.get("arguments", {}).get("input", {})
    given_name = input_data.get("givenName")
    family_name = input_data.get("familyName")
    city = input_data.get("city")
    state = input_data.get("state")
    unit_number = input_data.get("unitNumber")

    # Build DynamoDB update expression
    update_expressions = []
    expression_attribute_names = {}
    expression_attribute_values = {}

    if given_name is not None:
        update_expressions.append("#givenName = :givenName")
        expression_attribute_names["#givenName"] = "givenName"
        expression_attribute_values[":givenName"] = given_name

    if family_name is not None:
        update_expressions.append("#familyName = :familyName")
        expression_attribute_names["#familyName"] = "familyName"
        expression_attribute_values[":familyName"] = family_name

    if city is not None:
        update_expressions.append("#city = :city")
        expression_attribute_names["#city"] = "city"
        expression_attribute_values[":city"] = city

    if state is not None:
        update_expressions.append("#state = :state")
        expression_attribute_names["#state"] = "state"
        expression_attribute_values[":state"] = state

    if unit_number is not None:
        update_expressions.append("#unitNumber = :unitNumber")
        expression_attribute_names["#unitNumber"] = "unitNumber"
        expression_attribute_values[":unitNumber"] = unit_number

    # Always update updatedAt
    update_expressions.append("#updatedAt = :updatedAt")
    expression_attribute_names["#updatedAt"] = "updatedAt"
    expression_attribute_values[":updatedAt"] = datetime.now(timezone.utc).isoformat()

    # If no user-provided attributes, return error
    if len(update_expressions) == 1:  # Only updatedAt
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "At least one field must be provided (givenName, familyName, city, state, or unitNumber)",
        )

    # Update DynamoDB account record (multi-table design: accountId is the only key)
    account_id_key = f"ACCOUNT#{account_id}"
    table = get_accounts_table()

    try:
        response = table.update_item(
            Key={"accountId": account_id_key},
            UpdateExpression="SET " + ", ".join(update_expressions),
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
            ConditionExpression="attribute_exists(accountId)",  # Ensure account exists
            ReturnValues="ALL_NEW",
        )

        updated_item = response["Attributes"]
        logger.info(f"Updated account: {json.dumps(updated_item, default=str)}")

        # Return Account object
        account = {
            "accountId": updated_item.get("accountId"),
            "email": updated_item.get("email"),
            "givenName": updated_item.get("givenName"),
            "familyName": updated_item.get("familyName"),
            "phoneNumber": updated_item.get("phoneNumber"),
            "isAdmin": updated_item.get("isAdmin", False),
            "createdAt": updated_item.get("createdAt"),
            "updatedAt": updated_item.get("updatedAt"),
        }

        return account

    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise AppError(ErrorCode.NOT_FOUND, f"Account {account_id} not found")
        logger.error(f"Failed to update account: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to update account: {str(e)}")
        raise
