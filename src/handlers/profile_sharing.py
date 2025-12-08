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


def get_table() -> Table:
    """Get DynamoDB table instance."""
    table_name = os.getenv("TABLE_NAME", "PsmApp")
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

        # Store invite in DynamoDB
        table = get_table()
        invite_item = {
            "PK": profile_id,
            "SK": f"INVITE#{invite_code}",
            "inviteCode": invite_code,
            "profileId": profile_id,
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


def redeem_profile_invite(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Redeem profile invite code to gain access.

    GraphQL mutation: redeemProfileInvite(inviteCode: String!)

    Returns:
        {
          share: Share!
        }
    """
    logger = StructuredLogger(__name__, get_correlation_id(event))

    try:
        # Extract arguments
        args = event["arguments"]
        invite_code = args["inviteCode"].upper().strip()
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Redeeming profile invite", invite_code=invite_code, caller_account_id=caller_account_id
        )

        table = get_table()

        # Find invite (scan GSI or all invites - for now, we'll query known patterns)
        # In production, use GSI for inviteCode lookup
        # For now, assume we get profileId from a separate index

        # Query all active invites (simplified - needs GSI in production)
        # This is a placeholder - real implementation needs GSI
        response = table.scan(
            FilterExpression="begins_with(SK, :sk) AND inviteCode = :code",
            ExpressionAttributeValues={
                ":sk": "INVITE#",
                ":code": invite_code,
            },
        )

        if not response.get("Items"):
            raise AppError(ErrorCode.NOT_FOUND, "Invalid or expired invite code")

        invite = response["Items"][0]

        # Check if already used (check before expiration)
        if invite.get("used"):
            raise AppError(ErrorCode.INVITE_ALREADY_USED, "This invite code has already been used")

        # Check expiration
        expires_at_str = str(invite["expiresAt"])
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            raise AppError(ErrorCode.INVITE_EXPIRED, "This invite code has expired")

        profile_id = invite["profileId"]
        permissions = invite["permissions"]

        # Create share
        share_id = f"SHARE#{caller_account_id}"
        share_item = {
            "PK": profile_id,
            "SK": share_id,
            "profileId": profile_id,
            "accountId": caller_account_id,
            "permissions": permissions,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": invite["createdBy"],
            "inviteCode": invite_code,
            # GSI1 for "My Shared Profiles" view
            "GSI1PK": f"ACCOUNT#{caller_account_id}",
            "GSI1SK": profile_id,
        }

        # Mark invite as used
        table.update_item(
            Key={"PK": invite["PK"], "SK": invite["SK"]},
            UpdateExpression="SET #used = :true, usedBy = :account_id, usedAt = :used_at",
            ExpressionAttributeNames={"#used": "used"},
            ExpressionAttributeValues={
                ":true": True,
                ":account_id": caller_account_id,
                ":used_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Create share
        table.put_item(Item=share_item)

        logger.info("Profile invite redeemed", profile_id=profile_id, share_id=share_id)

        return {"share": share_item}

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to redeem invite", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to redeem invite")


def share_profile_direct(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Share profile directly with another account (no invite code).

    GraphQL mutation: shareProfileDirect(
        profileId: ID!,
        targetAccountId: ID!,
        permissions: [Permission!]!
    )

    Returns:
        {
          share: Share!
        }
    """
    logger = StructuredLogger(__name__, get_correlation_id(event))

    try:
        # Extract arguments
        args = event["arguments"]
        profile_id = args["profileId"]
        target_account_id = args["targetAccountId"]
        permissions = args["permissions"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Sharing profile directly",
            profile_id=profile_id,
            target_account_id=target_account_id,
            permissions=permissions,
        )

        # Authorization: Must be owner
        if not is_profile_owner(caller_account_id, profile_id):
            raise AppError(ErrorCode.FORBIDDEN, "Only profile owner can share directly")

        # Validate permissions
        valid_permissions = {"READ", "WRITE"}
        if not set(permissions).issubset(valid_permissions):
            raise AppError(
                ErrorCode.INVALID_INPUT, f"Invalid permissions. Must be one of: {valid_permissions}"
            )

        # Create share
        table = get_table()
        share_id = f"SHARE#{target_account_id}"
        share_item = {
            "PK": profile_id,
            "SK": share_id,
            "profileId": profile_id,
            "accountId": target_account_id,
            "permissions": permissions,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": caller_account_id,
            # GSI1 for "My Shared Profiles" view
            "GSI1PK": f"ACCOUNT#{target_account_id}",
            "GSI1SK": profile_id,
        }

        table.put_item(Item=share_item)

        logger.info("Profile shared directly", share_id=share_id)

        return {"share": share_item}

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to share profile", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to share profile")


# NOTE: revoke_share Lambda function REMOVED
# This operation is now handled by a VTL DynamoDB resolver directly in AppSync
# See cdk/cdk/cdk_stack.py - RevokeShareResolver
