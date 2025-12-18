"""
Profile sharing Lambda handlers.

Implements:
- createProfileInvite: Generate invite code for sharing profile
- redeemProfileInvite: Redeem invite code to gain access
- shareProfileDirect: Share profile directly with account (no invite)

NOTE: The following operation has been moved to AppSync resolvers:
- revokeShare: Now a VTL DynamoDB resolver (see cdk_stack.py)
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import boto3
from mypy_boto3_dynamodb.service_resource import Table

from ..utils.auth import is_profile_owner
from ..utils.errors import AppError, ErrorCode
from ..utils.logging import StructuredLogger, get_correlation_id

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def get_profiles_table() -> Table:
    """Get DynamoDB profiles table instance (multi-table design)."""
    table_name = os.getenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
    return dynamodb.Table(table_name)


def generate_invite_code() -> str:
    """Generate random 10-character alphanumeric invite code."""
    return secrets.token_urlsafe(8)[:10].upper().replace("-", "X").replace("_", "Y")


def create_profile_invite(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create profile invite code.

    GraphQL mutation: createProfileInvite(profileId: ID!, permissions: [Permission!]!)

    Returns:
        {
          inviteCode: String!
          profileId: ID!
          expiresAt: AWSDateTime!
          permissions: [Permission!]!
        }
    """
    logger = StructuredLogger(__name__, get_correlation_id(event))

    try:
        # Extract arguments
        args = event["arguments"]
        profile_id = args["profileId"]
        permissions = args["permissions"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Creating profile invite",
            profile_id=profile_id,
            permissions=permissions,
            caller_account_id=caller_account_id,
        )

        # Authorization: Must be owner to create invites
        if not is_profile_owner(caller_account_id, profile_id):
            raise AppError(ErrorCode.FORBIDDEN, "Only profile owner can create invites")

        # Validate permissions
        valid_permissions = {"READ", "WRITE"}
        if not set(permissions).issubset(valid_permissions):
            raise AppError(
                ErrorCode.INVALID_INPUT, f"Invalid permissions. Must be one of: {valid_permissions}"
            )

        # Generate invite code
        invite_code = generate_invite_code()

        # Calculate expiration (14 days from now)
        expires_at = datetime.now(timezone.utc) + timedelta(days=14)

        # Store invite in DynamoDB (multi-table design: profiles table)
        table = get_profiles_table()
        invite_item = {
            "profileId": profile_id,  # PK
            "recordType": f"INVITE#{invite_code}",  # SK
            "inviteCode": invite_code,  # GSI: inviteCode-index
            "permissions": permissions,
            "createdBy": caller_account_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": expires_at.isoformat(),
            "used": False,
            "TTL": int(expires_at.timestamp()),  # Auto-delete after expiration
        }

        table.put_item(Item=invite_item)

        logger.info(
            "Profile invite created", invite_code=invite_code, expires_at=expires_at.isoformat()
        )

        return {
            "inviteCode": invite_code,
            "profileId": profile_id,
            "expiresAt": expires_at.isoformat(),
            "permissions": permissions,
        }

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to create profile invite", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create invite")


# NOTE: The following Lambda functions have been migrated to AppSync pipeline resolvers:
# - redeem_profile_invite: Now a pipeline resolver (LookupInviteFn → CreateShareFn → MarkInviteUsedFn)
# - share_profile_direct: Now a pipeline resolver (LookupAccountByEmailFn → CreateShareFn)
# - revoke_share: Now a VTL DynamoDB resolver
# This operation is now handled by a VTL DynamoDB resolver directly in AppSync
# See cdk/cdk/cdk_stack.py - RevokeShareResolver
