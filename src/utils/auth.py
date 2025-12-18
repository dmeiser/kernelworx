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

# Initialize DynamoDB resource
dynamodb = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def get_profiles_table() -> "Table":
    """Get profiles DynamoDB table instance (multi-table design)."""
    table_name = os.getenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
    return dynamodb.Table(table_name)


def get_accounts_table() -> "Table":
    """Get accounts DynamoDB table instance (multi-table design)."""
    table_name = os.getenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    return dynamodb.Table(table_name)


def check_profile_access(
    caller_account_id: str, profile_id: str, required_permission: str = "READ"
) -> bool:
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
    # Normalize required_permission to uppercase for consistent comparison
    required_permission = required_permission.upper()

    table = get_profiles_table()

    # Get profile metadata (multi-table design: PK=profileId, SK=recordType)
    response = table.get_item(Key={"profileId": profile_id, "recordType": "METADATA"})

    if "Item" not in response:
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")

    profile = response["Item"]

    # Check if caller is owner
    # ownerAccountId in storage includes ACCOUNT# prefix
    stored_owner = profile.get("ownerAccountId", "")
    # Handle both with and without prefix for backward compatibility
    if stored_owner == caller_account_id or stored_owner == f"ACCOUNT#{caller_account_id}":
        return True

    # Check if caller has appropriate share (multi-table design)
    # Shares are stored with recordType=SHARE#ACCOUNT#{caller_account_id}
    share_key = f"SHARE#ACCOUNT#{caller_account_id}"
    share_response = table.get_item(Key={"profileId": profile_id, "recordType": share_key})

    if "Item" in share_response:
        share = share_response["Item"]
        permissions = share.get("permissions", [])

        # Type assertion: permissions is a list of strings
        if isinstance(permissions, list):
            # Normalize permissions to uppercase for case-insensitive comparison
            # Handle both native Python lists ["READ"] and raw DynamoDB format [{"S": "READ"}]
            normalized_permissions = []
            for perm in permissions:
                if isinstance(perm, str):
                    normalized_permissions.append(perm.upper())
                elif isinstance(perm, dict) and "S" in perm:
                    normalized_permissions.append(perm["S"].upper())

            # WRITE permission implicitly grants READ access
            if required_permission == "READ" and (
                "READ" in normalized_permissions or "WRITE" in normalized_permissions
            ):
                return True
            if required_permission == "WRITE" and "WRITE" in normalized_permissions:
                return True

    return False


def require_profile_access(
    caller_account_id: str, profile_id: str, required_permission: str = "READ"
) -> None:
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

    # Multi-table design: PK=profileId, SK=recordType
    response = table.get_item(Key={"profileId": profile_id, "recordType": "METADATA"})

    if "Item" not in response:
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")

    profile = response["Item"]
    return profile.get("ownerAccountId") == caller_account_id


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
