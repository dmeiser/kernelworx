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
# The delete_my_account data phase runs through this module-local name, the seam
# where a failing cascade is substituted in tests (#551).
from .deletion_cascade import delete_all_user_data as _delete_all_user_data

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.cognito import retry_on_transient_errors
    from utils.cognito_filters import cognito_user_filter
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.cognito import retry_on_transient_errors
    from ..utils.cognito_filters import cognito_user_filter
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
    1. Verifies Cognito credentials and connectivity before deleting data
    2. Deletes the user from Cognito User Pool with retry on transient errors (the commit point)
    3. Deletes all user data from DynamoDB (profiles, campaigns, orders, shares, invites; catalogs are preserved)

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

    # Handler-specific Cognito error handling stays in this try block: the
    # decorator only covers the generic unexpected-exception path, not typed
    # ClientError mapping.
    try:
        # Pre-check Cognito lookup to fail early on authorization/network/config issues
        try:
            username = _lookup_cognito_user_with_retry(cognito, user_pool_id, account_id)
            if not username:
                logger.warning(f"User not found in Cognito with sub: {account_id}")
        except ClientError as e:
            logger.error("Cognito lookup failed before deletion", account_id=account_id, error=str(e), exc_info=True)
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete account")

        # Delete the Cognito user FIRST so the Cognito call is the commit point
        # (#551): a data-phase failure afterwards leaves records the user can no
        # longer reach (no sign-in, so no post_authentication re-bootstrap) and a
        # re-run of the data phase is safe; a Cognito failure leaves every record
        # intact. Deleting data first would leave a sign-in-capable Cognito user
        # whose records are gone, silently re-bootstrapped on next sign-in.
        _delete_user_from_cognito(cognito, user_pool_id, account_id, username, logger)

    except ClientError as e:
        logger.error("Cognito error during account deletion", account_id=account_id, error=str(e), exc_info=True)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete account")

    # The data phase must not be caught by the Cognito-labeled except above; a
    # post-commit DynamoDB/S3 failure carries its own error_code-tagged log.
    try:
        _delete_all_user_data(account_id, logger)
    except Exception as e:
        logger.error(
            "Cognito user already deleted but user data cleanup failed; "
            "leftover records are inert because the user can no longer sign in",
            account_id=account_id,
            error=str(e),
            error_code=ErrorCode.INTERNAL_ERROR,
        )
        raise

    logger.info("Account deletion completed successfully")
    return True
