"""
Account operations Lambda handlers.

Handles user account management including deleting user accounts.
"""

import os
from typing import TYPE_CHECKING, Any, Dict

import boto3
from botocore.exceptions import ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import delete_all_user_data

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.cognito import is_transient_cognito_error, retry_on_transient_errors
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import is_transient_client_error
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.cognito import is_transient_cognito_error, retry_on_transient_errors
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
        AppError: If deletion error occurs
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

    # Pre-check Cognito lookup to fail early on authorization/network/config issues.
    # Handler-specific Cognito error handling stays in this handler: the
    # decorator only covers the generic unexpected-exception path, not typed
    # ClientError mapping.
    try:
        username = _lookup_cognito_user_with_retry(cognito, user_pool_id, account_id)
        if not username:
            logger.warning(f"User not found in Cognito with sub: {account_id}")
    except ClientError as error:
        # A retryable Cognito fault is a retryable outcome even when the retry
        # wrapper is already exhausted (#291): emit RESOURCE_BUSY, not a
        # permanent failure.
        error_code = ErrorCode.RESOURCE_BUSY if is_transient_cognito_error(error) else ErrorCode.INTERNAL_ERROR
        message = (
            "Failed to delete account. Retry to complete the deletion."
            if error_code == ErrorCode.RESOURCE_BUSY
            else "Failed to delete account"
        )
        logger.error("Cognito lookup failed before deletion", account_id=account_id, error=str(error), exc_info=True)
        raise AppError(error_code, message) from error

    # The data sweep runs before the Cognito delete and is safe to re-run, so a
    # retry after any failure below converges; a sweep failure leaves the
    # Cognito user untouched.
    try:
        delete_all_user_data(account_id, logger)
    except AppError as error:
        logger.error(
            "Data sweep failed before the Cognito delete; the Cognito user is untouched",
            account_id=account_id,
            error=str(error),
            error_code=error.error_code,
            exc_info=True,
        )
        raise
    except ClientError as error:
        logger.error(
            "Data sweep failed before the Cognito delete; the Cognito user is untouched",
            account_id=account_id,
            error=str(error),
            aws_error_code=error.response.get("Error", {}).get("Code", ""),
            exc_info=True,
        )
        if is_transient_client_error(error):
            raise AppError(
                ErrorCode.RESOURCE_BUSY,
                "Data sweep failed before the Cognito delete; the Cognito user is "
                "untouched. Retry to complete the deletion.",
            ) from error
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete account data") from error

    try:
        _delete_user_from_cognito(cognito, user_pool_id, account_id, username, logger)
    except Exception as error:
        # Only two facts are established here: the sweep completed (the
        # accounts row included — self-service deletes it in the sweep, with
        # Cognito as the commit point) and the Cognito delete did not report
        # success. Whether the user survives is unknown (the delete may have
        # landed, and a failed re-lookup of an absent user also lands here).
        # Non-ClientError faults (BotoCoreError network errors) land here too:
        # the partial state is just as unknown, so the narration must survive.
        logger.error(
            "Account data swept but the Cognito delete did not report success; "
            "the account's Cognito state is unknown and needs a retry or manual completion",
            account_id=account_id,
            error=str(error),
            aws_error_code=error.response.get("Error", {}).get("Code", "") if isinstance(error, ClientError) else "",
            exc_info=True,
        )
        if isinstance(error, ClientError) and is_transient_cognito_error(error):
            raise AppError(
                ErrorCode.RESOURCE_BUSY,
                "Account data was deleted but the Cognito user could not be confirmed deleted; "
                "retry to complete the deletion",
            ) from error
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Account data was deleted but the Cognito user could not be confirmed deleted; "
            "complete the deletion manually in Cognito",
        ) from error

    logger.info("Account deletion completed successfully")
    return True
