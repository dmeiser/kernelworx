"""Transfer profile ownership to another account.

This handler transfers ownership of a SellerProfile to a new owner who must already
have access via a share. The transfer involves:
1. Verifying caller is current owner
2. Verifying new owner has existing share
3. Updating profile's ownerAccountId
4. Deleting the share (since they're now the owner)
"""

import os
from typing import Any, Dict

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
profiles_table = dynamodb.Table(os.environ["PROFILES_TABLE_NAME"])
shares_table = dynamodb.Table(os.environ["SHARES_TABLE_NAME"])


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Transfer profile ownership."""
    caller_account_id = event["identity"]["sub"]
    profile_id = event["arguments"]["input"]["profileId"]
    new_owner_account_id = event["arguments"]["input"]["newOwnerAccountId"]

    # Normalize IDs
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"
    db_new_owner_id = (
        new_owner_account_id
        if new_owner_account_id.startswith("ACCOUNT#")
        else f"ACCOUNT#{new_owner_account_id}"
    )
    db_caller_id = caller_account_id if caller_account_id.startswith("ACCOUNT#") else f"ACCOUNT#{caller_account_id}"

    # 1. Get current profile and verify caller is owner
    # Profiles table uses ownerAccountId (PK) + profileId (SK)
    # We need to query by profileId using GSI or scan
    profile_response = profiles_table.query(
        IndexName="profileId-index",
        KeyConditionExpression=Key("profileId").eq(db_profile_id)
    )

    if not profile_response.get("Items"):
        raise ValueError(f"Profile not found: {profile_id}")

    profile = profile_response["Items"][0]

    if profile["ownerAccountId"] != db_caller_id:
        raise PermissionError("Only the profile owner can transfer ownership")

    # 2. Verify new owner has existing share
    share_response = shares_table.get_item(
        Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id}
    )

    if "Item" not in share_response:
        raise ValueError("New owner must have existing access to the profile")

    share = share_response["Item"]

    # 3. Transfer ownership by deleting and recreating the profile with new owner
    # Cannot update partition key, so we delete and put
    old_key = {"ownerAccountId": profile["ownerAccountId"], "profileId": db_profile_id}
    
    # Delete old profile
    profiles_table.delete_item(Key=old_key)
    
    # Create new profile with updated owner
    profile["ownerAccountId"] = db_new_owner_id
    profiles_table.put_item(Item=profile)

    # 4. Delete the share (new owner doesn't need it anymore)
    shares_table.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})

    # 5. Return updated profile
    return profile
