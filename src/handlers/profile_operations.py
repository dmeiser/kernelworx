"""Lambda resolvers for SellerProfile operations."""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import boto3

# Handle both Lambda (absolute) and unit test (relative) imports
try:
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:
    from ..utils.logging import get_logger

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

# Multi-table design: profiles table for profile records
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
profiles_table = dynamodb.Table(profiles_table_name)


def create_seller_profile(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new seller profile.

    In the multi-table design, profiles are stored in the profiles table with:
    - PK: profileId (e.g., "PROFILE#abc123")
    - SK: recordType (e.g., "METADATA", "SHARE#...", "INVITE#...")

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
        # Store with ACCOUNT# prefix for consistency with resolver ownership checks
        owner_account_id_stored = f"ACCOUNT#{caller_account_id}"
        now = datetime.now(timezone.utc).isoformat()

        # Profile data to return (matches GraphQL schema - no prefix for API clients)
        profile_data = {
            "profileId": profile_id,
            "ownerAccountId": caller_account_id,  # Return without prefix
            "sellerName": seller_name,
            "createdAt": now,
            "updatedAt": now,
        }

        # In multi-table design, we only need to create the profile METADATA record
        # in the profiles table. The ownerAccountId field + GSI (ownerAccountId-index)
        # enables listing profiles owned by an account.
        dynamodb_client = boto3.client("dynamodb")
        dynamodb_client.transact_write_items(
            TransactItems=[
                {
                    # Profile metadata item: for direct profile lookup and authorization
                    "Put": {
                        "TableName": profiles_table_name,
                        "Item": {
                            "profileId": {"S": profile_id},
                            "recordType": {"S": "METADATA"},
                            "ownerAccountId": {"S": owner_account_id_stored},  # Store with prefix
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
