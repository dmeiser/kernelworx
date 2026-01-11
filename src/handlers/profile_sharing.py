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
from typing import TYPE_CHECKING, Any, Dict, List, cast

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table
    from mypy_boto3_dynamodb.type_defs import BatchGetItemOutputServiceResourceTypeDef

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import is_profile_owner
    from utils.dynamodb import get_dynamodb_resource, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import StructuredLogger, get_correlation_id
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import is_profile_owner
    from ..utils.dynamodb import get_dynamodb_resource, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import StructuredLogger, get_correlation_id


# Expose a module-level proxy for test monkeypatching (tests patch ``profile_sharing.dynamodb.batch_get_item``)
class _DynamoProxy:
    def batch_get_item(self, RequestItems: Dict[str, Any]) -> "BatchGetItemOutputServiceResourceTypeDef":
        result: "BatchGetItemOutputServiceResourceTypeDef" = get_dynamodb_resource().batch_get_item(
            RequestItems=RequestItems
        )
        return result


# Default module-level proxy instance (tests may monkeypatch methods on this object)
dynamodb: _DynamoProxy = _DynamoProxy()


def generate_invite_code() -> str:
    """Generate random 10-character alphanumeric invite code."""
    return secrets.token_urlsafe(8)[:10].upper().replace("-", "X").replace("_", "Y")


def _deduplicate_shares(shares: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Deduplicate shares by profileId and extract key fields."""
    shares_by_profile: Dict[str, Dict[str, Any]] = {}
    for share in shares:
        profile_id_val = share.get("profileId")
        owner_account_id_val = share.get("ownerAccountId")
        if not (profile_id_val and owner_account_id_val):
            continue
        if not (isinstance(profile_id_val, str) and isinstance(owner_account_id_val, str)):
            continue
        if profile_id_val in shares_by_profile:
            continue
        shares_by_profile[profile_id_val] = {
            "profileId": profile_id_val,
            "ownerAccountId": owner_account_id_val,
            "permissions": share.get("permissions", []),
        }
    return shares_by_profile


def _extract_batch_profiles(
    batch_response: "BatchGetItemOutputServiceResourceTypeDef", table_name: str
) -> List[Dict[str, Any]]:
    """Extract profiles from a BatchGetItem response."""
    responses = batch_response.get("Responses", {})
    if table_name in responses:
        return cast(List[Dict[str, Any]], responses.get(table_name, []))
    # Fallback: aggregate all responses across keys (best-effort for test shapes)
    batch_profiles: List[Dict[str, Any]] = []
    for items in responses.values():
        batch_profiles.extend(items)
    return batch_profiles


def _batch_get_profiles(
    profile_keys: List[Dict[str, str]],
    profiles_table: "Table",
    logger: StructuredLogger,
) -> List[Dict[str, Any]]:
    """Batch get profiles with retry logic, processing in batches of 100."""
    all_profiles: List[Dict[str, Any]] = []
    for i in range(0, len(profile_keys), 100):  # pragma: no branch
        batch_keys = profile_keys[i : i + 100]
        batch_profiles = _fetch_batch_with_retry(batch_keys, profiles_table, logger)
        all_profiles.extend(batch_profiles)
    return all_profiles


def _fetch_batch_with_retry(
    batch_keys: List[Dict[str, str]],
    profiles_table: "Table",
    logger: StructuredLogger,
    retries: int = 3,
) -> List[Dict[str, Any]]:
    """Fetch a single batch of profiles with retry logic."""
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
            batch_profiles = _extract_batch_profiles(batch_response, profiles_table.name)
            _log_unprocessed_keys(batch_response, profiles_table.name, logger)
            return batch_profiles
        except AppError:
            raise
        except Exception as e:
            if attempt < retries - 1:
                logger.warning("BatchGetItem failed, retrying", attempt=attempt + 1, error=str(e))
                continue
            logger.error("BatchGetItem failed after retries", error=str(e))
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list shared profiles")
    return []  # Should never reach here due to raise above


def _log_unprocessed_keys(
    batch_response: "BatchGetItemOutputServiceResourceTypeDef", table_name: str, logger: StructuredLogger
) -> None:
    """Log any unprocessed keys from BatchGetItem."""
    unprocessed_keys = batch_response.get("UnprocessedKeys", {})
    unprocessed_table: Any = unprocessed_keys.get(table_name, {})
    if not unprocessed_table and isinstance(unprocessed_keys, dict):
        for v in unprocessed_keys.values():
            unprocessed_table = v
            break
    if unprocessed_table:
        unprocessed_key_list = unprocessed_table.get("Keys", [])
        if unprocessed_key_list:
            logger.warning("Unprocessed keys in batch", count=len(unprocessed_key_list))


def _build_shared_profile_result(
    profile: Dict[str, Any],
    shares_by_profile: Dict[str, Dict[str, Any]],
    caller_account_id_with_prefix: str,
) -> Dict[str, Any] | None:
    """Build a single shared profile result item."""
    profile_id_str = profile.get("profileId")
    if not isinstance(profile_id_str, str):
        return None
    share = shares_by_profile.get(profile_id_str)
    if not share:
        return None

    # Skip profiles with missing required fields (data quality issue)
    seller_name = profile.get("sellerName")
    created_at = profile.get("createdAt")
    updated_at = profile.get("updatedAt")
    if not seller_name or not created_at or not updated_at:
        return None

    owner_account_id_raw = profile.get("ownerAccountId", "")
    if not isinstance(owner_account_id_raw, str):
        owner_account_id_raw = ""
    owner_account_id = (
        owner_account_id_raw if owner_account_id_raw.startswith("ACCOUNT#") else f"ACCOUNT#{owner_account_id_raw}"
    )
    permissions = share.get("permissions", [])
    permissions_list = list(permissions) if isinstance(permissions, set) else permissions
    return {
        "profileId": profile_id_str,
        "ownerAccountId": owner_account_id,
        "sellerName": seller_name,
        "unitType": profile.get("unitType"),
        "unitNumber": profile.get("unitNumber"),
        "createdAt": created_at,
        "updatedAt": updated_at,
        "isOwner": profile.get("ownerAccountId") == caller_account_id_with_prefix,
        "permissions": permissions_list,
    }


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
        # Shares are stored with ACCOUNT# prefix on targetAccountId
        target_account_id_with_prefix = (
            caller_account_id if caller_account_id.startswith("ACCOUNT#") else f"ACCOUNT#{caller_account_id}"
        )
        response = tables.shares.query(
            IndexName="targetAccountId-index",
            KeyConditionExpression="targetAccountId = :targetAccountId",
            ExpressionAttributeValues={":targetAccountId": target_account_id_with_prefix},
        )
        shares = response.get("Items", [])

        if not shares:
            logger.info("No shares found")
            return []

        # Deduplicate by profileId (in case of duplicate shares)
        shares_by_profile = _deduplicate_shares(shares)

        logger.info("Found shares", count=len(shares_by_profile))

        # Step 2: BatchGetItem to get full profile data
        profile_keys = [
            {"ownerAccountId": s["ownerAccountId"], "profileId": s["profileId"]} for s in shares_by_profile.values()
        ]
        all_profiles = _batch_get_profiles(profile_keys, tables.profiles, logger)

        logger.info("Retrieved profiles", count=len(all_profiles))

        # Step 3: Merge profile data with share permissions
        caller_account_id_with_prefix = f"ACCOUNT#{caller_account_id}"
        result: List[Dict[str, Any]] = []
        for profile in all_profiles:  # pragma: no branch
            profile_result = _build_shared_profile_result(profile, shares_by_profile, caller_account_id_with_prefix)
            if profile_result:
                result.append(profile_result)

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
            raise AppError(ErrorCode.INVALID_INPUT, f"Invalid permissions. Must be one of: {valid_permissions}")

        # Generate invite code
        invite_code = generate_invite_code()

        # Calculate expiration (14 days from now)
        expires_at = datetime.now(timezone.utc) + timedelta(days=14)
        expires_at_epoch = int(expires_at.timestamp())

        # Ensure profileId is stored with PROFILE# prefix
        db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"

        # Store invite in DynamoDB (V2 design: invites table with inviteCode as PK)
        invite_item = {
            "inviteCode": invite_code,  # PK
            "profileId": db_profile_id,
            "permissions": permissions,
            "createdBy": caller_account_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "expiresAt": expires_at_epoch,  # Epoch seconds for TTL
            "used": False,
        }

        tables.invites.put_item(Item=invite_item)

        logger.info("Profile invite created", invite_code=invite_code, expires_at=expires_at.isoformat())

        return {
            "inviteCode": invite_code,
            "profileId": db_profile_id,
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
