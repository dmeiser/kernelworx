"""
Cognito Post-Authentication Lambda Trigger

Creates or updates the Account record in DynamoDB when a user successfully authenticates.
This ensures that getMyAccount always has data to return.

Trigger: Post Authentication
Event: After user signs in (including first-time social login)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Post-Authentication Lambda Trigger Handler

    Creates or updates Account record in DynamoDB after successful authentication.

    Event structure:
    {
        "version": "1",
        "triggerSource": "PostAuthentication_Authentication",
        "region": "us-east-1",
        "userPoolId": "us-east-1_EXAMPLE",
        "userName": "google_123456789",
        "callerContext": {...},
        "request": {
            "userAttributes": {
                "sub": "a1b2c3d4-...",
                "email": "user@example.com",
                "email_verified": "true",
                "identities": "[...]"
            }
        },
        "response": {}
    }

    Args:
        event: Cognito Post Authentication trigger event
        context: Lambda context

    Returns:
        event: Must return the event unmodified for Cognito to continue
    """
    try:
        # Get table reference (multi-table design: use dedicated accounts table)
        dynamodb = boto3.resource("dynamodb")
        table_name = os.environ.get("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        table = dynamodb.Table(table_name)

        logger.info(f"Post-authentication trigger invoked: {event.get('triggerSource')}")

        # Extract user attributes
        user_attributes = event.get("request", {}).get("userAttributes", {})
        account_id = user_attributes.get("sub")
        email = user_attributes.get("email", "")

        if not account_id:
            logger.error("Missing sub (account_id) in user attributes")
            return event  # Return event to allow auth to continue

        # Build the accountId key with prefix
        account_id_key = f"ACCOUNT#{account_id}"

        # Check if Account already exists (multi-table design: accountId is only key)
        existing_account = table.get_item(Key={"accountId": account_id_key}).get("Item")

        timestamp = datetime.now(timezone.utc).isoformat()

        if existing_account:
            # Update existing account (email might have changed, update timestamp)
            # Note: isAdmin is NOT stored in DynamoDB - it comes from JWT cognito:groups claim
            logger.info(f"Updating existing account: {account_id}")
            table.update_item(
                Key={"accountId": account_id_key},
                UpdateExpression="SET email = :email, updatedAt = :updated",
                ExpressionAttributeValues={
                    ":email": email,
                    ":updated": timestamp,
                },
            )
        else:
            # Create new Account record (multi-table design: simpler schema)
            # Note: isAdmin is NOT stored in DynamoDB - it comes from JWT cognito:groups claim
            logger.info(f"Creating new account: {account_id}")

            account_item = {
                "accountId": account_id_key,  # PK: ACCOUNT#uuid
                "email": email,  # GSI: email
                "givenName": user_attributes.get("given_name", ""),  # Optional metadata
                "familyName": user_attributes.get("family_name", ""),  # Optional metadata
                "city": "",  # Will be set via updateMyAccount if provided
                "state": "",  # Will be set via updateMyAccount if provided
                "unitNumber": "",  # Will be set via updateMyAccount if provided
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }

            table.put_item(Item=account_item)

            logger.info(f"Account created successfully: {account_id}, email={email}")

        # IMPORTANT: Must return the event for Cognito to continue
        return event

    except Exception as e:
        logger.exception(f"Error in post-authentication trigger: {str(e)}")
        # IMPORTANT: Still return event to allow authentication to succeed
        # Don't fail auth because of DynamoDB issues
        return event
