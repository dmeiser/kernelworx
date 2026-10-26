"""
Admin operations handlers for superadmin functionality.

Provides:
- adminResetUserPassword: Send password reset email to user
- createManagedCatalog: Create an ADMIN_MANAGED global catalog

The adminListUsers / adminSearchUser handlers live in ``admin_user_operations``
and the adminPurgeUserAccount handler lives in ``admin_account_purge`` (#773);
both are imported below so the dispatcher map stays the single registry.

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

from botocore.exceptions import ClientError

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import (
    delete_user_campaigns,
    delete_user_orders,
    delete_user_profiles,
    delete_user_shares,
    get_user_profiles,
    normalize_account_id,
)

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.auth import require_admin_mfa
    from utils.boto import get_cognito_client
    from utils.cognito_filters import cognito_user_filter
    from utils.dynamodb import (
        TRANSIENT_ERROR_CODES,
        batch_get_chunked,
        get_required_env,
        tables,
    )
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger, mask_email
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.auth import require_admin_mfa
    from ..utils.boto import get_cognito_client
    from ..utils.cognito_filters import cognito_user_filter
    from ..utils.dynamodb import (
        TRANSIENT_ERROR_CODES,
        batch_get_chunked,
        get_required_env,
        tables,
    )
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


# The account purge handler was extracted to its own module (#773) but stays
# registered on this Lambda. The import is safe at module load because
# `admin_account_purge` only imports from this module inside functions.
from .admin_account_purge import admin_purge_user_account

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
    """Validate and process a catalog product, returning processed product dict.

    Price may arrive as a number or a numeric string (e.g. from AppSync JSON
    deserialization); it is converted to Decimal before validation and storage.
    Non-numeric or unparsable values raise INVALID_INPUT.
    """
    product_name = product.get("productName", "").strip()

    if not product_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Product name is required")

    processed_product: Dict[str, Any] = {
        "productId": f"PRODUCT#{uuid.uuid4()}",
        "productName": product_name,
        "price": _parse_product_price(product.get("price")),
        "sortOrder": product.get("sortOrder", 0),
    }

    description = product.get("description", "").strip()
    if description:
        processed_product["description"] = description

    return processed_product


def _validate_catalog_input(catalog_input: Dict[str, Any]) -> tuple[str, bool, list[Dict[str, Any]]]:
    """Validate catalog input and extract name, isPublic, products."""
    catalog_name = catalog_input.get("catalogName", "").strip()
    is_public = catalog_input.get("isPublic", True)
    products = catalog_input.get("products", [])

    if not catalog_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Catalog name is required")
    if not products:
        raise AppError(ErrorCode.INVALID_INPUT, "Products array cannot be empty")

    return catalog_name, is_public, products


def _build_catalog_item(
    catalog_id: str,
    catalog_name: str,
    is_public: bool,
    caller_id: str,
    processed_products: list[Dict[str, Any]],
    now: str,
) -> Dict[str, Any]:
    """Build the catalog item dictionary for DynamoDB."""
    return {
        "catalogId": catalog_id,
        "catalogName": catalog_name,
        "catalogType": "ADMIN_MANAGED",  # Key difference from regular createCatalog
        "ownerAccountId": f"ACCOUNT#{caller_id}",  # Track who created it
        "isPublic": is_public,
        "isPublicStr": "true" if is_public else "false",  # For GSI queries
        "products": processed_products,
        "createdAt": now,
        "updatedAt": now,
    }


def _persist_catalog(catalog_item: Dict[str, Any], logger: Any) -> None:
    """Persist catalog to DynamoDB."""
    try:
        tables.catalogs.put_item(Item=catalog_item)
    except ClientError as e:
        logger.error("Failed to create catalog", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create catalog")


def _require_admin_and_get_actor_sub(event: Dict[str, Any]) -> str:
    """Require admin + MFA and return the acting administrator's own ``sub`` (#507).

    The actor counterpart to `_require_admin_and_get_target_account_id`: this
    one returns the caller, whose sub is what the audit line must record.
    """
    require_admin_mfa(event)

    caller_id = get_caller_id(event)
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

    return str(caller_id)


@with_error_handling(error_message="Failed to create catalog")
def create_managed_catalog(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create an ADMIN_MANAGED catalog (admin only).

    AppSync Lambda resolver for createManagedCatalog mutation.
    Creates a global catalog that is available to all users.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        Created Catalog object

    Raises:
        AppError: If not admin, validation fails, or creation error
    """
    logger = get_logger(__name__)

    caller_id = _require_admin_and_get_actor_sub(event)

    arguments = event.get("arguments", {})
    catalog_input = arguments.get("input", {})

    catalog_name, is_public, products = _validate_catalog_input(catalog_input)

    catalog_id = f"CATALOG#{uuid.uuid4()}"
    now = datetime.now(timezone.utc).isoformat()

    processed_products = [_validate_and_process_product(product) for product in products]

    catalog_item = _build_catalog_item(catalog_id, catalog_name, is_public, caller_id, processed_products, now)

    _persist_catalog(catalog_item, logger)

    logger.info(
        "Created managed catalog",
        catalog_id=catalog_id,
        catalog_name=catalog_name,
        actor_sub=caller_id,
    )

    return catalog_item


def _user_profiles_for(account_id: str) -> list[Dict[str, Any]]:
    """Sweep the profiles table once for a per-domain admin deletion."""
    return get_user_profiles(normalize_account_id(account_id))


@with_error_handling(error_message="Failed to delete user orders")
def admin_delete_user_orders(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all orders for all campaigns of all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted order is gone
    from the orders table before returning success.

    Returns the count of deleted orders.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_orders(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user orders", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user campaigns")
def admin_delete_user_campaigns(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all campaigns for all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted campaign is gone
    from the campaigns table before returning success.

    Returns the count of deleted campaigns.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_campaigns(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user campaigns", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user shares")
def admin_delete_user_shares(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all shares for all profiles owned by a user (admin only).

    Returns the count of deleted shares.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_shares(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user shares", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user profiles")
def admin_delete_user_profiles(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all profiles owned by a user (admin only).

    Returns the count of deleted profiles.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_profiles(account_id, _user_profiles_for(account_id), logger)
    logger.info("Admin deleted user profiles", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to get user profiles")
def admin_get_user_profiles(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all profiles owned by a user (admin only).

    Returns the list of profiles with full details.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query profiles by ownerAccountId
    profiles = query_all_items(
        tables.profiles,
        {
            "KeyConditionExpression": "ownerAccountId = :owner",
            "ExpressionAttributeValues": {":owner": db_account_id},
        },
    )

    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles), actor_sub=actor_sub)
    return profiles


@with_error_handling(error_message="Failed to get user catalogs")
def admin_get_user_catalogs(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all catalogs owned by a user (admin only).

    Returns the list of catalogs with full details.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query catalogs by ownerAccountId using GSI
    catalogs = query_all_items(
        tables.catalogs,
        {
            "IndexName": "ownerAccountId-index",
            "KeyConditionExpression": "ownerAccountId = :owner",
            "FilterExpression": "attribute_not_exists(isDeleted) OR isDeleted = :false",
            "ExpressionAttributeValues": {
                ":owner": db_account_id,
                ":false": False,
            },
        },
    )

    logger.info("Retrieved user catalogs", account_id=account_id, count=len(catalogs), actor_sub=actor_sub)
    return catalogs


def _extract_unique_catalog_ids(campaigns: list[Dict[str, Any]]) -> list[str]:
    """Extract the de-duplicated catalogIds from a campaign array, preserving first-seen order."""
    catalog_ids: list[str] = []
    seen: set[str] = set()
    for campaign in campaigns:
        catalog_id = campaign.get("catalogId")
        if catalog_id and catalog_id not in seen:
            seen.add(catalog_id)
            catalog_ids.append(catalog_id)
    return catalog_ids


def _batch_get_catalog_items(
    catalog_ids: list[str], catalogs_table_name: str, logger: Any
) -> Dict[str, Dict[str, Any]]:
    """Batch-get the catalogs by id; the shared helper owns the 100-key chunking.

    Raises AppError if keys stay unprocessed after the retries (#557).
    """
    catalog_map: Dict[str, Dict[str, Any]] = {}

    def _store_catalog(item: Dict[str, Any]) -> None:
        catalog_map[item["catalogId"]] = item

    batch_get_chunked(
        catalogs_table_name,
        [{"catalogId": catalog_id} for catalog_id in catalog_ids],
        _store_catalog,
        consistent_read=False,
        logger=logger,
    )
    return catalog_map


def _campaign_catalog_value(catalog: Dict[str, Any] | None, treat_deleted_as_null: bool) -> Dict[str, Any] | None:
    """Map a fetched catalog to its Campaign/SharedCampaign catalog contract value."""
    if catalog is not None and treat_deleted_as_null and catalog.get("isDeleted") is True:
        return None
    return catalog


def _attach_campaign_catalogs(
    campaigns: list[Dict[str, Any]], catalog_map: Dict[str, Dict[str, Any]], treat_deleted_as_null: bool
) -> None:
    """Attach each campaign's fetched catalog, mapping missing/soft-deleted per contract."""
    for campaign in campaigns:
        catalog_id = campaign.get("catalogId")
        if not catalog_id:
            continue
        campaign["catalog"] = _campaign_catalog_value(catalog_map.get(catalog_id), treat_deleted_as_null)


def _batch_get_campaign_catalogs(campaigns: list[Dict[str, Any]], treat_deleted_as_null: bool, logger: Any) -> None:
    """Batch-fetch the catalogs referenced by campaigns and attach each as `catalog`.

    Mirrors the #332 list-query pipeline batching (batch_get_catalogs_fn.js /
    batch_get_shared_campaign_catalogs_fn.js) inside the admin Lambda, which
    can chunk and loop where AppSync pipeline functions cannot. AppSync always
    executes the attached Campaign.catalog / SharedCampaign.catalog field
    resolver; since check_source_catalog_fn.js short-circuits when the source
    already carries `catalog`, attaching it here replaces the per-item GetItem
    (N+1) the admin campaign lists previously paid.

    Deleted-catalog contract matches the field resolvers: Campaign.catalog
    returns the raw item including soft-deleted catalogs (treat_deleted_as_null
    = False); SharedCampaign.catalog maps soft-deleted or missing catalogs to
    None (treat_deleted_as_null = True).
    """
    catalog_ids = _extract_unique_catalog_ids(campaigns)
    if not catalog_ids:
        return

    catalogs_table_name = get_required_env("CATALOGS_TABLE_NAME")
    # batch_get_chunked already translates every lookup failure (retryable
    # RESOURCE_BUSY on a throttle, INTERNAL_ERROR otherwise), so the typed
    # AppError propagates unchanged (#557).
    catalog_map = _batch_get_catalog_items(catalog_ids, catalogs_table_name, logger)

    _attach_campaign_catalogs(campaigns, catalog_map, treat_deleted_as_null)


def _get_campaigns_for_profiles(profiles: list[Dict[str, Any]], logger: Any, actor_sub: str) -> list[Dict[str, Any]]:
    """Query campaigns for each profile."""
    all_campaigns = []
    for profile in profiles:
        profile_id = profile.get("profileId")
        if profile_id:
            campaigns = query_all_items(
                tables.campaigns,
                {
                    "KeyConditionExpression": "profileId = :pid",
                    "ExpressionAttributeValues": {":pid": profile_id},
                },
            )
            all_campaigns.extend(campaigns)
            logger.info(
                "Retrieved campaigns for profile",
                profile_id=profile_id,
                count=len(campaigns),
                actor_sub=actor_sub,
            )
    return all_campaigns


@with_error_handling(error_message="Failed to get user campaigns")
def admin_get_user_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all campaigns for a user's profiles.

    Admin-only operation. Returns all campaigns across all profiles owned by the account.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # First, get all profiles owned by this account
    profiles = get_user_profiles(db_account_id)
    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles), actor_sub=actor_sub)

    # Now query campaigns for each profile
    all_campaigns = _get_campaigns_for_profiles(profiles, logger, actor_sub)
    # Pre-resolve catalogs in one chunked BatchGetItem so the Campaign.catalog
    # field resolver short-circuits instead of doing per-item GetItem reads (#332).
    _batch_get_campaign_catalogs(all_campaigns, treat_deleted_as_null=False, logger=logger)
    logger.info("Retrieved user campaigns", account_id=account_id, count=len(all_campaigns), actor_sub=actor_sub)
    return all_campaigns


@with_error_handling(error_message="Failed to get user shared campaigns")
def admin_get_user_shared_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shared campaigns created by a user.

    Admin-only operation.
    """
    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query shared campaigns by createdBy using GSI1
    campaigns = query_all_items(
        tables.shared_campaigns,
        {
            "IndexName": "GSI1",
            "KeyConditionExpression": "createdBy = :creator",
            "ExpressionAttributeValues": {
                ":creator": db_account_id,
            },
        },
    )

    # Pre-resolve catalogs in one chunked BatchGetItem so the SharedCampaign.catalog
    # field resolver short-circuits instead of doing per-item GetItem reads (#332).
    _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=True, logger=logger)

    logger.info(
        "Retrieved user shared campaigns",
        account_id=account_id,
        count=len(campaigns),
        actor_sub=actor_sub,
    )
    return campaigns


def _convert_permissions_to_lists(shares: list[Dict[str, Any]]) -> None:
    """Convert DynamoDB permission sets to lists for JSON serialization."""
    for share in shares:
        if "permissions" in share and isinstance(share["permissions"], set):
            share["permissions"] = list(share["permissions"])


def _query_profile_shares(db_profile_id: str) -> list[Dict[str, Any]]:
    """Query all shares for a profile."""
    return query_all_items(
        tables.shares,
        {
            "KeyConditionExpression": "profileId = :pid",
            "ExpressionAttributeValues": {":pid": db_profile_id},
        },
    )


def _require_admin_and_get_target_profile_id(event: Dict[str, Any]) -> tuple[str, str]:
    """Require admin + MFA, returning ``(db_profile_id, actor_sub)`` (#507).

    ``db_profile_id`` is the target profile named by the request; ``actor_sub``
    is the calling administrator, returned alongside so the audit line can
    attribute the operation.
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()

    if not profile_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID is required")

    # Add PROFILE# prefix if not present
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"
    return db_profile_id, actor_sub


@with_error_handling(error_message="Failed to get profile shares")
def admin_get_profile_shares(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shares for a specific profile.

    Admin-only operation. Returns all users who have access to this profile.
    """
    logger = get_logger(__name__)

    db_profile_id, actor_sub = _require_admin_and_get_target_profile_id(event)

    # Query shares and convert sets to lists
    shares = _query_profile_shares(db_profile_id)
    _convert_permissions_to_lists(shares)

    logger.info("Retrieved profile shares", profile_id=db_profile_id, count=len(shares), actor_sub=actor_sub)
    return shares


def _normalize_profile_and_account_ids(profile_id: str, target_account_id: str) -> tuple[str, str]:
    """Normalize profile ID and target account ID with prefixes."""
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"
    db_target_id = target_account_id if target_account_id.startswith("ACCOUNT#") else f"ACCOUNT#{target_account_id}"
    return db_profile_id, db_target_id


def _require_admin_and_get_share_ids(event: Dict[str, Any]) -> tuple[str, str, str]:
    """Require admin + MFA, returning ``(profile_id, target_account_id, actor_sub)`` (#507).

    The first two are the share the request names; the third is the calling
    administrator, carried so the revocation can be attributed.
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()
    target_account_id = arguments.get("targetAccountId", "").strip()

    if not profile_id or not target_account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID and target account ID are required")

    return profile_id, target_account_id, actor_sub


@with_error_handling(error_message="Failed to delete share")
def admin_delete_share(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete a specific share (revoke access).

    Admin-only operation. Allows admin to remove someone's access to a profile.
    """
    logger = get_logger(__name__)

    profile_id, target_account_id, actor_sub = _require_admin_and_get_share_ids(event)
    db_profile_id, db_target_id = _normalize_profile_and_account_ids(profile_id, target_account_id)

    tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_target_id})

    logger.info(
        "Deleted share",
        profile_id=profile_id,
        target_account_id=target_account_id,
        actor_sub=actor_sub,
    )
    return True


def _get_campaign_profile_id(db_campaign_id: str, campaign_id: str) -> str:
    """Get profile ID for a campaign via GSI lookup."""
    response = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": db_campaign_id},
    )

    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, f"Campaign not found: {campaign_id}")

    return str(items[0]["profileId"])


def _update_campaign_shared_code(
    profile_id: str, db_campaign_id: str, shared_campaign_code: Optional[str]
) -> Dict[str, Any]:
    """Update campaign's sharedCampaignCode field and return the stored item."""
    updated_at = datetime.now(timezone.utc).isoformat()

    if shared_campaign_code is None:
        update_expr = "REMOVE sharedCampaignCode SET updatedAt = :updated"
        expr_vals = {":updated": updated_at}
    else:
        update_expr = "SET sharedCampaignCode = :code, updatedAt = :updated"
        expr_vals = {":code": shared_campaign_code, ":updated": updated_at}

    response = tables.campaigns.update_item(
        Key={"profileId": profile_id, "campaignId": db_campaign_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_vals,
        ReturnValues="ALL_NEW",
    )

    return cast(Dict[str, Any], response.get("Attributes", {}))


def _require_admin_and_get_target_campaign_id(event: Dict[str, Any]) -> tuple[str, Optional[str], str]:
    """Require admin + MFA, returning ``(campaign_id, shared_campaign_code, actor_sub)`` (#507).

    ``campaign_id`` is the target campaign named by the request; ``actor_sub``
    is the calling administrator, carried so the update can be attributed.
    """
    require_admin_mfa(event)
    actor_sub = _actor_sub(event)

    arguments = event.get("arguments", {})
    campaign_id = arguments.get("campaignId", "").strip()
    shared_campaign_code = arguments.get("sharedCampaignCode")

    if not campaign_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Campaign ID is required")

    return campaign_id, shared_campaign_code, actor_sub


@with_error_handling(error_message="Failed to update campaign shared code")
def admin_update_campaign_shared_code(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update a campaign's sharedCampaignCode field and return the stored campaign item.

    Admin-only operation. Allows associating a campaign with a shared campaign.
    """
    logger = get_logger(__name__)

    campaign_id, shared_campaign_code, actor_sub = _require_admin_and_get_target_campaign_id(event)

    # Add CAMPAIGN# prefix if not present
    db_campaign_id = campaign_id if campaign_id.startswith("CAMPAIGN#") else f"CAMPAIGN#{campaign_id}"

    # Get campaign profile, update shared code, and return the stored item
    profile_id = _get_campaign_profile_id(db_campaign_id, campaign_id)
    updated_campaign = _update_campaign_shared_code(profile_id, db_campaign_id, shared_campaign_code)

    logger.info(
        "Updated campaign shared code",
        campaign_id=campaign_id,
        shared_campaign_code=shared_campaign_code,
        actor_sub=actor_sub,
    )
    return updated_campaign


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
