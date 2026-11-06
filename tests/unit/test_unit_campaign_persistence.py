"""Leaves 1.4.1/1.4.2: UnitCampaign data + join-code pointer, membership + guard.

Named contract tests:

- 1.4.1: Unit Campaign persistence and the join-code pointer. The pointer row
  is ``JOIN_CODE#<code>`` / ``UNIT_CAMPAIGN#<id>`` (data model §6.2); codes are
  16-char uppercase alphanumeric (§6.6); unknown, dangling, or inactive codes
  are NOT_FOUND without disclosing other Units (UNIT-Q-06); pointer collisions
  are regenerated, and unresolvable collisions fail INTERNAL_ERROR; ``catalogId``
  is immutable once stored (CAMP-M-02-02); campaign-scoped idempotency markers
  land in the ``unit_campaigns`` table (§8.9).
- 1.4.2: membership + guard persistence. A Scout campaign has at most one
  ACTIVE membership, guarded by the ``SCOUT_CAMPAIGN#<id>`` / ``MEMBERSHIP_GUARD``
  row whose ``membershipVersion`` mirrors the membership version; removal keeps
  the row with REMOVED status and clears the guard target while the Campaign
  keeps its joined-scope link (API-FIX-05); removed history does not block a
  new join target.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.handlers import unit_campaign_operations as ucco
from src.handlers.unit_campaign_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx


def _seed_all(
    units_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
) -> dict:
    return fx.seed_show_sell_fixtures(
        units_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
    )


def _campaign_row(unit_campaigns_table: Any, unit_campaign_id: str) -> dict:
    return unit_campaigns_table.get_item(
        Key={"pk": f"UNIT_CAMPAIGN#{unit_campaign_id}", "sk": "METADATA"}, ConsistentRead=True
    )["Item"]


def _pointer_rows(unit_campaigns_table: Any, join_code: str) -> list:
    return unit_campaigns_table.query(
        KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"JOIN_CODE#{join_code}"}
    )["Items"]


def _membership_row(unit_campaigns_table: Any, unit_campaign_id: str, profile_id: str) -> dict:
    return unit_campaigns_table.get_item(
        Key={"pk": f"UNIT_CAMPAIGN#{unit_campaign_id}", "sk": f"MEMBERSHIP#{profile_id}"}, ConsistentRead=True
    )["Item"]


def _guard_row(unit_campaigns_table: Any, campaign_id: str) -> dict:
    return unit_campaigns_table.get_item(
        Key={"pk": f"SCOUT_CAMPAIGN#{campaign_id}", "sk": "MEMBERSHIP_GUARD"}, ConsistentRead=True
    )["Item"]


def _markers(unit_campaigns_table: Any) -> list:
    return [i for i in unit_campaigns_table.scan()["Items"] if i["pk"].startswith("IDEM#")]


# ---------------------------------------------------------------------------
# 1.4.1: Unit Campaign data + join-code pointer
# ---------------------------------------------------------------------------


class TestUnitCampaignKeyShapes:
    def test_metadata_rows_use_the_data_model_key_shape(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        for unit_campaign_id, spec in fx.UNIT_CAMPAIGNS.items():
            item = _campaign_row(unit_campaigns_table, unit_campaign_id)
            assert item["pk"] == f"UNIT_CAMPAIGN#{unit_campaign_id}"
            assert item["sk"] == "METADATA"
            assert item["unitCampaignId"] == unit_campaign_id
            assert item["unitId"] == spec["unitId"]
            assert item["joinCode"] == spec["joinCode"]
            assert item["isActive"] == spec["isActive"]

    def test_pointer_rows_use_the_data_model_key_shape(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        for unit_campaign_id, spec in fx.UNIT_CAMPAIGNS.items():
            rows = _pointer_rows(unit_campaigns_table, spec["joinCode"])
            assert len(rows) == 1
            assert rows[0]["pk"] == f"JOIN_CODE#{spec['joinCode']}"
            assert rows[0]["sk"] == f"UNIT_CAMPAIGN#{unit_campaign_id}"
            assert rows[0]["unitCampaignId"] == unit_campaign_id

    def test_fixture_join_codes_are_sixteen_character_uppercase_alphanumeric(self) -> None:
        for spec in fx.UNIT_CAMPAIGNS.values():
            code = spec["joinCode"]
            assert len(code) == 16
            assert all(ch in ucco.JOIN_CODE_ALPHABET for ch in code)


class TestJoinCodePointerResolution:
    def test_unknown_code_returns_not_found_for_join_info(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        event = fx.unit_campaign_operation_event(
            "unitCampaignJoinInfo", "Riley", arguments={"joinCode": "ZZZZ9999ZZZZ9999"}
        )
        fx.assert_is_error(lambda_handler(event, None), "NOT_FOUND")

    def test_inactive_campaign_code_returns_not_found_without_disclosing_the_unit(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        """The OLD campaign is inactive; its code must not resolve to a preview."""
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        old_code = fx.UNIT_CAMPAIGNS[fx.PACK_3149_OLD]["joinCode"]
        event = fx.unit_campaign_operation_event("unitCampaignJoinInfo", "Riley", arguments={"joinCode": old_code})
        payload = fx.assert_is_error(lambda_handler(event, None), "NOT_FOUND")
        assert "Pack 3149" not in str(payload)

    def test_malformed_codes_are_not_found(self, unit_campaigns_table: Any) -> None:
        for bad in ("SHORT", "JOINPK3149FALL01!", "join pk 3149 fall", 123):
            event = fx.unit_campaign_operation_event("unitCampaignJoinInfo", "Riley", arguments={"joinCode": bad})
            fx.assert_is_error(lambda_handler(event, None), "NOT_FOUND")

    def test_lowercase_codes_resolve_case_insensitively(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed_all(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        code = fx.UNIT_CAMPAIGNS[fx.PACK_3149_FALL]["joinCode"].lower()
        event = fx.unit_campaign_operation_event("unitCampaignJoinInfo", "Riley", arguments={"joinCode": code})
        payload = lambda_handler(event, None)
        assert not payload.get("__isError"), payload
        assert payload["unitDisplayName"]


class TestJoinCodeCollisionHandling:
    def test_pointer_collision_regenerates_a_unique_code(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_all(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)

        class _FakeUuid4:
            def __init__(self, hex_value: str) -> None:
                self.hex = hex_value

        taken = "abcd1234efab9876"
        fresh = "fedcba9876543210"
        # First draw collides with the pre-existing pointer row; every later
        # draw (including logger correlation ids racing the reservation loop)
        # returns the known-free code.
        state = {"collided": False}

        def _fake_uuid4() -> Any:
            if not state["collided"]:
                state["collided"] = True
                return _FakeUuid4(taken + "00")
            return _FakeUuid4(fresh + "00")

        monkeypatch.setattr(ucco.uuid, "uuid4", _fake_uuid4)
        unit_campaigns_table.put_item(Item=fx.join_code_pointer_item(taken.upper(), "uc-taken-elsewhere"))
        event = fx.unit_campaign_operation_event(
            "createUnitCampaign",
            "Avery",
            input={
                "unitId": fx.PACK_3149,
                "campaignName": "Collision Retry Campaign",
                "campaignYear": 2026,
                "catalogId": "CATALOG#fixture-default",
                "idempotency": {"idempotencyKey": "collision-key-1"},
            },
        )
        payload = lambda_handler(event, None)
        assert not payload.get("__isError"), payload
        assert payload["joinCode"] == fresh.upper()
        assert len(_pointer_rows(unit_campaigns_table, fresh.upper())) == 1

    def test_unresolvable_collisions_fail_internal_error(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_all(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)

        class _FakeUuid4:
            hex = "abcd1234efab987600"

        monkeypatch.setattr(ucco.uuid, "uuid4", lambda: _FakeUuid4())
        unit_campaigns_table.put_item(Item=fx.join_code_pointer_item("ABCD1234EFAB9876", "uc-taken-elsewhere"))
        event = fx.unit_campaign_operation_event(
            "createUnitCampaign",
            "Avery",
            input={
                "unitId": fx.PACK_3149,
                "campaignName": "Doomed Campaign",
                "campaignYear": 2026,
                "catalogId": "CATALOG#fixture-default",
                "idempotency": {"idempotencyKey": "collision-key-2"},
            },
        )
        fx.assert_is_error(lambda_handler(event, None), "INTERNAL_ERROR")


class TestCreateWritesMarkerToUnitCampaignsTable:
    def test_create_marks_the_unit_campaigns_table_with_completed_result(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed_all(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = fx.unit_campaign_operation_event(
            "createUnitCampaign",
            "Avery",
            input={
                "unitId": fx.PACK_3149,
                "campaignName": "Marker Campaign",
                "campaignYear": 2026,
                "catalogId": "CATALOG#fixture-default",
                "idempotency": {"idempotencyKey": "marker-key-1"},
            },
        )
        payload = lambda_handler(event, None)
        assert not payload.get("__isError"), payload
        markers = _markers(unit_campaigns_table)
        assert len(markers) == 1
        marker = markers[0]
        assert marker["pk"].startswith(f"IDEM#{fx.account_id('Avery')}#createUnitCampaign#")
        assert marker["status"] == "COMPLETED"
        assert marker["resultId"] == payload["unitCampaignId"]
        assert marker["fingerprint"].startswith("sha256:")


# ---------------------------------------------------------------------------
# 1.4.2: membership + guard
# ---------------------------------------------------------------------------


class TestMembershipAndGuardShapes:
    def test_fixture_membership_rows_use_the_data_model_key_shape(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        devon = fx.PROFILES["Devon"]
        membership = _membership_row(unit_campaigns_table, fx.PACK_3149_FALL, devon["profileId"])
        assert membership["pk"] == f"UNIT_CAMPAIGN#{fx.PACK_3149_FALL}"
        assert membership["sk"] == f"MEMBERSHIP#{devon['profileId']}"
        assert membership["campaignId"] == devon["campaignId"]
        assert membership["profileId"] == devon["profileId"]
        assert membership["status"] == "ACTIVE"
        assert membership["version"] == 1

    def test_active_guard_points_at_the_unit_campaign_with_the_membership_version(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        guard = _guard_row(unit_campaigns_table, fx.PROFILES["Devon"]["campaignId"])
        assert guard["pk"] == f"SCOUT_CAMPAIGN#{fx.PROFILES['Devon']['campaignId']}"
        assert guard["sk"] == "MEMBERSHIP_GUARD"
        assert guard["activeUnitCampaignId"] == fx.PACK_3149_FALL
        assert guard["membershipVersion"] == 1

    def test_removed_guard_has_no_active_target_and_mirrors_the_bumped_version(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        guard = _guard_row(unit_campaigns_table, fx.PROFILES["Emery"]["campaignId"])
        # Nullable activeUnitCampaignId is an ABSENT attribute, never a null value.
        assert "activeUnitCampaignId" not in guard
        assert guard["membershipVersion"] == 2

    def test_removed_membership_keeps_audit_fields_and_the_campaign_keeps_its_link(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any, unit_campaigns_table: Any
    ) -> None:
        """API-FIX-05 fixture contract: removal history is retained, and the
        Scout Campaign's joined-scope link survives the removal."""
        fx.seed_show_sell_fixtures(
            units_table,
            profiles_table=profiles_table,
            campaigns_table=campaigns_table,
            shares_table=shares_table,
            unit_campaigns_table=unit_campaigns_table,
        )
        emery = fx.PROFILES["Emery"]
        membership = _membership_row(unit_campaigns_table, fx.PACK_3149_OLD, emery["profileId"])
        assert membership["status"] == "REMOVED"
        assert membership["version"] == 2
        assert membership["removedByAccountId"] == fx.account_id("Avery")
        assert membership["removedAt"]
        campaign = campaigns_table.get_item(
            Key={"profileId": emery["profileId"], "campaignId": emery["campaignId"]}, ConsistentRead=True
        )["Item"]
        assert campaign["unitId"] == fx.PACK_3149
        assert campaign["unitCampaignId"] == fx.PACK_3149_OLD
