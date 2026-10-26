"""
Admin operations handlers for superadmin functionality.

Provides:
- adminResetUserPassword: Send password reset email to user
- adminPurgeUserAccount: Sweep the client-unreachable residue, then delete the
  accounts record and the Cognito user
- createManagedCatalog: Create an ADMIN_MANAGED global catalog

The adminListUsers / adminSearchUser handlers live in ``admin_user_operations``
(#773) and are imported below so the dispatcher map stays the single registry.

User deletion is client-side by decision (#521). The client issues the
per-entity ``adminDeleteUser*`` mutations it can reach, reads the profile IDs
with ``adminGetUserProfiles`` before deleting the profile rows, and calls
``adminPurgeUserAccount`` with them as ``profileIds``. The purge sweeps the
four classes the browser cannot reach itself — invites for the account's
profiles, inbound shares on other owners' profiles, S3 report objects, and
payment-QR S3 objects — reusing the shared ``deletion_cascade`` helpers, then
deletes the ``accounts`` record and the Cognito user. Catalogs are never
deleted.

Audit attribution (#507): AppSync logs at ERROR level only, so these handlers
are the only record that an admin operation happened at all. Every admin audit
line therefore carries the acting administrator's ``sub`` as ``actor_sub``, and
the ``_require_admin_and_get_*`` helpers return the actor alongside the target
so it cannot be silently dropped: the target is the account, profile, or
campaign the request names, the actor is the caller, and they are different
principals.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Dict, NoReturn, Optional, cast

from botocore.exceptions import BotoCoreError, ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import (
    delete_inbound_shares,
    delete_invites_for_owned_profiles,
    delete_user_campaigns,
    delete_user_orders,
    delete_user_profiles,
    delete_user_s3_reports,
    delete_user_shares,
    get_user_profiles,
    normalize_account_id,
    run_deletion_steps,
)

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.auth import require_admin_mfa
    from utils.boto import get_cognito_client
    from utils.cognito import is_transient_cognito_error
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import (
        TRANSIENT_ERROR_CODES,
        batch_get_chunked,
        get_required_env,
        tables,
    )
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger, mask_email
    from utils.payment_methods import delete_all_user_qr_codes
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.auth import require_admin_mfa
    from ..utils.boto import get_cognito_client
    from ..utils.cognito import is_transient_cognito_error
    from ..utils.cognito_filters import cognito_user_filter
    from ..utils.dynamodb import (
        TRANSIENT_ERROR_CODES,
        batch_get_chunked,
        get_required_env,
        tables,
    )
    from ..utils.errors import AppError, ErrorCode
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


# The user listing & search handlers were extracted to their own module (#773) but
# stay registered on this Lambda. The import is safe at module load because
# `admin_user_operations` only imports from this module inside functions.
from .admin_user_operations import admin_list_users, admin_search_user

# Handle both Lambda (absolute) and unit test (relative) imports.  mypy sees the
# relative path it can resolve; the runtime fallback tries absolute first for Lambda.
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.pagination import query_all_items
else:  # pragma: no cover
    try:
        from utils.pagination import query_all_items
    except ModuleNotFoundError:
        from ..utils.pagination import query_all_items


# DynamoDB/Cognito throttling codes: the lookup is retryable, so surface a
# RESOURCE_BUSY error instead of silently incomplete admin data (#291, #456).
# This is the canonical transient/permanent split for these lookups: sibling
# handlers import it (see _raise_gather_failures, used by #556) rather than
# redeclaring their own copy. Only redeclare a local set when the caller's AWS
# surface genuinely differs (e.g. the DynamoDB BatchGetItem throttle code).
# The set itself is owned by utils.dynamodb and shared with the
# ownership-transfer share repair (#549), so the rule has one home.
_THROTTLING_ERROR_CODES = TRANSIENT_ERROR_CODES


def _throttling_error_code(error: BaseException) -> str:
    """Return the AWS error code of a ClientError, or "" for anything else.

    The single place the transient/permanent decision is read: a non-ClientError
    and a ClientError with an unrecognized code both return a value outside
    `_THROTTLING_ERROR_CODES`, i.e. permanent.
    """
    if not isinstance(error, ClientError):
        return ""
    return error.response.get("Error", {}).get("Code", "")


def _raise_batch_lookup_error(
    operation: str,
    logger: Any,
    error: BaseException,
    *,
    throttling_codes: frozenset[str] = _THROTTLING_ERROR_CODES,
    busy_message: str = "Temporarily unable to load data. Please retry.",
    **context: Any,
) -> NoReturn:
    """Translate a failed batch lookup into a typed AppError (#291).

    Throttling conditions become a retryable RESOURCE_BUSY so the admin UI can
    show a retry prompt; any other ClientError or unexpected exception becomes
    an INTERNAL_ERROR after an error-level log. Never returns: always raises.

    `throttling_codes` and `busy_message` let a caller reuse the classification
    with a service-specific code set or user-facing wording.
    """
    if isinstance(error, ClientError):
        error_code = _throttling_error_code(error)
        if error_code in throttling_codes:
            logger.warning(f"{operation} throttled", error=str(error), error_code=error_code, **context)
            raise AppError(ErrorCode.RESOURCE_BUSY, busy_message) from error
        logger.error(f"{operation} failed", error=str(error), error_code=error_code, **context)
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to {operation}") from error
    logger.error(f"{operation} failed unexpectedly", error=str(error), **context)
    raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to {operation}") from error


def _raise_gather_failures(
    operation: str,
    logger: Any,
    failures: list[BaseException],
    *,
    throttling_codes: frozenset[str] = _THROTTLING_ERROR_CODES,
    busy_message: str = "Temporarily unable to load data. Please retry.",
    **context: Any,
) -> NoReturn:
    """Refuse a partial answer when a parallel gather collected any failure.

    For N per-item lookups run concurrently, where returning the survivors would
    be an authoritative-looking but incomplete answer (#556). A single transient
    failure keeps the whole request retryable; otherwise the first failure is
    reported as permanent. Never returns: always raises.
    """
    for failure in failures:
        if _throttling_error_code(failure) in throttling_codes:
            _raise_batch_lookup_error(
                operation, logger, failure, throttling_codes=throttling_codes, busy_message=busy_message, **context
            )
    _raise_batch_lookup_error(
        operation, logger, failures[0], throttling_codes=throttling_codes, busy_message=busy_message, **context
    )


def _actor_sub(event: Dict[str, Any]) -> str:
    """Return the acting administrator's Cognito ``sub`` for audit logging (#507).

    Read only after ``require_admin_mfa`` has approved the caller, so resolving
    the actor can never change an authorization decision. A missing ``sub``
    yields an empty string rather than raising, so auditing can never turn a
    permitted operation into a failure.

    The read goes through ``get_caller_id`` like every other caller read
    (#660); it returns the raw ``identity.sub``, so this stays audit-only and
    cannot influence an authorization decision.
    """
    sub = get_caller_id(event)
    return str(sub) if sub else ""


def _require_admin_and_get_target_account_id(event: Dict[str, Any]) -> tuple[str, str]:
    """Require admin + MFA, returning ``(target_account_id, actor_sub)`` (#507).

    The two values are returned together so the actor travels with the target:
    every admin audit line downstream records both, which is what makes an
    administrative action attributable after the fact. ``target_account_id`` is
    the account named by the request — usually somebody else — and ``actor_sub``
    is the calling administrator's own Cognito ``sub``. They are distinct
    principals and must not be conflated (the historical helper name invited
    exactly that reading).
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    account_id = str(arguments.get("accountId", "")).strip()

    if not account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

    return account_id, actor_sub


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
    db_account_id = normalize_account_id(account_id)
    try:
        response = tables.accounts.get_item(Key={"accountId": db_account_id}, ProjectionExpression="accountId")
        exists = "Item" in response
        if not exists:
            logger.info("Account not found in DynamoDB", account_id=db_account_id, actor_sub=actor_sub)
        return exists
    except ClientError as e:
        logger.error("Failed to check account existence in DynamoDB", error=str(e), account_id=db_account_id)
        raise


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


def _check_not_self_deletion(caller_id: str, account_id: str) -> None:
    """Prevent admin from deleting their own account.

    Normalize both IDs to their canonical ACCOUNT# form before comparing so a
    caller passing ``ACCOUNT#<own-sub>`` cannot bypass the guard (#125).
    """
    if normalize_account_id(account_id) == normalize_account_id(caller_id):
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
        db_account_id = normalize_account_id(account_id)
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
    return profile_ids


def _assert_profiles_deleted(account_id: str, profile_ids: list[str], logger: Any, actor_sub: str = "") -> None:
    """Refuse the purge while any client-reported-deleted profile still exists (#521).

    The strongly consistent read is required because the profile rows were
    just deleted by a different writer (the client's cascade moments earlier).
    """
    db_account_id = normalize_account_id(account_id)
    for profile_id in profile_ids:
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


def _parse_product_price(price: Any) -> Decimal:
    """Convert a product price (number or numeric string) to a validated Decimal.

    A missing price, a non-numeric/unparsable value, a non-finite value
    (Infinity/inf/NaN), or a negative price raises INVALID_INPUT.
    """
    if price is None:
        raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")

    try:
        price_decimal = Decimal(str(price))
    except InvalidOperation, ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, "Product price must be a valid number")

    if not price_decimal.is_finite():
        raise AppError(ErrorCode.INVALID_INPUT, "Product price must be a valid number")

    if price_decimal < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")
    return price_decimal


def _validate_and_process_product(product: Dict[str, Any]) -> Dict[str, Any]:
