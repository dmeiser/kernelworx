"""Leaf 1.5.6: Unit Campaign query surface (UNIT-Q-06..09, AUTH-U).

Named contract tests:

- UNIT-Q-06: unitCampaignJoinInfo(joinCode) previews ``unitCampaignId``,
  ``campaignName``, ``unitDisplayName``, and ``catalogName`` for a valid,
  active code; unknown/malformed/inactive codes are NOT_FOUND; a code whose
  Unit or catalog is missing is NOT_FOUND too. Any authenticated caller in
  possession of the code may preview it (join codes are bearer capabilities).
- UNIT-Q-07: unitCampaign(id) returns the campaign for Unit Admins and null
  for non-admins (never FORBIDDEN); unknown ids are NOT_FOUND.
- UNIT-Q-08: unitCampaigns(unitId, isActive) lists a Unit's campaigns newest
  first, Unit Admin only; non-admins are FORBIDDEN.
- UNIT-Q-09: unitCampaignRoster(unitCampaignId, status) lists memberships
  newest first with optional status filter, Unit Admin only.
- unitCampaignCatalog(id) returns the attached catalog for Unit Admins, null
  for non-admins, and null when the catalog is deleted (never an error).
- AUTH-U: every query returns UNAUTHORIZED without a caller identity.
- PAGE-01: unitCampaigns and unitCampaignRoster honor first/after cursors.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.handlers.unit_campaign_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx

FALL_CODE = fx.UNIT_CAMPAIGNS[fx.PACK_3149_FALL]["joinCode"]
OLD_CODE = fx.UNIT_CAMPAIGNS[fx.PACK_3149_OLD]["joinCode"]


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


def _query(caller: Any, field: str, arguments: dict) -> Any:
    event = fx.unit_campaign_operation_event(field, caller, arguments=arguments)
    return lambda_handler(event, None)


# ---------------------------------------------------------------------------
# UNIT-Q-06: unitCampaignJoinInfo
# ---------------------------------------------------------------------------


class TestUnitCampaignJoinInfo:
    def test_valid_code_previews_name_unit_and_catalog(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _query("Riley", "unitCampaignJoinInfo", {"joinCode": FALL_CODE})
        # The member-safe preview carries NO ids, join code, or settings.
        assert payload == {
            "unitDisplayName": "Pack 3149 - Aurora, CO",
            "campaignName": "Pack 3149 Fall Show & Sell",
            "campaignYear": 2026,
            "catalogName": "Fixture Default Catalog",
            "isActive": True,
        }

    @pytest.mark.parametrize("code", ["ZZZZ9999ZZZZ9999", "SHORT", OLD_CODE, 42, None])
    def test_unknown_malformed_and_inactive_codes_are_not_found(
        self,
        code: Any,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.assert_is_error(_query("Riley", "unitCampaignJoinInfo", {"joinCode": code}), "NOT_FOUND")

    def test_dangling_pointer_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """A pointer whose Unit Campaign row is gone must not resolve."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        unit_campaigns_table.put_item(Item=fx.join_code_pointer_item("DANGLINGCODE1234", "uc-ghost-campaign"))
        fx.assert_is_error(_query("Riley", "unitCampaignJoinInfo", {"joinCode": "DANGLINGCODE1234"}), "NOT_FOUND")

    def test_missing_unit_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """A campaign row pointing at a deleted Unit must not resolve."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        unit_campaigns_table.put_item(
            Item=fx.unit_campaign_item(
                "uc-ghost-unit",
                unit_id="unit-ghost",
                campaign_name="Ghost",
                campaign_year=2026,
                catalog_id="CATALOG#fixture-default",
                join_code="GHOSTUNITCODE123",
                created_by="Avery",
            )
        )
        unit_campaigns_table.put_item(Item=fx.join_code_pointer_item("GHOSTUNITCODE123", "uc-ghost-unit"))
        fx.assert_is_error(_query("Riley", "unitCampaignJoinInfo", {"joinCode": "GHOSTUNITCODE123"}), "NOT_FOUND")

    def test_missing_catalog_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        unit_campaigns_table.put_item(
            Item=fx.unit_campaign_item(
                "uc-ghost-catalog",
                unit_id=fx.PACK_3149,
                campaign_name="Ghost Catalog",
                campaign_year=2026,
                catalog_id="CATALOG#ghost",
                join_code="GHOSTCATCODE1234",
                created_by="Avery",
            )
        )
        unit_campaigns_table.put_item(Item=fx.join_code_pointer_item("GHOSTCATCODE1234", "uc-ghost-catalog"))
        fx.assert_is_error(_query("Riley", "unitCampaignJoinInfo", {"joinCode": "GHOSTCATCODE1234"}), "NOT_FOUND")

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
        fx.assert_is_error(_query(None, "unitCampaignJoinInfo", {"joinCode": FALL_CODE}), "UNAUTHORIZED")


# ---------------------------------------------------------------------------
# UNIT-Q-07: unitCampaign
# ---------------------------------------------------------------------------


class TestUnitCampaignQuery:
    def test_admin_reads_the_campaign_with_its_join_code(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _query("Avery", "unitCampaign", {"unitCampaignId": fx.PACK_3149_FALL})
        assert payload["unitCampaignId"] == fx.PACK_3149_FALL
        assert payload["joinCode"] == FALL_CODE
        assert payload["campaignName"] == "Pack 3149 Fall Show & Sell"

    def test_non_admin_gets_null_not_forbidden(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        assert _query("Riley", "unitCampaign", {"unitCampaignId": fx.PACK_3149_FALL}) is None

    def test_unknown_id_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.assert_is_error(_query("Avery", "unitCampaign", {"unitCampaignId": "uc-ghost"}), "NOT_FOUND")


# ---------------------------------------------------------------------------
# UNIT-Q-08: unitCampaigns
# ---------------------------------------------------------------------------


class TestUnitCampaignsQuery:
    def test_admin_lists_campaigns_newest_first(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _query("Avery", "unitCampaigns", {"unitId": fx.PACK_3149})
        assert [i["unitCampaignId"] for i in payload["items"]] == [
            fx.PACK_3149_FALL,
            fx.PACK_3149_OLD,
        ]
        assert payload["pageInfo"] == {"endCursor": None, "hasNextPage": False}

    def test_is_active_filter(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        active = _query("Avery", "unitCampaigns", {"unitId": fx.PACK_3149, "isActive": True})
        assert [i["unitCampaignId"] for i in active["items"]] == [fx.PACK_3149_FALL]
        inactive = _query("Avery", "unitCampaigns", {"unitId": fx.PACK_3149, "isActive": False})
        assert [i["unitCampaignId"] for i in inactive["items"]] == [fx.PACK_3149_OLD]

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
        fx.assert_is_error(_query("Riley", "unitCampaigns", {"unitId": fx.PACK_3149}), "FORBIDDEN")

    def test_page_size_and_cursor(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """PAGE-01: a first=1 page yields a cursor that reaches the rest."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        first = _query("Avery", "unitCampaigns", {"unitId": fx.PACK_3149, "page": {"limit": 1}})
        assert [i["unitCampaignId"] for i in first["items"]] == [fx.PACK_3149_FALL]
        assert first["pageInfo"] == {"endCursor": "1", "hasNextPage": True}
        rest = _query(
            "Avery", "unitCampaigns", {"unitId": fx.PACK_3149, "page": {"cursor": first["pageInfo"]["endCursor"]}}
        )
        assert [i["unitCampaignId"] for i in rest["items"]] == [fx.PACK_3149_OLD]
        assert rest["pageInfo"] == {"endCursor": None, "hasNextPage": False}


# ---------------------------------------------------------------------------
# UNIT-Q-09: unitCampaignRoster
# ---------------------------------------------------------------------------


class TestUnitCampaignRoster:
    def test_admin_lists_memberships_newest_first(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _query("Avery", "unitCampaignRoster", {"unitCampaignId": fx.PACK_3149_FALL})
        assert [m["profileId"] for m in payload["items"]] == [fx.PROFILES["Devon"]["profileId"]]
        assert payload["items"][0]["status"] == "ACTIVE"

    def test_removed_memberships_appear_in_unfiltered_roster(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _query("Avery", "unitCampaignRoster", {"unitCampaignId": fx.PACK_3149_OLD})
        assert [m["status"] for m in payload["items"]] == ["REMOVED"]

    def test_status_filter(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _query("Avery", "unitCampaignRoster", {"unitCampaignId": fx.PACK_3149_OLD, "status": "ACTIVE"})
        assert payload["items"] == []
        payload = _query("Avery", "unitCampaignRoster", {"unitCampaignId": fx.PACK_3149_OLD, "status": "REMOVED"})
        assert len(payload["items"]) == 1

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
        fx.assert_is_error(_query("Devon", "unitCampaignRoster", {"unitCampaignId": fx.PACK_3149_FALL}), "FORBIDDEN")


# ---------------------------------------------------------------------------
# unitCampaignCatalog + AUTH-U
# ---------------------------------------------------------------------------


class TestUnitCampaignCatalog:
    def test_admin_reads_the_attached_catalog(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        payload = _query("Avery", "unitCampaignCatalog", {"unitCampaignId": fx.PACK_3149_FALL})
        assert payload["catalogId"] == "CATALOG#fixture-default"
        assert payload["catalogName"] == "Fixture Default Catalog"
        assert payload["products"][0]["productName"] == "Fixture Default Catalog Product 1"

    def test_non_admin_gets_null(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        assert _query("Riley", "unitCampaignCatalog", {"unitCampaignId": fx.PACK_3149_FALL}) is None

    def test_deleted_catalog_reads_null(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        unit_campaigns_table.put_item(
            Item=fx.unit_campaign_item(
                "uc-deleted-catalog",
                unit_id=fx.PACK_3149,
                campaign_name="Deleted Catalog Campaign",
                campaign_year=2026,
                catalog_id="CATALOG#fixture-deleted",
                join_code="DELETEDCATCODE12",
                created_by="Avery",
            )
        )
        assert _query("Avery", "unitCampaignCatalog", {"unitCampaignId": "uc-deleted-catalog"}) is None


class TestUnauthenticated:
    @pytest.mark.parametrize(
        "field,arguments",
        [
            ("unitCampaignJoinInfo", {"joinCode": FALL_CODE}),
            ("unitCampaign", {"unitCampaignId": fx.PACK_3149_FALL}),
            ("unitCampaigns", {"unitId": fx.PACK_3149}),
            ("unitCampaignRoster", {"unitCampaignId": fx.PACK_3149_FALL}),
            ("unitCampaignCatalog", {"unitCampaignId": fx.PACK_3149_FALL}),
        ],
    )
    def test_query_without_caller_is_unauthorized(
        self,
        field: str,
        arguments: dict,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.assert_is_error(_query(None, field, arguments), "UNAUTHORIZED")
