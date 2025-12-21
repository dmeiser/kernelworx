"""
Profile sharing Lambda handlers.

Implements:
- createProfileInvite: Generate invite code for sharing profile
- redeemProfileInvite: Redeem invite code to gain access
- shareProfileDirect: Share profile directly with account (no invite)
- list_my_shares: List profiles shared with the current user (hydrated)

NOTE: Most of these operations have been migrated to AppSync resolvers (pipeline/JS).
This Lambda code is kept for reference and potential future use.
See cdk_stack.py for the actual implementations.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import is_profile_owner  # type: ignore[import-not-found]
    from utils.errors import AppError, ErrorCode  # type: ignore[import-not-found]
    from utils.logging import StructuredLogger, get_correlation_id  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import is_profile_owner
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import StructuredLogger, get_correlation_id

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def get_invites_table() -> "Table":
    """Get DynamoDB invites table instance (V2 design - separate table)."""
    table_name = os.getenv("INVITES_TABLE_NAME", "kernelworx-invites-ue1-dev")
    return dynamodb.Table(table_name)


def get_shares_table() -> "Table":
    """Get DynamoDB shares table instance."""
    table_name = os.getenv("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")
    return dynamodb.Table(table_name)


def get_profiles_table() -> "Table":
    """Get DynamoDB profiles table instance."""
    table_name = os.getenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
    return dynamodb.Table(table_name)


def generate_invite_code() -> str:
    """Generate random 10-character alphanumeric invite code."""
    return secrets.token_urlsafe(8)[:10].upper().replace("-", "X").replace("_", "Y")


def list_my_shares(event: Dict[str, Any], context: Any) -> List[Dict[str, Any]]:
    """
    List profiles shared with the current user with full profile data.

    GraphQL query: listMyShares

    This Lambda is used instead of AppSync pipeline resolver because
    AppSync's BatchGetItem has intermittent issues with complex key schemas.

    Returns:
        [{
          profileId: ID!
          ownerAccountId: ID!
          sellerName: String!
          unitType: UnitType
          unitNumber: String
          createdAt: AWSDateTime!
          updatedAt: AWSDateTime!
          isOwner: Boolean!
          permissions: [Permission!]!
        }]
    """
    logger = StructuredLogger(__name__, get_correlation_id(event))
    caller_account_id = event["identity"]["sub"]

    logger.info("Listing shared profiles", caller_account_id=caller_account_id)

    try:
        # Step 1: Query shares table GSI to get all shares for this user
        shares_table = get_shares_table()
        response = shares_table.query(
            IndexName="targetAccountId-index",
            KeyConditionExpression="targetAccountId = :targetAccountId",
            ExpressionAttributeValues={":targetAccountId": caller_account_id},
        )
        shares = response.get("Items", [])

        if not shares:
            logger.info("No shares found")
            return []

        # Deduplicate by profileId (in case of duplicate shares)
        shares_by_profile: Dict[str, Dict[str, Any]] = {}
        for share in shares:
            profile_id_val = share.get("profileId")
            owner_account_id_val = share.get("ownerAccountId")
            if (
                profile_id_val
                and owner_account_id_val
                and isinstance(profile_id_val, str)
                and isinstance(owner_account_id_val, str)
                and profile_id_val not in shares_by_profile
            ):
                shares_by_profile[profile_id_val] = {
                    "profileId": profile_id_val,
                    "ownerAccountId": owner_account_id_val,
                    "permissions": share.get("permissions", []),
                }

        logger.info("Found shares", count=len(shares_by_profile))

        # Step 2: BatchGetItem to get full profile data
        # DynamoDB BatchGetItem supports up to 100 keys
        profiles_table = get_profiles_table()
        profile_keys = [
            {"ownerAccountId": s["ownerAccountId"], "profileId": s["profileId"]}
            for s in shares_by_profile.values()
        ]

        # Process in batches of 100
        all_profiles: List[Dict[str, Any]] = []
        for i in range(0, len(profile_keys), 100):  # pragma: no branch
            batch_keys = profile_keys[i : i + 100]

            # Use batch_get_item with retry logic
            retries = 3
            for attempt in range(retries):
                try:
                    batch_response = dynamodb.batch_get_item(
                        RequestItems={
                            profiles_table.name: {
                                "Keys": batch_keys,
                                "ConsistentRead": True,
                            }
                        }
                    )
                    batch_profiles = batch_response.get("Responses", {}).get(
                        profiles_table.name, []
                    )
                    all_profiles.extend(batch_profiles)

                    # Handle unprocessed keys (unlikely but possible)
                    unprocessed_keys = batch_response.get("UnprocessedKeys", {})
                    unprocessed_table: Dict[str, Any] = unprocessed_keys.get(  # type: ignore[assignment]
                        profiles_table.name, {}
                    )
                    if unprocessed_table:
                        unprocessed_key_list = unprocessed_table.get("Keys", [])
                        if unprocessed_key_list:
                            logger.warning(
                                "Unprocessed keys in batch",
                                count=len(unprocessed_key_list),
                            )
                    break  # Success, exit retry loop
                except Exception as e:
                    if attempt < retries - 1:
                        logger.warning(
                            "BatchGetItem failed, retrying",
                            attempt=attempt + 1,
                            error=str(e),
                        )
                        continue
                    logger.error("BatchGetItem failed after retries", error=str(e))
                    raise

        logger.info("Retrieved profiles", count=len(all_profiles))

        # Step 3: Merge profile data with share permissions
        caller_account_id_with_prefix = f"ACCOUNT#{caller_account_id}"
        result: List[Dict[str, Any]] = []
        for profile in all_profiles:  # pragma: no branch
            profile_id_str = profile.get("profileId")
            if not isinstance(profile_id_str, str):
                continue
            share = shares_by_profile.get(profile_id_str)  # type: ignore[assignment]
            if share:
                owner_account_id_raw = profile.get("ownerAccountId", "")
                if not isinstance(owner_account_id_raw, str):
                    owner_account_id_raw = ""
                # Strip ACCOUNT# prefix for API response
                owner_id_clean = (
                    owner_account_id_raw[8:]
                    if owner_account_id_raw.startswith("ACCOUNT#")
                    else owner_account_id_raw
                )
                # Convert permissions from set (DynamoDB SS type) to list for JSON serialization
                permissions = share.get("permissions", [])
                permissions_list = list(permissions) if isinstance(permissions, set) else permissions
                result.append(
                    {
                        "profileId": profile_id_str,  # Keep PROFILE# prefix
                        "ownerAccountId": owner_id_clean,
                        "sellerName": profile.get("sellerName"),
                        "unitType": profile.get("unitType"),
                        "unitNumber": profile.get("unitNumber"),
                        "createdAt": profile.get("createdAt"),
                        "updatedAt": profile.get("updatedAt"),
                        "isOwner": profile.get("ownerAccountId") == caller_account_id_with_prefix,
                        "permissions": permissions_list,
                    }
                )

        logger.info("Returning shared profiles", count=len(result))
        return result

    except AppError:
        raise
    except Exception as e:
        logger.error("Failed to list shared profiles", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list shared profiles")


def create_profile_invite(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create profile invite code.

    GraphQL mutation: createProfileInvite(profileId: ID!, permissions: [Permission!]!)

    NOTE: This Lambda is not used by AppSync anymore - the operation is handled by
    a pipeline resolver (VerifyProfileOwnerForInviteFn → CreateInviteFn).
    This code is kept for reference and potential future use.

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
        expires_at_epoch = int(expires_at.timestamp())

        # Store invite in DynamoDB (V2 design: invites table with inviteCode as PK)
        table = get_invites_table()
        invite_item = {
            "inviteCode": invite_code,  # PK
            "profileId": profile_id,
            "permissions": permissions,
            "createdBy": caller_account_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": expires_at_epoch,  # Epoch seconds for TTL
            "used": False,
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
