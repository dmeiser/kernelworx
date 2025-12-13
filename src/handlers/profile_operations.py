"""Lambda resolvers for SellerProfile operations."""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import boto3

# Handle both Lambda (absolute) and unit test (relative) imports
try:
    from utils.logging import get_logger
except ModuleNotFoundError:
    from ..utils.logging import get_logger  # type: ignore

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")
table_name = os.environ.get("TABLE_NAME", "psm-app-dev")
table = dynamodb.Table(table_name)


def create_seller_profile(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new seller profile with both ownership and metadata items.

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Created profile dict

    Raises:
        ValueError: If input validation fails
    """
    try:
        # Extract parameters
        seller_name = event["arguments"]["input"]["sellerName"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Creating seller profile",
            extra={"sellerName": seller_name, "callerAccountId": caller_account_id},
        )

        # Generate IDs and timestamp
        profile_id = f"PROFILE#{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()

        # Profile data
        profile_data = {
            "profileId": profile_id,
            "ownerAccountId": caller_account_id,
            "sellerName": seller_name,
            "createdAt": now,
            "updatedAt": now,
        }

        # Write both items using TransactWriteItems for atomicity
        dynamodb_client = boto3.client("dynamodb")
        dynamodb_client.transact_write_items(
            TransactItems=[
                {
                    # Ownership item: for listing profiles owned by account
                    "Put": {
                        "TableName": table_name,
                        "Item": {
                            "PK": {"S": f"ACCOUNT#{caller_account_id}"},
                            "SK": {"S": profile_id},
                            "profileId": {"S": profile_id},
                            "ownerAccountId": {"S": caller_account_id},
                            "sellerName": {"S": seller_name},
                            "createdAt": {"S": now},
                            "updatedAt": {"S": now},
                        },
                    }
                },
                {
                    # Metadata item: for direct profile lookup and authorization
                    "Put": {
                        "TableName": table_name,
                        "Item": {
                            "PK": {"S": profile_id},
                            "SK": {"S": "METADATA"},
                            "profileId": {"S": profile_id},
                            "ownerAccountId": {"S": caller_account_id},
                            "sellerName": {"S": seller_name},
                            "createdAt": {"S": now},
                            "updatedAt": {"S": now},
                        },
                    }
                },
            ]
        )

        logger.info(
            "Seller profile created successfully",
            extra={"profileId": profile_id, "sellerName": seller_name},
        )

        return profile_data

    except Exception as e:
        logger.error("Error creating seller profile", extra={"error": str(e)}, exc_info=True)
        raise RuntimeError(f"Failed to create seller profile: {str(e)}") from e
