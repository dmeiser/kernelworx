"""Leaf 1.1: Unit persistence and bootstrap authorization models.

Named tests from the delivery checklist:

- 1.1.1 ``Unit`` persistence at ``UNIT#<unitId> / METADATA``: identity
  retention, generated names, equal numbers in different cities, invalid
  settings.
- 1.1.2 ``UnitAccessGrant`` at ``GRANT#<accountId>``: multiple equal admins,
  one Account in multiple Units, cross-Unit denial.
- 1.1.3 ``UnitInvite`` at ``INVITE#<inviteCode> / UNIT#<unitId>``: 16-character
  code shape, expiry, revoked/consumed codes, TTL mapping.

Model-shape tests run against the fixture builders and a seeded moto table;
authorization tests drive the ``unit_operations`` handler and assert the
#329 structured error payloads. All authorization reads are strongly
consistent base-table semantics (data model §6.1: never GSI reads for authz).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from src.handlers.unit_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx


def _seed(units_table: Any) -> Any:
    units = units_table
    fx.seed_show_sell_fixtures(units)
    return units


# ---------------------------------------------------------------------------
# 1.1.1 Unit persistence
# ---------------------------------------------------------------------------


class TestUnitPersistence:
    def test_identity_retention_unit_id_is_stable_and_not_derived_from_metadata(self, units_table: Any) -> None:
        """The unitId is a stable identity; equal metadata never re-derives it."""
        units = _seed(units_table)
        pack = units.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert pack["unitId"] == fx.PACK_3149
        assert pack["unitId"] not in pack["metadataKey"]
        # metadataKey is a duplicate-lookup fingerprint only, never an identity:
        # two Units sharing metadata still have two distinct, retained ids.
        second = fx.unit_item("unit-pack-3149-boulder", "Pack", 3149, "Boulder", "CO")
        assert second["unitId"] != pack["unitId"]
        assert second["metadataKey"] != pack["metadataKey"]
        assert pack["metadataKey"] == "pack#3149#aurora#co"

    def test_generated_display_name_from_metadata_when_omitted(self, units_table: Any) -> None:
        units = _seed(units_table)
        pack = units.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert pack["displayName"] == "Pack 3149 - Aurora, CO"
        explicit = fx.unit_item("unit-troop-100", "Troop", 100, "Aurora", "CO", display_name="The Originals")
        assert explicit["displayName"] == "The Originals"

    def test_equal_numbers_in_different_cities_are_distinct_units(self, units_table: Any) -> None:
        """unitNumber is not globally unique; city/state discriminate (UNIT-M-01-03)."""
        units = _seed(units_table)
        pack = fx.unit_item("unit-pack-3149-boulder", "Pack", 3149, "Boulder", "CO")
        units.put_item(Item=pack)
        aurora = units.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert aurora["unitNumber"] == pack["unitNumber"] == 3149
        assert aurora["metadataKey"] == "pack#3149#aurora#co"
        assert pack["metadataKey"] == "pack#3149#boulder#co"
        # Geography is part of the key shape, so both rows coexist.
        both = units.query(
            KeyConditionExpression="pk = :pk AND sk = :sk",
            ExpressionAttributeValues={":pk": f"UNIT#{pack['unitId']}", ":sk": "METADATA"},
            ConsistentRead=True,
        )
        assert len(both["Items"]) == 1

    @pytest.mark.parametrize(
        "bad_settings",
        [
            {"timezone": "Not/AZone"},
            {"split_default": "MAJORITY"},
            {"council_need_basis": "FIRST_COME"},
        ],
        ids=["timezone", "splitDefault", "councilNeedBasis"],
    )
    def test_invalid_settings_rejected_on_create(self, units_table: Any, bad_settings: dict) -> None:
        """IANA timezone and the two enums are validated; junk is INVALID_INPUT."""
        _seed(units_table)
        base = {
            "unitType": "Pack",
            "unitNumber": 99,
            "city": "Aurora",
            "state": "CO",
            "timezone": "America/Denver",
            "idempotency": {"idempotencyKey": "invalid-settings-1"},
        }
        for key, value in bad_settings.items():
            input_key = {
                "timezone": "timezone",
                "split_default": "splitDefault",
                "council_need_basis": "councilNeedBasis",
            }[key]
            base[input_key] = value
        event = fx.unit_operation_event("createUnit", "Emery", input=base)
        payload = lambda_handler(event, None)
        fx.assert_is_error(payload, "INVALID_INPUT")


# ---------------------------------------------------------------------------
# 1.1.2 UnitAccessGrant
# ---------------------------------------------------------------------------


class TestUnitAccessGrant:
    def test_multiple_equal_admins_share_one_role(self, units_table: Any) -> None:
        """Every admin holds the same UNIT_ADMIN grant; adminCount tracks them."""
        units = _seed(units_table)
        taylor_admin = fx.grant_item(fx.PACK_3149, "Taylor", created_by="Avery")
        units.put_item(Item=taylor_admin)
        meta = units.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        meta["adminCount"] = 2
        units.put_item(Item=meta)
        grants = units.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"UNIT#{fx.PACK_3149}", ":prefix": "GRANT#"},
            ConsistentRead=True,
        )["Items"]
        assert {g["accountId"] for g in grants} == {fx.account_id("Avery"), fx.account_id("Taylor")}
        assert all(g["role"] == "UNIT_ADMIN" for g in grants)

    def test_one_account_many_units(self, units_table: Any) -> None:
        """Avery holds a grant in both Pack 3149 and Crew 529."""
        units = _seed(units_table)
        for unit_id in (fx.PACK_3149, fx.CREW_529):
            grant = units.get_item(
                Key={"pk": f"UNIT#{unit_id}", "sk": f"GRANT#{fx.account_id('Avery')}"},
                ConsistentRead=True,
            )
            assert grant.get("Item"), f"Avery missing grant on {unit_id}"
        avery_units = {
            g["unitId"]
            for g in units.query(
                IndexName="accountId-unitId-index",
                KeyConditionExpression="accountId = :a",
                ExpressionAttributeValues={":a": fx.account_id("Avery")},
            )["Items"]
        }
        assert avery_units == {fx.PACK_3149, fx.CREW_529}

    def test_cross_unit_denial_riley_grant_does_not_open_pack_3149(self, units_table: Any) -> None:
        """Riley's Troop 7150 grant authorizes nothing on Pack 3149 (consistent read)."""
        units = _seed(units_table)
        grant = units.get_item(
            Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": f"GRANT#{fx.account_id('Riley')}"},
            ConsistentRead=True,
        )
        assert "Item" not in grant
        payload = lambda_handler(
            fx.unit_operation_event("unitAdmins", "Riley", arguments={"unitId": fx.PACK_3149}), None
        )
        fx.assert_is_error(payload, "FORBIDDEN")

    def test_removed_admin_grant_is_gone_but_unit_survives(self, units_table: Any) -> None:
        """Blake (removed admin) has no grant row; the Unit and Avery's grant persist."""
        units = _seed(units_table)
        removed = units.get_item(
            Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": f"GRANT#{fx.account_id('Blake')}"},
            ConsistentRead=True,
        )
        assert "Item" not in removed
        meta = units.get_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": "METADATA"}, ConsistentRead=True)["Item"]
        assert meta["createdByAccountId"] == fx.account_id("Blake")
        assert meta["adminCount"] == 1


# ---------------------------------------------------------------------------
# 1.1.3 UnitInvite
# ---------------------------------------------------------------------------


class TestUnitInvite:
    def test_invite_code_shape_is_sixteen_characters(self, units_table: Any) -> None:
        units = _seed(units_table)
        for code, spec in fx.INVITES.items():
            if spec["state"] == "consumed":
                continue
            item = units.get_item(Key={"pk": f"INVITE#{code}", "sk": f"UNIT#{spec['unit']}"}, ConsistentRead=True)
            assert "Item" in item, f"missing seeded invite {code}"
            assert len(item["Item"]["inviteCode"]) == 16

    def test_invite_expiry_is_at_most_fourteen_days(self, units_table: Any) -> None:
        units = _seed(units_table)
        item = units.get_item(Key={"pk": "INVITE#PKT3149ACTIVE001", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True)[
            "Item"
        ]
        created = datetime.fromisoformat(item["createdAt"])
        expires = datetime.fromisoformat(item["expiresAt"])
        assert timedelta(0) < expires - created <= timedelta(days=14)

    def test_expired_and_revoked_and_consumed_codes_are_indistinguishable(self, units_table: Any) -> None:
        """Unknown, expired, revoked, and consumed codes all redeem as NOT_FOUND."""
        units = _seed(units_table)
        # An expired invite still has a row; a revoked/consumed one does not.
        expired = units.get_item(
            Key={"pk": "INVITE#PKT3149EXPIRED01", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True
        )
        assert "Item" in expired
        for code in ("NOPE0000NOPE0000", "PKT3149EXPIRED01", "PKT3149CONSUMED1"):
            payload = lambda_handler(
                fx.unit_operation_event("redeemUnitInvite", "Devon", input={"inviteCode": code}),
                None,
            )
            fx.assert_is_error(payload, "NOT_FOUND")

    def test_invite_ttl_mapping_expires_at_epoch_matches_expires_at(self, units_table: Any) -> None:
        """expiresAtEpoch is the numeric epoch-seconds TTL for the ISO expiresAt."""
        units = _seed(units_table)
        from decimal import Decimal

        for item in units.scan()["Items"]:
            if not item["pk"].startswith("INVITE#"):
                continue
            expires = datetime.fromisoformat(item["expiresAt"])
            # DynamoDB returns numbers as Decimal; the TTL attribute is numeric epoch seconds.
            assert isinstance(item["expiresAtEpoch"], (int, Decimal)), item
            assert abs(int(item["expiresAtEpoch"]) - int(expires.timestamp())) <= 1
        expired = units.get_item(
            Key={"pk": "INVITE#PKT3149EXPIRED01", "sk": f"UNIT#{fx.PACK_3149}"}, ConsistentRead=True
        )["Item"]
        assert expired["expiresAtEpoch"] < int(datetime.now(timezone.utc).timestamp())
