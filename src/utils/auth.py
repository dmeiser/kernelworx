"""
Authorization utilities for checking profile and resource access.

Implements owner-based and share-based authorization model.
"""

import os
from typing import TYPE_CHECKING, Any, Dict, Optional

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from .errors import AppError, ErrorCode
from .logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def _get_dynamodb():
    """Return a fresh boto3 DynamoDB resource (lazy for tests)."""
    return boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def get_profiles_table() -> "Table":
    """Get profiles DynamoDB table instance (multi-table design V2)."""
    table_name = os.getenv("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
    return _get_dynamodb().Table(table_name)


def get_shares_table() -> "Table":
    """Get shares DynamoDB table instance (new separate table)."""
    table_name = os.getenv("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")
    return _get_dynamodb().Table(table_name)


def get_accounts_table() -> "Table":
    """Get accounts DynamoDB table instance (multi-table design)."""
    table_name = os.getenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    return _get_dynamodb().Table(table_name)


def _normalize_profile_id(profile_id: str) -> str:
    """Normalize profileId with PROFILE# prefix for DynamoDB queries."""
    return profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"


def _normalize_account_id(account_id: str) -> str:
    """Normalize account ID with ACCOUNT# prefix for DynamoDB queries."""
    return account_id if account_id.startswith("ACCOUNT#") else f"ACCOUNT#{account_id}"


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


def _normalize_permissions(permissions: Any) -> list[str]:
    """Normalize permissions to uppercase list, handling various formats."""
    if not isinstance(permissions, (list, set)):
        return []
    result = []
    for perm in permissions:
        if isinstance(perm, str):
            result.append(perm.upper())
        elif isinstance(perm, dict) and "S" in perm:
            result.append(perm["S"].upper())
    return result


def _check_share_permissions(
    shares_table: "Table", db_profile_id: str, db_caller_id: str, required_permission: str
) -> bool:
    """Check if caller has required permission via share."""
    share_response = shares_table.get_item(Key={"profileId": db_profile_id, "targetAccountId": db_caller_id})
    if "Item" not in share_response:
        return False
    share = share_response["Item"]
    permissions = _normalize_permissions(share.get("permissions", []))
    if required_permission == "READ" and ("READ" in permissions or "WRITE" in permissions):
        return True
    if required_permission == "WRITE" and "WRITE" in permissions:
        return True
    return False


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
    profiles_table = get_profiles_table()
    db_profile_id = _normalize_profile_id(profile_id)

    # Check if caller is owner (faster, strongly consistent)
    if _is_profile_owner(profiles_table, caller_account_id, db_profile_id):
        return True

    # Verify profile exists
    if not _profile_exists(profiles_table, db_profile_id):
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")

    # Check share permissions
    db_caller_id = _normalize_account_id(caller_account_id)
    return _check_share_permissions(get_shares_table(), db_profile_id, db_caller_id, required_permission)


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
    table = get_profiles_table()

    # Normalize profile_id to PROFILE# prefix for queries
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"

    # Multi-table design V2: Query profileId-index GSI
    # Profile table structure: PK=ownerAccountId, SK=profileId, GSI=profileId-index
    response = table.query(
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
    table = get_accounts_table()

    # Multi-table design: accountId is the only key (format: ACCOUNT#uuid)
    response = table.get_item(Key={"accountId": f"ACCOUNT#{account_id}"})

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
