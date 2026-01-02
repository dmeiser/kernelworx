"""
Account operations Lambda handlers.

Handles user account management including updating DynamoDB account metadata.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

import boto3
from mypy_boto3_dynamodb import DynamoDBServiceResource
from mypy_boto3_dynamodb.service_resource import Table
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger

logger = get_logger(__name__)


def _get_dynamodb() -> DynamoDBServiceResource:
    """Return a fresh boto3 DynamoDB resource (lazy for tests)."""
    return boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def get_accounts_table() -> Table:
    """Get DynamoDB accounts table instance (multi-table design)."""
    table_name = os.environ.get("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    return _get_dynamodb().Table(table_name)


# Fields that can be updated directly (no transformation needed)
SIMPLE_UPDATE_FIELDS = ["givenName", "familyName", "city", "state", "unitType"]


def _validate_unit_number(value: Any) -> int | None:
    """Validate and convert unitNumber to int, or return None."""
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        raise AppError(ErrorCode.INVALID_INPUT, "unitNumber must be a valid integer")


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
        unit_number = _validate_unit_number(input_data["unitNumber"])
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
    table = get_accounts_table()

    try:
        response = table.update_item(
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
