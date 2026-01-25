"""
Authorization utilities for checking profile and resource access.

Implements owner-based and share-based authorization model.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .ids import ensure_account_id, ensure_profile_id
from .logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def _is_profile_owner(profiles_table: "Table", caller_account_id: str, db_profile_id: str) -> bool:
    """Check if caller is the profile owner via direct lookup."""
    direct_response = profiles_table.get_item(
        Key={"ownerAccountId": f"ACCOUNT#{caller_account_id}", "profileId": db_profile_id}
    )
    return "Item" in direct_response


def _profile_exists(profiles_table: "Table", db_profile_id: str) -> bool:
    """Check if profile exists via GSI query."""
    response = profiles_table.query(
        IndexName="profileId-index",
        KeyConditionExpression="profileId = :profileId",
        ExpressionAttributeValues={":profileId": db_profile_id},
        Limit=1,
    )
    return bool(response.get("Items", []))


def _convert_permission_to_string(perm: Any) -> str | None:
    """Convert a permission item to string, handling dict or string formats."""
    if isinstance(perm, str):
        return str(perm.upper())
    if isinstance(perm, dict) and "S" in perm:
        return str(perm["S"].upper())
    return None


def _normalize_permissions(permissions: Any) -> list[str]:
    """Normalize permissions to uppercase list, handling various formats."""
    if not isinstance(permissions, (list, set)):
        return []
    result = []
    for perm in permissions:
        converted = _convert_permission_to_string(perm)
        if converted:
            result.append(converted)
    return result


def _has_required_permission(permissions: list[str], required_permission: str) -> bool:
    """Check if permissions list contains the required permission."""
    if required_permission == "READ":
        return "READ" in permissions or "WRITE" in permissions
    if required_permission == "WRITE":
        return "WRITE" in permissions
    return False


def _check_share_permissions(
    shares_table: "Table", db_profile_id: str, db_caller_id: str, required_permission: str
) -> bool:
    """Check if caller has required permission via share."""
    share_response = shares_table.get_item(Key={"profileId": db_profile_id, "targetAccountId": db_caller_id})
    if "Item" not in share_response:
        return False
    share = share_response["Item"]
    permissions = _normalize_permissions(share.get("permissions", []))
    return _has_required_permission(permissions, required_permission)


def check_profile_access(caller_account_id: str, profile_id: str, required_permission: str = "READ") -> bool:
    """
    Check if caller has access to profile.

    Args:
        caller_account_id: Cognito sub (Account ID) of the caller
        profile_id: Profile ID to check access for
        required_permission: "READ" or "WRITE" (case-insensitive)

    Returns:
        True if caller has access, False otherwise

    Raises:
        AppError: If profile not found
    """
    required_permission = required_permission.upper()
    db_profile_id = ensure_profile_id(profile_id)
    # ensure_profile_id returns Optional[str], but we know profile_id is not None here
    assert db_profile_id is not None

    # Check if caller is owner (faster, strongly consistent)
    if _is_profile_owner(tables.profiles, caller_account_id, db_profile_id):
        return True

    # Verify profile exists
    if not _profile_exists(tables.profiles, db_profile_id):
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")

    # Check share permissions
    db_caller_id = ensure_account_id(caller_account_id)
    # ensure_account_id returns Optional[str], but we know caller_account_id is not None here
    assert db_caller_id is not None
    return _check_share_permissions(tables.shares, db_profile_id, db_caller_id, required_permission)


def require_profile_access(caller_account_id: str, profile_id: str, required_permission: str = "READ") -> None:
    """
    Require caller to have profile access or raise FORBIDDEN error.

    Args:
        caller_account_id: Cognito sub (Account ID) of the caller
        profile_id: Profile ID to check access for
        required_permission: "READ" or "WRITE"

    Raises:
        AppError: If caller doesn't have required access
    """
    if not check_profile_access(caller_account_id, profile_id, required_permission):
        raise AppError(
            ErrorCode.FORBIDDEN,
            f"You do not have {required_permission} access to this profile",
        )


def is_profile_owner(caller_account_id: str, profile_id: str) -> bool:
    """
    Check if caller is the owner of a profile.

    Args:
        caller_account_id: Cognito sub (Account ID) of the caller
        profile_id: Profile ID to check

    Returns:
        True if caller is owner, False otherwise

    Raises:
        AppError: If profile not found
    """
    # Normalize profile_id to PROFILE# prefix for queries
    db_profile_id = ensure_profile_id(profile_id)
    assert db_profile_id is not None

    # Multi-table design V2: Query profileId-index GSI
    # Profile table structure: PK=ownerAccountId, SK=profileId, GSI=profileId-index
    response = tables.profiles.query(
        IndexName="profileId-index",
        KeyConditionExpression="profileId = :profileId",
        ExpressionAttributeValues={":profileId": db_profile_id},
        Limit=1,
    )

    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")

    profile = items[0]
    stored_owner = profile.get("ownerAccountId", "")
    # Handle both with and without prefix for backward compatibility
    return stored_owner == caller_account_id or stored_owner == f"ACCOUNT#{caller_account_id}"


def get_account(account_id: str) -> Optional[Dict[str, Any]]:
    """
    Get account by ID.

    Args:
        account_id: Cognito sub (Account ID)

    Returns:
        Account item or None if not found
    """
    # Multi-table design: accountId is the only key (format: ACCOUNT#uuid)
    response = tables.accounts.get_item(Key={"accountId": f"ACCOUNT#{account_id}"})

    return response.get("Item")


def is_admin(event: Dict[str, Any]) -> bool:
    """
    Check if caller has admin privileges from JWT cognito:groups claim.

    IMPORTANT: This checks the JWT token claim, NOT DynamoDB cache.
    The DynamoDB isAdmin field is updated by post-auth Lambda but is NOT
    the source of truth - always use JWT claims for authorization.

    Args:
        event: Lambda event with identity.claims from AppSync

    Returns:
        True if caller is in ADMIN Cognito group, False otherwise
    """
    try:
        claims = event.get("identity", {}).get("claims", {})
        groups = claims.get("cognito:groups", [])
        # cognito:groups can be a string or list in JWT
        if isinstance(groups, str):
            groups = [groups]
        return "ADMIN" in groups
    except Exception:
        return False
