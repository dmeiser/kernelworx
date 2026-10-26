"""
Admin password-reset handler (extracted from admin_operations, #773).

Provides:
- adminResetUserPassword: Send password reset email to user

The handler stays registered on the shared admin-operations Lambda:
``admin_operations`` imports it for its operation dispatcher map, so the
Lambda entry point (``handlers.admin_operations.lambda_handler``) and the
AppSync handler mapping are unchanged.
"""

from typing import TYPE_CHECKING, Any, Dict

from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import require_admin_mfa
    from utils.boto import get_cognito_client
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import get_required_env
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger, mask_email
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import require_admin_mfa
    from ..utils.boto import get_cognito_client
    from ..utils.cognito_filters import cognito_user_filter
    from ..utils.dynamodb import get_required_env
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger, mask_email

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


def _find_user_by_email(cognito: Any, user_pool_id: str, email: str, logger: Any) -> str:
    """Find username by email. Returns username."""
    try:
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            # Built in one step so the value that was checked is the value sent (#124, #560).
            Filter=cognito_user_filter("email", email),
            Limit=1,
        )
    except ClientError as e:
        logger.error("Cognito list_users failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to search for user")

    users = response.get("Users", [])
    if not users:
        raise AppError(ErrorCode.NOT_FOUND, f"User with email '{email}' not found")

    return str(users[0]["Username"])


def _initiate_password_reset(cognito: Any, user_pool_id: str, username: str, email: str, logger: Any) -> None:
    """Initiate Cognito password reset for user."""
    try:
        cognito.admin_reset_user_password(
            UserPoolId=user_pool_id,
            Username=username,
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "UserNotFoundException":
            raise AppError(ErrorCode.NOT_FOUND, f"User with email '{email}' not found")
        if error_code == "InvalidParameterException":
            raise AppError(ErrorCode.INVALID_INPUT, "Cannot reset password for this user type")
        logger.error("Cognito admin_reset_user_password failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to initiate password reset")


@with_error_handling(error_message="Failed to reset password")
def admin_reset_user_password(event: Dict[str, Any], context: Any) -> bool:
    """
    Send password reset email to user (admin only).

    AppSync Lambda resolver for adminResetUserPassword mutation.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        True if password reset was initiated successfully

    Raises:
        AppError: If not admin, user not found, or Cognito error
    """
    from .admin_operations import _actor_sub

    logger = get_logger(__name__)

    # Verify caller is admin and extract email
    require_admin_mfa(event)

    arguments = event.get("arguments", {})
    email = arguments.get("email", "").strip().lower()

    if not email:
        raise AppError(ErrorCode.INVALID_INPUT, "Email is required")

    user_pool_id = get_required_env("USER_POOL_ID")
    cognito = get_cognito_client()

    # Find user and initiate reset
    username = _find_user_by_email(cognito, user_pool_id, email, logger)
    _initiate_password_reset(cognito, user_pool_id, username, email, logger)

    actor_sub = _actor_sub(event)
    logger.info(
        "Password reset initiated",
        email=mask_email(email),
        username=mask_email(username),
        actor_sub=actor_sub,
    )
    return True
