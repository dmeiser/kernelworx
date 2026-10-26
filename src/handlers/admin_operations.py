"""
Admin operations handlers for superadmin functionality.

Provides:
- adminResetUserPassword: Send password reset email to user

The adminListUsers / adminSearchUser handlers live in ``admin_user_operations``,
the adminPurgeUserAccount handler lives in ``admin_account_purge``, the
createManagedCatalog handler lives in ``admin_catalog_operations``, and the
per-entity adminDeleteUser* handlers live in ``admin_user_deletion`` (#773);
all four are imported below so the dispatcher map stays the single registry.

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

from typing import TYPE_CHECKING, Any, Dict, NoReturn

from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.auth import require_admin_mfa
    from utils.dynamodb import TRANSIENT_ERROR_CODES
    from utils.errors import AppError, ErrorCode
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.auth import require_admin_mfa
    from ..utils.dynamodb import TRANSIENT_ERROR_CODES
    from ..utils.errors import AppError, ErrorCode

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


# The account purge handler was extracted to its own module (#773) but stays
# registered on this Lambda. The import is safe at module load because
# `admin_account_purge` only imports from this module inside functions.
from .admin_account_purge import admin_purge_user_account

# The managed-catalog handler was extracted to its own module (#773) but stays
# registered on this Lambda. The import is safe at module load because
# `admin_catalog_operations` does not import from this module at all.
from .admin_catalog_operations import create_managed_catalog

# The password-reset handler was extracted to its own module (#773) but stays
# registered on this Lambda. The import is safe at module load because
# `admin_credential_reset` only imports from this module inside functions.
from .admin_credential_reset import admin_reset_user_password

# The profile-share and campaign shared-code handlers were extracted to their
# own module (#773) but stay registered on this Lambda. The import is safe at
# module load because `admin_share_campaign_ops` only imports from this module
# inside functions.
from .admin_share_campaign_ops import (
    admin_delete_share,
    admin_get_profile_shares,
    admin_update_campaign_shared_code,
)

# The per-entity user deletion handlers were extracted to their own module (#773)
# but stay registered on this Lambda. The import is safe at module load because
# `admin_user_deletion` only imports from this module inside functions.
from .admin_user_deletion import (
    admin_delete_user_campaigns,
    admin_delete_user_orders,
    admin_delete_user_profiles,
    admin_delete_user_shares,
)

# The user listing & search handlers were extracted to their own module (#773) but
# stay registered on this Lambda. The import is safe at module load because
# `admin_user_operations` only imports from this module inside functions.
from .admin_user_operations import admin_list_users, admin_search_user

# The account-scoped admin user read handlers were extracted to their own module
# (#773) but stay registered on this Lambda. The import is safe at module load
# because `admin_user_reads` only imports from this module inside functions.
from .admin_user_reads import (
    admin_get_user_campaigns,
    admin_get_user_catalogs,
    admin_get_user_profiles,
    admin_get_user_shared_campaigns,
)

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


# Operation dispatcher map
_OPERATION_HANDLERS = {
    "adminListUsers": admin_list_users,
    "adminSearchUser": admin_search_user,
    "adminResetUserPassword": admin_reset_user_password,
    "adminPurgeUserAccount": admin_purge_user_account,
    "adminDeleteUserOrders": admin_delete_user_orders,
    "adminDeleteUserCampaigns": admin_delete_user_campaigns,
    "adminDeleteUserShares": admin_delete_user_shares,
    "adminDeleteUserProfiles": admin_delete_user_profiles,
    "createManagedCatalog": create_managed_catalog,
    "adminGetUserProfiles": admin_get_user_profiles,
    "adminGetUserCatalogs": admin_get_user_catalogs,
    "adminGetUserCampaigns": admin_get_user_campaigns,
    "adminGetUserSharedCampaigns": admin_get_user_shared_campaigns,
    "adminGetProfileShares": admin_get_profile_shares,
    "adminDeleteShare": admin_delete_share,
    "adminUpdateCampaignSharedCode": admin_update_campaign_shared_code,
}


@with_error_handling(error_message="Failed to execute admin operation")
def lambda_handler(event: Dict[str, Any], context: Any) -> Any:
    """
    Main Lambda handler that dispatches to specific admin operations.

    Determines which operation to call based on the GraphQL field name.
    Wrapped in ``with_error_handling`` (#329) so dispatch-level errors also
    return the structured ``__isError`` payload instead of raising.

    Args:
        event: AppSync event
        context: Lambda context

    Returns:
        Result from the specific operation handler, or a structured error
        payload when the operation fails.
    """
    field_name = event.get("info", {}).get("fieldName", "")
    handler = _OPERATION_HANDLERS.get(field_name)

    if not handler:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown admin operation: {field_name}")

    return handler(event, context)
