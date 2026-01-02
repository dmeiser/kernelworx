from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.handlers import profile_sharing


class DummyTable:
    def __init__(self):
        self.stored = None

    def put_item(self, Item):
        self.stored = Item


def make_event_create_invite(profile_id, permissions, caller_sub="acct-1"):
    return {
        "arguments": {"profileId": profile_id, "permissions": permissions},
        "identity": {"sub": caller_sub},
        "requestId": "req-1",
    }


def test_create_profile_invite_prefixing(monkeypatch):
    dummy_table = DummyTable()
    monkeypatch.setattr("src.handlers.profile_sharing.get_invites_table", lambda: dummy_table)

    # Make caller owner
    monkeypatch.setattr("src.handlers.profile_sharing.is_profile_owner", lambda caller, pid: True)

    # Create invite using raw profile id (no prefix)
    event = make_event_create_invite("profile-123", ["READ"])
    res = profile_sharing.create_profile_invite(event, SimpleNamespace())

    assert res["profileId"].startswith("PROFILE#")
    assert res["permissions"] == ["READ"]
    assert "inviteCode" in res and isinstance(res["inviteCode"], str) and len(res["inviteCode"]) > 0

    # Ensure the item stored in DB has prefixed profile id
    assert dummy_table.stored is not None
    assert dummy_table.stored["profileId"].startswith("PROFILE#")


def test_list_my_shares_strips_account_prefix(monkeypatch):
    # Prepare shares GSI response
    shares_response = {
        "Items": [{"profileId": "PROFILE#p1", "ownerAccountId": "ACCOUNT#acct-1", "permissions": ["READ"]}]
    }
    dummy_shares_table = MagicMock()
    dummy_shares_table.query.return_value = shares_response
    monkeypatch.setattr("src.handlers.profile_sharing.get_shares_table", lambda: dummy_shares_table)

    # Prepare profiles batch response
    profile_item = {
        "profileId": "PROFILE#p1",
        "ownerAccountId": "ACCOUNT#acct-1",
        "sellerName": "Sam",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }

    # Patch dynamodb.batch_get_item via monkeypatch on boto3.resource().batch_get_item not used here, instead monkeypatch directly
    dummy_profiles_table = MagicMock()
    dummy_profiles_table.name = "profiles"

    # Monkeypatch get_profiles_table to return table whose name is used in batch_get_item calls
    monkeypatch.setattr("src.handlers.profile_sharing.get_profiles_table", lambda: dummy_profiles_table)

    # Patch dynamodb.batch_get_item function in module's dynamodb resource
    def fake_batch_get_item(RequestItems):
        return {
            dummy_profiles_table.name: {"Responses": {dummy_profiles_table.name: [profile_item]}}
        }  # not real shape, but not used directly

    # Instead of patching DynamoDB internals, monkeypatch the loop that calls batch_get_item by overriding the function body
    # Simpler: patch profile_sharing.dynamodb.batch_get_item to return a structure with Responses
    monkeypatch.setattr(
        "src.handlers.profile_sharing.dynamodb.batch_get_item",
        lambda RequestItems: {"Responses": {dummy_profiles_table.name: [profile_item]}},
    )

    # Call list_my_shares
    event = {"identity": {"sub": "acct-1"}}
    res = profile_sharing.list_my_shares(event, SimpleNamespace())

    assert isinstance(res, list)
    assert len(res) == 1
    item = res[0]
    # ownerAccountId should be stripped of ACCOUNT# prefix
    assert item["ownerAccountId"] == "acct-1"
    # profileId should remain prefixed
    assert item["profileId"].startswith("PROFILE#")
