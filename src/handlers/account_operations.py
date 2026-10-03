"""
Account operations Lambda handlers.

Handles user account management including deleting user accounts.
"""

import os
from typing import TYPE_CHECKING, Any, Dict

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import delete_all_user_data

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.cognito import retry_on_transient_errors
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import is_transient_client_error
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.cognito import retry_on_transient_errors
    from ..utils.cognito_filters import cognito_user_filter
    from ..utils.dynamodb import is_transient_client_error
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger

# The decorator stays typed for mypy via the relative import below; at runtime
# the absolute import resolves in the Lambda zip (package `utils`) and the
# relative fallback resolves in unit tests (package `src.handlers`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling


logger = get_logger(__name__)


def _lookup_cognito_user_with_retry(cognito: Any, user_pool_id: str, account_id: str) -> str | None:
    """Look up Cognito username by sub with retry for transient errors."""
    # Building the filter validates and quotes the value in one step, so the value that
    # was checked is the value sent (#124, #441, #560). The transient-fault backoff stays
    # with the shared retry helper landed in #580.
    filter_expression = cognito_user_filter("sub", account_id)
    users_response = retry_on_transient_errors(
        cognito.list_users, UserPoolId=user_pool_id, Filter=filter_expression, Limit=1
    )
    users = users_response.get("Users", [])
    if users:
        return str(users[0]["Username"])
    return None


def _delete_user_from_cognito(
    cognito: Any, user_pool_id: str, account_id: str, username: str | None, logger: Any
) -> None:
    """Delete user from Cognito User Pool with retry for transient errors."""
    if not username:
        username = _lookup_cognito_user_with_retry(cognito, user_pool_id, account_id)
    if not username:
        logger.warning(f"User not found in Cognito with sub: {account_id}")
        return

    try:
        retry_on_transient_errors(cognito.admin_delete_user, UserPoolId=user_pool_id, Username=username)
    except ClientError as e:
        # A user that no longer exists is a successful deletion, not an error.
        if e.response.get("Error", {}).get("Code") == "UserNotFoundException":
            return
        raise
    logger.info(f"Deleted user from Cognito: {username}")


@with_error_handling(error_message="Failed to delete account")
def delete_my_account(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete the authenticated user's account and all associated data.

    This is a self-service account deletion that:
    1. Verifies Cognito credentials and connectivity before deleting DynamoDB data
    2. Deletes all user data from DynamoDB (profiles, campaigns, orders, shares, invites; catalogs are preserved)
    3. Deletes the user from Cognito User Pool with retry on transient errors

    Args:
        event: AppSync event with identity
        context: Lambda context

    Returns:
        True if account was deleted successfully

    Raises:
        AppError: If deletion error occurs. When the data sweep succeeded but
            the Cognito delete failed, the error names the partial state so
            the caller knows the account needs a retry to complete.
    """
    logger.info("delete_my_account handler invoked")

    account_id = get_caller_id(event)
    if not account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Caller identity is required")
    logger.info(f"Deleting account for: {account_id}")

    user_pool_id = os.environ.get("USER_POOL_ID")
    if not user_pool_id:
        raise AppError(ErrorCode.INTERNAL_ERROR, "USER_POOL_ID not configured")

    cognito = boto3.client("cognito-idp")

    # Pre-check Cognito lookup to fail early on authorization/network/config issues
    try:
        username = _lookup_cognito_user_with_retry(cognito, user_pool_id, account_id)
        if not username:
            logger.warning(f"User not found in Cognito with sub: {account_id}")
    except (ClientError, BotoCoreError) as e:
        logger.error("Cognito lookup failed before deletion", account_id=account_id, error=str(e), exc_info=True)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete account") from e

    # The data sweep runs before the Cognito delete and is safe to re-run, so a
    # retry after any failure below converges; a sweep failure here leaves the
    # Cognito user untouched.
    delete_all_user_data(account_id, logger)

    try:
        _delete_user_from_cognito(cognito, user_pool_id, account_id, username, logger)
    except (ClientError, BotoCoreError, AppError) as e:
        # A typed AppError from the Cognito helper (or a future RESOURCE_BUSY)
        # propagates with its own code and message intact; only a raw
        # botocore fault is attributed here. BotoCoreError stays in the catch
        # because a transport failure after the request was sent is precisely
        # the unknown-state case below. Only two facts are then established:
        # the sweep completed and the Cognito delete did not report success.
        # Whether the user survives is unknown (the delete may have landed,
        # and a failed re-lookup of an absent user also lands here), so the
        # message says exactly that.
        if isinstance(e, AppError):
            raise
        error_code = (
            ErrorCode.RESOURCE_BUSY if isinstance(e, ClientError) and is_transient_client_error(e) else ErrorCode.INTERNAL_ERROR
        )
        logger.error(
            "Account data swept but the Cognito delete did not report success; "
            "the account's Cognito state is unknown and needs a retry or manual completion",
            account_id=account_id,
            error=str(e),
            error_code=error_code,
            exc_info=True,
        )
        raise AppError(
            error_code,
            "Account data was deleted but the Cognito user could not be confirmed deleted; "
            "retry to complete the deletion",
        ) from e

    logger.info("Account deletion completed successfully")
    return True
