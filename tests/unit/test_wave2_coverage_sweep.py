"""
Coverage sweep for the wave-2 Show & Sell handlers: error branches, marker
edge cases, transaction-cancel mapping, and pagination loops that the happy
-path suites do not reach.
"""

from typing import Any, Dict
from unittest.mock import MagicMock

import boto3
import pytest

from src.utils.dynamodb import TransactionCancelledError

ACCOUNT_A = "ACCOUNT#user-123-456"
ACCOUNT_B = "ACCOUNT#user-789"
PROFILE_A = "PROFILE#profile-1"
CAMPAIGN_A = "CAMPAIGN#campaign-1"
CATALOG_A = "CATALOG#catalog-1"


@pytest.fixture
def t(dynamodb_table: Any) -> Dict[str, Any]:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
        "catalogs": dynamodb.Table("kernelworx-catalogs-ue1-dev"),
        "throttles": dynamodb.Table("kernelworx-public-order-throttles-ue1-dev"),
    }


def _event(field: str, arguments: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {
        "arguments": arguments,
        "identity": {"sub": sub, "username": sub},
        "info": {"fieldName": field},
    }


def _seed_unit(t: Dict[str, Any], admin: str = ACCOUNT_A, unit_id: str = "unit-1") -> None:
    t["units"].put_item(
        Item={
            "unitId": unit_id,
            "itemKey": "METADATA",
            "accountId": admin,
            "unitType": "Pack",
            "unitNumber": "9999",
            "city": "Denver",
            "state": "CO",
            "displayName": f"Pack 9999 (Denver) {unit_id}",
            "timezone": "America/Denver",
            "splitDefault": "EQUAL",
            "councilNeedBasis": "PHYSICAL_STOCK",
            "metadataKey": f"pack|9999|denver|co|{unit_id}",
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
            "unitId": unit_id,
            "itemKey": f"GRANT#{admin}",
            "accountId": admin,
            "role": "UNIT_ADMIN",
            "createdByAccountId": admin,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )


def _seed_profile_campaign_catalog(t: Dict[str, Any], owner: str = ACCOUNT_A, with_catalog: bool = True) -> None:
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
    if with_catalog:
        t["catalogs"].put_item(
            Item={"catalogId": CATALOG_A, "catalogName": "Council Catalog", "products": [], "version": 1}
        )


def _create_unit_campaign(t: Dict[str, Any], key: str = "sw-uc-0001") -> Dict[str, Any]:
    from src.handlers.unit_campaign_operations import handler as campaign_handler

    _seed_unit(t)
    return campaign_handler(
        _event(
            "createUnitCampaign",
            {
                "input": {
                    "unitId": "unit-1",
                    "campaignName": "S&S",
                    "campaignYear": 2026,
                    "catalogId": CATALOG_A,
                    "idempotencyKey": key,
                }
            },
        ),
        None,
    )


class TestUnitOperationsSweep:
    def test_update_unit_all_optional_fields(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler

        _seed_unit(t)
        result = handler(
            _event(
                "updateUnit",
                {
                    "input": {
                        "unitId": "unit-1",
                        "unitType": "Troop",
                        "unitNumber": "42",
                        "city": "Aurora",
                        "state": "CO",
                        "displayName": "Troop 42",
                        "timezone": "America/Chicago",
                        "splitDefault": "RATIO",
                        "councilNeedBasis": "KERNEL_STOCK",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-upd-all",
                    }
                },
            ),
            None,
        )
        assert result["unitType"] == "Troop"
        assert result["splitDefault"] == "RATIO"

    def test_update_unit_geography_collision_invalid(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler

        _seed_unit(t, unit_id="unit-1")
        _seed_unit(t, unit_id="unit-2", admin=ACCOUNT_B)
        # unit-2's seed differs by unit_id in metadataKey; force a real collision.
        two = t["units"].get_item(Key={"unitId": "unit-2", "itemKey": "METADATA"})["Item"]
        two["metadataKey"] = "pack|9999|aurora|co"
        t["units"].put_item(Item=two)
        result = handler(
            _event(
                "updateUnit",
                {"input": {"unitId": "unit-1", "city": "Aurora", "expectedVersion": 1, "idempotencyKey": "sw-upd-col"}},
            ),
            None,
        )
        assert result["errorCode"] == "INVALID_INPUT"

    def test_marker_fingerprint_conflict_and_missing_result(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler

        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#createUnit#sw-mkr-001",
                "idemFingerprint": "other",
                "idemResult": {"unit": {}},
            }
        )
        conflict = handler(
            _event(
                "createUnit",
                {
                    "input": {
                        "unitType": "Pack",
                        "unitNumber": "1",
                        "city": "X",
                        "state": "CO",
                        "idempotencyKey": "sw-mkr-001",
                    }
                },
            ),
            None,
        )
        assert conflict["errorCode"] == "CONFLICT"
        import json as _json

        fingerprint = _json.dumps(
            {
                "unitType": "Pack",
                "unitNumber": "1",
                "city": "X",
                "state": "CO",
                "idempotencyKey": "sw-mkr-002",
                "actor": ACCOUNT_A,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#createUnit#sw-mkr-002",
                "idemFingerprint": fingerprint,
            }
        )
        broken = handler(
            _event(
                "createUnit",
                {
                    "input": {
                        "unitType": "Pack",
                        "unitNumber": "1",
                        "city": "X",
                        "state": "CO",
                        "idempotencyKey": "sw-mkr-002",
                    }
                },
            ),
            None,
        )
        assert broken["errorCode"] == "INTERNAL_ERROR"

    def test_replay_race_maps_to_conflict(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_operations

        _seed_unit(t)
        marker_entry_holder: Dict[str, Any] = {}

        def fake_execute(plan: Any, **kwargs: Any) -> None:
            marker_entry_holder["entry"] = plan[-1]["Put"]
            raise TransactionCancelledError([len(plan) - 1])

        monkeypatch.setattr(unit_operations, "execute_transaction", fake_execute)
        from src.utils.errors import AppError

        with pytest.raises(AppError) as exc_info:
            unit_operations._create_unit_invite(
                _event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "sw-race-001"}), None
            )
        assert exc_info.value.error_code == "CONFLICT"

    def test_throttle_race_over_limit(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from datetime import datetime, timezone

        from src.handlers import unit_operations

        monkeypatch.setattr(
            unit_operations.tables.public_order_throttles,
            "update_item",
            MagicMock(return_value={"Attributes": {"attempts": 11}}),
        )
        from src.utils.errors import AppError

        with pytest.raises(AppError) as exc_info:
            unit_operations._record_failed_redemption(ACCOUNT_B, datetime.now(timezone.utc))
        assert exc_info.value.error_code == "RATE_LIMIT_EXCEEDED"

    def test_revoke_grant_replay_and_version_mismatch(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler

        _seed_unit(t)
        t["units"].put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": f"GRANT#{ACCOUNT_B}",
                "accountId": ACCOUNT_B,
                "role": "UNIT_ADMIN",
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "2026-11-01T00:00:00Z",
            }
        )
        metadata = t["units"].get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        metadata["adminCount"] = 2
        t["units"].put_item(Item=metadata)
        args = {
            "unitId": "unit-1",
            "accountId": ACCOUNT_B,
            "expectedVersion": 5,
            "idempotencyKey": "sw-rg-repl",
        }
        stale = handler(_event("revokeUnitAccessGrant", args), None)
        assert stale["errorCode"] == "CONFLICT"

    def test_revoke_grant_cancel_mapping(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_operations
        from src.utils.errors import AppError

        _seed_unit(t)
        t["units"].put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": f"GRANT#{ACCOUNT_B}",
                "accountId": ACCOUNT_B,
                "role": "UNIT_ADMIN",
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "2026-11-01T00:00:00Z",
            }
        )
        metadata = t["units"].get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        metadata["adminCount"] = 2
        t["units"].put_item(Item=metadata)

        monkeypatch.setattr(
            unit_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([2]))
        )
        with pytest.raises(AppError) as exc_info:
            unit_operations._revoke_unit_access_grant(
                _event(
                    "revokeUnitAccessGrant",
                    {"unitId": "unit-1", "accountId": ACCOUNT_B, "expectedVersion": 1, "idempotencyKey": "sw-rg-cxl"},
                ),
                None,
            )
        assert exc_info.value.error_code == "CONFLICT"

    def test_my_units_paginates_past_grant_rows(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler

        _seed_unit(t, unit_id="unit-a")
        _seed_unit(t, unit_id="unit-b")
        result = handler(_event("myUnits", {"page": {"limit": 10}}), None)
        assert len(result["items"]) == 2

    def test_my_units_cursor_round_trip_and_tamper(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler
        from src.utils.pagination import encode_cursor

        _seed_unit(t)
        tampered = handler(
            _event(
                "myUnits",
                {"page": {"cursor": encode_cursor("myUnits:OTHER", {"unitId": "unit-1", "itemKey": "METADATA"})}},
            ),
            None,
        )
        assert tampered["errorCode"] == "INVALID_INPUT"

    def test_unit_invites_cursor(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler
        from src.utils.pagination import encode_cursor

        _seed_unit(t)
        bad = handler(
            _event(
                "unitInvites",
                {"unitId": "unit-1", "page": {"cursor": encode_cursor("unitInvites:other", {"x": "y"})}},
            ),
            None,
        )
        assert bad["errorCode"] == "INVALID_INPUT"


class TestUnitCampaignSweep:
    def test_marker_conflict_and_missing_result(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        _seed_unit(t)
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#createUnitCampaign#sw-mk-01",
                "idemFingerprint": "different",
                "idemResult": {},
            }
        )
        conflict = handler(
            _event(
                "createUnitCampaign",
                {
                    "input": {
                        "unitId": "unit-1",
                        "campaignName": "X",
                        "campaignYear": 2026,
                        "catalogId": CATALOG_A,
                        "idempotencyKey": "sw-mk-01",
                    }
                },
            ),
            None,
        )
        assert conflict["errorCode"] == "CONFLICT"

    def test_unauthenticated_caller(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        event = _event("unitCampaigns", {"unitId": "unit-1"})
        del event["identity"]
        assert handler(event, None)["errorCode"] == "UNAUTHORIZED"

    def test_join_unknown_campaign_and_missing_guard(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        # Dangling join: campaign id unknown.
        missing = handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": uc["joinCode"], "campaignId": "CAMPAIGN#ghost", "idempotencyKey": "sw-join-gh"},
            ),
            None,
        )
        assert missing["errorCode"] == "NOT_FOUND"
        # Remove the roster guard row to trip the internal guard check.
        t["unit_campaigns"].delete_item(Key={"unitCampaignId": uc["unitCampaignId"], "itemKey": "GUARD#ROSTER"})
        result = handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-join-gd"},
            ),
            None,
        )
        assert result["errorCode"] == "INTERNAL_ERROR"

    def test_create_year_range_and_code_retry(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_campaign_operations
        from src.handlers.unit_campaign_operations import handler

        _seed_unit(t)
        bad_year = handler(
            _event(
                "createUnitCampaign",
                {
                    "input": {
                        "unitId": "unit-1",
                        "campaignName": "X",
                        "campaignYear": 1999,
                        "catalogId": CATALOG_A,
                        "idempotencyKey": "sw-yr-0001",
                    }
                },
            ),
            None,
        )
        assert bad_year["errorCode"] == "INVALID_INPUT"

        calls = {"n": 0}
        real_taken = unit_campaign_operations._join_code_taken

        def flaky(code: str) -> bool:
            calls["n"] += 1
            return calls["n"] == 1  # first candidate collides

        monkeypatch.setattr(unit_campaign_operations, "_join_code_taken", flaky)
        result = handler(
            _event(
                "createUnitCampaign",
                {
                    "input": {
                        "unitId": "unit-1",
                        "campaignName": "X",
                        "campaignYear": 2026,
                        "catalogId": CATALOG_A,
                        "idempotencyKey": "sw-code-001",
                    }
                },
            ),
            None,
        )
        assert "joinCode" in result
        assert calls["n"] == 2

    def test_update_all_fields(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t)
        result = handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": uc["unitCampaignId"],
                        "campaignName": "Renamed",
                        "campaignYear": 2027,
                        "isActive": True,
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-uc-upd",
                    }
                },
            ),
            None,
        )
        assert result["campaignName"] == "Renamed"
        assert result["campaignYear"] == 2027

    def test_update_validations(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t)
        bad_year = handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": uc["unitCampaignId"],
                        "campaignYear": 3000,
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-uc-yr",
                    }
                },
            ),
            None,
        )
        assert bad_year["errorCode"] == "INVALID_INPUT"
        bad_flag = handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": uc["unitCampaignId"],
                        "isActive": "yes",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-uc-fl",
                    }
                },
            ),
            None,
        )
        assert bad_flag["errorCode"] == "INVALID_INPUT"
        missing = handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": "UC#ghost",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-uc-ms",
                    }
                },
            ),
            None,
        )
        assert missing["errorCode"] == "NOT_FOUND"

    def test_remove_membership_cancel_mappings(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_campaign_operations
        from src.utils.errors import AppError

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        handler_join = unit_campaign_operations.handler
        membership = handler_join(
            _event(
                "joinUnitCampaign",
                {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-rm-join"},
            ),
            None,
        )
        monkeypatch.setattr(
            unit_campaign_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([1]))
        )
        with pytest.raises(AppError) as exc_info:
            unit_campaign_operations._remove_unit_campaign_membership(
                _event(
                    "removeUnitCampaignMembership",
                    {
                        "unitCampaignId": membership["unitCampaignId"],
                        "campaignId": CAMPAIGN_A,
                        "expectedMembershipVersion": membership["version"],
                        "expectedGuardVersion": membership["guardVersion"],
                        "idempotencyKey": "sw-rm-guard",
                    },
                ),
                None,
            )
        assert exc_info.value.error_code == "CONFLICT"

    def test_remove_membership_not_found(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        result = handler(
            _event(
                "removeUnitCampaignMembership",
                {
                    "unitCampaignId": uc["unitCampaignId"],
                    "campaignId": CAMPAIGN_A,
                    "expectedMembershipVersion": 1,
                    "expectedGuardVersion": 1,
                    "idempotencyKey": "sw-rm-nf",
                },
            ),
            None,
        )
        assert result["errorCode"] == "NOT_FOUND"

    def test_queries_not_found_and_validation(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        missing = handler(_event("unitCampaign", {"unitCampaignId": "UC#ghost"}), None)
        assert missing["errorCode"] == "NOT_FOUND"
        _seed_unit(t)
        bad_flag = handler(_event("unitCampaigns", {"unitId": "unit-1", "isActive": "yes"}), None)
        assert bad_flag["errorCode"] == "INVALID_INPUT"
        uc = _create_unit_campaign(t)
        bad_status = handler(
            _event("unitCampaignRoster", {"unitCampaignId": uc["unitCampaignId"], "status": "MAYBE"}), None
        )
        assert bad_status["errorCode"] == "INVALID_INPUT"
        missing_roster = handler(_event("unitCampaignRoster", {"unitCampaignId": "UC#ghost"}), None)
        assert missing_roster["errorCode"] == "NOT_FOUND"

    def test_listing_and_roster_cursors(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler
        from src.utils.pagination import encode_cursor

        _seed_unit(t)
        bad_list = handler(
            _event(
                "unitCampaigns",
                {"unitId": "unit-1", "page": {"cursor": encode_cursor("unitCampaigns:unit-1:True", {"u": "x"})}},
            ),
            None,
        )
        assert bad_list["errorCode"] == "INVALID_INPUT"
        uc = handler(
            _event(
                "createUnitCampaign",
                {
                    "input": {
                        "unitId": "unit-1",
                        "campaignName": "S&S",
                        "campaignYear": 2026,
                        "catalogId": CATALOG_A,
                        "idempotencyKey": "sw-ls-cur",
                    }
                },
            ),
            None,
        )
        bad_roster = handler(
            _event(
                "unitCampaignRoster",
                {
                    "unitCampaignId": uc["unitCampaignId"],
                    "page": {"cursor": encode_cursor("roster:other:None", {"u": "x"})},
                },
            ),
            None,
        )
        assert bad_roster["errorCode"] == "INVALID_INPUT"

    def test_catalog_missing(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        _seed_unit(t)
        uc = handler(
            _event(
                "createUnitCampaign",
                {
                    "input": {
                        "unitId": "unit-1",
                        "campaignName": "S&S",
                        "campaignYear": 2026,
                        "catalogId": "CATALOG#dangling",
                        "idempotencyKey": "sw-cat-mis",
                    }
                },
            ),
            None,
        )
        result = handler(_event("unitCampaignCatalog", {"unitCampaignId": uc["unitCampaignId"]}), None)
        assert result["errorCode"] == "NOT_FOUND"


class TestParticipantSweep:
    def test_preview_catalog_missing_uses_empty_name(self, t: Dict[str, Any]) -> None:
        from src.handlers.participant_data import handler

        _seed_unit(t)
        uc_table = t["unit_campaigns"]
        uc_table.put_item(
            Item={
                "unitCampaignId": "uc-1",
                "itemKey": "METADATA",
                "unitId": "unit-1",
                "campaignName": "S&S",
                "campaignYear": 2026,
                "catalogId": "CATALOG#dangling",
                "joinCode": "JOINCODE1234567",
                "isActive": True,
                "version": 1,
                "createdAt": "t",
                "updatedAt": "t",
                "createdByAccountId": ACCOUNT_A,
            }
        )
        t["units"].put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": "JOIN#JOINCODE1234567",
                "metadataKey": "JOINCODE1234567",
                "unitCampaignId": "uc-1",
                "createdAt": "t",
                "status": "ACTIVE",
            }
        )
        result = handler(_event("unitCampaignJoinInfo", {"joinCode": "JOINCODE1234567"}, sub="user-789"), None)
        assert result["catalogName"] == ""
        assert result["campaignName"] == "S&S"

    def test_preview_missing_arguments(self, t: Dict[str, Any]) -> None:
        from src.handlers.participant_data import handler

        result = handler(_event("unitCampaignJoinInfo", {}), None)
        assert result["errorCode"] == "INVALID_INPUT"


class TestFinalCoverage:
    def test_execute_or_replay_bare_reraise(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_operations

        _seed_unit(t)
        monkeypatch.setattr(
            unit_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0]))
        )
        with pytest.raises(TransactionCancelledError):
            unit_operations._create_unit_invite(
                _event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "sw-bare-001"}), None
            )

    def test_revoke_grant_replay_and_marker_race(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_operations
        from src.handlers.unit_operations import handler
        from src.utils.errors import AppError

        _seed_unit(t)
        t["units"].put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": f"GRANT#{ACCOUNT_B}",
                "accountId": ACCOUNT_B,
                "role": "UNIT_ADMIN",
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "2026-11-01T00:00:00Z",
            }
        )
        metadata = t["units"].get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        metadata["adminCount"] = 2
        t["units"].put_item(Item=metadata)
        args = {
            "unitId": "unit-1",
            "accountId": ACCOUNT_B,
            "expectedVersion": 1,
            "idempotencyKey": "sw-rg-race",
        }
        first = handler(_event("revokeUnitAccessGrant", args), None)
        assert first["adminCount"] == 1
        replayed = handler(_event("revokeUnitAccessGrant", args), None)
        assert replayed == first
        # Marker race: a cancel on the marker index maps to CONFLICT. Re-seed
        # the grant + count so the plan actually reaches execution.
        t["units"].put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": f"GRANT#{ACCOUNT_B}",
                "accountId": ACCOUNT_B,
                "role": "UNIT_ADMIN",
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "2026-11-01T00:00:00Z",
            }
        )
        metadata = t["units"].get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        metadata["adminCount"] = 2
        t["units"].put_item(Item=metadata)
        monkeypatch.setattr(
            unit_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([3]))
        )
        with pytest.raises(AppError) as exc_info:
            unit_operations._revoke_unit_access_grant(
                _event(
                    "revokeUnitAccessGrant",
                    {"unitId": "unit-1", "accountId": ACCOUNT_B, "expectedVersion": 2, "idempotencyKey": "sw-rg-r2"},
                ),
                None,
            )
        assert exc_info.value.error_code == "CONFLICT"

    def test_my_units_fetch_more_loop(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers.unit_operations import handler
        from src.utils.dynamodb import tables as util_tables

        _seed_unit(t)
        real_query = util_tables.units.query

        def paged_query(**kwargs: Any) -> Dict[str, Any]:
            if "ExclusiveStartKey" not in kwargs:
                # First page: only the grant row, with more pages behind it.
                return {
                    "Items": [
                        {
                            "unitId": "unit-1",
                            "itemKey": f"GRANT#{ACCOUNT_A}",
                            "accountId": ACCOUNT_A,
                        }
                    ],
                    "LastEvaluatedKey": {"accountId": ACCOUNT_A, "unitId": "unit-1"},
                }
            metadata = t["units"].get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
            return {"Items": [metadata]}

        monkeypatch.setattr(util_tables.units, "query", paged_query)
        result = handler(_event("myUnits", {"page": {"limit": 10}}), None)
        assert len(result["items"]) == 1
        assert result["items"][0]["unitId"] == "unit-1"

    def test_campaign_marker_missing_result(self, t: Dict[str, Any]) -> None:
        import json as _json

        from src.handlers.unit_campaign_operations import handler

        _seed_unit(t)
        fingerprint = _json.dumps(
            {"unitCampaignId": "UC#anything", "expectedVersion": 1, "idempotencyKey": "sw-mr-01", "actor": ACCOUNT_A},
            sort_keys=True,
            separators=(",", ":"),
        )
        t["units"].put_item(
            Item={
                "unitId": "__IDEM__",
                "itemKey": f"{ACCOUNT_A}#updateUnitCampaign#sw-mr-01",
                "idemFingerprint": fingerprint,
            }
        )
        result = handler(
            _event(
                "updateUnitCampaign",
                {
                    "input": {
                        "unitCampaignId": "UC#anything",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-mr-01",
                    }
                },
            ),
            None,
        )
        assert result["errorCode"] == "INTERNAL_ERROR"

    def test_campaign_replay_race_bare_reraise(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_campaign_operations

        _seed_unit(t)
        monkeypatch.setattr(
            unit_campaign_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0]))
        )
        with pytest.raises(TransactionCancelledError):
            unit_campaign_operations._create_unit_campaign(
                _event(
                    "createUnitCampaign",
                    {
                        "input": {
                            "unitId": "unit-1",
                            "campaignName": "X",
                            "campaignYear": 2026,
                            "catalogId": CATALOG_A,
                            "idempotencyKey": "sw-br-0001",
                        }
                    },
                ),
                None,
            )

    def test_join_replay_and_display_name_none(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        args = {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-jr-0001"}
        first = handler(_event("joinUnitCampaign", args), None)
        assert first["profileDisplayName"] == "Scout Sam"
        replayed = handler(_event("joinUnitCampaign", args), None)
        assert replayed == first
        created2 = handler(
            _event(
                "createUnitCampaign",
                {
                    "input": {
                        "unitId": "unit-1",
                        "campaignName": "Second",
                        "campaignYear": 2026,
                        "catalogId": CATALOG_A,
                        "idempotencyKey": "sw-jr-0002",
                    }
                },
            ),
            None,
        )
        joined = handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": created2["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-jr-0003"},
            ),
            None,
        )
        assert joined["profileDisplayName"] == "Scout Sam"
        # Deleting the profile after the join leaves the roster projection
        # without a display name (None), without touching the membership row.
        t["profiles"].delete_item(Key={"ownerAccountId": ACCOUNT_A, "profileId": PROFILE_A})
        roster = handler(
            _event("unitCampaignRoster", {"unitCampaignId": created2["unitCampaignId"], "page": {"limit": 10}}),
            None,
        )
        assert roster["items"][0]["profileDisplayName"] is None

    def test_authoritative_campaign_missing_after_pointer(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        # GSI pointer row exists but the base row is gone (stale projection).
        t["campaigns"].delete_item(Key={"profileId": PROFILE_A, "campaignId": CAMPAIGN_A})
        result = handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-ac-0001"},
            ),
            None,
        )
        assert result["errorCode"] == "NOT_FOUND"

    def test_update_campaign_replay(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t, "sw-uc-replay")
        args = {
            "input": {
                "unitCampaignId": uc["unitCampaignId"],
                "campaignName": "Replayed",
                "expectedVersion": 1,
                "idempotencyKey": "sw-uc-repl",
            }
        }
        first = handler(_event("updateUnitCampaign", args), None)
        second = handler(_event("updateUnitCampaign", args), None)
        assert second == first

    def test_remove_replay_and_uc_missing(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        missing = handler(
            _event(
                "removeUnitCampaignMembership",
                {
                    "unitCampaignId": "UC#ghost",
                    "campaignId": CAMPAIGN_A,
                    "expectedMembershipVersion": 1,
                    "expectedGuardVersion": 1,
                    "idempotencyKey": "sw-rm-ms",
                },
            ),
            None,
        )
        assert missing["errorCode"] == "NOT_FOUND"

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        membership = handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-rm-rj"},
            ),
            None,
        )
        args = {
            "unitCampaignId": membership["unitCampaignId"],
            "campaignId": CAMPAIGN_A,
            "expectedMembershipVersion": membership["version"],
            "expectedGuardVersion": membership["guardVersion"],
            "idempotencyKey": "sw-rm-repl",
        }
        first = handler(_event("removeUnitCampaignMembership", args), None)
        second = handler(_event("removeUnitCampaignMembership", args), None)
        assert second == first

    def test_remove_cancel_mappings_marker_and_member(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_campaign_operations
        from src.utils.errors import AppError

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        membership = unit_campaign_operations.handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-rc-join"},
            ),
            None,
        )
        base_args = {
            "unitCampaignId": membership["unitCampaignId"],
            "campaignId": CAMPAIGN_A,
            "expectedMembershipVersion": membership["version"],
            "expectedGuardVersion": membership["guardVersion"],
        }
        # Member version lost the race.
        monkeypatch.setattr(
            unit_campaign_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0]))
        )
        with pytest.raises(AppError) as exc_info:
            unit_campaign_operations._remove_unit_campaign_membership(
                _event("removeUnitCampaignMembership", {**base_args, "idempotencyKey": "sw-rc-mem"}), None
            )
        assert exc_info.value.error_code == "CONFLICT"
        # Marker race.
        monkeypatch.setattr(
            unit_campaign_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([3]))
        )
        with pytest.raises(AppError) as exc_info2:
            unit_campaign_operations._remove_unit_campaign_membership(
                _event("removeUnitCampaignMembership", {**base_args, "idempotencyKey": "sw-rc-mkr"}), None
            )
        assert exc_info2.value.error_code == "CONFLICT"
        # Unknown failure index re-raises.
        monkeypatch.setattr(
            unit_campaign_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([2]))
        )
        with pytest.raises(TransactionCancelledError):
            unit_campaign_operations._remove_unit_campaign_membership(
                _event("removeUnitCampaignMembership", {**base_args, "idempotencyKey": "sw-rc-raw"}), None
            )

    def test_listing_fetch_more_loop(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers.unit_campaign_operations import handler
        from src.utils.dynamodb import tables as util_tables

        uc = _create_unit_campaign(t)
        real_query = util_tables.unit_campaigns.query
        calls = {"n": 0}

        def paged_query(**kwargs: Any) -> Dict[str, Any]:
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "Items": [
                        {
                            "unitCampaignId": uc["unitCampaignId"],
                            "itemKey": "GUARD#ROSTER",
                            "unitId": "unit-1",
                            "createdAt": "t",
                        }
                    ],
                    "LastEvaluatedKey": {"unitId": "unit-1", "createdAt": "t"},
                }
            metadata = t["unit_campaigns"].get_item(
                Key={"unitCampaignId": uc["unitCampaignId"], "itemKey": "METADATA"}
            )["Item"]
            return {"Items": [metadata]}

        monkeypatch.setattr(util_tables.unit_campaigns, "query", paged_query)
        result = handler(_event("unitCampaigns", {"unitId": "unit-1", "page": {"limit": 10}}), None)
        assert len(result["items"]) == 1

    def test_roster_fetch_more_loop(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers.unit_campaign_operations import handler

        uc = _create_unit_campaign(t)
        _seed_profile_campaign_catalog(t)
        handler(
            _event(
                "joinUnitCampaign",
                {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "sw-rf-join"},
            ),
            None,
        )
        from src.utils.dynamodb import tables as util_tables

        real_query = util_tables.unit_campaigns.query
        calls = {"n": 0}

        def paged_query(**kwargs: Any) -> Dict[str, Any]:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"Items": [], "LastEvaluatedKey": {"unitCampaignId": uc["unitCampaignId"], "itemKey": "A"}}
            member = t["unit_campaigns"].get_item(
                Key={"unitCampaignId": uc["unitCampaignId"], "itemKey": f"MEMBER#{PROFILE_A}"}
            )["Item"]
            return {"Items": [member]}

        monkeypatch.setattr(util_tables.unit_campaigns, "query", paged_query)
        result = handler(
            _event("unitCampaignRoster", {"unitCampaignId": uc["unitCampaignId"], "page": {"limit": 10}}), None
        )
        assert len(result["items"]) == 1

    def test_catalog_uc_missing_and_dispatcher_unknown(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_campaign_operations import handler

        missing = handler(_event("unitCampaignCatalog", {"unitCampaignId": "UC#ghost"}), None)
        assert missing["errorCode"] == "NOT_FOUND"
        unknown = handler(_event("mysteryField", {}), None)
        assert unknown["errorCode"] == "INTERNAL_ERROR"


class TestBranchArcs:
    def test_find_duplicate_continues_past_non_metadata_rows(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import _find_duplicate_geography

        _seed_unit(t)
        # A non-METADATA row sharing the key must be skipped, not returned.
        t["units"].put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": "INVITE#QQQQ8888QQQQ8888",
                "metadataKey": "pack|9999|aurora|co",
                "inviteCode": "QQQQ8888QQQQ8888",
                "createdAt": "t",
            }
        )
        assert _find_duplicate_geography("pack|9999|aurora|co", exclude_unit_id=None) is None
        assert _find_duplicate_geography("pack|9999|aurora|co", exclude_unit_id="unit-1") is None

    def test_update_unit_display_name_only(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler

        _seed_unit(t)
        result = handler(
            _event(
                "updateUnit",
                {
                    "input": {
                        "unitId": "unit-1",
                        "displayName": "Renamed Pack",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-dn-0001",
                    }
                },
            ),
            None,
        )
        assert result["displayName"] == "Renamed Pack"
        assert result["version"] == 2

    def test_invite_code_collision_retries(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_operations
        from src.utils.dynamodb import tables as util_tables

        _seed_unit(t)
        calls = {"n": 0}
        real_get = util_tables.units.get_item

        def flaky_get(**kwargs: Any) -> Dict[str, Any]:
            key = kwargs.get("Key", {})
            if str(key.get("itemKey", "")).startswith("INVITE#"):
                calls["n"] += 1
                if calls["n"] == 1:
                    return {"Item": {"unitId": "unit-1", "itemKey": "INVITE#TAKEN00000000"}}
            return real_get(**kwargs)

        monkeypatch.setattr(util_tables.units, "get_item", flaky_get)
        result = unit_operations.handler(
            _event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "sw-ic-0001"}), None
        )
        assert "inviteCode" in result
        assert calls["n"] >= 2

    def test_revoke_grant_unknown_cancel_index_reraises(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_operations

        _seed_unit(t)
        t["units"].put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": f"GRANT#{ACCOUNT_B}",
                "accountId": ACCOUNT_B,
                "role": "UNIT_ADMIN",
                "createdByAccountId": ACCOUNT_A,
                "createdAt": "2026-11-01T00:00:00Z",
            }
        )
        metadata = t["units"].get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        metadata["adminCount"] = 2
        t["units"].put_item(Item=metadata)
        monkeypatch.setattr(
            unit_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([0]))
        )
        with pytest.raises(TransactionCancelledError):
            unit_operations._revoke_unit_access_grant(
                _event(
                    "revokeUnitAccessGrant",
                    {"unitId": "unit-1", "accountId": ACCOUNT_B, "expectedVersion": 1, "idempotencyKey": "sw-rg-raw"},
                ),
                None,
            )

    def test_campaign_marker_race_conflict(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_campaign_operations
        from src.utils.errors import AppError

        _seed_unit(t)
        monkeypatch.setattr(
            unit_campaign_operations, "execute_transaction", MagicMock(side_effect=TransactionCancelledError([3]))
        )
        with pytest.raises(AppError) as exc_info:
            unit_campaign_operations._create_unit_campaign(
                _event(
                    "createUnitCampaign",
                    {
                        "input": {
                            "unitId": "unit-1",
                            "campaignName": "X",
                            "campaignYear": 2026,
                            "catalogId": CATALOG_A,
                            "idempotencyKey": "sw-cm-race",
                        }
                    },
                ),
                None,
            )
        assert exc_info.value.error_code == "CONFLICT"

    def test_authoritative_campaign_base_row_missing(self, t: Dict[str, Any], monkeypatch: Any) -> None:
        from src.handlers import unit_campaign_operations
        from src.utils.errors import AppError

        monkeypatch.setattr(
            unit_campaign_operations,
            "_find_campaign_owner",
            MagicMock(return_value={"profileId": PROFILE_A, "campaignId": CAMPAIGN_A}),
        )
        with pytest.raises(AppError) as exc_info:
            unit_campaign_operations._authoritative_campaign(CAMPAIGN_A)
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_update_unit_geography_unchanged_arc(self, t: Dict[str, Any]) -> None:
        from src.handlers.unit_operations import handler

        _seed_unit(t)
        # Canonical (unsuffixed) metadataKey: a displayName-only update leaves
        # the geography key unchanged, exercising the no-op branch.
        metadata = t["units"].get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        metadata["metadataKey"] = "pack|9999|denver|co"
        t["units"].put_item(Item=metadata)
        result = handler(
            _event(
                "updateUnit",
                {
                    "input": {
                        "unitId": "unit-1",
                        "displayName": "Same Geography",
                        "expectedVersion": 1,
                        "idempotencyKey": "sw-geo-arc",
                    }
                },
            ),
            None,
        )
        assert result["displayName"] == "Same Geography"
