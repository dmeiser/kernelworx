"""
Unit tests for src/handlers/unit_campaign_operations.py and
src/handlers/participant_data.py (Show & Sell wave 2).

Covers join-time catalog identity, the roster guard versioning, join-code
indistinguishability, and the participant-safe preview projection.
"""

from typing import Any, Dict

import boto3
import pytest

from src.handlers.participant_data import handler as participant_handler
from src.handlers.unit_campaign_operations import handler as campaign_handler
from src.utils.errors import ErrorCode

ACCOUNT_A = "ACCOUNT#user-123-456"
ACCOUNT_B = "ACCOUNT#user-789"
PROFILE_A = "PROFILE#profile-1"
CAMPAIGN_A = "CAMPAIGN#campaign-1"
CATALOG_A = "CATALOG#catalog-1"


@pytest.fixture
def _tables(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
        "catalogs": dynamodb.Table("kernelworx-catalogs-ue1-dev"),
    }


def _seed_unit(t: Dict[str, Any], admin: str = ACCOUNT_A) -> None:
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": "METADATA",
            "accountId": admin,
            "unitType": "Pack",
            "unitNumber": "9999",
            "city": "Denver",
            "state": "CO",
            "displayName": "Pack 9999 (Denver)",
            "timezone": "America/Denver",
            "splitDefault": "EQUAL",
            "councilNeedBasis": "PHYSICAL_STOCK",
            "metadataKey": "pack|9999|denver|co",
            "adminCount": 1,
            "activeInviteCount": 0,
            "version": 1,
            "createdAt": "2026-11-01T00:00:00Z",
            "updatedAt": "2026-11-01T00:00:00Z",
            "createdByAccountId": admin,
        }
    )
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": f"GRANT#{admin}",
            "accountId": admin,
            "role": "UNIT_ADMIN",
            "createdByAccountId": admin,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )


def _seed_profile_and_campaign(t: Dict[str, Any], owner: str = ACCOUNT_A) -> None:
    t["profiles"].put_item(
        Item={
            "ownerAccountId": owner,
            "profileId": PROFILE_A,
            "displayName": "Scout Sam",
            "createdAt": "2026-11-01T00:00:00Z",
            "version": 1,
        }
    )
    t["campaigns"].put_item(
        Item={
            "profileId": PROFILE_A,
            "campaignId": CAMPAIGN_A,
            "campaignName": "Fall Sale",
            "campaignYear": 2026,
            "catalogId": CATALOG_A,
            "isActive": True,
            "version": 1,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )
    t["catalogs"].put_item(
        Item={
            "catalogId": CATALOG_A,
            "catalogName": "Council Catalog",
            "products": [{"productId": "P1", "productName": "Kettle Corn"}],
            "version": 1,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )


def _event(field: str, arguments: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {
        "arguments": arguments,
        "identity": {"sub": sub, "username": sub},
        "info": {"fieldName": field, "parentTypeName": "Mutation"},
    }


def _create_uc(t: Dict[str, Any], key: str = "uc-create-01") -> Dict[str, Any]:
    _seed_unit(t)
    return campaign_handler(
        _event(
            "createUnitCampaign",
            {
                "input": {
                    "unitId": "unit-1",
                    "campaignName": "Show and Sell 2026",
                    "campaignYear": 2026,
                    "catalogId": CATALOG_A,
                    "idempotencyKey": key,
                }
            },
        ),
        None,
    )


class TestCreateUnitCampaign:
    def test_success(self, _tables: Dict[str, Any]) -> None:
        result = _create_uc(_tables)
        assert result["unitId"] == "unit-1"
        assert result["joinCode"]
        assert len(result["joinCode"]) == 16
        assert result["isActive"] is True
        guard = _tables["unit_campaigns"].get_item(
            Key={"unitCampaignId": result["unitCampaignId"], "itemKey": "GUARD#ROSTER"}
        )["Item"]
        assert int(guard["guardVersion"]) == 1
        pointer = _tables["units"].get_item(Key={"unitId": "unit-1", "itemKey": f"JOIN#{result['joinCode']}"})["Item"]
        assert pointer["unitCampaignId"] == result["unitCampaignId"]

    def test_non_admin_blocked(self, _tables: Dict[str, Any]) -> None:
        _seed_unit(_tables)
        result = campaign_handler(
            _event(
                "createUnitCampaign",
                {
                    "input": {
                        "unitId": "unit-1",
                        "campaignName": "Nope",
                        "campaignYear": 2026,
                        "catalogId": CATALOG_A,
                        "idempotencyKey": "uc-create-02",
                    }
                },
                sub="user-789",
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_replay(self, _tables: Dict[str, Any]) -> None:
        first = _create_uc(_tables, "uc-create-03")
        second = _create_uc(_tables, "uc-create-03")
        assert second == first


class TestUpdateUnitCampaign:
    def test_success_and_version(self, _tables: Dict[str, Any]) -> None:
        created = _create_uc(_tables)
        uc_id = created["unitCampaignId"]
        result = campaign_handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": uc_id,
                        "isActive": False,
                        "expectedVersion": 1,
                        "idempotencyKey": "uc-update-01",
                    }
                },
            ),
            None,
        )
        assert result["isActive"] is False
        assert result["version"] == 2

    def test_version_mismatch(self, _tables: Dict[str, Any]) -> None:
        created = _create_uc(_tables)
        result = campaign_handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": created["unitCampaignId"],
                        "isActive": False,
                        "expectedVersion": 9,
                        "idempotencyKey": "uc-update-02",
                    }
                },
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT


class TestJoinUnitCampaign:
    def _joinable(self, t: Dict[str, Any], owner: str = ACCOUNT_A) -> Dict[str, Any]:
        created = _create_uc(t)
        _seed_profile_and_campaign(t, owner=owner)
        return created

    def test_success(self, _tables: Dict[str, Any]) -> None:
        created = self._joinable(_tables)
        result = campaign_handler(
            _event(
                "joinUnitCampaign",
                {
                    "joinCode": created["joinCode"],
                    "campaignId": CAMPAIGN_A,
                    "idempotencyKey": "uc-join-001",
                },
            ),
            None,
        )
        assert result["status"] == "ACTIVE"
        assert result["profileId"] == PROFILE_A
        assert result["guardVersion"] == 2
        assert result["profileDisplayName"] == "Scout Sam"
        # The legacy campaign now carries the join pointer.
        campaign = _tables["campaigns"].get_item(Key={"profileId": PROFILE_A, "campaignId": CAMPAIGN_A})["Item"]
        assert campaign["unitCampaignKey"] == created["unitCampaignId"]

    def test_replay(self, _tables: Dict[str, Any]) -> None:
        created = self._joinable(_tables)
        args = {"joinCode": created["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "uc-join-002"}
        first = campaign_handler(_event("joinUnitCampaign", args), None)
        second = campaign_handler(_event("joinUnitCampaign", args), None)
        assert second == first

    def test_unknown_code_not_found(self, _tables: Dict[str, Any]) -> None:
        self._joinable(_tables)
        result = campaign_handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": "ZZZZ8888ZZZZ8888", "campaignId": CAMPAIGN_A, "idempotencyKey": "uc-join-003"},
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_catalog_mismatch_rejected(self, _tables: Dict[str, Any]) -> None:
        created = self._joinable(_tables)
        campaign = _tables["campaigns"].get_item(Key={"profileId": PROFILE_A, "campaignId": CAMPAIGN_A})["Item"]
        campaign["catalogId"] = "CATALOG#other"
        _tables["campaigns"].put_item(Item=campaign)
        result = campaign_handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": created["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "uc-join-004"},
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_campaign_without_access_forbidden(self, _tables: Dict[str, Any]) -> None:
        created = self._joinable(_tables, owner=ACCOUNT_A)
        result = campaign_handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": created["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "uc-join-005"},
                sub="user-789",
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_inactive_unit_campaign_not_found(self, _tables: Dict[str, Any]) -> None:
        created = self._joinable(_tables)
        campaign_handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": created["unitCampaignId"],
                        "isActive": False,
                        "expectedVersion": 1,
                        "idempotencyKey": "uc-join-006",
                    }
                },
            ),
            None,
        )
        result = campaign_handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": created["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "uc-join-007"},
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND


class TestRemoveMembership:
    def _joined(self, t: Dict[str, Any]) -> Dict[str, Any]:
        created = _create_uc(t)
        _seed_profile_and_campaign(t)
        membership = campaign_handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": created["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "uc-rm-0001"},
            ),
            None,
        )
        return {"uc": created, "membership": membership}

    def test_success(self, _tables: Dict[str, Any]) -> None:
        state = self._joined(_tables)
        membership = state["membership"]
        result = campaign_handler(
            _event(
                "removeUnitCampaignMembership",
                {
                    "unitCampaignId": membership["unitCampaignId"],
                    "campaignId": CAMPAIGN_A,
                    "expectedMembershipVersion": membership["version"],
                    "expectedGuardVersion": membership["guardVersion"],
                    "idempotencyKey": "uc-rm-0002",
                },
            ),
            None,
        )
        assert result["status"] == "REMOVED"
        # The legacy campaign pointer is detached.
        campaign = _tables["campaigns"].get_item(Key={"profileId": PROFILE_A, "campaignId": CAMPAIGN_A})["Item"]
        assert "unitCampaignKey" not in campaign

    def test_guard_mismatch(self, _tables: Dict[str, Any]) -> None:
        state = self._joined(_tables)
        membership = state["membership"]
        result = campaign_handler(
            _event(
                "removeUnitCampaignMembership",
                {
                    "unitCampaignId": membership["unitCampaignId"],
                    "campaignId": CAMPAIGN_A,
                    "expectedMembershipVersion": membership["version"],
                    "expectedGuardVersion": 99,
                    "idempotencyKey": "uc-rm-0003",
                },
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_membership_version_mismatch(self, _tables: Dict[str, Any]) -> None:
        state = self._joined(_tables)
        membership = state["membership"]
        result = campaign_handler(
            _event(
                "removeUnitCampaignMembership",
                {
                    "unitCampaignId": membership["unitCampaignId"],
                    "campaignId": CAMPAIGN_A,
                    "expectedMembershipVersion": 99,
                    "expectedGuardVersion": membership["guardVersion"],
                    "idempotencyKey": "uc-rm-0004",
                },
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT


class TestQueries:
    def test_unit_campaign_admin_read(self, _tables: Dict[str, Any]) -> None:
        created = _create_uc(_tables)
        result = campaign_handler(_event("unitCampaign", {"unitCampaignId": created["unitCampaignId"]}), None)
        assert result["joinCode"] == created["joinCode"]

    def test_unit_campaigns_listing_filter(self, _tables: Dict[str, Any]) -> None:
        created = _create_uc(_tables)
        campaign_handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": created["unitCampaignId"],
                        "isActive": False,
                        "expectedVersion": 1,
                        "idempotencyKey": "uc-q-00001",
                    }
                },
            ),
            None,
        )
        active = campaign_handler(
            _event("unitCampaigns", {"unitId": "unit-1", "isActive": True, "page": {"limit": 10}}), None
        )
        assert active["items"] == []
        inactive = campaign_handler(
            _event("unitCampaigns", {"unitId": "unit-1", "isActive": False, "page": {"limit": 10}}), None
        )
        assert len(inactive["items"]) == 1

    def test_roster_lists_members_with_guard(self, _tables: Dict[str, Any]) -> None:
        created = _create_uc(_tables)
        _seed_profile_and_campaign(_tables)
        campaign_handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": created["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "uc-q-00002"},
            ),
            None,
        )
        roster = campaign_handler(
            _event("unitCampaignRoster", {"unitCampaignId": created["unitCampaignId"], "page": {"limit": 10}}),
            None,
        )
        assert len(roster["items"]) == 1
        assert roster["items"][0]["guardVersion"] == 2

    def test_roster_non_admin_blocked(self, _tables: Dict[str, Any]) -> None:
        created = _create_uc(_tables)
        result = campaign_handler(
            _event(
                "unitCampaignRoster",
                {"unitCampaignId": created["unitCampaignId"], "page": {"limit": 10}},
                sub="user-789",
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_unit_campaign_catalog(self, _tables: Dict[str, Any]) -> None:
        _seed_profile_and_campaign(_tables)
        created = _create_uc(_tables)
        result = campaign_handler(_event("unitCampaignCatalog", {"unitCampaignId": created["unitCampaignId"]}), None)
        assert result["catalogName"] == "Council Catalog"
        assert result["products"][0]["productId"] == "P1"


class TestParticipantData:
    def test_join_preview(self, _tables: Dict[str, Any]) -> None:
        _seed_profile_and_campaign(_tables)
        created = _create_uc(_tables)
        result = participant_handler(
            _event("unitCampaignJoinInfo", {"joinCode": created["joinCode"]}, sub="user-789"), None
        )
        assert result["unitDisplayName"] == "Pack 9999 (Denver)"
        assert result["catalogName"] == "Council Catalog"
        assert result["isActive"] is True
        # Participant-safe: no admin-only fields leak.
        assert "unitCampaignId" not in result
        assert "version" not in result

    def test_unknown_code_not_found(self, _tables: Dict[str, Any]) -> None:
        _seed_profile_and_campaign(_tables)
        _create_uc(_tables)
        result = participant_handler(
            _event("unitCampaignJoinInfo", {"joinCode": "ZZZZ8888ZZZZ8888"}, sub="user-789"), None
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_inactive_preview_not_found(self, _tables: Dict[str, Any]) -> None:
        _seed_profile_and_campaign(_tables)
        created = _create_uc(_tables)
        campaign_handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": created["unitCampaignId"],
                        "isActive": False,
                        "expectedVersion": 1,
                        "idempotencyKey": "uc-p-00001",
                    }
                },
            ),
            None,
        )
        result = participant_handler(
            _event("unitCampaignJoinInfo", {"joinCode": created["joinCode"]}, sub="user-789"), None
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_dispatcher_unknown_field(self, _tables: Dict[str, Any]) -> None:
        result = participant_handler(_event("mysteryField", {}), None)
        assert result["__isError"] is True
