"""Leaves 1.5.1/1.5.2: createUnitCampaign and updateUnitCampaign contract tests.

Named contract tests:

- CAMP-M-01: createUnitCampaign. Unit Admins create Unit Campaigns; non-admins
  are FORBIDDEN; names are 1-100 characters; years are integers inside
  1900-2200; ``catalogId`` must reference a usable catalog (owned, public, or
  admin-managed; a private foreign or deleted catalog is NOT_FOUND); the
  generated join code is a 16-char uppercase alphanumeric; the new campaign
  starts at version 1 with ``isActive`` true; a missing idempotency key is
  INVALID_INPUT (IDEM-01); retries replay without a second write (IDEM-01) and
  a reused key with different content is rejected (IDEM-02).
- CAMP-M-02 / VER-01: updateUnitCampaign. Unit Admins may rename, restate the
  year, and activate/deactivate; the version increments monotonically; a stale
  ``expectedVersion`` fails CONFLICT; deactivation changes no other row;
  unknown ids are NOT_FOUND.
- CAMP-M-02-02: catalogId is immutable: update never accepts or rewrites it.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.handlers.unit_campaign_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx


def _seed(
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


def _create_event(
    caller: str,
    *,
    unit_id: str = fx.PACK_3149,
    campaign_name: str = "New Unit Campaign",
    campaign_year: Any = 2026,
    catalog_id: str = "CATALOG#fixture-default",
    key: str = "create-key-1",
) -> dict:
    return fx.unit_campaign_operation_event(
        "createUnitCampaign",
        caller,
        input={
            "unitId": unit_id,
            "campaignName": campaign_name,
            "campaignYear": campaign_year,
            "catalogId": catalog_id,
            "idempotency": {"idempotencyKey": key},
        },
    )


def _create(
    caller: str = "Avery",
    **kwargs: Any,
) -> Any:
    return lambda_handler(_create_event(caller, **kwargs), None)


def _campaign_row(unit_campaigns_table: Any, unit_campaign_id: str) -> dict:
    return unit_campaigns_table.get_item(
        Key={"pk": f"UNIT_CAMPAIGN#{unit_campaign_id}", "sk": "METADATA"}, ConsistentRead=True
    )["Item"]


# ---------------------------------------------------------------------------
# CAMP-M-01: createUnitCampaign
# ---------------------------------------------------------------------------


class TestCreateUnitCampaign:
    def test_unit_admin_creates_a_campaign_with_a_valid_join_code(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _create("Avery")
        assert not payload.get("__isError"), payload
        assert payload["unitId"] == fx.PACK_3149
        assert payload["campaignName"] == "New Unit Campaign"
        assert payload["campaignYear"] == 2026
        assert payload["catalogId"] == "CATALOG#fixture-default"
        assert payload["isActive"] is True
        assert payload["version"] == 1
        assert payload["createdByAccountId"] == fx.account_id("Avery")
        assert payload["createdAt"]
        assert payload["updatedAt"]
        code = payload["joinCode"]
        assert len(code) == 16
        assert all(ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for ch in code)
        row = _campaign_row(unit_campaigns_table, payload["unitCampaignId"])
        assert row["joinCode"] == code
        assert row["catalogId"] == "CATALOG#fixture-default"
        pointer = unit_campaigns_table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": f"JOIN_CODE#{code}"},
        )["Items"]
        assert len(pointer) == 1
        assert pointer[0]["unitCampaignId"] == payload["unitCampaignId"]

    def test_non_admin_cannot_create(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _create("Riley")
        assert payload == {
            "__isError": True,
            "errorCode": "FORBIDDEN",
            "message": "Unit Admin required",
        }

    def test_missing_idempotency_key_is_invalid_input(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = fx.unit_campaign_operation_event(
            "createUnitCampaign",
            "Avery",
            input={
                "unitId": fx.PACK_3149,
                "campaignName": "x",
                "campaignYear": 2026,
                "catalogId": "CATALOG#fixture-default",
            },
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_no_caller_is_unauthorized(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _create_event("Avery")
        event["identity"] = None
        fx.assert_is_error(lambda_handler(event, None), "UNAUTHORIZED")

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "   ",
            "x" * 101,
            123,
            None,
        ],
    )
    def test_invalid_names_are_rejected(
        self,
        name: Any,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _create_event("Avery", campaign_name=name)
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_boundary_name_lengths_are_accepted(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        assert not _create("Avery", campaign_name="x" * 100).get("__isError")

    @pytest.mark.parametrize("year", [1899, 2201, 2026.5, "twenty-six", True])
    def test_invalid_years_are_rejected(
        self,
        year: Any,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _create_event("Avery", campaign_year=year)
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_numeric_string_year_is_accepted(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _create("Avery", campaign_year="2027")
        assert not payload.get("__isError"), payload
        assert payload["campaignYear"] == 2027

    def test_year_bounds_are_accepted(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        for year in (1900, 2200):
            event = _create_event("Avery", campaign_year=year, key=f"year-{year}")
            payload = lambda_handler(event, None)
            assert not payload.get("__isError"), payload
            assert payload["campaignYear"] == year

    def test_unknown_unit_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _create_event("Avery", unit_id="unit-ghost")
        fx.assert_is_error(lambda_handler(event, None), "NOT_FOUND")

    def test_deleted_catalog_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _create_event("Avery", catalog_id="CATALOG#fixture-deleted")
        fx.assert_is_error(lambda_handler(event, None), "NOT_FOUND")

    def test_private_foreign_catalog_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """A catalog owned by another account, not public, not admin-managed."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        catalogs_table.put_item(
            Item=fx.catalog_item("CATALOG#fixture-private", "Private Foreign", owner="Riley", is_public=False)
        )
        event = _create_event("Avery", catalog_id="CATALOG#fixture-private")
        fx.assert_is_error(lambda_handler(event, None), "NOT_FOUND")

    @pytest.mark.parametrize(
        "catalog_id",
        [
            "CATALOG#fixture-default",  # owned by the caller
            "CATALOG#fixture-public",  # visible to all
            "CATALOG#fixture-admin",  # admin-managed
        ],
    )
    def test_owned_public_and_admin_catalogs_are_usable(
        self,
        catalog_id: str,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _create("Avery", catalog_id=catalog_id)
        assert not payload.get("__isError"), payload
        assert payload["catalogId"] == catalog_id

    def test_idempotent_retry_replays_without_a_second_row(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        first = _create("Avery")
        assert not first.get("__isError"), first
        second = _create("Avery")
        assert second == first
        rows = [
            i
            for i in unit_campaigns_table.scan()["Items"]
            if i["pk"] == f"UNIT_CAMPAIGN#{first['unitCampaignId']}" and i["sk"] == "METADATA"
        ]
        assert len(rows) == 1

    def test_reused_key_with_different_content_is_rejected(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        first = _create("Avery")
        assert not first.get("__isError"), first
        payload = _create("Avery", campaign_name="A Different Name")
        assert payload == {
            "__isError": True,
            "errorCode": "INVALID_INPUT",
            "message": "This idempotencyKey was already used with different request content.",
        }


# ---------------------------------------------------------------------------
# CAMP-M-02 / VER-01: updateUnitCampaign
# ---------------------------------------------------------------------------


def _update_event(
    caller: str,
    unit_campaign_id: str,
    *,
    name: Any = None,
    year: Any = None,
    is_active: Any = None,
    expected_version: Any = 1,
    key: str = "update-key-1",
) -> dict:
    input_: dict[str, Any] = {"unitCampaignId": unit_campaign_id, "expectedVersion": expected_version}
    if name is not None:
        input_["campaignName"] = name
    if year is not None:
        input_["campaignYear"] = year
    if is_active is not None:
        input_["isActive"] = is_active
    input_["idempotency"] = {"idempotencyKey": key}
    return fx.unit_campaign_operation_event("updateUnitCampaign", caller, input=input_)


class TestUpdateUnitCampaign:
    def test_admin_updates_name_year_and_active_flag(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _update_event("Avery", fx.PACK_3149_FALL, name="Fall Sale Renamed", year=2027, is_active=False)
        payload = lambda_handler(event, None)
        assert not payload.get("__isError"), payload
        assert payload["campaignName"] == "Fall Sale Renamed"
        assert payload["campaignYear"] == 2027
        assert payload["isActive"] is False
        assert payload["version"] == 2
        assert payload["updatedByAccountId"] == fx.account_id("Avery")
        row = _campaign_row(unit_campaigns_table, fx.PACK_3149_FALL)
        assert row["campaignName"] == "Fall Sale Renamed"
        assert row["campaignYear"] == 2027
        assert row["isActive"] is False

    def test_stale_expected_version_conflicts(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _update_event("Avery", fx.PACK_3149_FALL, name="Stale", expected_version=7)
        payload = lambda_handler(event, None)
        assert payload == {
            "__isError": True,
            "errorCode": "CONFLICT",
            "message": "Unit campaign has been modified",
        }
        row = _campaign_row(unit_campaigns_table, fx.PACK_3149_FALL)
        assert row["version"] == 1

    def test_non_admin_is_forbidden(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _update_event("Devon", fx.PACK_3149_FALL, name="Sneaky")
        payload = lambda_handler(event, None)
        assert payload["errorCode"] == "FORBIDDEN", payload

    def test_unknown_campaign_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _update_event("Avery", "uc-ghost")
        fx.assert_is_error(lambda_handler(event, None), "NOT_FOUND")

    @pytest.mark.parametrize("version", [None, "1", 1.5, True])
    def test_invalid_expected_version_types_are_rejected(
        self,
        version: Any,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _update_event("Avery", fx.PACK_3149_FALL, name="x", expected_version=version)
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_update_without_changes_conflicts_on_any_version(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """An update with no field arguments is a no-op that still must match."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = fx.unit_campaign_operation_event(
            "updateUnitCampaign",
            "Avery",
            input={
                "unitCampaignId": fx.PACK_3149_FALL,
                "expectedVersion": 99,
                "idempotency": {"idempotencyKey": "noop-key"},
            },
        )
        fx.assert_is_error(lambda_handler(event, None), "CONFLICT")

    def test_version_increments_monotonically_across_updates(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        first = lambda_handler(_update_event("Avery", fx.PACK_3149_FALL, name="V2"), None)
        assert not first.get("__isError"), first
        assert first["version"] == 2
        second = lambda_handler(
            _update_event("Avery", fx.PACK_3149_FALL, name="V3", expected_version=2, key="update-key-2"), None
        )
        assert not second.get("__isError"), second
        assert second["version"] == 3

    def test_retry_replays_the_stored_result(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """IDEM-01: a completed retry replays the stored result even if the
        row version has since moved on (the replay gate runs first)."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        first = lambda_handler(_update_event("Avery", fx.PACK_3149_FALL, name="Replayed"), None)
        assert not first.get("__isError"), first
        # The row version advanced after the first call; the same key+content
        # replay must still succeed with the stored result, not CONFLICT.
        replay = lambda_handler(_update_event("Avery", fx.PACK_3149_FALL, name="Replayed"), None)
        assert replay == first
        row = _campaign_row(unit_campaigns_table, fx.PACK_3149_FALL)
        assert row["version"] == 2

    def test_reused_key_with_different_content_is_rejected(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        first = lambda_handler(_update_event("Avery", fx.PACK_3149_FALL, name="One"), None)
        assert not first.get("__isError"), first
        payload = lambda_handler(_update_event("Avery", fx.PACK_3149_FALL, name="Two"), None)
        assert payload["errorCode"] == "INVALID_INPUT", payload

    def test_invalid_is_active_type_is_rejected(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        event = _update_event("Avery", fx.PACK_3149_FALL, is_active="yes")
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")


# ---------------------------------------------------------------------------
# CAMP-M-02-02: catalogId is immutable
# ---------------------------------------------------------------------------


class TestCatalogIdImmutability:
    def test_update_never_rewrites_catalog_id(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        original = _campaign_row(unit_campaigns_table, fx.PACK_3149_FALL)
        payload = lambda_handler(_update_event("Avery", fx.PACK_3149_FALL, name="Renamed Only"), None)
        assert not payload.get("__isError"), payload
        row = _campaign_row(unit_campaigns_table, fx.PACK_3149_FALL)
        assert row["catalogId"] == original["catalogId"]

    def test_membership_and_guard_rows_survive_an_update(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """Deactivation/updates must never dirty joined-campaign rows."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = lambda_handler(_update_event("Avery", fx.PACK_3149_FALL, is_active=False), None)
        assert not payload.get("__isError"), payload
        devon = fx.PROFILES["Devon"]
        membership = unit_campaigns_table.get_item(
            Key={"pk": f"UNIT_CAMPAIGN#{fx.PACK_3149_FALL}", "sk": f"MEMBERSHIP#{devon['profileId']}"},
            ConsistentRead=True,
        )["Item"]
        assert membership["status"] == "ACTIVE"
        assert membership["version"] == 1
        guard = unit_campaigns_table.get_item(
            Key={"pk": f"SCOUT_CAMPAIGN#{devon['campaignId']}", "sk": "MEMBERSHIP_GUARD"}, ConsistentRead=True
        )["Item"]
        assert guard["activeUnitCampaignId"] == fx.PACK_3149_FALL
        campaign = campaigns_table.get_item(
            Key={"profileId": devon["profileId"], "campaignId": devon["campaignId"]}, ConsistentRead=True
        )["Item"]
        assert campaign["unitId"] == fx.PACK_3149
        assert campaign["unitCampaignId"] == fx.PACK_3149_FALL
