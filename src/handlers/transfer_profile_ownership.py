"""Transfer profile ownership to another account.

This handler transfers ownership of a SellerProfile to a new owner who must already
have access via a share. The transfer involves:
1. Verifying caller is current owner
2. Verifying new owner has existing share
3. Updating profile's ownerAccountId
4. Deleting the share (since they're now the owner)
"""

from typing import Any, Dict

from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.ids import ensure_account_id, ensure_profile_id
    from utils.auth import is_admin
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.ids import ensure_account_id, ensure_profile_id
    from ..utils.auth import is_admin


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Transfer profile ownership."""
    caller_account_id = event["identity"]["sub"]
    profile_id = event["arguments"]["input"]["profileId"]
    new_owner_account_id = event["arguments"]["input"]["newOwnerAccountId"]

    # Normalize IDs using centralized utilities
    db_profile_id = ensure_profile_id(profile_id) or ""
    db_new_owner_id = ensure_account_id(new_owner_account_id) or ""
    db_caller_id = ensure_account_id(caller_account_id) or ""

    # 1. Get current profile and verify caller is owner
    # Profiles table uses ownerAccountId (PK) + profileId (SK)
    # We need to query by profileId using GSI or scan
    profile_response = tables.profiles.query(
        IndexName="profileId-index", KeyConditionExpression=Key("profileId").eq(db_profile_id)
    )

    if not profile_response.get("Items"):
        raise ValueError(f"Profile not found: {profile_id}")

    profile: Dict[str, Any] = profile_response["Items"][0]

    # Check authorization: caller must be owner OR admin
    caller_is_owner = profile["ownerAccountId"] == db_caller_id
    caller_is_admin = is_admin(event)
    
    if not caller_is_owner and not caller_is_admin:
        raise PermissionError("Only the profile owner or an admin can transfer ownership")

    # 2. Verify new owner has existing share (skip for admin transfers)
    # Admins can transfer to any user, but regular owners need the target to have a share
    if not caller_is_admin:
        share_response = tables.shares.get_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
        if "Item" not in share_response:
            raise ValueError("New owner must have existing access to the profile")

    # 3. Transfer ownership by deleting and recreating the profile with new owner
    # Cannot update partition key, so we delete and put
    old_key = {"ownerAccountId": profile["ownerAccountId"], "profileId": db_profile_id}

    # Delete old profile
    tables.profiles.delete_item(Key=old_key)

    # Create new profile with updated owner
    profile["ownerAccountId"] = db_new_owner_id
    tables.profiles.put_item(Item=profile)

    # 4. Delete the share if it exists (new owner doesn't need it anymore)
    # Only delete if share existed (might not exist for admin transfers)
    try:
        tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
    except Exception:
        pass  # Share might not exist for admin transfers

    # 5. Return updated profile
    return profile
