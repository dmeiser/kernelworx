"""
Account operations Lambda handlers.

Handles user account management including deleting user accounts.
"""

import os
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger

logger = get_logger(__name__)


def _delete_all_user_data(account_id: str, context: Any, logger: Any) -> None:
    """Delete all user data from DynamoDB using shared deletion internals."""
    from .admin_operations import (
        _delete_inbound_shares,
        _delete_invites_for_owned_profiles,
        _delete_user_campaigns,
        _delete_user_catalogs,
        _delete_user_orders,
        _delete_user_profiles,
        _delete_user_shares,
    )

    _delete_user_orders(account_id, logger)
    _delete_user_campaigns(account_id, logger)
    _delete_user_shares(account_id, logger)
    _delete_invites_for_owned_profiles(account_id, logger)
    _delete_inbound_shares(account_id, logger)
    _delete_user_profiles(account_id, logger)
    _delete_user_catalogs(account_id, logger)

    # TODO(KW-REVIEW-GLM53-1-decision-qr-code-retention-policy): Payment QR S3
    # objects are intentionally not deleted here pending the captain decision on
    # retention policy.

    account_id_key = f"ACCOUNT#{account_id}"
    tables.accounts.delete_item(Key={"accountId": account_id_key})
    logger.info("Deleted all user data from DynamoDB")


def _lookup_cognito_user_with_retry(cognito: Any, user_pool_id: str, account_id: str, logger: Any) -> str | None:
    """Look up Cognito username by sub with retry for transient errors."""
    attempt = 0
    max_retries = 3
    while True:
        try:
            users_response = cognito.list_users(UserPoolId=user_pool_id, Filter=f'sub = "{account_id}"', Limit=1)
            users = users_response.get("Users", [])
            if users:
                return str(users[0]["Username"])
            return None
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if attempt < max_retries - 1 and error_code in (
                "TooManyRequestsException",
                "InternalErrorException",
                "ProvisionedThroughputExceededException",
            ):
                import time

                time.sleep(0.1 * (2**attempt))
                attempt += 1
                continue
            raise


def _delete_user_from_cognito(
    cognito: Any, user_pool_id: str, account_id: str, username: str | None, logger: Any
) -> None:
    """Delete user from Cognito User Pool with retry for transient errors."""
    if not username:
        username = _lookup_cognito_user_with_retry(cognito, user_pool_id, account_id, logger)
    if not username:
        logger.warning(f"User not found in Cognito with sub: {account_id}")
        return

    attempt = 0
    max_retries = 3
    while True:
        try:
            cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
            logger.info(f"Deleted user from Cognito: {username}")
            return
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "UserNotFoundException":
                return
            if attempt < max_retries - 1 and error_code in (
                "TooManyRequestsException",
                "InternalErrorException",
                "ProvisionedThroughputExceededException",
            ):
                import time

                time.sleep(0.1 * (2**attempt))
                attempt += 1
                continue
            raise


def delete_my_account(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete the authenticated user's account and all associated data.

    This is a self-service account deletion that:
    1. Verifies Cognito credentials and connectivity before deleting DynamoDB data
    2. Deletes all user data from DynamoDB (profiles, campaigns, orders, shares, catalogs, invites)
    3. Deletes the user from Cognito User Pool with retry on transient errors

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
        # Pre-check Cognito lookup to fail early on authorization/network/config issues
        try:
            username = _lookup_cognito_user_with_retry(cognito, user_pool_id, account_id, logger)
            if not username:
                logger.warning(f"User not found in Cognito with sub: {account_id}")
        except ClientError as e:
            logger.error(f"Cognito lookup failed before deletion: {str(e)}")
            raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to verify account in Cognito: {str(e)}")

        _delete_all_user_data(account_id, context, logger)
        _delete_user_from_cognito(cognito, user_pool_id, account_id, username, logger)
        logger.info("Account deletion completed successfully")
        return True

    except AppError:
        raise
    except ClientError as e:
        logger.error(f"Cognito error during account deletion: {str(e)}")
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to delete account from Cognito: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to delete account: {str(e)}")
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to delete account: {str(e)}")
