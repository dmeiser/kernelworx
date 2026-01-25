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
    from utils.auth import is_admin
    from utils.dynamodb import tables
    from utils.ids import ensure_account_id, ensure_profile_id
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import is_admin
    from ..utils.dynamodb import tables
    from ..utils.ids import ensure_account_id, ensure_profile_id


def _get_and_verify_profile(db_profile_id: str, db_caller_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Get profile and verify caller is owner or admin."""
    profile_response = tables.profiles.query(
        IndexName="profileId-index", KeyConditionExpression=Key("profileId").eq(db_profile_id)
    )

    if not profile_response.get("Items"):
        raise ValueError(f"Profile not found: {db_profile_id}")

    profile: Dict[str, Any] = profile_response["Items"][0]

    caller_is_owner = profile["ownerAccountId"] == db_caller_id
    caller_is_admin = is_admin(event)

    if not caller_is_owner and not caller_is_admin:
        raise PermissionError("Only the profile owner or an admin can transfer ownership")

    return profile


def _verify_new_owner_has_share(db_profile_id: str, db_new_owner_id: str, caller_is_admin: bool) -> None:
    """Verify new owner has existing share (skip for admin transfers)."""
    if not caller_is_admin:
        share_response = tables.shares.get_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
        if "Item" not in share_response:
            raise ValueError("New owner must have existing access to the profile")


def _transfer_ownership(profile: Dict[str, Any], db_profile_id: str, db_new_owner_id: str) -> None:
    """Transfer ownership by deleting and recreating profile with new owner."""
    old_key = {"ownerAccountId": profile["ownerAccountId"], "profileId": db_profile_id}
    tables.profiles.delete_item(Key=old_key)
    profile["ownerAccountId"] = db_new_owner_id
    tables.profiles.put_item(Item=profile)


def _delete_share_if_exists(db_profile_id: str, db_new_owner_id: str) -> None:
    """Delete the share if it exists (new owner doesn't need it anymore)."""
    try:
        tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})
    except Exception:
        pass  # Share might not exist for admin transfers


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Transfer profile ownership."""
    caller_account_id = event["identity"]["sub"]
    profile_id = event["arguments"]["input"]["profileId"]
    new_owner_account_id = event["arguments"]["input"]["newOwnerAccountId"]

    db_profile_id = ensure_profile_id(profile_id) or ""
    db_new_owner_id = ensure_account_id(new_owner_account_id) or ""
    db_caller_id = ensure_account_id(caller_account_id) or ""

    profile = _get_and_verify_profile(db_profile_id, db_caller_id, event)
    caller_is_admin = is_admin(event)
    _verify_new_owner_has_share(db_profile_id, db_new_owner_id, caller_is_admin)
    _transfer_ownership(profile, db_profile_id, db_new_owner_id)
    _delete_share_if_exists(db_profile_id, db_new_owner_id)

    return profile
