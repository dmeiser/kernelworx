"""
Admin account purge handler (extracted from admin_operations, #773).

Provides:
- adminPurgeUserAccount: Sweep the client-unreachable residue, then delete the
  accounts record and the Cognito user

The handler stays registered on the shared admin-operations Lambda:
``admin_operations`` imports it for its operation dispatcher map, so the
Lambda entry point (``handlers.admin_operations.lambda_handler``) and the
AppSync handler mapping are unchanged.
"""

from typing import TYPE_CHECKING, Any, Dict

from botocore.exceptions import BotoCoreError, ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import (
    delete_inbound_shares,
    delete_invites_for_owned_profiles,
    delete_user_s3_reports,
    run_deletion_steps,
)

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.boto import get_cognito_client
    from utils.cognito import is_transient_cognito_error
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import get_required_env, tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id, ensure_profile_id
    from utils.logging import get_logger, mask_email
    from utils.payment_methods import delete_all_user_qr_codes
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.boto import get_cognito_client
    from ..utils.cognito import is_transient_cognito_error
    from ..utils.cognito_filters import cognito_user_filter
    from ..utils.dynamodb import get_required_env, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id, ensure_profile_id
    from ..utils.logging import get_logger, mask_email
    from ..utils.payment_methods import delete_all_user_qr_codes

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


def _find_cognito_user_by_sub(
    cognito: Any, user_pool_id: str, account_id: str, logger: Any
) -> tuple[str | None, str | None]:
    """Find Cognito user by sub and return (username, email).

    Only an empty Cognito response indicates the user is already absent.
    Lookup failures (throttling, InternalErrorException, etc.) raise an
    AppError so the caller does not proceed to delete DynamoDB data while
    the Cognito user still exists.
    """
    raw_sub = account_id[8:] if account_id.startswith("ACCOUNT#") else account_id
    try:
        users_response = cognito.list_users(
            UserPoolId=user_pool_id,
            # Built in one step so the value that was checked is the value sent (#124, #560).
            Filter=cognito_user_filter("sub", raw_sub),
            Limit=1,
        )
        users = users_response.get("Users", [])
        if users:
            username = users[0]["Username"]
            attributes = {attr["Name"]: attr["Value"] for attr in users[0].get("Attributes", [])}
            email = attributes.get("email", "")
            return username, email
    except (ClientError, BotoCoreError) as e:
        # BotoCoreError is a transport fault, not a service verdict, so it
        # classifies as retryable below; the lookup runs before any delete, so
        # nothing was mutated and the retry converges.
        logger.error("Cognito lookup by sub failed", error=str(e), account_id=account_id)
        if is_transient_cognito_error(e):
            raise AppError(
                ErrorCode.RESOURCE_BUSY,
                "Failed to look up Cognito user. Retry the purge to complete the deletion.",
            ) from e
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to look up Cognito user") from e
    return None, None


def _delete_user_from_cognito(
    cognito: Any, user_pool_id: str, username: str, email: str, logger: Any, actor_sub: str = ""
) -> None:
    """Delete user from Cognito, treating UserNotFoundException as idempotent success.

    Failures propagate unchanged — the caller owns failure
    logging and typed-error mapping, so the real AWS error code survives to
    where the context (account, actor, partial state) is added.
    """
    masked_email = mask_email(email)
    try:
        cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
        logger.info(
            "Deleted user from Cognito",
            username=mask_email(username),
            email=masked_email,
            actor_sub=actor_sub,
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "UserNotFoundException":
            logger.info(
                "Cognito user already deleted",
                username=mask_email(username),
                email=masked_email,
                actor_sub=actor_sub,
            )
            return
        raise


def _delete_cognito_user_after_sweep(
    cognito: Any,
    user_pool_id: str,
    username: str | None,
    email: str,
    account_id: str,
    actor_sub: str,
    logger: Any,
) -> None:
    """Delete the Cognito user after the data sweep, or note it is already absent.

    Failure handling is not here: ``run_deletion_steps`` owns the
    partial-state report for both deletion paths, logging once with the
    caller's ``log_context`` (actor attribution included) before raising the
    typed error whose code matches the retry guidance in its message.
    """
    if username:
        _delete_user_from_cognito(cognito, user_pool_id, username, email, logger, actor_sub)
    else:
        logger.info("Cognito user already absent", account_id=account_id, actor_sub=actor_sub)


def _sweep_purge_residue(profiles_for_sweep: list[Dict[str, Any]], account_id: str, logger: Any) -> None:
    """Sweep the four residue classes the browser cannot reach itself (#521)."""
    delete_invites_for_owned_profiles(profiles_for_sweep, logger)
    delete_inbound_shares(account_id, logger)
    delete_user_s3_reports(profiles_for_sweep, logger)
    delete_all_user_qr_codes(account_id, logger)


def _account_exists_in_dynamodb(account_id: str, logger: Any, actor_sub: str = "") -> bool:
    """Check whether an account record exists in DynamoDB."""
    db_account_id = ensure_account_id(account_id)
    try:
        response = tables.accounts.get_item(Key={"accountId": db_account_id}, ProjectionExpression="accountId")
        exists = "Item" in response
        if not exists:
            logger.info("Account not found in DynamoDB", account_id=db_account_id, actor_sub=actor_sub)
        return exists
    except ClientError as e:
        logger.error("Failed to check account existence in DynamoDB", error=str(e), account_id=db_account_id)
        raise


def _check_not_self_deletion(caller_id: str, account_id: str) -> None:
    """Prevent admin from deleting their own account.

    Normalize both IDs to their canonical ACCOUNT# form before comparing so a
    caller passing ``ACCOUNT#<own-sub>`` cannot bypass the guard (#125).
    """
    if ensure_account_id(account_id) == ensure_account_id(caller_id):
        raise AppError(ErrorCode.INVALID_INPUT, "Cannot delete your own account")


@with_error_handling(error_message="Failed to purge user account")
def admin_purge_user_account(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete the account record and the Cognito user (admin only).

    AppSync Lambda resolver for the adminPurgeUserAccount mutation. This is the
    deliberately minimal server-side operation that user deletion cannot be
    completed without (#521): the browser holds no AWS credentials, so it can
    neither delete the ``accounts`` table row nor call Cognito
    ``AdminDeleteUser``. Everything else a browser CAN delete (orders,
    campaigns, shares, profiles) is deleted by the client through the
    per-entity ``adminDeleteUser*`` mutations, and catalogs are never deleted.

    The caller supplies the profile IDs it read via ``adminGetUserProfiles``
    BEFORE deleting the profile rows, as the ``profileIds`` argument. The purge
    first verifies each of them is actually gone with a strongly consistent
    read — a surviving profile means the client cascade has not completed, so
    it refuses with CONFLICT and deletes nothing — then sweeps the four
    classes the browser cannot reach, reusing the shared deletion_cascade
    helpers: invites for the account's profiles, inbound shares on other
    owners' profiles, S3 report objects, and payment-QR S3 objects. Invites
    and reports are keyed by profileId, which survives the deleted profile
    rows.

    Call this after the client's per-entity deletes, so a failure there leaves
    the account intact rather than half-deleted.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        True if the account was purged successfully

    Raises:
        AppError: If not admin, self-purge is attempted, the user does not
            exist, a supplied profile still exists (CONFLICT), or a deletion
            error occurs. An absent Cognito user is treated as idempotent
            success. When the sweep succeeded but the Cognito delete failed,
            the error names the partial state so the operator knows the
            account needs a retry to complete.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    profile_ids = _validate_profile_ids_argument(event.get("arguments", {}).get("profileIds"))

    # get_caller_id reads the raw `identity.sub` (no normalization), so this
    # guard's decision is unchanged from the inline read it replaced; it only
    # hardens a malformed event to None instead of raising (#660).
    caller_id = get_caller_id(event)
    _check_not_self_deletion(str(caller_id), account_id)

    user_pool_id = get_required_env("USER_POOL_ID")
    cognito = get_cognito_client()

    username, email = _find_cognito_user_by_sub(cognito, user_pool_id, account_id, logger)
    account_exists = _account_exists_in_dynamodb(account_id, logger, actor_sub)

    if not username and not account_exists:
        raise AppError(ErrorCode.NOT_FOUND, f"User not found: {account_id}")

    # The purge runs after the client's per-entity deletes (#521). It verifies
    # rather than trusts: while any supplied profile still exists the cascade
    # has not completed, so nothing is deleted and the account stays intact.
    _assert_profiles_deleted(account_id, profile_ids, logger, actor_sub)

    profiles_for_sweep = [{"profileId": profile_id} for profile_id in profile_ids]
    # The sweep runs before the Cognito delete and before the accounts row, so
    # a retry after any failure below converges. Both phases and their failure
    # classification live in the shared helper so the two deletion paths report
    # them identically; ``log_context`` carries the actor attribution every
    # admin audit line must have (#507).
    run_deletion_steps(
        sweep=lambda: _sweep_purge_residue(profiles_for_sweep, account_id, logger),
        delete_cognito=lambda: _delete_cognito_user_after_sweep(
            cognito, user_pool_id, username, email or "", account_id, actor_sub, logger
        ),
        logger=logger,
        log_context={"account_id": account_id, "actor_sub": actor_sub},
        sweep_log_message=(
            "Data sweep failed before the Cognito delete; the Cognito user and the accounts record are untouched"
        ),
        sweep_retry_message=(
            "Data sweep failed before the Cognito delete; the Cognito user and the "
            "accounts record are untouched. Retry the purge to complete the deletion."
        ),
        sweep_fatal_message=(
            "Data sweep failed before the Cognito delete; the Cognito user and the accounts record are untouched."
        ),
        partial_retry_message=(
            "Account data was swept but the Cognito user could not be confirmed deleted; "
            "the accounts record still exists. Retry the purge to complete the deletion."
        ),
        partial_fatal_message=(
            "Account data was swept but the Cognito user could not be confirmed deleted; "
            "the accounts record still exists and the Cognito user may also survive — "
            "complete the deletion manually."
        ),
    )

    if account_exists:
        db_account_id = ensure_account_id(account_id)
        try:
            tables.accounts.delete_item(Key={"accountId": db_account_id})
            logger.info("Deleted account record", account_id=db_account_id, actor_sub=actor_sub)
        except ClientError as e:
            logger.error("Failed to delete account record", error=str(e), account_id=db_account_id)
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete account record") from e
    else:
        logger.info("Account record already absent", account_id=account_id, actor_sub=actor_sub)

    logger.info("User account purged", account_id=account_id, email=mask_email(email), actor_sub=actor_sub)
    return True


def _validate_profile_ids_argument(profile_ids: Any) -> list[str]:
    """Validate the client-supplied profileIds list for the purge (#521).

    The schema requires ``[ID!]!``; this guards the Lambda entry point itself,
    which a caller can reach without going through GraphQL validation.
    """
    if not isinstance(profile_ids, list) or not all(
        isinstance(profile_id, str) and profile_id.strip() for profile_id in profile_ids
    ):
        raise AppError(ErrorCode.INVALID_INPUT, "profileIds must be a list of profile IDs")
    return [ensure_profile_id(profile_id.strip()) for profile_id in profile_ids]


def _assert_profiles_deleted(account_id: str, profile_ids: list[str], logger: Any, actor_sub: str = "") -> None:
    """Refuse the purge while any client-reported-deleted profile still exists (#521).

    The strongly consistent read is required because the profile rows were
    just deleted by a different writer (the client's cascade moments earlier).
    The import is function-level: a top-level import would be circular
    (`admin_operations` imports this module for its operation dispatcher map).
    """
    from .admin_operations import _raise_batch_lookup_error

    db_account_id = ensure_account_id(account_id)
    for raw_profile_id in profile_ids:
        profile_id = ensure_profile_id(raw_profile_id.strip() if isinstance(raw_profile_id, str) else raw_profile_id)
        try:
            response = tables.profiles.get_item(
                Key={"ownerAccountId": db_account_id, "profileId": profile_id},
                ConsistentRead=True,
            )
        except ClientError as e:
            _raise_batch_lookup_error("verify profile deletion", logger, e, profile_id=profile_id)
        if "Item" in response:
            logger.warning("Purge refused: profile still present", profile_id=profile_id, actor_sub=actor_sub)
            raise AppError(
                ErrorCode.CONFLICT,
                "The account's profiles must be deleted before the account can be purged",
            )
