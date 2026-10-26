"""
Shared helpers for the admin-operations handlers.

The #773 split moved every admin operation handler out of this module into
its own module; what remains here is what those modules import from it — the
admin auth/audit helpers and the throttling/batch-lookup-error classifiers —
plus the dispatcher re-export. ``admin_dispatcher`` owns the operation map
and ``lambda_handler``; this module re-exports it so the Terraform-wired
Lambda entry point (``handlers.admin_operations.lambda_handler``) is
unchanged.

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

from typing import Any, Dict, NoReturn

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

# The dispatcher was extracted to ``admin_dispatcher`` (#773). The Lambda
# entry point stays ``handlers.admin_operations.lambda_handler`` (wired in
# ``tofu/application/modules/lambda/main.tf``), so it is re-exported here.
from .admin_dispatcher import lambda_handler  # noqa: F401

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
